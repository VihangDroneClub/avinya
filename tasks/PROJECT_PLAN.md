# VIHANG AI Knowledge Automation System

## Purpose
This repo now has a file-based control plane for the Vihang automation effort. The goal is to let Gemini CLI continue implementation even if chat history disappears.

The current codebase is not a blank slate. It already has:
- local Ollama generation
- Chroma-backed retrieval
- embeddings
- prompt assembly
- session memory and summarization
- CLI and desktop front ends

The right implementation path is to extend those pieces, not duplicate them.

## Control Files

- `tasks/project_plan.json`: canonical task graph
- `tasks/STATUS.md`: current progress snapshot
- `tasks/WORKLOG.md`: running implementation log

## Existing Reuse Map

| Current file | What it already does | Planned reuse |
| --- | --- | --- |
| `embeddings/embedder.py` | Loads BAAI/bge-small-en-v1.5 locally | Reuse for all indexing and retrieval |
| `retrieval.py` | Chroma query + MMR + token budget | Wrap for API and bot use |
| `core/prompt_builder.py` | Builds the final Ollama prompt | Reuse for conversational answer generation |
| `core/session_ops.py` | Rolling summary maintenance | Reuse in any long-running interface |
| `memory/session_memory.py` | Recent turns and long-term summary | Reuse for UI and bot sessions |
| `memory/summarizer.py` | Summarizes dialogue with Ollama | Reuse for memory compression |
| `llm/ollama_adapter.py` | Generates text/stream from Ollama | Reuse for all model calls |
| `llm/router.py` | Simple reasoning model selection | Reuse or replace only if the heuristic becomes a problem |
| `ingest_documents.py` | Markdown ingestion into Chroma | Use as the baseline ingestion pattern |

## Execution Order

1. Write the control plane files.
2. Build converter interfaces and type routing.
3. Implement PDF, DOCX, and XLSX conversion.
4. Add inbox watching, categorization, formatting, and archiving.
5. Wrap retrieval in a FastAPI service.
6. Add Telegram bot integration.
7. Write handover documentation and operations notes.

## Task Rules for Gemini

1. Keep each task bounded to one file set or one narrow subsystem.
2. Update `tasks/STATUS.md` after each completed task.
3. Append one short entry to `tasks/WORKLOG.md` for each meaningful decision.
4. Do not rewrite working Avinya modules unless a task explicitly requires it.
5. Prefer adapter layers over full rewrites.
6. If a dependency is missing, record it in the worklog and stop that task cleanly.

## Status Snapshot

- Control plane: started
- Converter pipeline: pending
- Inbox automation: pending
- RAG API: pending
- Telegram interface: pending
- Docs and handover: pending

## Gemini Execution Prompt

Use this when running the next task:

```text
Implement the next task from tasks/project_plan.json.

Repository root: /home/pratik/avinya
Task status file: tasks/STATUS.md
Worklog: tasks/WORKLOG.md

Requirements:
- Follow existing repo patterns.
- Do not revert other changes.
- Keep the change minimal and testable.
- Update status and worklog when finished.

Return:
1. Files changed
2. Tests run
3. Any blockers
4. Next task to run
```

