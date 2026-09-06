"""Complete, evidence-bounded daily facts, independent of editorial highlights."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Mapping

from azure_region_monitor.display import plain_feature_name
from azure_region_monitor.feature_context import describe_feature
from azure_region_monitor.models import FeatureResult, Snapshot
from azure_region_monitor.summary import ChangeContext, ChangeKey, _modality, feature_details

BRIEFING_KINDS = (
    "new_listings",
    "restorations",
    "delistings",
    "observation_gaps",
    "observation_recoveries",
    "continuing_absences",
    "other_changes",
    "scope_changes",
)
_CATALOG_MODALITIES = {
    "extensionCatalog": "AKS extensions",
    "aiModelCatalog": "Azure AI models",
    "vmSkuCatalog": "VM SKUs",
}


def build_briefing(
    current: Snapshot,
    previous: Snapshot | None,
    *,
    contexts: Mapping[ChangeKey, ChangeContext] | None = None,
    prior_day: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return all reader-facing facts without limiting features or region records.

    Counts are mutually exclusive region/service/feature records, not products:
    new_listings are positive listings in an already monitored region/modality;
    restorations additionally require earlier positive evidence; delistings are
    available -> unavailable/absent within that scope. Unknown observations
    (including unchanged ones) are gaps, and unknown -> known is a recovery,
    never evidence of a new rollout. Continuing absences require a prior tracked
    disappearance. Other changed statuses are other_changes. Added/removed
    region/modality checks are scope_changes, not availability conclusions.

    Scope added_checks/removed_checks count all added/removed keys, including
    discovered catalog entries. Coverage gives each snapshot's own denominator.
    Tracking is bounded by retained full records; it is not lifetime history.
    A failed-catalog sentinel makes absent dynamic keys observation gaps; their
    raw status stays None, while evidence names the failed catalog observation.
    """
    before = _results(previous)
    after = _results(current)
    before_regions = set(previous.regions) if previous is not None else set()
    after_regions = set(current.regions)
    before_modalities = {(r, s, _category(f)) for r, s, f in before}
    after_modalities = {(r, s, _category(f)) for r, s, f in after}
    stable_modalities = before_modalities & after_modalities
    before_failures = _catalog_failures(before)
    after_failures = _catalog_failures(after)
    before_coverage = _coverage(previous, before)
    after_coverage = _coverage(current, after)
    prior = _prior_briefing(prior_day, previous)
    tracked = {
        (item["region"], item["service"], item["feature"]): item
        for item in prior.get("records", [])
        if isinstance(item, dict)
        and all(isinstance(item.get(key), str) for key in ("region", "service", "feature"))
    }
    current_time = _timestamp(current.timestamp)
    previous_time = _timestamp(previous.timestamp) if previous is not None else None
    records: list[dict[str, Any]] = []

    continuing_keys = {
        key for key, item in tracked.items()
        if item.get("last_available_date")
        and (item.get("absence_since") or item.get("kind") == "observation_gaps")
        and (key[0], key[1], _category(key[2])) in stable_modalities
    }
    for key in sorted(before.keys() | after.keys() | continuing_keys):
        region, service, feature = key
        modality = _category(feature)
        is_measurement = modality in {"Model latency", "Azure model latency"}
        old_result, new_result = before.get(key), after.get(key)
        old = old_result.status if old_result is not None else None
        new = new_result.status if new_result is not None else None
        old_failure = before_failures.get((region, service, modality)) if old is None else None
        new_failure = after_failures.get((region, service, modality)) if new is None else None
        old_gap = old == "unknown" or old_failure is not None
        new_gap = new == "unknown" or new_failure is not None
        prior_record = tracked.get(key, {})
        context = (contexts or {}).get(key)
        scope_reason = None
        if previous is not None:
            if region not in before_regions:
                scope_reason = "region_added"
            elif region not in after_regions:
                scope_reason = "region_removed"
            elif (region, service, modality) not in before_modalities:
                scope_reason = "modality_added"
            elif (region, service, modality) not in after_modalities:
                scope_reason = "modality_removed"

        last_available = (
            previous_time[:10]
            if old == "available" and previous_time is not None
            else prior_record.get("last_available_date")
            or (context.last_available_date if context is not None else None)
        )
        known_available = bool(
            last_available or (context is not None and context.available_days > 0)
        )
        absence_since = prior_record.get("absence_since")
        kind = None
        if new_gap:
            kind = "observation_gaps"
        elif previous is None:
            continue
        elif scope_reason is not None:
            kind = "scope_changes"
        elif old_gap and (
            new in {"available", "unavailable", "partial"}
            or (region, service, modality) in after_modalities
        ):
            kind = "observation_recoveries"
        elif is_measurement and old != new:
            kind = "other_changes"
        elif new == "available" and old in {None, "unavailable"}:
            kind = "restorations" if known_available else "new_listings"
        elif old == "available" and new in {None, "unavailable"}:
            kind = "delistings"
        elif new in {None, "unavailable"} and absence_since and known_available:
            kind = "continuing_absences"
        elif old != new:
            kind = "other_changes"
        if kind is None:
            continue

        if (
            new in {None, "unavailable"} and not new_gap
            and known_available and scope_reason is None and not is_measurement
        ):
            absence_since = absence_since or current_time[:10]
        elif not new_gap or scope_reason is not None:
            absence_since = None
        details_label, details_url, feature_note = feature_details(feature)
        record = {
            "kind": kind,
            "modality": modality,
            "region": region,
            "service": service,
            "feature": feature,
            "label": plain_feature_name(feature),
            "previous": old,
            "current": new,
            "coverage_before": _feature_coverage(previous, before_coverage, service, feature),
            "coverage_after": _feature_coverage(current, after_coverage, service, feature),
            "evidence_before": _evidence(old_result, previous_time, old_failure),
            "evidence_after": _evidence(new_result, current_time, new_failure),
            "details_url": details_url,
            "details_label": details_label,
            "feature_note": feature_note,
            "last_available_date": last_available,
            "absence_since": absence_since,
            "scope_reason": scope_reason,
            "novelty": (
                "First observed in retained monitoring history; not a confirmed product launch."
                if kind == "new_listings" and context is not None and context.expansion_kind == "new_feature"
                else None
            ),
        }
        records.append(record)

    groups = _groups(records)
    counts = dict.fromkeys(BRIEFING_KINDS, 0)
    for record in records:
        counts[record["kind"]] += 1
    tracking = prior.get("tracking", {})
    return enrich_briefing_features({
        "version": 1,
        "current_timestamp": current_time,
        "previous_timestamp": previous_time,
        "baseline_available": previous is not None,
        "comparison_days": (
            (_utc(current.timestamp).date() - _utc(previous.timestamp).date()).days
            if previous is not None else None
        ),
        "regions": sorted(before_regions | after_regions),
        "modalities": sorted({item[2] for item in before_modalities | after_modalities}),
        "scope": {
            "added_regions": sorted(after_regions - before_regions) if previous else [],
            "removed_regions": sorted(before_regions - after_regions) if previous else [],
            "added_checks": len(after.keys() - before.keys()) if previous else 0,
            "removed_checks": len(before.keys() - after.keys()) if previous else 0,
            "previous_regions": len(before_regions) if previous else None,
            "current_regions": len(after_regions),
            "previous_checks": len(before) if previous else None,
            "current_checks": len(after),
        },
        "tracking": {
            "since": tracking.get("since") or (previous_time or current_time)[:10],
            "complete": False,
            "mode": "tracked_absences",
        },
        "counts": counts,
        "groups": groups,
        "records": records,
    })


