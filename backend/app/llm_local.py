"""
Local LLM client — the pilot's language layer runs ON-PREMISE, not in a cloud.

The copilot uses a small quantized instruct model (a 3B is plenty for
grounded Q&A over structured context) served by Ollama on localhost. No data
ever leaves the machine and the marginal cost per question is zero — exactly
what a pricing tool handling commercial data wants in a pilot.

Configuration (env):
    MAPLE_LLM_URL     base URL of the Ollama server (default http://localhost:11434)
    MAPLE_LLM_MODEL   model tag (default qwen2.5:3b — ~2GB quantized)

The client is strictly best-effort: if the server is down or the model is
missing, callers get None and the copilot falls back to its deterministic
answer built from the same context — the pilot never breaks.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

DEFAULT_URL = os.getenv("MAPLE_LLM_URL", "http://localhost:11434").rstrip("/")
DEFAULT_MODEL = os.getenv("MAPLE_LLM_MODEL", "qwen2.5:3b")


def llm_status() -> dict:
    """Is the local model server up, and is our model pulled?"""
    try:
        with urllib.request.urlopen(f"{DEFAULT_URL}/api/tags", timeout=3) as r:
            tags = json.loads(r.read())
        models = [m.get("name", "") for m in tags.get("models", [])]
        ready = any(m.split(":")[0] == DEFAULT_MODEL.split(":")[0] for m in models)
        return {
            "server": "up",
            "url": DEFAULT_URL,
            "model": DEFAULT_MODEL,
            "model_ready": ready,
            "available_models": models,
        }
    except Exception as exc:  # noqa: BLE001 - down is a normal state
        return {
            "server": "down",
            "url": DEFAULT_URL,
            "model": DEFAULT_MODEL,
            "model_ready": False,
            "error": str(exc)[:200],
        }


def local_chat(
    system: str,
    user: str,
    *,
    model: str | None = None,
    timeout: float = 120.0,
) -> str | None:
    """One chat completion against the local model. None on ANY failure."""
    payload = {
        "model": model or DEFAULT_MODEL,
        "stream": False,
        "options": {"temperature": 0.1, "num_ctx": 8192},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    try:
        req = urllib.request.Request(
            f"{DEFAULT_URL}/api/chat",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read())
        text = (body.get("message") or {}).get("content", "")
        return text.strip() or None
    except Exception:  # noqa: BLE001 - fall back to deterministic answer
        return None
