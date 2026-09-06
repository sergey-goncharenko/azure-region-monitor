"""Public page identity shared by feedback and optional reader measurements."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

REPOSITORY_URL = "https://github.com/sergey-goncharenko/azure-region-monitor"
SITE_URL = "https://azwatch.operator.lat"
PROTOCOL_VERSION = "reader-check-v1"
READING_BUDGET_MS = 15_000


def presentation_id() -> str:
    root = Path(__file__).resolve().parent
    paths = [
        root / "static_site.py", root / "blog.py", root / "briefing_view.py",
        root / "display.py", root / "feature_context.py", root / "feedback_context.py",
        root / "github_feedback.py", root / "reader_feedback.py",
        root / "assets" / "dashboard.css", root / "assets" / "briefing.js",
        root / "assets" / "github-feedback.js", root / "assets" / "reader-feedback.js",
    ]
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_text(encoding="utf-8").encode("utf-8"))
    return digest.hexdigest()[:16]


def measurement_context(day: dict[str, Any], view_id: str) -> dict[str, Any]:
    briefing = day["briefing"]
    facts = {
        "current_timestamp": briefing["current_timestamp"],
        "previous_timestamp": briefing.get("previous_timestamp"),
        "counts": briefing["counts"],
        "scope": briefing.get("scope", {}),
        "groups": [
            {key: group[key] for key in ("kind", "modality", "feature_count", "listing_count", "region_counts")}
            for group in briefing["groups"]
        ],
    }
    encoded = json.dumps(facts, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "protocol": PROTOCOL_VERSION, "view_id": view_id,
        "case_id": hashlib.sha256(encoded).hexdigest()[:16],
        "date": day["date"], "current_timestamp": briefing["current_timestamp"],
        "previous_timestamp": briefing.get("previous_timestamp"),
        "reading_budget_ms": READING_BUDGET_MS, "repository_url": REPOSITORY_URL,
    }
