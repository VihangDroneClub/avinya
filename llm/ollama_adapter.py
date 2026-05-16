from __future__ import annotations

import json
from typing import Generator
from urllib.parse import urlparse

import requests

from core.config import OLLAMA_GENERATE_URL, OLLAMA_TIMEOUT_CONNECT, OLLAMA_TIMEOUT_READ


class OllamaError(Exception):
    pass


def check_ollama() -> None:
    """Raise OllamaError if the server is not reachable."""
    parsed = urlparse(OLLAMA_GENERATE_URL)
    base = f"{parsed.scheme}://{parsed.netloc}"
    try:
        r = requests.get(f"{base}/api/tags", timeout=OLLAMA_TIMEOUT_CONNECT)
        r.raise_for_status()
    except requests.RequestException as e:
        raise OllamaError(
            f"Cannot reach Ollama at {base}. Start it with: ollama serve"
        ) from e


def generate_stream(prompt: str, model: str) -> Generator[str, None, None]:
    payload = {"model": model, "prompt": prompt, "stream": True}

    try:
        response = requests.post(
            OLLAMA_GENERATE_URL,
            json=payload,
            stream=True,
            timeout=(OLLAMA_TIMEOUT_CONNECT, OLLAMA_TIMEOUT_READ),
        )
        if response.status_code >= 400:
            body = response.text[:500] if response.text else ""
            raise OllamaError(f"Ollama HTTP {response.status_code}: {body}")

        for line in response.iter_lines(decode_unicode=False):
            if not line:
                continue
            try:
                data = json.loads(line.decode("utf-8") if isinstance(line, bytes) else line)
            except json.JSONDecodeError:
                continue
            if "error" in data:
                raise OllamaError(str(data["error"]))
            if "response" in data:
                yield data["response"]
            if data.get("done"):
                break
    except requests.RequestException as e:
        raise OllamaError(f"Ollama request failed: {e}") from e


def generate_text(prompt: str, model: str) -> str:
    """Non-streaming aggregation (e.g. summarization)."""
    return "".join(generate_stream(prompt, model))
