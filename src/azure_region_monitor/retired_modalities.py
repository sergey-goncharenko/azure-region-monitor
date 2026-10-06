"""Modalities that are no longer probed, with the reason readers see.

A retired category is removed from the live snapshot when snapshots are merged,
so its last results do not linger as current evidence. Retained history keeps
the old observations.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetiredModality:
    category: str
    label: str
    retired_on: str
    reason: str
    source_url: str


RETIRED_MODALITIES: dict[str, RetiredModality] = {
    "modelLatency": RetiredModality(
        category="modelLatency",
        label="GitHub Models latency",
        retired_on="2026-07-30",
        reason="GitHub retired the GitHub Models service, so its global endpoint no longer answers.",
        source_url=(
            "https://github.blog/changelog/"
            "2026-07-01-github-models-is-being-fully-retired-on-july-30-2026/"
        ),
    ),
}


def retired_modality(feature: str) -> RetiredModality | None:
    return RETIRED_MODALITIES.get(feature.split(".", 1)[0])
