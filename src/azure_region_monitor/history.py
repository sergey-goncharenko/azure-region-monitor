from __future__ import annotations

import gzip
import json
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from azure_region_monitor.diff import build_diff
from azure_region_monitor.latency_view import (
    extract_latency_metrics,
    extract_regional_latency_metrics,
)
from azure_region_monitor.models import Change, Snapshot
from azure_region_monitor.storage import load_snapshot
from azure_region_monitor.summary import (
    ChangeContext,
    ChangeKey,
    NarrativeClient,
    build_change_narrative,
    change_key,
    expansion_label,
    feature_details,
)

RECENT_CHANGE_DAYS = 10
CHANGE_HIGHLIGHTS = 10
LATENCY_HISTORY_DAYS = 60
# A CDN blip must not abort the deploy, but a sustained outage still has to fail loudly:
# silently skipping the fetch would republish the history index with only today's day.
HISTORY_FETCH_ATTEMPTS = 3
HISTORY_RETRY_BACKOFF_SECONDS = 2.0
_REGION_GROUPS: dict[str, str] = {
    "australiaeast": "Oceania",
    "australiacentral": "Oceania",
    "australiacentral2": "Oceania",
    "australiasoutheast": "Oceania",
    "newzealandnorth": "Oceania",
    "austriaeast": "Europe",
    "belgiumcentral": "Europe",
    "denmarkeast": "Europe",
    "francecentral": "Europe",
    "francesouth": "Europe",
    "germanynorth": "Europe",
    "germanywestcentral": "Europe",
    "italynorth": "Europe",
    "northeurope": "Europe",
    "norwayeast": "Europe",
    "norwaywest": "Europe",
    "polandcentral": "Europe",
    "spaincentral": "Europe",
    "swedencentral": "Europe",
    "switzerlandnorth": "Europe",
    "switzerlandwest": "Europe",
    "uksouth": "Europe",
    "ukwest": "Europe",
    "westeurope": "Europe",
    "brazilsouth": "South America",
    "brazilsoutheast": "South America",
    "chilecentral": "South America",
    "canadacentral": "North America",
    "canadaeast": "North America",
    "centralus": "North America",
    "centraluseuap": "North America",
    "eastus": "North America",
    "eastus2": "North America",
    "eastus2euap": "North America",
    "eastusstg": "North America",
    "mexicocentral": "North America",
    "northcentralus": "North America",
    "southcentralus": "North America",
    "southcentralusstg": "North America",
    "westcentralus": "North America",
    "westus": "North America",
    "westus2": "North America",
    "westus3": "North America",
    "centralindia": "Asia",
    "eastasia": "Asia",
    "indonesiacentral": "Asia",
    "japaneast": "Asia",
    "japanwest": "Asia",
    "jioindiacentral": "Asia",
    "jioindiawest": "Asia",
    "koreacentral": "Asia",
    "koreasouth": "Asia",
    "malaysiawest": "Asia",
    "southindia": "Asia",
    "southeastasia": "Asia",
    "westindia": "Asia",
    "israelcentral": "Middle East",
    "qatarcentral": "Middle East",
    "uaecentral": "Middle East",
    "uaenorth": "Middle East",
    "southafricanorth": "Africa",
    "southafricawest": "Africa",
}


def fetch_history(history_dir: Path, base_url: str) -> bool:
    history_dir.mkdir(parents=True, exist_ok=True)
    index = _fetch_json(_join_url(base_url, "index.json"))
    if index is None:
        return False

    _write_json(history_dir / "index.json", index)
    paths = _history_paths(index)
    paths.add("recent-changes.json")
    for path in sorted(paths):
        _download_file(_join_url(base_url, path), history_dir / path)
    return True


