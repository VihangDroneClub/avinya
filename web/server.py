"""Avinya Web — browser-based interface for the Vihang AI club member."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import queue
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Response
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from collections import defaultdict
import time

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("avinya.web")

from core.config import MODEL_DEFAULT, MODEL_REASONING, SESSION_MAX_TURNS, VAULT_PATH, CHROMA_PATH, COLLECTION_NAME
from core.prompt_builder import build_full_prompt
from core.session_ops import maybe_roll_summary
from core.startup import initialise_system
from llm.ollama_adapter import OllamaError, check_ollama, generate_stream
from llm.router import choose_model
from memory.session_memory import SessionMemory
from memory.summarizer import summarize_conversation
from rag.retriever import retrieve_query_context
from rag.indexer import reindex_vault, collection
from prompts.system_prompt import SYSTEM_PROMPT

app = FastAPI(title="Avinya Web", version="2.0")

RATE_LIMIT_REQUESTS = int(os.environ.get("AVINYA_RATE_LIMIT", "60"))
RATE_LIMIT_WINDOW = int(os.environ.get("AVINYA_RATE_LIMIT_WINDOW", "60"))

class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_requests: int = 60, window_seconds: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.clients: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        window_start = now - self.window_seconds
        self.clients[client_ip] = [t for t in self.clients[client_ip] if t > window_start]
        if len(self.clients[client_ip]) >= self.max_requests:
            return JSONResponse(
                {"error": "rate limit exceeded", "retry_after": int(self.window_seconds - (now - self.clients[client_ip][0]))},
                status_code=429,
            )
        self.clients[client_ip].append(now)
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.max_requests)
        response.headers["X-RateLimit-Remaining"] = str(self.max_requests - len(self.clients[client_ip]))
        return response

app.add_middleware(RateLimitMiddleware, max_requests=RATE_LIMIT_REQUESTS, window_seconds=RATE_LIMIT_WINDOW)

static_dir = _ROOT / "web" / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

_sessions: dict[str, dict] = {}
_ready = False
_ollama_ok = False
_ollama_error_msg = ""

AUTH_PIN_HASH = os.environ.get("AVINYA_WEB_PIN", "vihang2026")
if not AUTH_PIN_HASH.startswith("sha256:"):
    AUTH_PIN_HASH = "sha256:" + hashlib.sha256(AUTH_PIN_HASH.encode()).hexdigest()

SESSION_COOKIE = "avinya_auth"


def _verify_pin(pin: str) -> bool:
    return "sha256:" + hashlib.sha256(pin.encode()).hexdigest() == AUTH_PIN_HASH


def _check_auth(request: Request) -> bool:
    cookie = request.cookies.get(SESSION_COOKIE, "")
    return cookie == AUTH_PIN_HASH


@app.on_event("startup")
def startup() -> None:
    global _ready, _ollama_ok, _ollama_error_msg
    logger.info("Starting Avinya Web...")
    try:
        initialise_system()
        _ready = True
        logger.info("Knowledge base initialized")
    except Exception as e:
        _ollama_error_msg = str(e)
        logger.error("Failed to initialize knowledge base: %s", e)
    try:
        check_ollama()
        _ollama_ok = True
        logger.info("Ollama connected")
    except OllamaError as e:
        _ollama_error_msg = str(e)
        logger.warning("Ollama not available: %s", e)
    logger.info("Avinya Web ready: backend=%s, ollama=%s", _ready, _ollama_ok)


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    if not _check_auth(request):
        return HTMLResponse(content=(static_dir / "index.html").read_text())
    return HTMLResponse(content=(static_dir / "index.html").read_text())


@app.get("/api/health")
def health() -> JSONResponse:
    return JSONResponse({
        "ready": _ready,
        "ollama": _ollama_ok,
        "status": "ok" if _ready and _ollama_ok else "degraded",
        "error": _ollama_error_msg if _ollama_error_msg else None,
    })


@app.post("/api/auth")
async def auth(request: Request) -> JSONResponse:
    body = await request.json()
    pin = body.get("pin", "")
    if _verify_pin(pin):
        resp = JSONResponse({"status": "ok"})
        resp.set_cookie(SESSION_COOKIE, AUTH_PIN_HASH, httponly=True, max_age=86400 * 30, samesite="lax")
        return resp
    return JSONResponse({"status": "invalid"}, status_code=401)


@app.post("/api/auth/check")
async def auth_check(request: Request) -> JSONResponse:
    if _check_auth(request):
        return JSONResponse({"authenticated": True})
    return JSONResponse({"authenticated": False})


@app.post("/api/auth/logout")
def auth_logout() -> JSONResponse:
    resp = JSONResponse({"status": "ok"})
    resp.delete_cookie(SESSION_COOKIE)
    return resp


def _require_auth(request: Request) -> JSONResponse | None:
    if not _check_auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return None


def _get_or_create_session(session_id: str) -> dict:
    if session_id not in _sessions:
        _sessions[session_id] = {
            "id": session_id,
            "memory": SessionMemory(max_recent=SESSION_MAX_TURNS),
            "created": datetime.now().isoformat(),
            "updated": datetime.now().isoformat(),
            "title": "New conversation",
            "messages": [],
        }
    return _sessions[session_id]


def _build_web_prompt(user_message: str, kb_text: str, memory: SessionMemory) -> str:
    parts = [SYSTEM_PROMPT]
    summ = (memory.get_summary() or "").strip()
    if summ:
        parts.append("\n## Conversation memory (rolling summary)\n" + summ)
    recent = (memory.get_recent_context() or "").strip()
    if recent:
        parts.append("\n## Recent dialogue\n[Sorted oldest → newest]\n" + recent)
    if (kb_text or "").strip():
        parts.append("\n## Knowledge Base (retrieved passages)\n" + kb_text.strip())
    else:
        parts.append("\n## Knowledge Base (retrieved passages)\n(No matching passages in the index for this query.)")
    parts.append("\n## Current user message\n" + user_message.strip())
    parts.append("\n## Assistant (respond now)\n")
    return "\n".join(parts)


@app.post("/api/chat/stream")
async def chat_stream(request: Request) -> Response:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err

    body = await request.json()
    message = body.get("message", "").strip()
    session_id = body.get("session_id", "default")

    if not message:
        return JSONResponse({"error": "empty message"}, status_code=400)

    if not _ready or not _ollama_ok:
        return JSONResponse({"error": "backend not ready: " + _ollama_error_msg}, status_code=503)

    session = _get_or_create_session(session_id)
    memory = session["memory"]
    memory.add_user_message(message)
    session["messages"].append({"role": "user", "content": message, "ts": datetime.now().isoformat()})
    if len(session["messages"]) == 1:
        session["title"] = message[:80]

    q: queue.Queue = queue.Queue()
    stream_text = ""
    assistant_failed = False

    def worker() -> None:
        nonlocal stream_text, assistant_failed
        started = time.perf_counter()
        try:
            model = choose_model(message)
            retrieval = retrieve_query_context(message, rerank=True)
            prompt = _build_web_prompt(message, retrieval.answer_context, memory)
            q.put(("meta", model, retrieval))
            for token in generate_stream(prompt, model):
                q.put(("tok", token))
        except OllamaError as exc:
            q.put(("err", str(exc)))
        except Exception as exc:
            q.put(("err", str(exc)))
        finally:
            q.put(("done", time.perf_counter() - started))

    threading.Thread(target=worker, daemon=True).start()

    async def event_generator():
        nonlocal stream_text, assistant_failed
        while True:
            if await request.is_disconnected():
                return
            try:
                item = q.get(timeout=2)
            except queue.Empty:
                yield "data: {\"type\": \"ping\"}\n\n"
                continue
            kind = item[0]
            if kind == "meta":
                _, model, retrieval = item
                sources = [{"file": s.source, "score": s.relevance_score} for s in retrieval.sources]
                yield f"data: {json.dumps({'type': 'meta', 'model': model, 'sources': sources})}\n\n"
            elif kind == "tok":
                token = item[1]
                stream_text += token
                yield f"data: {json.dumps({'type': 'token', 'text': token})}\n\n"
            elif kind == "err":
                assistant_failed = True
                yield f"data: {json.dumps({'type': 'error', 'message': item[1]})}\n\n"
            elif kind == "done":
                elapsed = float(item[1]) if len(item) > 1 else 0.0
                if stream_text and not assistant_failed:
                    memory.add_assistant_message(stream_text)
                    session["messages"].append({"role": "assistant", "content": stream_text, "ts": datetime.now().isoformat()})
                    session["updated"] = datetime.now().isoformat()
                    threading.Thread(target=lambda: maybe_roll_summary(memory), daemon=True).start()
                yield f"data: {json.dumps({'type': 'done', 'elapsed': round(elapsed, 2)})}\n\n"
                return

    from fastapi.responses import StreamingResponse
    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/chat")
async def chat(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err

    body = await request.json()
    message = body.get("message", "").strip()
    session_id = body.get("session_id", "default")

    if not message:
        return JSONResponse({"error": "empty message"}, status_code=400)
    if not _ready or not _ollama_ok:
        return JSONResponse({"error": "backend not ready: " + _ollama_error_msg}, status_code=503)

    session = _get_or_create_session(session_id)
    memory = session["memory"]
    memory.add_user_message(message)
    session["messages"].append({"role": "user", "content": message, "ts": datetime.now().isoformat()})
    if len(session["messages"]) == 1:
        session["title"] = message[:80]

    started = time.perf_counter()
    try:
        model = choose_model(message)
        retrieval = retrieve_query_context(message, rerank=True)
        prompt = _build_web_prompt(message, retrieval.answer_context, memory)
        answer = ""
        for token in generate_stream(prompt, model):
            answer += token
    except OllamaError as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)

    elapsed = time.perf_counter() - started
    memory.add_assistant_message(answer)
    session["messages"].append({"role": "assistant", "content": answer, "ts": datetime.now().isoformat()})
    session["updated"] = datetime.now().isoformat()
    threading.Thread(target=lambda: maybe_roll_summary(memory), daemon=True).start()

    return JSONResponse({
        "answer": answer,
        "model": model,
        "sources": [{"file": s.source, "score": s.relevance_score, "snippet": s.chunk[:200]} for s in retrieval.sources],
        "elapsed": round(elapsed, 2),
    })


@app.get("/api/sessions")
def list_sessions(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    result = []
    for sid, s in _sessions.items():
        result.append({"id": sid, "title": s["title"], "created": s["created"], "updated": s["updated"], "message_count": len(s["messages"])})
    result.sort(key=lambda x: x["updated"], reverse=True)
    return JSONResponse(result)


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str, request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    if session_id not in _sessions:
        return JSONResponse({"error": "not found"}, status_code=404)
    s = _sessions[session_id]
    return JSONResponse({"id": s["id"], "title": s["title"], "messages": s["messages"], "summary": s["memory"].get_summary()})


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str, request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    if session_id in _sessions:
        del _sessions[session_id]
    return JSONResponse({"status": "ok"})


@app.post("/api/search")
async def search_documents(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err

    body = await request.json()
    query = body.get("query", "").strip()
    limit = body.get("limit", 10)

    if not query:
        return JSONResponse({"error": "empty query"}, status_code=400)

    if not _ready:
        return JSONResponse({"error": "backend not ready"}, status_code=503)

    try:
        results = collection.query(
            query_texts=[query],
            n_results=min(limit, 20),
            include=["documents", "metadatas", "distances"],
        )

        items = []
        if results["documents"] and results["documents"][0]:
            for i, doc in enumerate(results["documents"][0]):
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                distance = results["distances"][0][i] if results["distances"] else None
                score = 1.0 - (distance or 0)
                items.append({
                    "content": doc[:500],
                    "source": meta.get("source", "unknown"),
                    "score": round(score, 3),
                    "metadata": meta,
                })

        return JSONResponse({"query": query, "results": items, "total": len(items)})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/reindex")
def reindex(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    try:
        result = reindex_vault(VAULT_PATH)
        return JSONResponse({
            "status": result.status,
            "files_indexed": result.files_indexed,
            "chunks_created": result.chunks_created,
            "time_elapsed": result.time_elapsed,
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/upload")
async def upload_file(request: Request, file: UploadFile = File(...)) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err

    import shutil
    inbox = _ROOT / "vihang_data" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    dest = inbox / file.filename
    content = await file.read()
    dest.write_bytes(content)
    try:
        result = reindex_vault(VAULT_PATH, files=[str(dest)])
        return JSONResponse({
            "status": "uploaded",
            "file": file.filename,
            "indexed": result.files_indexed,
            "chunks": result.chunks_created,
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/upload/bulk")
async def upload_bulk(request: Request, files: list[UploadFile] = File(...)) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err

    inbox = _ROOT / "vihang_data" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    results = []
    errors = []
    for file in files:
        try:
            dest = inbox / file.filename
            content = await file.read()
            dest.write_bytes(content)
            result = reindex_vault(VAULT_PATH, files=[str(dest)])
            results.append({
                "file": file.filename,
                "indexed": result.files_indexed,
                "chunks": result.chunks_created,
            })
        except Exception as exc:
            errors.append({"file": file.filename, "error": str(exc)})

    return JSONResponse({
        "status": "bulk_upload_complete",
        "total": len(files),
        "success": len(results),
        "failed": len(errors),
        "results": results,
        "errors": errors,
    })


@app.get("/api/knowledge")
def list_knowledge(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err

    vault = Path(VAULT_PATH)
    if not vault.exists():
        return JSONResponse([])
    files = []
    for f in vault.rglob("*.md"):
        stat = f.stat()
        files.append({
            "name": f.name,
            "path": str(f.relative_to(vault)),
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    files.sort(key=lambda x: x["modified"], reverse=True)
    return JSONResponse(files[:50])


@app.get("/api/stats")
def stats(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    try:
        doc_count = collection.count()
    except Exception:
        doc_count = 0
    return JSONResponse({
        "documents": doc_count,
        "sessions": len(_sessions),
        "ollama": _ollama_ok,
        "ready": _ready,
    })


@app.get("/api/documents/{path:path}")
def view_document(path: str, request: Request) -> FileResponse | JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    vault = Path(VAULT_PATH)
    file_path = (vault / path).resolve()
    if not str(file_path).startswith(str(vault.resolve())):
        return JSONResponse({"error": "invalid path"}, status_code=400)
    if not file_path.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    if file_path.suffix in (".md", ".txt", ".csv"):
        return FileResponse(str(file_path), media_type="text/plain")
    return FileResponse(str(file_path))


@app.get("/api/sessions/{session_id}/export")
def export_session(session_id: str, request: Request) -> Response:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    if session_id not in _sessions:
        return JSONResponse({"error": "not found"}, status_code=404)
    s = _sessions[session_id]
    lines = [f"# {s['title']}", f"Created: {s['created']}", f"Updated: {s['updated']}", ""]
    summary = s["memory"].get_summary()
    if summary:
        lines.extend(["## Summary", "", summary, ""])
    for m in s["messages"]:
        role = "You" if m["role"] == "user" else "Avinya"
        lines.extend([f"## {role}", "", m["content"], ""])
    md = "\n".join(lines)
    return Response(content=md, media_type="text/markdown", headers={
        "Content-Disposition": f'attachment; filename="avinya_{session_id}.md"',
    })


@app.post("/api/upload/audio")
async def upload_audio(request: Request, file: UploadFile = File(...)) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    if not file.filename or not file.filename.lower().endswith((".wav", ".mp3", ".m4a", ".ogg", ".flac")):
        return JSONResponse({"error": "unsupported audio format"}, status_code=400)
    inbox = _ROOT / "vihang_data" / "inbox" / "audio"
    inbox.mkdir(parents=True, exist_ok=True)
    dest = inbox / file.filename
    content = await file.read()
    dest.write_bytes(content)
    logger.info("Audio uploaded: %s (%d bytes)", file.filename, len(content))
    return JSONResponse({
        "status": "uploaded",
        "file": file.filename,
        "path": str(dest),
        "note": "Audio files are stored for manual transcription. Add a text summary alongside for indexing.",
    })


@app.post("/api/upload/image")
async def upload_image(request: Request, file: UploadFile = File(...), description: str = "") -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    if not file.filename or not file.filename.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg")):
        return JSONResponse({"error": "unsupported image format"}, status_code=400)
    images_dir = _ROOT / "vihang_data" / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    dest = images_dir / file.filename
    content = await file.read()
    dest.write_bytes(content)
    if description.strip():
        md_content = f"""---
