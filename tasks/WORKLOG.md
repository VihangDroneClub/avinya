# Worklog

## 2026-05-14

### T001 - Control plane created

- Created `tasks/project_plan.json` as the canonical task graph.
- Added `tasks/PROJECT_PLAN.md` for human-readable execution guidance.
- Added `tasks/STATUS.md` so progress can be tracked without chat history.
- Added `tasks/WORKLOG.md` for durable decision logging.
- Chosen strategy: extend the current Avinya repo rather than rebuild the existing Ollama/Chroma stack.

### T002 - Converter interface and factory

- Added `converters/base_converter.py` with a shared `BaseConverter` contract and `ConversionResult`.
- Added `converters/converter_factory.py` with extension-based routing and lazy registration.
- Added `converters/__init__.py` to expose the package API.
- Added `tests/test_converter_factory.py` to verify routing for PDF, DOCX/DOC, XLSX/XLS and rejection of unknown types.
- Added `tests/conftest.py` to make local repo imports work under pytest without depending on runner cwd.

### T003 - PDF conversion path

- Added `converters/pdf_converter.py` with `pypdf`-based text extraction, markdown frontmatter, and structured page sections.
- Added `tests/test_pdf_converter.py` with a handcrafted minimal PDF fixture plus failure cases for missing and invalid PDFs.
- Updated `requirements.txt` to declare `pypdf` as a dependency.
- Verified the new converter and routing tests with `7 passed`.

### T004 - DOCX and XLSX conversion paths

- Added `converters/docx_converter.py` using the available `docx` module to extract paragraphs and tables into markdown.
- Added `converters/xlsx_converter.py` with a self-contained OOXML reader for simple spreadsheets, avoiding an extra spreadsheet dependency.
- Added `tests/test_docx_xlsx_converter.py` with generated DOCX and minimal OOXML XLSX fixtures.
- Verified the office-document converters with `8 passed`.
- Hardened `converters/converter_factory.py` so it refreshes the registry before lookup in long-running processes.

### T005 - Inbox watcher and processor

- Added `processors/archiver.py` to move processed files into dated archive folders with collision-safe naming.
- Added `processors/processor.py` to convert files, archive originals, chunk markdown, and index chunks into Chroma.
- Added `processors/watcher.py` for inbox scanning and polling-based processing.
- Added `scripts/process_file.py` as a CLI entry point for single-file processing.
- Added `tests/test_processor_pipeline.py` covering inbox scanning, archiving, conversion, and indexing.
- Verified the inbox pipeline with `15 passed`.

### T006 - Categorization and markdown formatting

- Added `config/category_rules.yaml` with rule-based categories and priorities.
- Added `processors/categorizer.py` to score filename and content against category rules.
- Added `processors/formatter.py` to normalize frontmatter and emit a standard markdown envelope.
- Updated `processors/processor.py` so formatted markdown is written before archiving and indexing.
- Added `tests/test_categorizer_formatter.py` to verify category selection and markdown frontmatter generation.
- Verified the categorization and formatting stack with `18 passed`.

### T007 - RAG API

- Added `rag/retriever.py` to expose query context objects, metadata filters, and source chunk metadata.
- Added `rag/indexer.py` to support full vault reindexing and stats tracking.
- Added `rag/api.py` with `/query`, `/reindex`, `/health`, and `/stats` endpoints.
- Updated `retrieval.py` to delegate to the new retriever module.
- Added `tests/test_rag_api.py` and `tests/test_rag_indexer.py` for the API surface and vault-relative reindexing.
- Added config paths and dependency declarations for the API stack.
- Verified the RAG stack with `23 passed`.

### T008 - Query filtering and reranking

- Added `rag/types.py` to share `SourceChunk` and `QueryResult` without circular imports.
- Added `rag/reranker.py` with a lightweight lexical reranking pass over retrieved chunks.
- Extended `rag/retriever.py` and `rag/api.py` with an optional `rerank` flag.
- Added `tests/test_rag.py` to verify category/date filters and reranked source ordering.
- Verified the query filtering and reranking slice with `26 passed`.

### T009 - Telegram integration surface

- Added `telegram/commands.py` for command parsing and simple response objects.
- Added `telegram/bot.py` as a framework-agnostic surface that routes queries, health, and reindex requests to the local RAG API.
- Added upload intake that saves incoming files into the inbox with collision-safe naming.
- Added `tests/test_telegram_surface.py` to verify command parsing, API routing, and upload handling.
- Extended `core/config.py` with Telegram API base URL and token placeholders.
- Verified the Telegram surface with `30 passed`.

### T010 - Handover and operations docs

- Added `docs/HANDOVER.md` for setup, startup order, runtime commands, and maintenance guidance.
- Added `docs/API_REFERENCE.md` for `/query`, `/reindex`, `/health`, and `/stats`.
- Added `docs/TROUBLESHOOTING.md` for Ollama, indexing, upload, and desktop recovery steps.
- Finalized the project tracker so no planned tasks remain.

### Deployment model setup

- Removed the previously installed local model so the machine could be reset for the option-B configuration.
- Pulled and installed `hermes3:8b-llama3.1-q4_K_M` for the reasoning role.
- Pulled and installed `gemma2:2b-instruct-q4_K_M` for the default and summary roles.
- Updated `core/config.py` defaults to point at the installed model pair.
- Verified the installed models with `ollama list`.
- Ran a minimal runtime check against both installed models to confirm they generate responses.

### Telegram bot runtime

- Added `telegram/runtime.py` as the live bot runner using `pyTelegramBotAPI`.
- Added `scripts/run_telegram_bot.py` as the start command for the Telegram bot.
- Added allowed-chat-id filtering and document upload processing through the existing inbox pipeline.
- Installed `pytest` and `pyTelegramBotAPI` into the project virtualenv.
- Verified the Telegram runtime with `9 passed` and confirmed the runner CLI starts with `--help`.
- Added explicit validation for real BotFather tokens so the runner fails fast on placeholders like `...`.

### Desktop and API cleanup

- Added reliable auto-scroll handling to `ui/desktop.py` so new chat content stays in view and mousewheel scrolling works over the transcript.
- Added `GET /` and `GET /favicon.ico` to `rag/api.py` so browser startup no longer shows 404 noise.
- Updated `docs/TROUBLESHOOTING.md` to document the new API root behavior.
- Fixed the stale RAG API test expectation to match the current default model pair.
- Verified the updated API and Telegram slice with `16 passed`.

### Feynman-style desktop redesign

- Added `ui/feynman_desktop.py` with a dark, compact, source-first desktop shell.
- Rewired `scripts/launch_desktop.sh` to launch the new desktop module directly.
- Rebuilt the conversation surface around a scrollable transcript and lighter side panels.
- Reduced the inspector to sources, notes, and session state instead of dumping backend detail.
- Kept the orange accent palette and simplified the composer so it behaves like a command workspace.
- Verified the new desktop module imports cleanly and passes syntax checks.
