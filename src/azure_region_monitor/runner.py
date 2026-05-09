from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from azure_region_monitor.models import FeatureResult, Snapshot
from azure_region_monitor.probes.base import ProbeResult, SyntheticProbe


def run_probes(
    regions: Iterable[str],
    probes: Iterable[SyntheticProbe],
    timestamp: datetime | None = None,
) -> Snapshot:
    snapshot_regions: dict[str, dict[str, dict[str, object]]] = {}
    normalized_feature_keys: set[tuple[str, str]] = set()
    blocked_normalized_regions: dict[tuple[str, str], FeatureResult] = {}

    for region in regions:
        services: dict[str, dict[str, object]] = {}
        for probe in probes:
            for probe_result in probe.run(region):
                _merge_probe_result(services, probe_result)
                if getattr(probe, "normalize_missing_features", False):
                    if probe_result.result.status == "unknown":
                        blocked_normalized_regions[(region, probe_result.service)] = probe_result.result
                    else:
                        normalized_feature_keys.add((probe_result.service, probe_result.feature))
        snapshot_regions[region] = services

    _fill_missing_normalized_features(
        snapshot_regions,
        normalized_feature_keys,
        blocked_normalized_regions,
    )

    return Snapshot(
        timestamp=timestamp or datetime.now(timezone.utc),
        regions=snapshot_regions,
    )


def _merge_probe_result(services: dict[str, dict[str, object]], probe_result: ProbeResult) -> None:
    service_features = services.setdefault(probe_result.service, {})
    service_features[probe_result.feature] = probe_result.result


def _fill_missing_normalized_features(
    snapshot_regions: dict[str, dict[str, dict[str, object]]],
    normalized_feature_keys: set[tuple[str, str]],
    blocked_normalized_regions: dict[tuple[str, str], FeatureResult],
) -> None:
    for region, services in snapshot_regions.items():
        for service, feature in normalized_feature_keys:
            service_features = services.setdefault(service, {})
            blocked_result = blocked_normalized_regions.get((region, service))
            if blocked_result:
                service_features.setdefault(
                    feature,
                    FeatureResult(
                        status="unknown",
                        error_code=blocked_result.error_code,
                        message=blocked_result.message,
                    ),
                )
            else:
                service_features.setdefault(
                    feature,
                    FeatureResult(
                        status="unavailable",
                        message="Feature was not listed in this region's catalog.",
                    ),
                )
