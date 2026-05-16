# Architecture 108 — Avinya Roadmap

> "The member who never graduates" — Vihang Drone Club's permanent AI knowledge system.

## Vision

Avinya exists so that when seniors graduate, their knowledge doesn't leave with them. It is the one member who is always here, always remembers, and always helps — whether it's 2 AM before a competition or the first day a new member walks into the workspace.

---

## Current Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        ACCESS LAYER                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │  Web UI      │  │  Desktop UI  │  │  Telegram Bot        │   │
│  │  (mobile)    │  │  (laptop)    │  │  (messaging)         │   │
│  │  FastAPI+JS  │  │  CustomTkinter│  │  pyTelegramBotAPI    │   │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘   │
│         │                 │                      │               │
│         └─────────────────┼──────────────────────┘               │
│                           ▼                                      │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    APPLICATION LAYER                       │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │   │
│  │  │  LLM     │  │  RAG     │  │  Memory  │  │  Voice   │  │   │
│  │  │  Ollama  │  │  Retriever│  │  Session │  │  TTS/STT │  │   │
│  │  │  Router  │  │  ChromaDB│  │  Summary │  │  Jarvis  │  │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                           │                                      │
│                           ▼                                      │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    DATA LAYER                              │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │   │
│  │  │  Vault   │  │  ChromaDB│  │  Sessions│  │  Archive │  │   │
│  │  │  (MD)    │  │  (Vector)│  │  (JSON)  │  │  (Files) │  │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                           ▲                                      │
│                           │                                      │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                  INGESTION LAYER                           │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │   │
│  │  │  PDF     │  │  DOCX    │  │  XLSX    │  │  Upload  │  │   │
│  │  │  Parser  │  │  Parser  │  │  Parser  │  │  (Web)   │  │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘  │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Completed

- [x] Core RAG pipeline (ChromaDB + Ollama + embeddings)
- [x] Document ingestion (PDF, DOCX, XLSX)
- [x] CLI interface
- [x] Desktop UI (Feynman-style, dark theme, 3-panel layout)
- [x] Desktop UI features (light/dark toggle, sessions, export, regenerate, markdown rendering, syntax highlighting, keyboard shortcuts)
- [x] Telegram bot interface
- [x] Voice stack (Jarvis mode, TTS, STT, wake word)
- [x] Web interface (mobile-first, streaming chat, any device)
- [x] Club personality system prompt (Avinya as permanent member)
- [x] Structured knowledge base (FAQ, onboarding guide, history & traditions)
- [x] Knowledge upload flow (drag & drop via web UI)
- [x] Session management (multiple conversations, load/delete)
- [x] Auto-knowledge capture (conversations saved per session)
- [x] PIN authentication for web interface (env: AVINYA_WEB_PIN)
- [x] Document search endpoint and UI (search across indexed documents)
- [x] Docker deployment (Dockerfile + docker-compose.yml)
- [x] Ollama error handling and health reporting
- [x] Backup strategy — automated script with rotation (keeps last 7)
- [x] Systemd service files for auto-start on boot
- [x] Document viewer — read vault files in-browser
- [x] Conversation export — download any chat as Markdown
- [x] PWA support — installable on phones (manifest + service worker)
- [x] Voice note upload — audio file ingestion endpoint
- [x] Structured logging — timestamps, levels, journal integration
- [x] Basic test suite — 7 tests covering config, LLM, router, markdown, prompts, types
- [x] Consolidated desktop UI — fixed ui/desktop.py wrapper
- [x] Bulk folder upload — drag entire folders or select multiple files at once
- [x] Knowledge graph — graph generation, API endpoint, visual browser in web UI
- [x] Image/schematic support — upload images with descriptions, indexed into vault
- [x] Meeting note capture — record meetings, auto-summarize, extract action items
- [x] Rate limiting — configurable rate limiter middleware on web API

---

## Phase 1: Make It Actually Useful (Now)

### 1.1 Always-On Deployment
- [x] Dockerize the entire stack (web server + Ollama + ChromaDB)
- [x] Docker Compose for one-command deployment
- [ ] Deploy on a Raspberry Pi 5 or old laptop for 24/7 access
- [x] Auto-start on boot (systemd service files provided)
- [x] Network access — bind to 0.0.0.0:8080
- [x] Backup strategy — automated script with rotation

### 1.2 Better Knowledge Onboarding
- [x] Voice note upload — audio file upload endpoint
- [x] Bulk upload — drag entire folders, not just single files
- [ ] Knowledge review flow — preview what was extracted before indexing
- [ ] Context prompts — when uploading, ask "what should future members know about this?"
- [ ] Tagging system — categorize documents (project, budget, meeting, technical, tutorial)

### 1.3 Web UI Improvements
- [x] Authentication — simple PIN or password so only club members can access
- [x] Search — search across all indexed documents directly
- [x] Document viewer — click a source to read the full document in-browser
- [x] Conversation export — download any conversation as Markdown
- [x] Offline indicator — health endpoint reports Ollama status
- [x] PWA support — install as an app on phones

---

## Phase 2: Make It Smart

### 2.1 Knowledge Graph
- [x] Extract entities from documents (people, projects, dates, decisions)
- [x] Build a graph of relationships between documents and topics
- [x] Visual knowledge graph browser
- [ ] "Related documents" suggestions in chat responses

### 2.2 Proactive Knowledge
- [ ] Avinya suggests documents when a topic comes up
- [ ] "You might also want to read..." after answering
- [ ] Gap detection — identifies topics members ask about but have no documents
- [ ] Alerts seniors: "3 people asked about X but we have no docs on it"

