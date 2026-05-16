# Avinya — The Member Who Never Graduates

Avinya is the permanent AI member of **Vihang Drone Club**. Built by seniors before they left, it holds the club's collective knowledge — projects, history, rules, budgets, decisions, and lessons learned — so that future members are never without guidance.

> "No one is there every time, and contact after graduation can't be kept all the time. Avinya fixes that."

## What It Does

- **Answers questions** about the club using indexed documents (meeting notes, budgets, project reports)
- **Guides new members** through onboarding, safety rules, and club culture
- **Preserves institutional memory** — knowledge doesn't leave when seniors graduate
- **Accepts new knowledge** — upload documents to keep the club's brain growing
- **Works offline** — runs locally with Ollama, no cloud dependencies

## Quick Start

### Web Interface (Recommended — works on any device)

```bash
# Ingest the built-in knowledge base first
./venv/bin/python scripts/ingest_knowledge_base.py

# Start the web server
./venv/bin/python -m web.server
```

Then open `http://<server-ip>:8080` on any device — phone, laptop, tablet.

### Desktop App (For laptop use)

```bash
./scripts/launch_desktop.sh
```

### CLI

```bash
./venv/bin/python app.py
```

### Telegram Bot

```bash
AVINYA_TELEGRAM_BOT_TOKEN=<token> ./venv/bin/python scripts/run_telegram_bot.py
```

## Knowledge Base

The `knowledge_base/` directory contains structured club knowledge:

| File | Purpose |
|---|---|
| `faq.md` | Frequently asked questions about the club |
| `onboarding_guide.md` | New member onboarding — safety, skills, culture |
| `history_and_traditions.md` | Club history, traditions, and lessons learned |

To add your own documents:
1. Place them in `knowledge_base/` or upload via the web interface
2. Run `./venv/bin/python scripts/ingest_knowledge_base.py`
3. Or use the "Upload Knowledge" button in the web UI

## Architecture

- **LLM**: Ollama (`gemma2:2b` for responses, `hermes3:8b` for reasoning)
- **Embeddings**: `BAAI/bge-small-en-v1.5`
- **Vector DB**: ChromaDB
- **Web**: FastAPI + vanilla HTML/CSS/JS (no frontend framework needed)
- **Desktop**: CustomTkinter (Python Tkinter)
- **Voice**: Piper TTS, faster-whisper STT, openwakeword

## Project Structure

```
avinya/
├── web/                    # Web interface (new)
│   ├── server.py           # FastAPI web server
│   └── static/
│       ├── index.html      # Single-page app
│       ├── style.css       # Mobile-first responsive design
│       └── app.js          # Frontend logic
├── ui/                     # Desktop interfaces
│   ├── feynman_desktop.py  # Current desktop app (dark theme)
│   ├── laptop_desktop.py   # Light theme variant
│   └── desktop.py          # Compatibility wrapper
├── knowledge_base/         # Structured club knowledge
│   ├── faq.md
│   ├── onboarding_guide.md
│   └── history_and_traditions.md
├── core/                   # Core modules (config, prompts, sessions)
├── rag/                    # Retrieval-augmented generation
├── llm/                    # Ollama adapter and model router
├── memory/                 # Session memory and summarization
├── voice/                  # TTS, STT, wake word, orchestrator
├── telegram/               # Telegram bot
├── processors/             # Document processing
├── converters/             # File format conversion
├── scripts/                # Launchers and utilities
├── prompts/                # System prompts
└── tasks/                  # Project planning
```

## For Seniors Contributing Knowledge

Before you graduate:
1. Upload your project files, meeting notes, and reports
2. Add context — explain what future members should know
3. Document decisions and their reasoning
4. Record lessons learned from failures and successes
5. Update Avinya with your contact info if you're willing to be reached

The more you put in, the more valuable Avinya becomes for those who come after you.

## Models

```bash
ollama pull gemma2:2b-instruct-q4_K_M
ollama pull hermes3:8b-llama3.1-q4_K_M
```

## Repo Contract

The existing Avinya modules remain the source of truth for:
- prompt assembly
- memory compression
- embeddings
- retrieval
- Ollama generation

Do not duplicate those subsystems unless a change explicitly requires replacement.