def update_history(
    snapshot_path: Path,
    history_dir: Path,
    base_url: str | None = None,
    narrative_client: NarrativeClient | None = None,
) -> dict[str, Any]:
    history_dir.mkdir(parents=True, exist_ok=True)
    if base_url:
        fetch_history(history_dir, base_url)

    current = load_snapshot(snapshot_path)
    current_date = _snapshot_date(current)
    snapshot_history_path = Path("snapshots") / f"{current_date}.json.gz"
    change_history_path = Path("changes") / f"{current_date}.json"

    existing_index = _read_json(history_dir / "index.json") or {}
    _migrate_history_snapshot_paths(history_dir, existing_index)
    previous_entry = _previous_snapshot_entry(existing_index, current_date)
    previous = _load_previous_snapshot(history_dir, previous_entry)
    diff = build_diff(previous, current) if previous else None
    changes = diff.changes if diff else []
    change_contexts = _build_change_contexts(history_dir, existing_index, current_date, changes, previous, current)

    _write_snapshot_gzip(history_dir / snapshot_history_path, current)
    day_summary = _build_day_summary(
        current=current,
        current_date=current_date,
        snapshot_path=snapshot_history_path,
        change_path=change_history_path,
        previous_entry=previous_entry,
        changes=changes,
        narrative=build_change_narrative(
            changes, client=narrative_client, contexts=change_contexts, date=current_date
        ),
        change_contexts=change_contexts,
    )
    _write_json(history_dir / change_history_path, day_summary)

    days_by_date = {
        str(day.get("date")): day
        for day in existing_index.get("days", [])
        if isinstance(day, dict) and day.get("date")
    }
    days_by_date[current_date] = day_summary
    days = sorted(days_by_date.values(), key=lambda day: str(day["date"]), reverse=True)

    generated_at = _utc_now()
    index = {
        "generated_at": generated_at,
        "latest_date": current_date,
        "latest_snapshot_path": str(snapshot_history_path).replace("\\", "/"),
        "recent_changes_path": "recent-changes.json",
        "days": days,
    }
    recent_changes = {
        "generated_at": generated_at,
        "days": _recent_change_days(days, current_date),
    }

    _write_json(history_dir / "index.json", index)
    _write_json(history_dir / "recent-changes.json", recent_changes)
    _update_latency_history(history_dir, current, current_date, generated_at)
    return recent_changes


def _update_latency_history(
    history_dir: Path, snapshot: Snapshot, current_date: str, generated_at: str
) -> None:
    path = history_dir / "latency-history.json"
    existing = _read_json(path) or {}
    days_by_date = {
        str(day.get("date")): day
        for day in existing.get("days", [])
        if isinstance(day, dict) and day.get("date")
    }
    if not days_by_date:
        days_by_date.update(_backfill_latency_history(history_dir))

    entry = _latency_history_entry(snapshot, current_date)
    if entry is not None:
        days_by_date[current_date] = entry

    days = sorted(days_by_date.values(), key=lambda day: str(day["date"]), reverse=True)
    _write_json(
        path,
        {"generated_at": generated_at, "days": days[:LATENCY_HISTORY_DAYS]},
    )


def _latency_history_entry(snapshot: Snapshot, date: str) -> dict[str, Any] | None:
    metrics = extract_latency_metrics(snapshot)
    regional = extract_regional_latency_metrics(snapshot)
    if not metrics and not regional:
        return None
    entry: dict[str, Any] = {"date": date, "models": metrics}
    if regional:
        entry["regional"] = regional
    return entry


def _backfill_latency_history(history_dir: Path) -> dict[str, dict[str, Any]]:
    snapshots_dir = history_dir / "snapshots"
    if not snapshots_dir.exists():
        return {}
    result: dict[str, dict[str, Any]] = {}
    for gz_path in sorted(snapshots_dir.glob("*.json.gz"))[-LATENCY_HISTORY_DAYS:]:
        try:
            snapshot = _load_history_snapshot(gz_path)
        except (OSError, ValueError):
            continue
        date = _snapshot_date(snapshot)
        entry = _latency_history_entry(snapshot, date)
        if entry is not None:
            result[date] = entry
    return result


