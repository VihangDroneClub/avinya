# VIHANG AI Handover

## What This System Is

Vihang AI is a local document automation and RAG system built on top of the existing Avinya codebase.

Current capabilities:
- convert PDF, DOCX, and XLSX files into structured markdown
- categorize and format documents before indexing
- archive originals into dated folders
- index markdown into ChromaDB
- answer questions through a local FastAPI RAG service
- expose a Telegram-facing command surface and a real Telegram bot runner

## Repository Layout

- `app.py` starts the CLI after bootstrapping embeddings and the vector DB
- `ui/feynman_desktop.py` contains the current desktop interface
- `scripts/launch_desktop.sh` launches the Feynman-style desktop shell
- `scripts/process_file.py` processes one inbox file end to end
- `rag/api.py` serves `/query`, `/reindex`, `/health`, and `/stats`
- `telegram/bot.py` is the integration surface for command routing and upload intake
- `telegram/runtime.py` runs the real Telegram bot via `pyTelegramBotAPI`
- `tasks/STATUS.md` shows current project state
- `tasks/WORKLOG.md` records implementation history
- `tasks/project_plan.json` is the canonical task graph

## Prerequisites

- Python environment in `./venv`
- Ollama running locally
- ChromaDB persistence available in `./chroma_db`
- Model files already pulled into Ollama:
  - `gemma2:2b-instruct-q4_K_M`
  - `hermes3:8b-llama3.1-q4_K_M`

## Runtime Commands

From `/home/pratik/avinya`:

```bash
./venv/bin/python app.py
```

Starts the terminal CLI. This is the default entrypoint in the repo.

```bash
./venv/bin/python -m ui.desktop
```

Starts the desktop UI wrapper for the Feynman-style shell.

```bash
./venv/bin/python scripts/process_file.py --input ~/vihang_data/inbox/sample.pdf --vault ~/vihang_data/vault --archive ~/vihang_data/archive
```

Processes one file, writes markdown into the vault, archives the original, and indexes the result.

```bash
./venv/bin/uvicorn rag.api:app --host 127.0.0.1 --port 8000
```

Starts the local RAG API.

```bash
AVINYA_TELEGRAM_BOT_TOKEN=... ./venv/bin/python scripts/run_telegram_bot.py
```

Starts the Telegram bot runner and connects it to the local RAG API.
Use a real BotFather token in the form `<digits>:<secret>`, not `...`.

## Recommended Startup Order

1. Start Ollama.
2. Start the RAG API.
3. Start the CLI, desktop UI, or Telegram bot runner.
4. Process or upload documents.

## Maintenance

- Run the health endpoint when something looks wrong.
- Rebuild the vault index after large document changes.
- Keep the `tasks/STATUS.md` and `tasks/WORKLOG.md` files updated if more work is added.

## Current Repo Contract

The existing Avinya modules are the source of truth for:
- prompt assembly
- memory compression
- embeddings
- retrieval
- Ollama generation

Avoid duplicating those subsystems unless a change explicitly requires replacement.
