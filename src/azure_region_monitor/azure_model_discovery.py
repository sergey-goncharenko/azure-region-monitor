from __future__ import annotations

import re
from typing import Any

# Model name prefixes that are region-attributable chat models worth probing.
DEFAULT_INCLUDE = (
    "gpt-4o",
    "gpt-4.1",
    "gpt-5",
    "o3",
    "o4-mini",
)
# Substrings that mark non-chat or unsuitable variants.
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
    "pro",
)
DEFAULT_MAX_MODELS = 8


def select_regional_standard_models(
    models_by_region: dict[str, list[dict[str, Any]]],
    include: tuple[str, ...] = DEFAULT_INCLUDE,
    exclude: tuple[str, ...] = DEFAULT_EXCLUDE,
    max_models: int = DEFAULT_MAX_MODELS,
) -> list[dict[str, Any]]:
    """Pick OpenAI models that offer a single-region Standard SKU, per region.

    ``models_by_region`` maps an Azure region to the JSON returned by
    ``az cognitiveservices model list --location <region>``. For each model name we
    choose one version (the newest version that offers a regional Standard SKU in the
    most regions) and list the regions that support that exact name+version+Standard.

    Returns a list shaped for the regional-latency Bicep ``models`` parameter:
    ``[{name, version, deploymentName, regions: [...]}]``. Pure and offline-testable.
    """

    # (name, version) -> set of regions offering a regional Standard SKU.
    regions_by_model_version: dict[tuple[str, str], set[str]] = {}
    for region, items in models_by_region.items():
        if not isinstance(items, list):
            continue
        for item in items:
            name, version = _standard_model(item, include, exclude)
            if name is None:
                continue
            regions_by_model_version.setdefault((name, version), set()).add(region)

    # For each model name, choose the best single version.
    best_by_name: dict[str, tuple[str, set[str]]] = {}
    for (name, version), regions in regions_by_model_version.items():
        current = best_by_name.get(name)
        if current is None or _version_rank(version, len(regions)) > _version_rank(
            current[0], len(current[1])
        ):
            best_by_name[name] = (version, regions)

    selected = sorted(best_by_name.items(), key=lambda entry: entry[0])[:max_models]
    return [
        {
            "name": name,
            "version": version,
            "deploymentName": name,
            "regions": sorted(regions),
        }
        for name, (version, regions) in selected
    ]


def _standard_model(
    item: object, include: tuple[str, ...], exclude: tuple[str, ...]
) -> tuple[str | None, str]:
    if not isinstance(item, dict) or item.get("kind") != "OpenAI":
        return None, ""
    model = item.get("model")
    if not isinstance(model, dict):
        return None, ""
    name = str(model.get("name", "")).strip()
    version = str(model.get("version", "")).strip()
    if not name or not version:
        return None, ""
    lowered = name.lower()
    if not any(lowered.startswith(prefix) for prefix in include):
        return None, ""
    if any(token in lowered for token in exclude):
        return None, ""
    skus = model.get("skus")
    if not isinstance(skus, list):
        return None, ""
    if not any(isinstance(s, dict) and s.get("name") == "Standard" for s in skus):
        return None, ""
    return name, version


def _version_rank(version: str, region_count: int) -> tuple:
    # Newer version wins; ties break on the number of regions offering it.
    digits = tuple(int(part) for part in re.findall(r"\d+", version))
    return (digits, region_count)
