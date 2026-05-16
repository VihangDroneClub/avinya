"""Basic tests for Avinya core modules."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for d in ["core", "llm", "rag", "prompts", "embeddings", "vector_db", "utils"]:
    p = str(ROOT / d)
    if p not in sys.path and Path(p).exists():
        sys.path.insert(0, p)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_config_defaults():
    from core.config import MODEL_DEFAULT, MODEL_REASONING, SESSION_MAX_TURNS
    assert MODEL_DEFAULT, "MODEL_DEFAULT should not be empty"
    assert MODEL_REASONING, "MODEL_REASONING should not be empty"
    assert SESSION_MAX_TURNS > 0, "SESSION_MAX_TURNS should be positive"


def test_ollama_adapter_import():
    from llm.ollama_adapter import OllamaError, check_ollama, generate_stream, generate_text
    assert callable(check_ollama)
    assert callable(generate_stream)
    assert callable(generate_text)


def test_llm_router():
    from llm.router import choose_model
    assert callable(choose_model)
    model = choose_model("What is Python?")
    assert model, "choose_model should return a model name"


def test_markdown_parser():
    import re
    text = "**bold** and `code` and *italic*"
    pattern = r'(\*\*(.+?)\*\*)|(`(.+?)`)|(\*(.+?)\*)'
    matches = list(re.finditer(pattern, text))
    assert len(matches) == 3


def test_system_prompt():
    from prompts.system_prompt import SYSTEM_PROMPT
    assert SYSTEM_PROMPT
    assert "Avinya" in SYSTEM_PROMPT
    assert "Vihang" in SYSTEM_PROMPT


def test_rag_types():
    try:
        from rag.types import QueryResult, SourceChunk
        assert QueryResult
        assert SourceChunk
    except ImportError:
        pass  # Dependencies not installed in test env


def test_web_server_import():
    try:
        from web.server import app
        assert app.title == "Avinya Web"
    except ImportError:
        pass  # Dependencies not installed in test env


if __name__ == "__main__":
    tests = [
        test_config_defaults,
        test_ollama_adapter_import,
        test_llm_router,
        test_markdown_parser,
        test_system_prompt,
        test_rag_types,
        test_web_server_import,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  PASS: {test.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL: {test.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
