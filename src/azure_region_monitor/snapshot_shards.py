from __future__ import annotations

import re
from typing import Any, Iterable

STATUSES = ("available", "unavailable", "partial", "unknown")


def modality_slug(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    return slug or "other"


def build_summary(
    timestamp: str, regions: Iterable[str], rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """Tiny headline payload: timestamp, region count, status and modality counts."""

    status_counts: dict[str, int] = {status: 0 for status in STATUSES}
    modality_counts: dict[str, dict[str, int]] = {}
    for row in rows:
        status = str(row.get("status", "unknown"))
        status_counts[status] = status_counts.get(status, 0) + 1
        modality = str(row.get("category", "unknown"))
        bucket = modality_counts.setdefault(
            modality, {"checks": 0, **{status_key: 0 for status_key in STATUSES}}
        )
        bucket["checks"] += 1
        bucket[status] = bucket.get(status, 0) + 1
    return {
        "timestamp": timestamp,
        "regions": len(list(regions)),
        "checks": len(rows),
        "status_counts": status_counts,
        "modality_counts": dict(sorted(modality_counts.items())),
    }


def build_modality_shards(
    timestamp: str, regions: Iterable[str], rows: list[dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Split flattened rows into per-modality shards plus a manifest.

    Returns (manifest, shards) where shards maps slug -> shard payload. Each shard
    row keeps region, service, feature, status, and message so the heatmap can
    render details and search without loading any other modality.
    """

    by_modality: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_modality.setdefault(str(row.get("category", "unknown")), []).append(row)

    used_slugs: set[str] = set()
    manifest_modalities: list[dict[str, Any]] = []
    shards: dict[str, dict[str, Any]] = {}
    for label in sorted(by_modality):
        slug = _unique_slug(modality_slug(label), used_slugs)
        modality_rows = by_modality[label]
        modality_regions = sorted({str(row.get("region", "")) for row in modality_rows if row.get("region")})
        shard_rows = [
            {
                "region": row.get("region", ""),
                "service": row.get("service", ""),
                "feature": row.get("feature", ""),
                "status": row.get("status", "unknown"),
                "message": row.get("message", ""),
            }
            for row in modality_rows
        ]
        shards[slug] = {
            "timestamp": timestamp,
            "modality": label,
            "slug": slug,
            "regions": modality_regions,
            "rows": shard_rows,
        }
        manifest_modalities.append(
            {
                "slug": slug,
                "label": label,
                "rows": len(shard_rows),
                "regions": len(modality_regions),
                "path": f"modalities/{slug}.json",
            }
        )

    manifest = {
        "timestamp": timestamp,
        "regions": sorted({str(region) for region in regions}),
        "modalities": manifest_modalities,
    }
    return manifest, shards


def _unique_slug(slug: str, used: set[str]) -> str:
    candidate = slug
    counter = 2
    while candidate in used:
        candidate = f"{slug}-{counter}"
        counter += 1
    used.add(candidate)
    return candidate