def _build_day_summary(
    *,
    current: Snapshot,
    current_date: str,
    snapshot_path: Path,
    change_path: Path,
    previous_entry: dict[str, Any] | None,
    changes: list[Change],
    narrative: dict[str, Any] | None = None,
    change_contexts: dict[ChangeKey, ChangeContext] | None = None,
) -> dict[str, Any]:
    change_type_counts: dict[str, int] = {}
    for change in changes:
        change_type_counts[change.change_type] = change_type_counts.get(change.change_type, 0) + 1
    status_counts = _status_counts(current)

    return {
        "date": current_date,
        "snapshot_timestamp": _normalize_timestamp(current.timestamp).isoformat(),
        "snapshot_path": str(snapshot_path).replace("\\", "/"),
        "change_path": str(change_path).replace("\\", "/"),
        "previous_date": previous_entry.get("date") if previous_entry else None,
        "previous_snapshot_path": previous_entry.get("snapshot_path") if previous_entry else None,
        "total_changes": len(changes),
        "change_type_counts": {
            "new_availability": change_type_counts.get("new_availability", 0),
            "regression": change_type_counts.get("regression", 0),
            "status_change": change_type_counts.get("status_change", 0),
        },
        "parked_unknown_changes": _parked_unknown_change_count(changes),
        "status_counts": status_counts,
        "summary_counts": _summary_counts(current, status_counts),
        "modality_counts": _modality_counts(current),
        "change_context_counts": _change_context_counts(change_contexts or {}),
        "narrative": (narrative or {}).get("narrative", ""),
        "editorial_excerpt": (narrative or {}).get("editorial_excerpt", ""),
        "social_drafts": (narrative or {}).get("social_drafts", {}),
        "narrative_source": (narrative or {}).get("narrative_source", "rule"),
        "narrative_fallback_reason": (narrative or {}).get("narrative_fallback_reason"),
        "narrative_model_deployment": (narrative or {}).get("narrative_model_deployment"),
        "narrative_generation_error": (narrative or {}).get("narrative_generation_error"),
        "narrative_mcp_status": (narrative or {}).get("narrative_mcp_status"),
        "narrative_mcp_error": (narrative or {}).get("narrative_mcp_error"),
        "narrative_grounding_status": (narrative or {}).get("narrative_grounding_status"),
        "narrative_microsoft_learn_urls": (narrative or {}).get(
            "narrative_microsoft_learn_urls", []
        ),
        "highlights": [
            _summarize_change(change, (change_contexts or {}).get(change_key(change)))
            for change in _highlight_changes(changes)
        ],
    }


def _recent_change_days(days: list[dict[str, Any]], current_date: str) -> list[dict[str, Any]]:
    current = next((day for day in days if day.get("date") == current_date), None)
    previous_change_days = [
        day
        for day in days
        if day.get("date") != current_date and _clear_signal_count(day) > 0
    ]
    if current is None:
        return previous_change_days[:RECENT_CHANGE_DAYS]
    return [current, *previous_change_days][:RECENT_CHANGE_DAYS]


def _clear_signal_count(day: dict[str, Any]) -> int:
    counts = day.get("change_type_counts")
    if not isinstance(counts, dict):
        return 0
    return int(counts.get("new_availability", 0)) + int(counts.get("regression", 0))


def _highlight_changes(changes: list[Change]) -> list[Change]:
    priority = {"regression": 0, "new_availability": 1, "status_change": 2}
    clear_signal_changes = [
        change for change in changes if change.change_type in {"regression", "new_availability"}
    ]
    return sorted(
        clear_signal_changes,
        key=lambda change: (
            priority.get(change.change_type, 3),
            change.region,
            _feature_category(change.feature),
            change.feature,
        ),
    )[:CHANGE_HIGHLIGHTS]


def _parked_unknown_change_count(changes: list[Change]) -> int:
    return sum(1 for change in changes if "unknown" in {change.previous, change.current})