### 2.3 Better Responses
- [x] Image support — show diagrams, circuit schematics, photos from documents
- [ ] Table rendering — display tabular data from spreadsheets properly
- [ ] Citation linking — click a citation to jump to the exact passage
- [ ] Response confidence — show how certain Avinya is about an answer
- [ ] Multi-document synthesis — combine info from multiple sources with attribution

---

## Phase 3: Make It Indispensable

### 3.1 Club Operations
- [x] Meeting note capture — record meetings, auto-summarize, extract action items
- [ ] Project tracker — track project status, blockers, and milestones
- [ ] Inventory management — know what parts the club has and where
- [ ] Event calendar — competitions, build sessions, flight days
- [ ] Member directory — who knows what, who to ask for help

### 3.2 Multi-Modal Input
- [ ] Photo upload — take a photo of a circuit board, ask "what is this?"
- [ ] Schematic analysis — upload a circuit diagram, get explanation
- [ ] Video processing — extract knowledge from recorded tech talks
- [ ] Audio transcription — transcribe and index recorded meetings

### 3.3 Community Features
- [ ] Q&A board — members post questions, Avinya answers, seniors can correct
- [ ] Knowledge contributions — members can add notes that get indexed
- [ ] "Ask a senior" fallback — if Avinya doesn't know, route to a human
- [ ] Usage analytics — what are members asking about? what's missing?

---

## Phase 4: Make It Last Forever

### 4.1 Self-Maintenance
- [ ] Auto-reindex on file changes
- [ ] Health monitoring — alert when something breaks
- [ ] Self-diagnosis — "I notice I haven't been asked about X in a while"
- [ ] Knowledge freshness — flag outdated information
- [ ] Auto-cleanup — remove duplicate or superseded documents

### 4.2 Portability
- [ ] Export entire knowledge base as a portable package
- [ ] Import from other clubs' Avinya instances
- [ ] Template system — new clubs can start with a base knowledge set
- [ ] Version control for knowledge — track how club knowledge evolves

### 4.3 Succession
- [ ] Annual knowledge audit — prompt graduating seniors to contribute
- [ ] Knowledge transfer reports — what was added this year, what's missing
- [ ] "State of the club" auto-generated report each semester
- [ ] Mentor matching — Avinya suggests which senior can help with what

---

## Technical Debt & Fixes

- [ ] Fix `ui/desktop.py` — currently a wrapper, ensure it works correctly
- [ ] Consolidate duplicate code between `feynman_desktop.py` and `laptop_desktop.py`
- [ ] Add proper error handling for Ollama connection drops
- [ ] Add rate limiting to web API
- [ ] Add logging and monitoring
- [ ] Add tests for core modules
- [ ] Reduce memory usage for large document collections
- [ ] Improve embedding quality for technical documents

---

## File Structure

```
avinya/
├── web/                          # Web interface
│   ├── server.py                 # FastAPI web server
│   └── static/
│       ├── index.html            # Single-page app
│       ├── style.css             # Mobile-first responsive CSS
│       └── app.js                # Frontend logic
├── ui/                           # Desktop interfaces
│   ├── feynman_desktop.py        # Current desktop app
│   ├── laptop_desktop.py         # Light theme variant
│   └── desktop.py                # Compatibility wrapper
├── knowledge_base/               # Structured club knowledge
│   ├── faq.md
│   ├── onboarding_guide.md
│   └── history_and_traditions.md
├── core/                         # Core modules
│   ├── config.py
│   ├── prompt_builder.py
│   ├── session_ops.py
│   └── startup.py
├── rag/                          # Retrieval-augmented generation
│   ├── api.py
│   ├── indexer.py
│   ├── reranker.py
│   ├── retriever.py
│   └── types.py
├── llm/                          # Ollama integration
│   ├── ollama_adapter.py
│   └── router.py
├── memory/                       # Session memory
│   ├── session_memory.py
│   └── summarizer.py
├── voice/                        # Voice stack
│   ├── audio_recorder.py
│   ├── orchestrator.py
│   ├── stt.py
│   ├── tts.py
│   └── wake_word.py
├── telegram/                     # Telegram bot
├── processors/                   # Document processing
├── converters/                   # File format conversion
├── prompts/                      # System prompts
│   └── system_prompt.py
├── scripts/                      # Launchers and utilities
│   ├── ingest_knowledge_base.py
│   ├── launch_desktop.sh
│   ├── launch_web.sh
│   ├── process_file.py
│   ├── run_telegram_bot.py
│   └── update_graph.py
├── tasks/                        # Project planning
├── docs/                         # Documentation
├── tests/                        # Tests
├── embeddings/                   # Embedding models
├── vector_db/                    # Vector DB client
├── utils/                        # Utilities
├── app.py                        # CLI entry point
├── requirements.txt
├── architecture108.md            # This file
└── README.md
```

---

## Technical Debt & Fixes

- [x] Add error handling for Ollama connection drops
- [x] Add structured logging
- [x] Add basic test suite
- [x] Fix ui/desktop.py wrapper
- [x] Add rate limiting to web API
- [ ] Consolidate duplicate code between `feynman_desktop.py` and `laptop_desktop.py`
- [ ] Reduce memory usage for large document collections
- [ ] Improve embedding quality for technical documents

---

## How to Update This File

When something is completed:
1. Move the item from its phase to the "Completed" section
2. Update the date
3. Commit with a message like "Update architecture108: completed X"

When adding new items:
1. Place them in the appropriate phase
2. Be specific about what "done" looks like
3. Don't add vague items — if you can't describe what done looks like, it's not ready

---

*Last updated: 2026-05-16*