source: {file.filename}
category: image
uploaded: {datetime.now().isoformat()}
---

# Image: {file.filename}

{description.strip()}

![{file.filename}](/api/images/{file.filename})
"""
        vault = Path(VAULT_PATH) / "images"
        vault.mkdir(parents=True, exist_ok=True)
        (vault / f"{file.filename}.md").write_text(md_content, encoding="utf-8")
        try:
            reindex_vault(VAULT_PATH)
        except Exception as e:
            logger.warning("Failed to reindex after image upload: %s", e)
    logger.info("Image uploaded: %s (%d bytes)", file.filename, len(content))
    return JSONResponse({
        "status": "uploaded",
        "file": file.filename,
        "path": str(dest),
        "url": f"/api/images/{file.filename}",
    })


@app.get("/api/images/{filename}")
def get_image(filename: str, request: Request) -> FileResponse | JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    images_dir = _ROOT / "vihang_data" / "images"
    file_path = (images_dir / filename).resolve()
    if not str(file_path).startswith(str(images_dir.resolve())):
        return JSONResponse({"error": "invalid path"}, status_code=400)
    if not file_path.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".bmp": "image/bmp", ".webp": "image/webp", ".svg": "image/svg+xml"}
    return FileResponse(str(file_path), media_type=mime_map.get(file_path.suffix, "application/octet-stream"))


@app.get("/api/graph")
def knowledge_graph(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    ckb_dir = _ROOT / "CKB"
    graph_file = ckb_dir / "graph.json"
    if not graph_file.exists():
        return JSONResponse({"nodes": [], "edges": [], "report": None})
    try:
        graph_data = json.loads(graph_file.read_text(encoding="utf-8"))
        report_file = ckb_dir / "GRAPH_REPORT.md"
        report = report_file.read_text(encoding="utf-8") if report_file.exists() else None
        return JSONResponse({"nodes": graph_data.get("nodes", []), "edges": graph_data.get("edges", []), "report": report})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/graph/generate")
def generate_graph(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    import subprocess
    script = _ROOT / "scripts" / "update_graph.py"
    if not script.exists():
        return JSONResponse({"error": "graph generation script not found"}, status_code=500)
    try:
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(_ROOT),
            capture_output=True,
            text=True,
            timeout=300,
        )
        return JSONResponse({
            "status": "completed" if result.returncode == 0 else "failed",
            "stdout": result.stdout[-2000:],
            "stderr": result.stderr[-2000:],
        })
    except subprocess.TimeoutExpired:
        return JSONResponse({"error": "graph generation timed out"}, status_code=504)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/meeting")
async def capture_meeting(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    body = await request.json()
    title = body.get("title", "Untitled Meeting").strip()
    attendees = body.get("attendees", [])
    raw_notes = body.get("notes", "").strip()
    if not raw_notes:
        return JSONResponse({"error": "empty notes"}, status_code=400)
    if not _ready or not _ollama_ok:
        return JSONResponse({"error": "backend not ready: " + _ollama_error_msg}, status_code=503)
    meeting_prompt = f"""You are Avinya, the permanent member of Vihang Drone Club. Process these meeting notes and return a structured summary in markdown.

