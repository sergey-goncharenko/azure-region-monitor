from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol

from azure_region_monitor.models import FeatureResult


@dataclass(frozen=True)
class ProbeResult:
    service: str
    feature: str
    result: FeatureResult


class SyntheticProbe(Protocol):
    name: str

    def run(self, region: str) -> Iterable[ProbeResult]:
        """Run the probe for one Azure region."""