def compact_briefing(briefing: dict[str, Any]) -> dict[str, Any]:
    """The index carries groups, while change_path carries the full records."""
    return {key: value for key, value in briefing.items() if key not in {"records", "feature_contexts"}}


def enrich_briefing_features(briefing: dict[str, Any]) -> dict[str, Any]:
    """Refresh product documentation without recalculating historical change facts."""
    records = [dict(record) for record in briefing["records"]]
    contexts = {feature: describe_feature(feature) for feature in sorted({record["feature"] for record in records})}
    for record in records:
        if record["kind"] == "new_listings" and not record.get("novelty"):
            before = record.get("coverage_before")
            if isinstance(before, dict) and before.get("available") == 0:
                record["novelty"] = "First observed in this comparison; older history or a product launch is not established."
            else:
                record["novelty"] = "New regional listing of an already observed feature."
    groups = _groups(records)
    for group in groups:
        for example in group["examples"]:
            example["feature_context"] = contexts[example["feature"]]
    return {**briefing, "records": records, "groups": groups, "feature_contexts": contexts}


def _prior_briefing(
    prior_day: dict[str, Any] | None, previous: Snapshot | None
) -> dict[str, Any]:
    if previous is None or not isinstance(prior_day, dict):
        return {}
    briefing = prior_day.get("briefing", prior_day)
    if (
        not isinstance(briefing, dict)
        or briefing.get("version") != 1
        or briefing.get("current_timestamp") != _timestamp(previous.timestamp)
    ):
        return {}
    return briefing


