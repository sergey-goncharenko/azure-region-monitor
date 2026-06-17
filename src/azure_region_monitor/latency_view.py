from __future__ import annotations

import re
from typing import Any

from azure_region_monitor.models import Snapshot

LATENCY_SERVICE = "model-latency"

_LATENCY_MESSAGE_RE = re.compile(
    r"p50\s+(?P<p50>\d+)ms,\s*"
    r"p95\s+(?P<p95>\d+)ms,\s*"
    r"TTFT\s+p50\s+(?P<ttft>\d+)ms,\s*"
    r"(?P<tps>[\d.]+)\s*tok/s\s+over\s+"
    r"(?P<collected>\d+)/(?P<requested>\d+)\s+samples",
    re.IGNORECASE,
)


def parse_latency_message(message: str | None) -> dict[str, Any] | None:
    """Extract structured latency metrics from a probe message.

    The model latency probe emits a stable message such as:
    "openai/gpt-4o from github-global: p50 1607ms, p95 1610ms, TTFT p50 1478ms,
    62.2 tok/s over 3/3 samples." Returns None when the message does not match.
    """

    if not message:
        return None
    match = _LATENCY_MESSAGE_RE.search(message)
    if not match:
        return None
    return {
        "p50_ms": int(match.group("p50")),
        "p95_ms": int(match.group("p95")),
        "ttft_ms": int(match.group("ttft")),
        "tokens_per_second": float(match.group("tps")),
        "samples_collected": int(match.group("collected")),
        "samples_requested": int(match.group("requested")),
    }


def build_latency_rows(snapshot: Snapshot) -> list[dict[str, Any]]:
    """Build sorted latency leaderboard rows from the model-latency modality.

    Rows are sorted by p50 latency ascending (fastest first); rows without a
    parseable p50 fall to the end. Each row carries the vantage region, model,
    status, structured metrics (when available), and the raw message.
    """

    rows: list[dict[str, Any]] = []
    for region, services in snapshot.regions.items():
        features = services.get(LATENCY_SERVICE)
        if not features:
            continue
        for feature, result in features.items():
            metrics = parse_latency_message(result.message)
            p50 = result.latency_ms if result.latency_ms is not None else (
                metrics["p50_ms"] if metrics else None
            )
            rows.append(
                {
                    "region": region,
                    "feature": feature,
                    "model": _model_label(feature),
                    "status": result.status,
                    "latency_ms": p50,
                    "p95_ms": metrics["p95_ms"] if metrics else None,
                    "ttft_ms": metrics["ttft_ms"] if metrics else None,
                    "tokens_per_second": metrics["tokens_per_second"] if metrics else None,
                    "samples_collected": metrics["samples_collected"] if metrics else None,
                    "samples_requested": metrics["samples_requested"] if metrics else None,
                    "message": result.message or "",
                }
            )

    rows.sort(key=lambda row: (row["latency_ms"] is None, row["latency_ms"] or 0, row["model"]))
    return rows


def extract_latency_metrics(snapshot: Snapshot) -> dict[str, dict[str, Any]]:
    """Return per-model latency metrics keyed by model label for history storage."""

    metrics: dict[str, dict[str, Any]] = {}
    for row in build_latency_rows(snapshot):
        metrics[row["model"]] = {
            "status": row["status"],
            "p50_ms": row["latency_ms"],
            "ttft_ms": row["ttft_ms"],
            "tokens_per_second": row["tokens_per_second"],
        }
    return metrics


def build_latency_series(history: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    """Build per-model ascending time series of p50 latency from latency history.

    Accepts a latency-history payload (with a 'days' list) and returns a mapping
    of model label to a list of {date, p50_ms} points ordered oldest-first.
    Points without a numeric p50 are skipped.
    """

    days = history.get("days", []) if isinstance(history, dict) else []
    valid_days = [day for day in days if isinstance(day, dict) and day.get("date")]
    series: dict[str, list[dict[str, Any]]] = {}
    for day in sorted(valid_days, key=lambda item: str(item["date"])):
        models = day.get("models")
        if not isinstance(models, dict):
            continue
        for model, metrics in models.items():
            if not isinstance(metrics, dict):
                continue
            p50 = metrics.get("p50_ms")
            if not isinstance(p50, (int, float)) or isinstance(p50, bool):
                continue
            series.setdefault(model, []).append({"date": str(day["date"]), "p50_ms": p50})
    return series


def _model_label(feature: str) -> str:
    label = feature
    if label.startswith("modelLatency."):
        label = label.removeprefix("modelLatency.")
    publisher, separator, rest = label.partition(".")
    if separator and rest:
        return f"{publisher}/{rest}"
    return label
