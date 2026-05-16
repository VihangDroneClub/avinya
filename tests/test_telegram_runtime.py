from __future__ import annotations

from pathlib import Path

import pytest

from telegram.runtime import build_upload_message, is_chat_allowed, parse_allowed_chat_ids, validate_bot_token


def test_parse_allowed_chat_ids_handles_whitespace() -> None:
    assert parse_allowed_chat_ids(" 12, 34 , -56 ") == (12, 34, -56)


def test_parse_allowed_chat_ids_rejects_bad_values() -> None:
    with pytest.raises(ValueError):
        parse_allowed_chat_ids("12,abc")


def test_chat_allowlist_open_when_empty() -> None:
    assert is_chat_allowed(123, ())


def test_chat_allowlist_restricts_when_configured() -> None:
    assert is_chat_allowed(7, (7, 9))
    assert not is_chat_allowed(8, (7, 9))


def test_build_upload_message_formats_paths() -> None:
    message = build_upload_message(Path("/tmp/vault/doc.md"), Path("/tmp/archive/doc.pdf"), 3)
    assert "doc.md" in message
    assert "doc.pdf" in message
    assert "Indexed chunks: 3" in message


def test_validate_bot_token_rejects_placeholder() -> None:
    with pytest.raises(RuntimeError):
        validate_bot_token("...")


def test_validate_bot_token_requires_colon() -> None:
    with pytest.raises(RuntimeError):
        validate_bot_token("not-a-token")


def test_validate_bot_token_returns_clean_value() -> None:
    assert validate_bot_token(" 123:abc ") == "123:abc"