def _summarize_change(change: Change, context: ChangeContext | None = None) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "region": change.region,
        "service": change.service,
        "modality": _feature_category(change.feature),
        "group": _feature_group(change.feature),
        "feature": change.feature,
        "previous": change.previous,
        "current": change.current,
        "change_type": change.change_type,
    }
    if context is not None:
        summary.update(
            {
                "classification": context.classification,
                "classification_label": context.label,
                "expansion_kind": context.expansion_kind,
                "expansion_label": expansion_label(context.expansion_kind, context.region_group),
                "region_group": context.region_group,
                "history_days": context.history_days,
                "available_days": context.available_days,
                "missing_days": context.missing_days,
                "unknown_days": context.unknown_days,
                "unavailable_pct": context.unavailable_pct,
                "prior_disappearances": context.prior_disappearances,
                "last_available_date": context.last_available_date,
                "last_missing_date": context.last_missing_date,
                "feature_total_regions": context.feature_total_regions,
                "feature_previous_available_regions": context.feature_previous_available_regions,
                "feature_current_available_regions": context.feature_current_available_regions,
                "feature_previous_coverage_pct": context.feature_previous_coverage_pct,
                "feature_current_coverage_pct": context.feature_current_coverage_pct,
                "feature_coverage_delta": context.feature_coverage_delta,
                "feature_deprecated_coverage_pct": context.feature_deprecated_coverage_pct,
                "region_group_previous_available_regions": context.region_group_previous_available_regions,
                "region_group_current_available_regions": context.region_group_current_available_regions,
                "same_day_new_regions": list(context.same_day_new_regions),
                "still_available_regions": list(context.still_available_regions),
                "details_url": context.details_url,
                "details_label": context.details_label,
                "feature_note": context.feature_note,
            }
        )
    return summary


def _build_change_contexts(
    history_dir: Path,
    existing_index: dict[str, Any],
    current_date: str,
    changes: list[Change],
    previous: Snapshot | None,
    current: Snapshot,
) -> dict[ChangeKey, ChangeContext]:
    signals = [change for change in changes if change.change_type in {"new_availability", "regression"}]
    if not signals:
        return {}

    keys = {change_key(change) for change in signals}
    features = {(change.service, change.feature) for change in signals}
    timelines = _historical_timelines(history_dir, existing_index, current_date, keys)
    historical_feature_regions = _historical_feature_regions(
        history_dir,
        existing_index,
        current_date,
        features,
    )
    return {
        change_key(change): _classify_change_context(
            change,
            timelines.get(change_key(change), []),
            previous,
            current,
            historical_feature_regions.get((change.service, change.feature), set()),
        )
        for change in signals
    }


def _historical_timelines(
    history_dir: Path,
    existing_index: dict[str, Any],
    current_date: str,
    keys: set[ChangeKey],
) -> dict[ChangeKey, list[tuple[str, str | None]]]:
    timelines = {key: [] for key in keys}
    days: list[tuple[str, str]] = []
    for day in existing_index.get("days", []):
        if not isinstance(day, dict):
            continue
        date = str(day.get("date", "")).strip()
        snapshot_path = day.get("snapshot_path")
        if not date or date >= current_date or not isinstance(snapshot_path, str):
            continue
        days.append((date, snapshot_path))

    for date, snapshot_path in sorted(days):
        try:
            snapshot = _load_history_snapshot(_safe_history_path(history_dir, snapshot_path))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        for key in keys:
            timelines[key].append((date, _snapshot_status(snapshot, key)))
    return timelines


def _historical_feature_regions(
    history_dir: Path,
    existing_index: dict[str, Any],
    current_date: str,
    features: set[tuple[str, str]],
) -> dict[tuple[str, str], set[str]]:
    regions_by_feature = {feature: set() for feature in features}
    days: list[tuple[str, str]] = []
    for day in existing_index.get("days", []):
        if not isinstance(day, dict):
            continue
        date = str(day.get("date", "")).strip()
        snapshot_path = day.get("snapshot_path")
        if not date or date >= current_date or not isinstance(snapshot_path, str):
            continue
        days.append((date, snapshot_path))

    for _date, snapshot_path in sorted(days):
        try:
            snapshot = _load_history_snapshot(_safe_history_path(history_dir, snapshot_path))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        for service, feature in features:
            regions_by_feature[(service, feature)].update(_available_regions(snapshot, service, feature))
    return regions_by_feature


def _snapshot_status(snapshot: Snapshot, key: ChangeKey) -> str | None:
    region, service, feature = key
    result = snapshot.regions.get(region, {}).get(service, {}).get(feature)
    return result.status if result is not None else None


