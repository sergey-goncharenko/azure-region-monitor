from __future__ import annotations

from typing import Any


def select_physical_regions(locations: list[dict[str, Any]] | Any) -> list[str]:
    """Return sorted physical Azure region names from `az account list-locations`.

    `az account list-locations --output json` returns one entry per location. Real
    deployable regions have ``metadata.regionType == "Physical"``; logical groupings
    (for example "asia", "europe", "unitedstates") are ``"Logical"`` and are excluded.
    Filtering to Physical means brand-new Azure regions are picked up automatically
    without editing a hardcoded list. Pure and offline-testable.
    """

    if not isinstance(locations, list):
        return []

    names: set[str] = set()
    for location in locations:
        if not isinstance(location, dict):
            continue
        metadata = location.get("metadata")
        if not isinstance(metadata, dict):
            continue
        if str(metadata.get("regionType", "")).strip().lower() != "physical":
            continue
        name = str(location.get("name", "")).strip()
        if name:
            names.add(name)
    return sorted(names)
