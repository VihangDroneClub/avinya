# Avinya / Vihang AI Context

This repository is the local working base for the Vihang AI knowledge automation system built on top of Avinya.

## Current State

The system is complete enough to run end to end locally:

- document ingestion for PDF, DOCX, and XLSX
- categorization and markdown formatting
- archive of processed originals
- ChromaDB indexing and retrieval
- FastAPI query, reindex, health, and stats endpoints
- Telegram command surface and real bot runner
- Feynman-style desktop UI for laptop use
- voice stack with Jarvis mode, TTS, STT, and wake word detection

## Key Entry Points

From `/home/pratik/avinya`:

```bash
./venv/bin/python app.py
```

Runs the CLI entrypoint.

```bash
./scripts/launch_desktop.sh
```

Runs the current desktop UI shell.

```bash
./venv/bin/uvicorn rag.api:app --host 127.0.0.1 --port 8000
```

Runs the local RAG API.

```bash
./venv/bin/python scripts/process_file.py --input <file> --vault ~/vihang_data/vault --archive ~/vihang_data/archive
```

Processes one document manually.

```bash
AVINYA_TELEGRAM_BOT_TOKEN=<real_token> ./venv/bin/python scripts/run_telegram_bot.py
```

Runs the Telegram bot. Use a real BotFather token.

## Models On The Machine

The local Ollama setup uses the current lightweight pair:

- `gemma2:2b-instruct-q4_K_M` for default responses
- `hermes3:8b-llama3.1-q4_K_M` for reasoning

Embeddings use `BAAI/bge-small-en-v1.5`.

## Desktop UI Notes

The old desktop shell was replaced with a Feynman-style interface:

- dark, compact, source-first layout
- left rail for actions and recent turns
- center transcript with normal scrolling
- right side panel for sources and session notes
- orange accent on black panels

Current module:

- `ui/feynman_desktop.py`

Launcher:

- `scripts/launch_desktop.sh`

## Voice Stack Notes

Jarvis mode exists and the Piper TTS mismatch was fixed by aligning `voice/tts.py` with the installed Piper API. The voice thread now catches synthesis failures instead of crashing the app.

Voice modules:

- `voice/tts.py`
- `voice/stt.py`
- `voice/wake_word.py`
- `voice/audio_recorder.py`
- `voice/orchestrator.py`

## Repo Contract

The existing Avinya modules remain the source of truth for:

- prompt assembly
- memory compression
- embeddings
- retrieval
- Ollama generation

Do not duplicate those subsystems unless a change explicitly requires replacement.

## Durable Project Files

- `tasks/project_plan.json`
- `tasks/STATUS.md`
- `tasks/WORKLOG.md`
- `docs/HANDOVER.md`
- `docs/API_REFERENCE.md`
- `docs/TROUBLESHOOTING.md`

## Notes For Next Work

The next likely extension is to evaluate replacing the current `CKB/` document source with Graphify-based knowledge generation if that integrates cleanly with the existing ingestion and vault pipeline.