def _classify_change_context(
    change: Change,
    timeline: list[tuple[str, str | None]],
    previous: Snapshot | None,
    current: Snapshot,
    historical_feature_regions: set[str],
) -> ChangeContext:
    first_available = next((index for index, (_, status) in enumerate(timeline) if status == "available"), None)
    statuses_since_first = timeline[first_available:] if first_available is not None else []
    prior_disappearances = _prior_disappearance_count(statuses_since_first)
    available_days = sum(1 for _, status in timeline if status == "available")
    missing_days = sum(1 for _, status in timeline if status in {None, "unavailable"})
    unknown_days = sum(1 for _, status in timeline if status in {"unknown", "partial"})
    last_available_date = _last_status_date(timeline, {"available"})
    last_missing_date = _last_status_date(timeline, {None, "unavailable"})
    unavailable_pct = _pct(missing_days, len(timeline))
    feature_context = _feature_context(change, previous, current, available_days, historical_feature_regions)

    if change.change_type == "new_availability":
        classification = "restored_availability" if available_days else "net_new_availability"
    elif not timeline or available_days == 0:
        classification = "uncertain_regression"
    elif prior_disappearances or unknown_days:
        classification = "recurring_regression"
    else:
        classification = "deprecation_candidate"

    return ChangeContext(
        classification=classification,
        history_days=len(timeline),
        available_days=available_days,
        missing_days=missing_days,
        unknown_days=unknown_days,
        unavailable_pct=unavailable_pct,
        prior_disappearances=prior_disappearances,
        last_available_date=last_available_date,
        last_missing_date=last_missing_date,
        **feature_context,
    )


def _feature_context(
    change: Change,
    previous: Snapshot | None,
    current: Snapshot,
    historical_region_available_days: int,
    historical_feature_regions: set[str],
) -> dict[str, Any]:
    previous_regions = _available_regions(previous, change.service, change.feature) if previous else set()
    current_regions = _available_regions(current, change.service, change.feature)
    total_regions = len(current.regions)
    region_group = _region_group(change.region)
    previous_group_regions = _regions_in_group(previous_regions, region_group)
    current_group_regions = _regions_in_group(current_regions, region_group)
    same_day_new_regions = tuple(sorted(current_regions - previous_regions))
    coverage_delta = len(current_regions) - len(previous_regions)
    deprecated_coverage_pct = _pct(max(len(previous_regions) - len(current_regions), 0), len(previous_regions))
    expansion_kind = _expansion_kind(
        change,
        historical_region_available_days,
        historical_feature_regions,
        _regions_in_group(historical_feature_regions, region_group),
    )
    details_label, details_url, feature_note = feature_details(change.feature)

    return {
        "region_group": region_group,
        "expansion_kind": expansion_kind,
        "feature_total_regions": total_regions,
        "feature_previous_available_regions": len(previous_regions),
        "feature_current_available_regions": len(current_regions),
        "feature_previous_coverage_pct": _pct(len(previous_regions), total_regions),
        "feature_current_coverage_pct": _pct(len(current_regions), total_regions),
        "feature_coverage_delta": coverage_delta,
        "feature_deprecated_coverage_pct": deprecated_coverage_pct,
        "region_group_previous_available_regions": len(previous_group_regions),
        "region_group_current_available_regions": len(current_group_regions),
        "same_day_new_regions": same_day_new_regions,
        "still_available_regions": tuple(sorted(current_regions)),
        "details_url": details_url,
        "details_label": details_label,
        "feature_note": feature_note,
    }


def _available_regions(snapshot: Snapshot, service: str, feature: str) -> set[str]:
    regions: set[str] = set()
    for region, services in snapshot.regions.items():
        result = services.get(service, {}).get(feature)
        if result is not None and result.status == "available":
            regions.add(region)
    return regions


def _regions_in_group(regions: set[str], region_group: str | None) -> set[str]:
    if region_group is None:
        return set()
    return {region for region in regions if _region_group(region) == region_group}


def _expansion_kind(
    change: Change,
    historical_region_available_days: int,
    historical_feature_regions: set[str],
    historical_group_regions: set[str],
) -> str | None:
    if change.change_type != "new_availability":
        return None
    if historical_region_available_days > 0:
        return "restored_region"
    if not historical_feature_regions:
        return "new_feature"
    if not historical_group_regions:
        return "region_group_first"
    return "regional_expansion"


def _region_group(region: str) -> str | None:
    return _REGION_GROUPS.get(region)


