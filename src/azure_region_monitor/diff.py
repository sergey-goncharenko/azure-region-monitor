from __future__ import annotations

from datetime import datetime, timezone

from azure_region_monitor.models import Change, ChangeType, Diff, FeatureStatus, Snapshot

FeatureKey = tuple[str, str, str]


def build_diff(previous: Snapshot, current: Snapshot, timestamp: datetime | None = None) -> Diff:
    previous_statuses = _flatten_statuses(previous)
    current_statuses = _flatten_statuses(current)
    keys = sorted(previous_statuses.keys() | current_statuses.keys())

    changes = [
        Change(
            region=region,
            service=service,
            feature=feature,
            previous=previous_statuses.get(key),
            current=current_statuses.get(key),
            change_type=_classify_change(previous_statuses.get(key), current_statuses.get(key)),
        )
        for key in keys
        for region, service, feature in [key]
        if previous_statuses.get(key) != current_statuses.get(key)
    ]

    return Diff(
        timestamp=timestamp or datetime.now(timezone.utc),
        previous_timestamp=previous.timestamp,
        current_timestamp=current.timestamp,
        changes=changes,
    )


def _flatten_statuses(snapshot: Snapshot) -> dict[FeatureKey, FeatureStatus]:
    statuses: dict[FeatureKey, FeatureStatus] = {}
    for region, services in snapshot.regions.items():
        for service, features in services.items():
            for feature, result in features.items():
                statuses[(region, service, feature)] = result.status
    return statuses


def _classify_change(previous: FeatureStatus | None, current: FeatureStatus | None) -> ChangeType:
    if previous in {None, "unavailable", "unknown"} and current == "available":
        return "new_availability"
    if previous == "available" and current in {None, "unavailable", "unknown"}:
        return "regression"
    return "status_change"
