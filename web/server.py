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
import uuid
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from collections import defaultdict

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Response
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

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

import re

_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "\U0001f926-\U0001f937"
    "\U00010000-\U0010ffff"
    "\u2640-\u2642"
    "\u2600-\u2B55"
    "\u23cf"
    "\u23e9"
    "\u231a"
    "\ufe0f"
    "\u3030"
    "\u200d"
    "\u20e3"
    "\u25aa-\u25ab"
    "\u25b6"
    "\u25c0"
    "\u25fb-\u25fe"
    "]+",
    flags=re.UNICODE,
)

_SYMBOLS_TO_STRIP = re.compile(r"[✓✗✔✘★☆♦♠♣♥→←↑↓⇒⇔•·‣⁃◦▪▫⦿●○■□▲▼◆◇★☆☀☁☂☃☄★☆☎☏✉✈✊✋✌✍✎✏✐✑✒✓✔✕✖✗✘✙✚✛✜✝✞✟✠✡✢✣✤✥✦✧✩✪✫✬✭✮✯✰✱✲✳✴✵✶✷✸✹✺✻✼✽✾✿❀❁❂❃❄❅❆❇❈❉❊❋❌❍❎❏❐❑❒❓❔❕❖❗❘❙❚❛❜❝❞]")


def _clean_for_voice(text: str) -> str:
    text = _EMOJI_PATTERN.sub("", text)
    text = _SYMBOLS_TO_STRIP.sub("", text)
    text = text.replace("**", "")
    text = text.replace("*", "")
    text = re.sub(r"#{1,6}\s*", "", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _format_for_tts(text: str) -> str:
    text = _clean_for_voice(text)
    text = re.sub(r"(\d+)\s*([A-Za-z])", r"\1 \2", text)
    text = text.replace("e.g.,", "for example,")
    text = text.replace("i.e.,", "that is,")
    text = text.replace("etc.", "and so on.")
    text = text.replace("vs.", "versus")
    return text

app = FastAPI(title="Avinya Web", version="3.0")

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

DATA_DIR = _ROOT / "vihang_data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
TAGS_FILE = DATA_DIR / "tags.json"
PROJECTS_FILE = DATA_DIR / "projects.json"
INVENTORY_FILE = DATA_DIR / "inventory.json"
CALENDAR_FILE = DATA_DIR / "calendar.json"
MEMBERS_FILE = DATA_DIR / "members.json"
QA_FILE = DATA_DIR / "qa.json"
ANALYTICS_FILE = DATA_DIR / "analytics.json"
GAPS_FILE = DATA_DIR / "gaps.json"
TEMPLATES_DIR = DATA_DIR / "templates"
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
EXPORTS_DIR = DATA_DIR / "exports"
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
AUDIT_FILE = DATA_DIR / "audit.json"
MENTORS_FILE = DATA_DIR / "mentors.json"
QUERY_LOG = DATA_DIR / "query_log.json"

VALID_TAGS = ["project", "budget", "meeting", "technical", "tutorial", "image", "audio", "video", "manual", "research", "competition", "design"]

def _load_json(path: Path, default=None):
    if default is None:
        default = []
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default

def _save_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

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

def _log_query(query: str, has_results: bool, session_id: str = ""):
    log = _load_json(QUERY_LOG, [])
    log.append({
        "query": query,
        "timestamp": datetime.now().isoformat(),
        "has_results": has_results,
        "session_id": session_id,
    })
    if len(log) > 1000:
        log = log[-500:]
    _save_json(QUERY_LOG, log)

def _detect_gap(query: str, sources: list) -> str | None:
    if not sources and query.strip():
        gaps = _load_json(GAPS_FILE, [])
        for gap in gaps:
            if gap["query"].lower() == query.lower():
                gap["count"] = gap.get("count", 1) + 1
                gap["last_asked"] = datetime.now().isoformat()
                _save_json(GAPS_FILE, gaps)
                return None
        gaps.append({
            "query": query,
            "count": 1,
            "first_asked": datetime.now().isoformat(),
            "last_asked": datetime.now().isoformat(),
        })
        _save_json(GAPS_FILE, gaps)
        return query
    return None

@app.post("/api/chat/stream")
async def chat_stream(request: Request) -> Response:
    from fastapi.responses import StreamingResponse
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
            related = []
            if retrieval.sources:
                source_files = list(set(s.source for s in retrieval.sources[:3]))
                all_results = collection.query(
                    query_texts=[message],
                    n_results=10,
                    include=["documents", "metadatas", "distances"],
                )
                if all_results["metadatas"] and all_results["metadatas"][0]:
                    seen = set(source_files)
                    for i, meta in enumerate(all_results["metadatas"][0]):
                        src = meta.get("source", "")
                        if src and src not in seen:
                            related.append({"file": src, "score": round(1.0 - (all_results["distances"][0][i] if all_results["distances"] else 0), 3)})
                            seen.add(src)
                            if len(related) >= 3:
                                break
            confidence = "high" if retrieval.sources and any(s.relevance_score > 0.7 for s in retrieval.sources) else ("medium" if retrieval.sources else "low")
            _log_query(message, bool(retrieval.sources), session_id)
            gap = _detect_gap(message, retrieval.sources)
            q.put(("meta", model, retrieval, related, confidence, gap))
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
                _, model, retrieval, related, confidence, gap = item
                sources = [{"file": s.source, "score": s.relevance_score, "chunk_index": s.chunk[:100] if hasattr(s, 'chunk') else ""} for s in retrieval.sources]
                yield f"data: {json.dumps({'type': 'meta', 'model': model, 'sources': sources, 'related': related, 'confidence': confidence, 'gap': gap})}\n\n"
            elif kind == "tok":
                token = item[1]
                clean_token = _clean_for_voice(token)
                stream_text += clean_token
                yield f"data: {json.dumps({'type': 'token', 'text': clean_token})}\n\n"
            elif kind == "err":
                assistant_failed = True
                yield f"data: {json.dumps({'type': 'error', 'message': item[1]})}\n\n"
            elif kind == "done":
                elapsed = float(item[1]) if len(item) > 1 else 0.0
                if stream_text and not assistant_failed:
                    cleaned = _clean_for_voice(stream_text)
                    memory.add_assistant_message(cleaned)
                    session["messages"].append({"role": "assistant", "content": cleaned, "ts": datetime.now().isoformat()})
                    session["updated"] = datetime.now().isoformat()
                    threading.Thread(target=lambda: maybe_roll_summary(memory), daemon=True).start()
                yield f"data: {json.dumps({'type': 'done', 'elapsed': round(elapsed, 2)})}\n\n"
                return

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
            answer += _clean_for_voice(token)
    except OllamaError as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)

    elapsed = time.perf_counter() - started
    cleaned = _clean_for_voice(answer)
    memory.add_assistant_message(cleaned)
    session["messages"].append({"role": "assistant", "content": cleaned, "ts": datetime.now().isoformat()})
    session["updated"] = datetime.now().isoformat()
    threading.Thread(target=lambda: maybe_roll_summary(memory), daemon=True).start()

    confidence = "high" if retrieval.sources and any(s.relevance_score > 0.7 for s in retrieval.sources) else ("medium" if retrieval.sources else "low")
    _log_query(message, bool(retrieval.sources), session_id)
    _detect_gap(message, retrieval.sources)

    return JSONResponse({
        "answer": answer,
        "model": model,
        "sources": [{"file": s.source, "score": s.relevance_score, "snippet": s.chunk[:200]} for s in retrieval.sources],
        "elapsed": round(elapsed, 2),
        "confidence": confidence,
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
    tag_filter = body.get("tag", "")

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
                if tag_filter and meta.get("category") != tag_filter:
                    continue
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

@app.post("/api/upload/preview")
async def preview_upload(request: Request, file: UploadFile = File(...)) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    content = await file.read()
    preview = ""
    file_type = "unknown"
    try:
        if file.filename.endswith((".md", ".txt", ".csv")):
            preview = content.decode("utf-8", errors="replace")[:2000]
            file_type = "text"
        elif file.filename.endswith(".pdf"):
            from processors.pdf_converter import PDFConverter
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(content)
                tmp.flush()
                result = PDFConverter().convert(Path(tmp.name), Path(tempfile.gettempdir()))
                preview = result.content[:2000] if result.content else ""
                file_type = "pdf"
        elif file.filename.endswith(".docx"):
            from processors.docx_converter import DOCXConverter
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
                tmp.write(content)
                tmp.flush()
                result = DOCXConverter().convert(Path(tmp.name), Path(tempfile.gettempdir()))
                preview = result.content[:2000] if result.content else ""
                file_type = "docx"
        elif file.filename.endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")):
            file_type = "image"
            preview = f"[Image: {file.filename} - {len(content)} bytes]"
        else:
            preview = content.decode("utf-8", errors="replace")[:2000]
            file_type = "binary"
    except Exception as e:
        preview = f"Could not preview: {str(e)}"
    return JSONResponse({
        "filename": file.filename,
        "size": len(content),
        "type": file_type,
        "preview": preview,
        "suggested_tags": _suggest_tags(file.filename, preview),
    })

def _suggest_tags(filename: str, content: str) -> list[str]:
    tags = []
    lower = filename.lower()
    if any(x in lower for x in ["meeting", "minutes", "sync"]):
        tags.append("meeting")
    if any(x in lower for x in ["budget", "cost", "expense", "finance"]):
        tags.append("budget")
    if any(x in lower for x in ["tutorial", "guide", "howto", "how-to"]):
        tags.append("tutorial")
    if any(x in lower for x in ["project", "design", "build"]):
        tags.append("project")
    if any(x in lower for x in ["circuit", "schematic", "pcb", "diagram"]):
        tags.append("technical")
    if lower.endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")):
        tags.append("image")
    if any(x in lower for x in ["manual", "spec", "datasheet"]):
        tags.append("manual")
    if any(x in lower for x in ["competition", "comp", "event"]):
        tags.append("competition")
    if not tags:
        tags.append("technical")
    return tags

@app.post("/api/upload")
async def upload_file(request: Request, file: UploadFile = File(...), tags: str = "", context_note: str = "") -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    inbox = DATA_DIR / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    dest = inbox / file.filename
    content = await file.read()
    dest.write_bytes(content)
    try:
        result = reindex_vault(VAULT_PATH, files=[str(dest)])
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else _suggest_tags(file.filename, content.decode("utf-8", errors="replace")[:500])
        _apply_tags(file.filename, tag_list, context_note)
        return JSONResponse({
            "status": "uploaded",
            "file": file.filename,
            "indexed": result.files_indexed,
            "chunks": result.chunks_created,
            "tags": tag_list,
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)

@app.post("/api/upload/bulk")
async def upload_bulk(request: Request, files: list[UploadFile] = File(...), tags: str = "") -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    inbox = DATA_DIR / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    results = []
    errors = []
    for file in files:
        try:
            dest = inbox / file.filename
            content = await file.read()
            dest.write_bytes(content)
            result = reindex_vault(VAULT_PATH, files=[str(dest)])
            file_tags = tag_list or _suggest_tags(file.filename, content.decode("utf-8", errors="replace")[:500])
            _apply_tags(file.filename, file_tags)
            results.append({
                "file": file.filename,
                "indexed": result.files_indexed,
                "chunks": result.chunks_created,
                "tags": file_tags,
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

def _apply_tags(filename: str, tags: list[str], context_note: str = ""):
    all_tags = _load_json(TAGS_FILE, {})
    all_tags[filename] = {
        "tags": tags,
        "context": context_note,
        "added": datetime.now().isoformat(),
    }
    _save_json(TAGS_FILE, all_tags)

@app.get("/api/tags")
def list_tags(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    return JSONResponse(_load_json(TAGS_FILE, {}))

@app.post("/api/tags")
async def add_tag(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    body = await request.json()
    filename = body.get("filename", "")
    tag = body.get("tag", "")
    if not filename or not tag:
        return JSONResponse({"error": "filename and tag required"}, status_code=400)
    all_tags = _load_json(TAGS_FILE, {})
    if filename not in all_tags:
        all_tags[filename] = {"tags": [], "context": "", "added": datetime.now().isoformat()}
    if tag not in all_tags[filename]["tags"]:
        all_tags[filename]["tags"].append(tag)
    _save_json(TAGS_FILE, all_tags)
    return JSONResponse({"status": "ok", "tags": all_tags[filename]["tags"]})

@app.delete("/api/tags")
async def remove_tag(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    body = await request.json()
    filename = body.get("filename", "")
    tag = body.get("tag", "")
    if not filename or not tag:
        return JSONResponse({"error": "filename and tag required"}, status_code=400)
    all_tags = _load_json(TAGS_FILE, {})
    if filename in all_tags and tag in all_tags[filename]["tags"]:
        all_tags[filename]["tags"].remove(tag)
        _save_json(TAGS_FILE, all_tags)
    return JSONResponse({"status": "ok"})

@app.get("/api/tags/list")
def available_tags(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    return JSONResponse({"tags": VALID_TAGS})

@app.get("/api/knowledge")
def list_knowledge(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    vault = Path(VAULT_PATH)
    if not vault.exists():
        return JSONResponse([])
    all_tags = _load_json(TAGS_FILE, {})
    files = []
    for f in vault.rglob("*.md"):
        stat = f.stat()
        tag_info = all_tags.get(f.name, {})
        files.append({
            "name": f.name,
            "path": str(f.relative_to(vault)),
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "tags": tag_info.get("tags", []),
            "context": tag_info.get("context", ""),
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
    all_tags = _load_json(TAGS_FILE, {})
    tag_counts = defaultdict(int)
    for info in all_tags.values():
        for t in info.get("tags", []):
            tag_counts[t] += 1
    return JSONResponse({
        "documents": doc_count,
        "sessions": len(_sessions),
        "ollama": _ollama_ok,
        "ready": _ready,
        "tags": dict(tag_counts),
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
async def upload_audio(request: Request, file: UploadFile = File(...), transcribe: bool = False) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    if not file.filename or not file.filename.lower().endswith((".wav", ".mp3", ".m4a", ".ogg", ".flac")):
        return JSONResponse({"error": "unsupported audio format"}, status_code=400)
    inbox = DATA_DIR / "inbox" / "audio"
    inbox.mkdir(parents=True, exist_ok=True)
    dest = inbox / file.filename
    content = await file.read()
    dest.write_bytes(content)
    logger.info("Audio uploaded: %s (%d bytes)", file.filename, len(content))

    if transcribe:
        try:
            from voice.stt import STT
            stt = STT("tiny.en", download_root=str(_ROOT / "assets/models/whisper"))
            transcription = stt.transcribe_file(str(dest))
            if transcription:
                md_content = f"""---
source: {file.filename}
category: transcription
uploaded: {datetime.now().isoformat()}
---

# Audio Transcription: {file.filename}

**Date:** {datetime.now().strftime("%Y-%m-%d")}
**Duration:** {len(content) / 32000:.1f} seconds (approximate)

## Transcript

{transcription}
"""
                transcriptions_dir = Path(VAULT_PATH) / "transcriptions"
                transcriptions_dir.mkdir(parents=True, exist_ok=True)
                safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in file.filename)
                md_path = transcriptions_dir / f"{safe_name}.md"
                md_path.write_text(md_content, encoding="utf-8")
                try:
                    reindex_vault(VAULT_PATH)
                except Exception as e:
                    logger.warning("Failed to reindex after transcription: %s", e)
                return JSONResponse({
                    "status": "transcribed",
                    "file": file.filename,
                    "transcription": transcription,
                    "indexed": True,
                })
            return JSONResponse({"error": "no speech detected"}, status_code=400)
        except Exception as exc:
            logger.error("Transcription failed: %s", exc)
            return JSONResponse({"error": f"transcription failed: {str(exc)}"}, status_code=500)

    return JSONResponse({
        "status": "uploaded",
        "file": file.filename,
        "path": str(dest),
        "note": "Audio file stored. Use transcribe=true to transcribe.",
    })


@app.post("/api/transcribe")
async def transcribe_audio(request: Request, file: UploadFile = File(...), title: str = "") -> JSONResponse:
    """Transcribe an audio file and index the result into the knowledge base."""
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    if not file.filename or not file.filename.lower().endswith((".wav", ".mp3", ".m4a", ".ogg", ".flac")):
        return JSONResponse({"error": "unsupported audio format"}, status_code=400)

    inbox = DATA_DIR / "inbox" / "audio"
    inbox.mkdir(parents=True, exist_ok=True)
    dest = inbox / file.filename
    content = await file.read()
    dest.write_bytes(content)

    try:
        from voice.stt import STT
        stt = STT("tiny.en", download_root=str(_ROOT / "assets/models/whisper"))
        transcription = stt.transcribe_file(str(dest))
        if not transcription:
            return JSONResponse({"error": "no speech detected in audio"}, status_code=400)

        display_title = title.strip() or f"Transcription: {file.filename}"
        md_content = f"""---
source: {file.filename}
category: transcription
title: {display_title}
uploaded: {datetime.now().isoformat()}
---

# {display_title}

**Date:** {datetime.now().strftime("%Y-%m-%d")}
**Source:** {file.filename}

## Transcript

{transcription}
"""
        transcriptions_dir = Path(VAULT_PATH) / "transcriptions"
        transcriptions_dir.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in display_title)
        md_path = transcriptions_dir / f"{safe_name}.md"
        md_path.write_text(md_content, encoding="utf-8")
        try:
            reindex_vault(VAULT_PATH)
        except Exception as e:
            logger.warning("Failed to reindex after transcription: %s", e)

        logger.info("Audio transcribed and indexed: %s", file.filename)
        return JSONResponse({
            "status": "transcribed",
            "file": file.filename,
            "title": display_title,
            "transcription": transcription,
            "word_count": len(transcription.split()),
            "indexed": True,
        })
    except Exception as exc:
        logger.error("Transcription failed: %s", exc)
        return JSONResponse({"error": f"transcription failed: {str(exc)}"}, status_code=500)

@app.post("/api/upload/image")
async def upload_image(request: Request, file: UploadFile = File(...), description: str = "") -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    if not file.filename or not file.filename.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg")):
        return JSONResponse({"error": "unsupported image format"}, status_code=400)
    images_dir = DATA_DIR / "images"
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

@app.post("/api/upload/photo")
async def upload_photo(request: Request, file: UploadFile = File(...), question: str = "") -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    if not file.filename or not file.filename.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")):
        return JSONResponse({"error": "unsupported image format"}, status_code=400)
    photos_dir = DATA_DIR / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)
    dest = photos_dir / file.filename
    content = await file.read()
    dest.write_bytes(content)
    analysis = ""
    if question.strip() and _ollama_ok:
        try:
            model = choose_model(question)
            prompt = f"""A club member uploaded a photo and asked: "{question}"
Describe what you can infer about this image based on the filename and context.
If it's a circuit board, explain what components you might expect.
If it's a drone part, explain its likely function.

Photo filename: {file.filename}
Question: {question}
"""
            analysis = ""
            for token in generate_stream(prompt, model):
                analysis += token
        except Exception as e:
            analysis = f"Analysis unavailable: {str(e)}"
    return JSONResponse({
        "status": "uploaded",
        "file": file.filename,
        "url": f"/api/photos/{file.filename}",
        "analysis": analysis,
    })

@app.get("/api/photos/{filename}")
def get_photo(filename: str, request: Request) -> FileResponse | JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    photos_dir = DATA_DIR / "photos"
    file_path = (photos_dir / filename).resolve()
    if not str(file_path).startswith(str(photos_dir.resolve())):
        return JSONResponse({"error": "invalid path"}, status_code=400)
    if not file_path.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".bmp": "image/bmp", ".webp": "image/webp"}
    return FileResponse(str(file_path), media_type=mime_map.get(file_path.suffix, "application/octet-stream"))

@app.post("/api/upload/video")
async def upload_video(request: Request, file: UploadFile = File(...)) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    if not file.filename or not file.filename.lower().endswith((".mp4", ".avi", ".mov", ".mkv", ".webm")):
        return JSONResponse({"error": "unsupported video format"}, status_code=400)
    videos_dir = DATA_DIR / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)
    dest = videos_dir / file.filename
    content = await file.read()
    dest.write_bytes(content)
    logger.info("Video uploaded: %s (%d bytes)", file.filename, len(content))
    return JSONResponse({
        "status": "uploaded",
        "file": file.filename,
        "path": str(dest),
        "note": "Video stored for future transcription. Audio extraction coming soon.",
    })

@app.get("/api/images/{filename}")
def get_image(filename: str, request: Request) -> FileResponse | JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    images_dir = DATA_DIR / "images"
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

@app.get("/api/projects")
def list_projects(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    return JSONResponse(_load_json(PROJECTS_FILE, []))

@app.post("/api/projects")
async def create_project(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    body = await request.json()
    projects = _load_json(PROJECTS_FILE, [])
    project = {
        "id": str(uuid.uuid4())[:8],
        "name": body.get("name", "Untitled"),
        "description": body.get("description", ""),
        "status": body.get("status", "planning"),
        "blockers": body.get("blockers", []),
        "milestones": body.get("milestones", []),
        "created": datetime.now().isoformat(),
        "updated": datetime.now().isoformat(),
    }
    projects.append(project)
    _save_json(PROJECTS_FILE, projects)
    return JSONResponse({"status": "created", "project": project})

@app.put("/api/projects/{project_id}")
async def update_project(project_id: str, request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    body = await request.json()
    projects = _load_json(PROJECTS_FILE, [])
    for p in projects:
        if p["id"] == project_id:
            p.update(body)
            p["updated"] = datetime.now().isoformat()
            _save_json(PROJECTS_FILE, projects)
            return JSONResponse({"status": "updated", "project": p})
    return JSONResponse({"error": "not found"}, status_code=404)

@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str, request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    projects = _load_json(PROJECTS_FILE, [])
    projects = [p for p in projects if p["id"] != project_id]
    _save_json(PROJECTS_FILE, projects)
    return JSONResponse({"status": "deleted"})

@app.get("/api/inventory")
def list_inventory(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    return JSONResponse(_load_json(INVENTORY_FILE, []))

@app.post("/api/inventory")
async def add_inventory_item(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    body = await request.json()
    items = _load_json(INVENTORY_FILE, [])
    item = {
        "id": str(uuid.uuid4())[:8],
        "name": body.get("name", "Untitled"),
        "category": body.get("category", "general"),
        "quantity": body.get("quantity", 1),
        "location": body.get("location", ""),
        "condition": body.get("condition", "good"),
        "notes": body.get("notes", ""),
        "added": datetime.now().isoformat(),
    }
    items.append(item)
    _save_json(INVENTORY_FILE, items)
    return JSONResponse({"status": "added", "item": item})

@app.put("/api/inventory/{item_id}")
async def update_inventory_item(item_id: str, request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    body = await request.json()
    items = _load_json(INVENTORY_FILE, [])
    for item in items:
        if item["id"] == item_id:
            item.update(body)
            _save_json(INVENTORY_FILE, items)
            return JSONResponse({"status": "updated", "item": item})
    return JSONResponse({"error": "not found"}, status_code=404)

@app.delete("/api/inventory/{item_id}")
def delete_inventory_item(item_id: str, request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    items = _load_json(INVENTORY_FILE, [])
    items = [i for i in items if i["id"] != item_id]
    _save_json(INVENTORY_FILE, items)
    return JSONResponse({"status": "deleted"})

@app.get("/api/calendar")
def list_events(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    return JSONResponse(_load_json(CALENDAR_FILE, []))

@app.post("/api/calendar")
async def create_event(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    body = await request.json()
    events = _load_json(CALENDAR_FILE, [])
    event = {
        "id": str(uuid.uuid4())[:8],
        "title": body.get("title", "Untitled"),
        "description": body.get("description", ""),
        "type": body.get("type", "general"),
        "date": body.get("date", ""),
        "time": body.get("time", ""),
        "location": body.get("location", ""),
        "created": datetime.now().isoformat(),
    }
    events.append(event)
    events.sort(key=lambda e: e.get("date", ""))
    _save_json(CALENDAR_FILE, events)
    return JSONResponse({"status": "created", "event": event})

@app.delete("/api/calendar/{event_id}")
def delete_event(event_id: str, request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    events = _load_json(CALENDAR_FILE, [])
    events = [e for e in events if e["id"] != event_id]
    _save_json(CALENDAR_FILE, events)
    return JSONResponse({"status": "deleted"})

@app.get("/api/members")
def list_members(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    return JSONResponse(_load_json(MEMBERS_FILE, []))

@app.post("/api/members")
async def add_member(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    body = await request.json()
    members = _load_json(MEMBERS_FILE, [])
    member = {
        "id": str(uuid.uuid4())[:8],
        "name": body.get("name", "Anonymous"),
        "role": body.get("role", "member"),
        "year": body.get("year", ""),
        "expertise": body.get("expertise", []),
        "contact": body.get("contact", ""),
        "joined": datetime.now().isoformat(),
    }
    members.append(member)
    _save_json(MEMBERS_FILE, members)
    return JSONResponse({"status": "added", "member": member})

@app.delete("/api/members/{member_id}")
def delete_member(member_id: str, request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    members = _load_json(MEMBERS_FILE, [])
    members = [m for m in members if m["id"] != member_id]
    _save_json(MEMBERS_FILE, members)
    return JSONResponse({"status": "deleted"})

@app.get("/api/qa")
def list_qa(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    return JSONResponse(_load_json(QA_FILE, []))

@app.post("/api/qa")
async def post_question(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    body = await request.json()
    qa = _load_json(QA_FILE, [])
    question = body.get("question", "").strip()
    if not question:
        return JSONResponse({"error": "empty question"}, status_code=400)
    answer = ""
    if _ready and _ollama_ok:
        try:
            model = choose_model(question)
            retrieval = retrieve_query_context(question, rerank=True)
            prompt = f"""You are Avinya. Answer this question based on club knowledge.

{retrieval.answer_context if retrieval.answer_context else "(No relevant documents found)"}

Question: {question}
"""
            for token in generate_stream(prompt, model):
                answer += token
        except Exception:
            pass
    entry = {
        "id": str(uuid.uuid4())[:8],
        "question": question,
        "answer": answer,
        "asked_by": body.get("asked_by", "anonymous"),
        "answered_by": "avinya" if answer else "pending",
        "senior_correction": body.get("senior_correction", ""),
        "status": "answered" if answer else "open",
        "created": datetime.now().isoformat(),
    }
    qa.append(entry)
    _save_json(QA_FILE, qa)
    return JSONResponse({"status": "posted", "entry": entry})

@app.put("/api/qa/{qa_id}")
async def update_qa(qa_id: str, request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    body = await request.json()
    qa = _load_json(QA_FILE, [])
    for entry in qa:
        if entry["id"] == qa_id:
            if "senior_correction" in body:
                entry["senior_correction"] = body["senior_correction"]
                entry["status"] = "corrected"
            if "answer" in body:
                entry["answer"] = body["answer"]
                entry["status"] = "answered"
            _save_json(QA_FILE, qa)
            return JSONResponse({"status": "updated", "entry": entry})
    return JSONResponse({"error": "not found"}, status_code=404)

@app.get("/api/analytics")
def analytics(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    queries = _load_json(QUERY_LOG, [])
    gaps = _load_json(GAPS_FILE, [])
    total_queries = len(queries)
    queries_with_results = sum(1 for q in queries if q.get("has_results"))
    top_queries = sorted(queries, key=lambda q: q.get("timestamp", ""), reverse=True)[:20]
    topics = defaultdict(int)
    for q in queries:
        words = q.get("query", "").lower().split()
        for w in words:
            if len(w) > 3:
                topics[w] += 1
    top_topics = sorted(topics.items(), key=lambda x: x[1], reverse=True)[:15]
    high_demand_gaps = sorted([g for g in gaps if g.get("count", 1) >= 3], key=lambda g: g.get("count", 0), reverse=True)
    return JSONResponse({
        "total_queries": total_queries,
        "queries_with_results": queries_with_results,
        "success_rate": round(queries_with_results / max(total_queries, 1) * 100, 1),
        "top_queries": top_queries,
        "top_topics": [{"topic": t, "count": c} for t, c in top_topics],
        "knowledge_gaps": gaps[:10],
        "high_demand_gaps": high_demand_gaps,
        "alerts": [f"{g['count']} people asked about '{g['query']}' but we have no docs" for g in high_demand_gaps],
    })

@app.get("/api/gaps")
def list_gaps(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    return JSONResponse(_load_json(GAPS_FILE, []))

@app.post("/api/knowledge/export")
def export_knowledge_base(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    export_id = str(uuid.uuid4())[:8]
    export_dir = EXPORTS_DIR / export_id
    export_dir.mkdir(parents=True, exist_ok=True)
    vault = Path(VAULT_PATH)
    if vault.exists():
        shutil.copytree(vault, export_dir / "vault")
    for data_file in [TAGS_FILE, PROJECTS_FILE, INVENTORY_FILE, CALENDAR_FILE, MEMBERS_FILE, QA_FILE]:
        if data_file.exists():
            shutil.copy2(data_file, export_dir / data_file.name)
    manifest = {
        "export_id": export_id,
        "exported": datetime.now().isoformat(),
        "files": [str(f.relative_to(export_dir)) for f in export_dir.rglob("*") if f.is_file()],
    }
    (export_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return JSONResponse({
        "status": "exported",
        "export_id": export_id,
        "path": str(export_dir),
    })

@app.post("/api/knowledge/import")
async def import_knowledge_base(request: Request, file: UploadFile = File(...)) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    if not file.filename.endswith(".zip"):
        return JSONResponse({"error": "upload a .zip export"}, status_code=400)
    import zipfile
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = Path(tmpdir) / file.filename
        zip_path.write_bytes(await file.read())
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmpdir)
        imported = {"vault": 0, "tags": 0, "projects": 0, "inventory": 0, "calendar": 0, "members": 0, "qa": 0}
        src_vault = Path(tmpdir) / "vault"
        if src_vault.exists():
            dest_vault = Path(VAULT_PATH)
            for f in src_vault.rglob("*"):
                if f.is_file():
                    rel = f.relative_to(src_vault)
                    dest = dest_vault / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, dest)
                    imported["vault"] += 1
        for key in ["tags", "projects", "inventory", "calendar", "members", "qa"]:
            src = Path(tmpdir) / f"{key}.json"
            if src.exists():
                existing = _load_json(globals()[f"{key.upper()}_FILE"], [])
                new_data = _load_json(src, [])
                if isinstance(existing, list):
                    existing.extend(new_data)
                    _save_json(globals()[f"{key.upper()}_FILE"], existing)
                imported[key] = len(new_data)
        try:
            reindex_vault(VAULT_PATH)
        except Exception:
            pass
        return JSONResponse({"status": "imported", "counts": imported})

@app.get("/api/templates")
def list_templates(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    templates = []
    for f in TEMPLATES_DIR.rglob("*.md"):
        templates.append({
            "name": f.stem,
            "path": str(f.relative_to(TEMPLATES_DIR)),
            "content": f.read_text(encoding="utf-8")[:500],
        })
    return JSONResponse(templates)

@app.post("/api/templates")
async def create_template(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    body = await request.json()
    name = body.get("name", "untitled").replace(" ", "_")
    content = body.get("content", "")
    (TEMPLATES_DIR / f"{name}.md").write_text(content, encoding="utf-8")
    return JSONResponse({"status": "created", "name": name})

@app.get("/api/audit")
def knowledge_audit(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    vault = Path(VAULT_PATH)
    files = list(vault.rglob("*.md")) if vault.exists() else []
    now = datetime.now()
    stale = []
    for f in files:
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        age_days = (now - mtime).days
        if age_days > 180:
            stale.append({"path": str(f.relative_to(vault)), "age_days": age_days, "modified": mtime.isoformat()})
    gaps = _load_json(GAPS_FILE, [])
    audit = {
        "total_documents": len(files),
        "stale_documents": stale,
        "knowledge_gaps": gaps,
        "high_demand_gaps": sorted([g for g in gaps if g.get("count", 1) >= 3], key=lambda g: g.get("count", 0), reverse=True),
        "audit_date": now.isoformat(),
    }
    _save_json(AUDIT_FILE, audit)
    return JSONResponse(audit)

@app.get("/api/reports/state")
def state_of_club_report(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    if not _ready or not _ollama_ok:
        return JSONResponse({"error": "backend not ready"}, status_code=503)
    vault = Path(VAULT_PATH)
    files = list(vault.rglob("*.md")) if vault.exists() else []
    projects = _load_json(PROJECTS_FILE, [])
    members = _load_json(MEMBERS_FILE, [])
    gaps = _load_json(GAPS_FILE, [])
    queries = _load_json(QUERY_LOG, [])
    summary_prompt = f"""Generate a "State of the Club" report for Vihang Drone Club based on this data:

- {len(files)} documents in knowledge base
- {len(projects)} projects tracked
- {len(members)} members registered
- {len(gaps)} knowledge gaps identified
- {len(queries)} total queries asked

Top knowledge gaps (asked but no docs):
{json.dumps(gaps[:5], indent=2)}

Write a concise report covering:
1. Knowledge base health
2. Active projects
3. Member engagement
4. Gaps and recommendations
5. Priorities for next semester
"""
    try:
        model = choose_model(summary_prompt)
        report = ""
        for token in generate_stream(summary_prompt, model):
            report += token
        return JSONResponse({
            "report": report,
            "stats": {
                "documents": len(files),
                "projects": len(projects),
                "members": len(members),
                "gaps": len(gaps),
                "queries": len(queries),
            },
            "generated": datetime.now().isoformat(),
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)

@app.get("/api/mentors")
def list_mentors(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    return JSONResponse(_load_json(MENTORS_FILE, []))

@app.post("/api/mentors")
async def generate_mentors(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    members = _load_json(MEMBERS_FILE, [])
    gaps = _load_json(GAPS_FILE, [])
    matches = []
    for gap in gaps:
        query = gap.get("query", "").lower()
        for member in members:
            expertise = [e.lower() for e in member.get("expertise", [])]
            if any(e in query for e in expertise):
                matches.append({
                    "topic": gap["query"],
                    "mentor": member["name"],
                    "expertise": member.get("expertise", []),
                    "contact": member.get("contact", ""),
                })
    _save_json(MENTORS_FILE, matches)
    return JSONResponse({"matches": matches})

@app.post("/api/knowledge/freshness")
def check_freshness(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    vault = Path(VAULT_PATH)
    files = list(vault.rglob("*.md")) if vault.exists() else []
    now = datetime.now()
    freshness = {"fresh": [], "stale": [], "outdated": []}
    for f in files:
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        age_days = (now - mtime).days
        info = {"path": str(f.relative_to(vault)), "age_days": age_days, "modified": mtime.isoformat()}
        if age_days < 90:
            freshness["fresh"].append(info)
        elif age_days < 180:
            freshness["stale"].append(info)
        else:
            freshness["outdated"].append(info)
    return JSONResponse(freshness)

@app.post("/api/knowledge/cleanup")
def cleanup_knowledge(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    vault = Path(VAULT_PATH)
    files = list(vault.rglob("*.md")) if vault.exists() else []
    duplicates = []
    seen = {}
    for f in files:
        content = f.read_text(encoding="utf-8", errors="ignore")[:500]
        if content in seen:
            duplicates.append({"file": str(f.relative_to(vault)), "duplicate_of": seen[content]})
        else:
            seen[content] = str(f.relative_to(vault))
    return JSONResponse({
        "total_files": len(files),
        "duplicates": duplicates,
        "unique_files": len(files) - len(duplicates),
    })

@app.post("/api/auto-reindex/enable")
def enable_auto_reindex(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    config_file = DATA_DIR / "auto_reindex.json"
    _save_json(config_file, {"enabled": True, "last_check": datetime.now().isoformat(), "interval_minutes": 30})
    return JSONResponse({"status": "enabled"})

@app.post("/api/auto-reindex/disable")
def disable_auto_reindex(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    config_file = DATA_DIR / "auto_reindex.json"
    _save_json(config_file, {"enabled": False, "last_check": datetime.now().isoformat()})
    return JSONResponse({"status": "disabled"})

@app.get("/api/auto-reindex/status")
def auto_reindex_status(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    config_file = DATA_DIR / "auto_reindex.json"
    return JSONResponse(_load_json(config_file, {"enabled": False}))


@app.post("/api/chat/tts")
async def chat_tts(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    body = await request.json()
    message = body.get("message", "").strip()
    if not message:
        return JSONResponse({"error": "empty message"}, status_code=400)
    if not _ready or not _ollama_ok:
        return JSONResponse({"error": "backend not ready"}, status_code=503)
    try:
        model = choose_model(message)
        retrieval = retrieve_query_context(message, rerank=True)
        prompt = _build_web_prompt(message, retrieval.answer_context, SessionMemory(max_recent=10))
        answer = ""
        for token in generate_stream(prompt, model):
            answer += token
        cleaned = _format_for_tts(answer)
        return JSONResponse({
            "text": cleaned,
            "raw": answer,
            "confidence": "high" if retrieval.sources else "low",
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/tts/speak")
async def tts_speak(request: Request) -> JSONResponse:
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    body = await request.json()
    text = body.get("text", "").strip()
    if not text:
        return JSONResponse({"error": "empty text"}, status_code=400)
    cleaned = _format_for_tts(text)
    return JSONResponse({"text": cleaned})


def main() -> None:
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)

if __name__ == "__main__":
    main()