def _pct(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator * 100 / denominator, 1)


def _prior_disappearance_count(timeline: list[tuple[str, str | None]]) -> int:
    disappearances = 0
    previous_status: str | None = None
    for _, status in timeline:
        if previous_status == "available" and status in {None, "unavailable"}:
            disappearances += 1
        previous_status = status
    return disappearances


def _last_status_date(timeline: list[tuple[str, str | None]], statuses: set[str | None]) -> str | None:
    for date, status in reversed(timeline):
        if status in statuses:
            return date
    return None


def _change_context_counts(contexts: dict[ChangeKey, ChangeContext]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for context in contexts.values():
        counts[context.classification] = counts.get(context.classification, 0) + 1
    return dict(sorted(counts.items()))


def _status_counts(snapshot: Snapshot) -> dict[str, int]:
    counts = {"available": 0, "unavailable": 0, "partial": 0, "unknown": 0}
    for _, _, _, status in _iter_statuses(snapshot):
        counts[status] = counts.get(status, 0) + 1
    return counts


def _summary_counts(snapshot: Snapshot, status_counts: dict[str, int]) -> dict[str, int]:
    features = {feature for _, _, feature, _ in _iter_statuses(snapshot)}
    return {
        "regions": len(snapshot.regions),
        "features": len(features),
        "checks": sum(status_counts.values()),
    }


def _modality_counts(snapshot: Snapshot) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for _, _, feature, status in _iter_statuses(snapshot):
        modality = _feature_category(feature)
        modality_counts = counts.setdefault(
            modality,
            {"checks": 0, "available": 0, "unavailable": 0, "partial": 0, "unknown": 0},
        )
        modality_counts["checks"] += 1
        modality_counts[status] = modality_counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def _iter_statuses(snapshot: Snapshot):
    for region, services in snapshot.regions.items():
        for service, features in services.items():
            for feature, result in features.items():
                yield region, service, feature, result.status


def _previous_snapshot_entry(index: dict[str, Any], current_date: str) -> dict[str, Any] | None:
    days = [day for day in index.get("days", []) if isinstance(day, dict)]
    previous_days = [day for day in days if str(day.get("date")) < current_date]
    if previous_days:
        return max(previous_days, key=lambda day: str(day.get("date")))

    same_day = [day for day in days if day.get("date") == current_date]
    return same_day[0] if same_day else None


def _load_previous_snapshot(history_dir: Path, entry: dict[str, Any] | None) -> Snapshot | None:
    if not entry or not entry.get("snapshot_path"):
        return None
    path = _safe_history_path(history_dir, str(entry["snapshot_path"]))
    if not path.exists():
        return None
    return _load_history_snapshot(path)


def _load_history_snapshot(path: Path) -> Snapshot:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            return Snapshot.model_validate_json(stream.read())
    return load_snapshot(path)


def _write_snapshot_gzip(path: Path, snapshot: Snapshot) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(snapshot.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        stream.write(payload)


def _migrate_history_snapshot_paths(history_dir: Path, index: dict[str, Any]) -> None:
    path_map: dict[str, str] = {}
    for day in index.get("days", []):
        if not isinstance(day, dict):
            continue
        snapshot_path = day.get("snapshot_path")
        if not isinstance(snapshot_path, str) or not snapshot_path.endswith(".json"):
            continue
        if not _is_safe_relative_path(snapshot_path):
            continue
        compressed_path = f"{snapshot_path}.gz"
        source = history_dir / snapshot_path
        target = history_dir / compressed_path
        if source.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                with source.open("rb") as input_stream, gzip.open(target, "wb") as output_stream:
                    shutil.copyfileobj(input_stream, output_stream)
            source.unlink()
        if target.exists():
            path_map[snapshot_path] = compressed_path
            day["snapshot_path"] = compressed_path

    if not path_map:
        return

    latest_snapshot_path = index.get("latest_snapshot_path")
    if isinstance(latest_snapshot_path, str) and latest_snapshot_path in path_map:
        index["latest_snapshot_path"] = path_map[latest_snapshot_path]

    for day in index.get("days", []):
        if not isinstance(day, dict):
            continue
        previous_snapshot_path = day.get("previous_snapshot_path")
        if isinstance(previous_snapshot_path, str) and previous_snapshot_path in path_map:
            day["previous_snapshot_path"] = path_map[previous_snapshot_path]


def _history_paths(index: dict[str, Any]) -> set[str]:
    paths: set[str] = set()
    for day in index.get("days", []):
        if not isinstance(day, dict):
            continue
        for key in ("snapshot_path", "change_path"):
            value = day.get(key)
            if isinstance(value, str) and _is_safe_relative_path(value):
                paths.add(value)
    return paths


def _is_transient_http_status(code: int) -> bool:
    return code == 429 or 500 <= code < 600


def _urlopen_with_retry(url: str, timeout: int) -> bytes:
    attempt = 1
    while True:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if attempt >= HISTORY_FETCH_ATTEMPTS or not _is_transient_http_status(error.code):
                raise
        except urllib.error.URLError:
            if attempt >= HISTORY_FETCH_ATTEMPTS:
                raise
        time.sleep(HISTORY_RETRY_BACKOFF_SECONDS * attempt)
        attempt += 1


def _download_file(url: str, path: Path) -> bool:
    try:
        payload = _urlopen_with_retry(url, timeout=120)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return False
        raise
    except urllib.error.URLError:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return True


def _fetch_json(url: str) -> dict[str, Any] | None:
    try:
        return json.loads(_urlopen_with_retry(url, timeout=60).decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise
    except (urllib.error.URLError, json.JSONDecodeError):
        return None


def _safe_history_path(history_dir: Path, relative_path: str) -> Path:
    if not _is_safe_relative_path(relative_path):
        raise ValueError(f"Unsafe history path: {relative_path}")
    return history_dir / relative_path


def _is_safe_relative_path(path: str) -> bool:
    parsed = urllib.parse.urlparse(path)
    return not parsed.scheme and not parsed.netloc and not Path(path).is_absolute() and ".." not in Path(path).parts


def _join_url(base_url: str, path: str) -> str:
    return base_url.rstrip("/") + "/" + urllib.parse.quote(path.replace("\\", "/"), safe="/")


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def copy_history_to_api(history_dir: Path, api_history_dir: Path) -> None:
    if not history_dir.exists():
        return
    if api_history_dir.exists():
        shutil.rmtree(api_history_dir)
    api_history_dir.mkdir(parents=True, exist_ok=True)

    paths = {"recent-changes.json", "latency-history.json"}

    index_path = history_dir / "index.json"
    if index_path.exists():
        shutil.copyfile(index_path, api_history_dir / "index.json")
        index = _read_json(index_path) or {}
        paths.update(_history_paths(index))

    recent_changes = _read_json(history_dir / "recent-changes.json") or {}
    paths.update(_history_paths(recent_changes))

    for relative_path in sorted(paths):
        source = _safe_history_path(history_dir, relative_path)
        if not source.exists():
            continue
        target = _safe_history_path(api_history_dir, relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def _snapshot_date(snapshot: Snapshot) -> str:
    return _normalize_timestamp(snapshot.timestamp).date().isoformat()


def _normalize_timestamp(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _feature_category(feature: str) -> str:
    if feature == "extensionCatalog" or feature.startswith("extensions.") or feature.startswith("extensionTypes."):
        return "AKS extensions"
    if feature.startswith("kubernetesVersions."):
        return "AKS Kubernetes versions"
    if feature.startswith("vmSkus."):
        return "VM SKUs"
    if feature.startswith("aiModels."):
        return "Azure AI models"
    return feature.split(".", 1)[0]


def _feature_group(feature: str) -> str:
    if feature.startswith("extensionTypes."):
        parts = feature.removeprefix("extensionTypes.").split(".")
        return parts[0] if parts else "unknown"
    if feature.startswith("extensions."):
        return "curated"
    if feature.startswith("kubernetesVersions."):
        return feature.removeprefix("kubernetesVersions.")
    if feature.startswith("vmSkus."):
        sku = feature.removeprefix("vmSkus.").removeprefix("standard.")
        letters = "".join(char for char in sku if char.isalpha())
        return letters.upper() if letters else "Other"
    return feature.split(".", 1)[0]