def _results(snapshot: Snapshot | None) -> dict[ChangeKey, FeatureResult]:
    if snapshot is None:
        return {}
    return {
        (region, service, feature): result
        for region, services in snapshot.regions.items()
        for service, features in services.items()
        for feature, result in features.items()
    }


def _category(feature: str) -> str:
    return _CATALOG_MODALITIES.get(feature) or _modality(feature)


def _catalog_failures(
    results: dict[ChangeKey, FeatureResult],
) -> dict[tuple[str, str, str], tuple[str, FeatureResult]]:
    # Dynamic catalogs emit one failed-catalog row instead of every missing item.
    # Their absent item keys are gaps, not catalog delistings or subsequent rollouts.
    return {
        (region, service, _category(feature)): (feature, result)
        for (region, service, feature), result in results.items()
        if feature in _CATALOG_MODALITIES and result.status == "unknown"
    }


def _coverage(
    snapshot: Snapshot | None, results: dict[ChangeKey, FeatureResult]
) -> dict[tuple[str, str], dict[str, int]]:
    coverage: dict[tuple[str, str], dict[str, int]] = {}
    for (_, service, feature), result in results.items():
        item = coverage.setdefault((service, feature), _empty_coverage(snapshot))
        item["observed"] += 1
        item[result.status] += 1
    return coverage


def _empty_coverage(snapshot: Snapshot | None) -> dict[str, int]:
    return {
        "available": 0,
        "unavailable": 0,
        "partial": 0,
        "unknown": 0,
        "observed": 0,
        "total_regions": len(snapshot.regions) if snapshot is not None else 0,
    }


def _feature_coverage(
    snapshot: Snapshot | None,
    coverage: dict[tuple[str, str], dict[str, int]],
    service: str,
    feature: str,
) -> dict[str, int] | None:
    if snapshot is None:
        return None
    return coverage.get((service, feature), _empty_coverage(snapshot))


def _evidence(
    result: FeatureResult | None,
    timestamp: str | None,
    catalog_failure: tuple[str, FeatureResult] | None = None,
) -> dict[str, Any] | None:
    if timestamp is None:
        return None
    if catalog_failure is not None:
        result = catalog_failure[1]
    evidence = {
        "timestamp": timestamp,
        "source": "snapshot",
        "status": result.status if result is not None else None,
        "detail": result.message if result is not None else None,
        "error_code": result.error_code if result is not None else None,
        "latency_ms": result.latency_ms if result is not None else None,
    }
    if catalog_failure is not None:
        evidence["feature"] = catalog_failure[0]
    return evidence


def _groups(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[(record["kind"], record["modality"])].append(record)
    result = []
    for (kind, modality), items in sorted(
        grouped.items(), key=lambda item: (BRIEFING_KINDS.index(item[0][0]), item[0][1])
    ):
        region_counts = dict(sorted(Counter(item["region"] for item in items).items()))
        result.append({
            "kind": kind,
            "modality": modality,
            "feature_count": len({(item["service"], item["feature"]) for item in items}),
            "listing_count": len(items),
            "regions": list(region_counts),
            "region_counts": region_counts,
            "region_feature_counts": dict(region_counts),
            "examples": [dict(items[0])],
        })
    return result


def _utc(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def _timestamp(timestamp: datetime) -> str:
    return _utc(timestamp).isoformat()
