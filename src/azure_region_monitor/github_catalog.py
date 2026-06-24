from __future__ import annotations

import json
import os
import urllib.request

from azure_region_monitor.config import LatencyModel

DEFAULT_CATALOG_URL = "https://models.github.ai/catalog/models"
DEFAULT_PUBLISHERS = ("openai",)
# Substrings that mark non-chat or unsuitable models for a latency leaderboard.
DEFAULT_EXCLUDE = (
    "audio",
    "realtime",
    "transcribe",
    "diarize",
    "image",
    "embedding",
    "embeddings",
    "tts",
    "whisper",
    "dall",
    "codex",
)
DEFAULT_MAX_MODELS = 24


def select_catalog_models(
    catalog: list[dict],
    publishers: tuple[str, ...] = DEFAULT_PUBLISHERS,
    exclude: tuple[str, ...] = DEFAULT_EXCLUDE,
    max_models: int = DEFAULT_MAX_MODELS,
) -> list[LatencyModel]:
    """Select chat-capable text models from a GitHub Models catalog payload.

    Keeps models whose publisher is in ``publishers`` and that take and return text,
    excluding ids containing any ``exclude`` substring (audio, embeddings, codex, ...).
    Returns deterministic LatencyModel entries, capped at ``max_models``. Pure: no
    network, so it is fully unit-testable.
    """

    allowed = {p.lower() for p in publishers}
    selected: list[LatencyModel] = []
    seen: set[str] = set()
    for item in catalog:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id", "")).strip()
        if not model_id or model_id in seen:
            continue
        publisher = str(item.get("publisher", "")).strip().lower()
        if allowed and publisher not in allowed:
            continue
        if not _is_text_chat(item):
            continue
        lowered = model_id.lower()
        if any(token in lowered for token in exclude):
            continue
        feature = _feature_key(model_id)
        if feature is None:
            continue
        seen.add(model_id)
        selected.append(LatencyModel(feature=feature, model=model_id))

    selected.sort(key=lambda model: model.model)
    return selected[:max_models]


def _is_text_chat(item: dict) -> bool:
    inputs = item.get("supported_input_modalities")
    outputs = item.get("supported_output_modalities")
    if not isinstance(inputs, list) or not isinstance(outputs, list):
        return False
    return "text" in inputs and "text" in outputs


def _feature_key(model_id: str) -> str | None:
    publisher, separator, model = model_id.partition("/")
    if not separator or not model:
        return None
    return f"modelLatency.{publisher.lower()}.{model}"


def fetch_catalog(token: str | None = None, url: str = DEFAULT_CATALOG_URL, timeout: int = 30) -> list[dict]:
    """Fetch the GitHub Models catalog. Raises on transport or decode failure."""

    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload if isinstance(payload, list) else []


def default_catalog_fetcher() -> list[dict]:
    token = os.environ.get("GITHUB_MODELS_TOKEN") or os.environ.get("GITHUB_TOKEN")
    return fetch_catalog(token=token)