Format your response as:
## Summary
(Brief 2-3 sentence overview)

## Key Discussion Points
- Point 1
- Point 2
...

## Action Items
- [ ] Action item (assignee if mentioned)
...

## Decisions Made
- Decision 1
...

## Follow-up Topics
- Topic 1
...

Meeting title: {title}
Attendees: {', '.join(attendees) if attendees else 'Not specified'}

Raw notes:
{raw_notes}
"""
    try:
        model = choose_model(raw_notes)
        summary = ""
        for token in generate_stream(meeting_prompt, model):
            summary += token
        md_content = f"""---
source: meeting
category: meeting
title: {title}
attendees: {', '.join(attendees) if attendees else 'Not specified'}
created: {datetime.now().isoformat()}
---

# Meeting: {title}

**Date:** {datetime.now().strftime("%Y-%m-%d")}
**Attendees:** {', '.join(attendees) if attendees else 'Not specified'}

## Raw Notes
{raw_notes}

## AI Summary
{summary}
"""
        meetings_dir = Path(VAULT_PATH) / "meetings"
        meetings_dir.mkdir(parents=True, exist_ok=True)
        safe_title = "".join(c if c.isalnum() or c in " _-" else "_" for c in title)
        filename = f"{datetime.now().strftime('%Y-%m-%d')}_{safe_title}.md"
        (meetings_dir / filename).write_text(md_content, encoding="utf-8")
        try:
            reindex_vault(VAULT_PATH)
        except Exception as e:
            logger.warning("Failed to reindex after meeting capture: %s", e)
        return JSONResponse({
            "status": "captured",
            "title": title,
            "filename": filename,
            "summary": summary,
        })
    except OllamaError as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


def main() -> None:
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()
