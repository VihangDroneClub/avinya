# Troubleshooting

## Ollama Is Unreachable

Symptoms:
- CLI prints an Ollama warning on startup
- `/health` reports `ollama: unhealthy`
- `/query` returns a 503

Fix:

```bash
ollama serve
```

Make sure the models referenced in `core/config.py` are present.

## Query Returns No Useful Passages

Symptoms:
- the answer is generic
- the query response has few or no sources

Fix:
1. Rebuild the index with `POST /reindex`.
2. Confirm the markdown files exist in the vault.
3. Check that document categories were written into frontmatter.

## Reindex Fails or Returns Zero Files

Symptoms:
- `/reindex` reports zero indexed files
- index count stays flat after new docs are added

Fix:
1. Verify the vault path in `core/config.py` or `AVINYA_VAULT_PATH`.
2. Confirm the files are `.md`.
3. Confirm the files are under the vault root, not only in the inbox or archive.

## Uploads Appear in Inbox But Nothing Gets Indexed

Symptoms:
- Telegram uploads save to the inbox
- no markdown or Chroma entries appear

Fix:
1. Run the processor manually:

```bash
./venv/bin/python scripts/process_file.py --input ~/vihang_data/inbox/example.pdf --vault ~/vihang_data/vault --archive ~/vihang_data/archive
```

2. Check that the file type is supported.
3. Check the console for `ConversionError`.

## Module Import Errors Under Pytest

Symptoms:
- local imports fail in test runs

Fix:
- Run tests from the repo root.
- Keep `tests/conftest.py` in place so the repo root is injected into `sys.path`.

## Desktop UI Does Not Open

Symptoms:
- `scripts/launch_desktop.sh` exits immediately

Fix:
- Confirm `customtkinter` and `pillow` are installed in `./venv`.
- Launch from the repo root:

```bash
./scripts/launch_desktop.sh
```

The launcher now points at `ui/feynman_desktop.py`.

## Browser Shows 404 on `/`

Symptoms:
- opening `http://127.0.0.1:8000/` returns 404
- browser requests `/favicon.ico`

Fix:
- The API now serves a basic root response and a no-op favicon route.
- If you still see 404s, restart the RAG API after pulling the latest code.

## Maintenance Check

Use these checks when the system drifts:

1. `GET /health`
2. `GET /stats`
3. `./venv/bin/python app.py`
4. `./scripts/launch_desktop.sh`
5. `./venv/bin/python scripts/process_file.py --input ...`
