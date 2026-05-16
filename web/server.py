"""Avinya Web — browser-based interface for the Vihang AI club member."""

from __future__ import annotations

import json
import queue
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.config import MODEL_DEFAULT, MODEL_REASONING, SESSION_MAX_TURNS, VAULT_PATH
from core.prompt_builder import build_full_prompt
from core.session_ops import maybe_roll_summary
from core.startup import initialise_system
from llm.ollama_adapter import OllamaError, check_ollama, generate_stream
from llm.router import choose_model
from memory.session_memory import SessionMemory
from memory.summarizer import summarize_conversation
from rag.retriever import retrieve_query_context
from rag.indexer import reindex_vault
from prompts.system_prompt import SYSTEM_PROMPT

app = FastAPI(title="Avinya Web", version="2.0")

static_dir = _ROOT / "web" / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

_sessions: dict[str, dict] = {}
_ready = False
_ollama_ok = False


@app.on_event("startup")
def startup() -> None:
    global _ready, _ollama_ok
    try:
        initialise_system()
        _ready = True
    except Exception:
        pass
    try:
        check_ollama()
        _ollama_ok = True
    except Exception:
        pass


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


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    index_file = static_dir / "index.html"
    if index_file.exists():
        return HTMLResponse(content=index_file.read_text())
    return HTMLResponse(content="<h1>Avinya Web — index.html not found</h1>", status_code=404)


@app.get("/api/health")
def health() -> JSONResponse:
    return JSONResponse({
        "ready": _ready,
        "ollama": _ollama_ok,
        "status": "ok" if _ready and _ollama_ok else "degraded",
    })


@app.post("/api/chat/stream")
async def chat_stream(request: Request) -> Response:
    body = await request.json()
    message = body.get("message", "").strip()
    session_id = body.get("session_id", "default")

    if not message:
        return JSONResponse({"error": "empty message"}, status_code=400)

    if not _ready or not _ollama_ok:
        return JSONResponse({"error": "backend not ready"}, status_code=503)

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
    body = await request.json()
    message = body.get("message", "").strip()
    session_id = body.get("session_id", "default")

    if not message:
        return JSONResponse({"error": "empty message"}, status_code=400)

    if not _ready or not _ollama_ok:
        return JSONResponse({"error": "backend not ready"}, status_code=503)

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
def list_sessions() -> JSONResponse:
    result = []
    for sid, s in _sessions.items():
        result.append({
            "id": sid,
            "title": s["title"],
            "created": s["created"],
            "updated": s["updated"],
            "message_count": len(s["messages"]),
        })
    result.sort(key=lambda x: x["updated"], reverse=True)
    return JSONResponse(result)


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str) -> JSONResponse:
    if session_id not in _sessions:
        return JSONResponse({"error": "not found"}, status_code=404)
    s = _sessions[session_id]
    return JSONResponse({
        "id": s["id"],
        "title": s["title"],
        "messages": s["messages"],
        "summary": s["memory"].get_summary(),
    })


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str) -> JSONResponse:
    if session_id in _sessions:
        del _sessions[session_id]
    return JSONResponse({"status": "ok"})


@app.post("/api/reindex")
def reindex() -> JSONResponse:
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
async def upload_file(file: UploadFile = File(...)) -> JSONResponse:
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


@app.get("/api/knowledge")
def list_knowledge() -> JSONResponse:
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


def main() -> None:
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()
