from __future__ import annotations

from azure_region_monitor.models import FeatureResult, FeatureStatus
from azure_region_monitor.probes.base import ProbeResult


class SampleAksExtensionProbe:
    name = "sample-aks-extension"

    _status_by_region: dict[str, dict[str, FeatureStatus]] = {
        "westeurope": {
            "extensions.gitops": "available",
            "extensions.monitor": "available",
        },
        "swedencentral": {
            "extensions.gitops": "available",
            "extensions.monitor": "unavailable",
        },
        "eastus": {
            "extensions.gitops": "unavailable",
            "extensions.monitor": "available",
        },
    }

    def run(self, region: str):
        feature_statuses = self._status_by_region.get(
            region,
            {
                "extensions.gitops": "unknown",
                "extensions.monitor": "unknown",
            },
        )

        for feature, status in feature_statuses.items():
            yield ProbeResult(
                service="aks",
                feature=feature,
                result=FeatureResult(
                    status=status,
                    latency_ms=_stable_latency_ms(region, feature),
                    message="Deterministic sample probe result for project bootstrap.",
                ),
            )


def _stable_latency_ms(region: str, feature: str) -> int:
    return 25 + (sum(ord(character) for character in f"{region}:{feature}") % 90)
