from __future__ import annotations

import http.client
import json
import re
import urllib.error

REASONING_MIN_COMPLETION_TOKENS = 512


def _is_reasoning_model(model: str) -> bool:
    name = model.split("/")[-1].lower()
    if "gpt-5-chat" in name:
        return False
    if name.startswith(("gpt-5", "gpt-6")):
        return True
    return bool(re.match(r"o\d", name))


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value.strip()))
    except (TypeError, ValueError):
        return None


def _read_error_body(error: urllib.error.HTTPError) -> str:
    """Read an HTTP error body without letting a truncated/broken read escape."""

    try:
        return error.read().decode("utf-8", errors="replace").strip()
    except (http.client.HTTPException, OSError):
        return ""


def _safe_json(payload: str) -> dict | None:
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _chunk_has_content(chunk: dict) -> bool:
    choices = chunk.get("choices")
    if not isinstance(choices, list):
        return False
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta")
        if isinstance(delta, dict) and delta.get("content"):
            return True
    return False


def _usage_output_tokens(chunk: dict) -> int | None:
    usage = chunk.get("usage")
    if not isinstance(usage, dict):
        return None
    value = usage.get("completion_tokens")
    return value if isinstance(value, int) else None
