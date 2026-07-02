from __future__ import annotations

import re
from typing import Any

from azure_region_monitor.models import Snapshot

LATENCY_SERVICE = "model-latency"
REGIONAL_LATENCY_SERVICE = "ai-latency"

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


def build_regional_latency_rows(snapshot: Snapshot) -> list[dict[str, Any]]:
    """Build per-region rows for the Azure (ai-latency) modality.

    Each Azure OpenAI deployment is single-region, so rows are keyed by the real
    Azure region. Sorted by p50 ascending (fastest region first). Rows without a
    parseable p50 fall to the end.
    """

    rows: list[dict[str, Any]] = []
    for region, services in snapshot.regions.items():
        features = services.get(REGIONAL_LATENCY_SERVICE)
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
                    "model": _regional_model_label(feature),
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

    rows.sort(key=lambda row: (row["latency_ms"] is None, row["latency_ms"] or 0, row["region"]))
    return rows


def _regional_model_label(feature: str) -> str:
    label = feature
    if label.startswith("aiLatency."):
        label = label.removeprefix("aiLatency.")
    # Drop only the publisher segment; the model name itself may contain dots
    # (for example "openai.gpt-5.1" -> "gpt-5.1").
    _publisher, separator, model = label.partition(".")
    return model if separator and model else label


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


def extract_regional_latency_metrics(snapshot: Snapshot) -> dict[str, dict[str, Any]]:
    """Return Azure per-region latency metrics for history storage.

    Shaped as ``{model_label: {region: {status, p50_ms}}}`` so region speed rankings
    can be compared across snapshots. Only the fields needed for ranking are kept.
    """

    metrics: dict[str, dict[str, dict[str, Any]]] = {}
    for row in build_regional_latency_rows(snapshot):
        model = str(row["model"])
        region = str(row["region"])
        metrics.setdefault(model, {})[region] = {
            "status": row["status"],
            "p50_ms": row["latency_ms"],
        }
    return metrics


def _ranks_from_metrics(metrics: dict[str, Any] | None) -> dict[str, int]:
    """Rank labels by ascending p50 (fastest = rank 1); skip non-numeric p50."""

    if not isinstance(metrics, dict):
        return {}
    ranked = [
        (label, entry["p50_ms"])
        for label, entry in metrics.items()
        if isinstance(entry, dict)
        and isinstance(entry.get("p50_ms"), (int, float))
        and not isinstance(entry.get("p50_ms"), bool)
    ]
    ranked.sort(key=lambda item: (item[1], item[0]))
    return {label: index + 1 for index, (label, _p50) in enumerate(ranked)}


def _latest_previous_day(history: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return the most recent latency-history day that precedes the newest one."""

    days = history.get("days", []) if isinstance(history, dict) else []
    valid = [day for day in days if isinstance(day, dict) and day.get("date")]
    if len(valid) < 2:
        return None
    ordered = sorted(valid, key=lambda day: str(day["date"]), reverse=True)
    return ordered[1]


def previous_leaderboard_ranks(history: dict[str, Any] | None) -> dict[str, int]:
    """Model -> rank in the previous snapshot's GitHub Models leaderboard."""

    previous = _latest_previous_day(history)
    if previous is None:
        return {}
    return _ranks_from_metrics(previous.get("models"))


def previous_regional_ranks(history: dict[str, Any] | None) -> dict[str, dict[str, int]]:
    """Model -> {region -> rank} in the previous snapshot's per-region tables."""

    previous = _latest_previous_day(history)
    if previous is None:
        return {}
    regional = previous.get("regional")
    if not isinstance(regional, dict):
        return {}
    return {
        str(model): _ranks_from_metrics(regions)
        for model, regions in regional.items()
        if isinstance(regions, dict)
    }


def annotate_rank_changes(
    rows: list[dict[str, Any]],
    previous_ranks: dict[str, int],
    key_field: str = "model",
) -> list[dict[str, Any]]:
    """Annotate rows in-place with rank movement vs a previous ranking.

    Rows are expected pre-sorted fastest-first. Rows with a numeric ``latency_ms``
    get a 1-based ``rank``; each row also gets ``previous_rank``, ``rank_delta``
    (previous - current, so positive means moved up), and ``rank_state`` which is
    one of ``up``, ``down``, ``same``, ``new`` (unranked before), or ``none``
    (no numeric latency this snapshot).
    """

    position = 0
    for row in rows:
        latency = row.get("latency_ms")
        has_rank = isinstance(latency, (int, float)) and not isinstance(latency, bool)
        if has_rank:
            position += 1
            row["rank"] = position
        else:
            row["rank"] = None

        previous = previous_ranks.get(str(row.get(key_field, "")))
        row["previous_rank"] = previous

        if row["rank"] is None:
            row["rank_delta"] = None
            row["rank_state"] = "none"
        elif previous is None:
            row["rank_delta"] = None
            row["rank_state"] = "new"
        else:
            delta = previous - row["rank"]
            row["rank_delta"] = delta
            row["rank_state"] = "up" if delta > 0 else "down" if delta < 0 else "same"
    return rows


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
