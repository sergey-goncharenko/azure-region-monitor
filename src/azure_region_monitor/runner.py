from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from azure_region_monitor.models import Snapshot
from azure_region_monitor.probes.base import ProbeResult, SyntheticProbe


def run_probes(
    regions: Iterable[str],
    probes: Iterable[SyntheticProbe],
    timestamp: datetime | None = None,
) -> Snapshot:
    snapshot_regions: dict[str, dict[str, dict[str, object]]] = {}

    for region in regions:
        services: dict[str, dict[str, object]] = {}
        for probe in probes:
            for probe_result in probe.run(region):
                _merge_probe_result(services, probe_result)
        snapshot_regions[region] = services

    return Snapshot(
        timestamp=timestamp or datetime.now(timezone.utc),
        regions=snapshot_regions,
    )


def _merge_probe_result(services: dict[str, dict[str, object]], probe_result: ProbeResult) -> None:
    service_features = services.setdefault(probe_result.service, {})
    service_features[probe_result.feature] = probe_result.result
