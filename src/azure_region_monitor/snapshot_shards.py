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
        "default": select_default_modality(manifest_modalities),
    }
    return manifest, shards


# Core per-region modalities, in the order we prefer to open the heatmap on. These
# span (nearly) every region and are small enough to load fast, so the heatmap opens
# showing all regions instead of a single-vantage modality like model latency.
_PREFERRED_DEFAULTS = (
    "AKS Kubernetes versions",
    "Container Apps",
    "Azure Functions",
    "Azure AI models",
    "AKS extensions",
    "VM SKUs",
)


def select_default_modality(modalities: list[dict[str, Any]]) -> str | None:
    """Pick the slug the heatmap should open on.

    Prefers a real per-region modality that spans (nearly) all regions, so the
    heatmap opens full-width rather than on a single-vantage modality such as
    model latency (one 'github-global' region). Falls back to the widest, then
    smallest, modality, and finally to None when there are no modalities.
    """

    if not modalities:
        return None

    max_regions = max(int(item.get("regions", 0) or 0) for item in modalities)
    full_region = [
        item for item in modalities if int(item.get("regions", 0) or 0) >= max(2, max_regions)
    ]
    pool = full_region or list(modalities)

    by_label = {str(item.get("label", "")): item for item in pool}
    for label in _PREFERRED_DEFAULTS:
        if label in by_label:
            return str(by_label[label].get("slug"))

    # No preferred label present: widest region coverage, then fewest rows, then slug.
    best = min(
        pool,
        key=lambda item: (
            -int(item.get("regions", 0) or 0),
            int(item.get("rows", 0) or 0),
            str(item.get("slug", "")),
        ),
    )
    return str(best.get("slug"))


def _unique_slug(slug: str, used: set[str]) -> str:
    candidate = slug
    counter = 2
    while candidate in used:
        candidate = f"{slug}-{counter}"
        counter += 1
    used.add(candidate)
    return candidate
