from datetime import datetime, timezone

from azure_region_monitor.diff import build_diff
from azure_region_monitor.models import FeatureResult, Snapshot
from azure_region_monitor.probes.base import ProbeResult
from azure_region_monitor.runner import run_probes


def test_build_diff_classifies_new_availability_and_regression():
    previous = Snapshot(
        timestamp=datetime(2026, 5, 7, tzinfo=timezone.utc),
        regions={
            "swedencentral": {
                "aks": {
                    "extensions.gitops": FeatureResult(status="unavailable"),
                    "extensions.monitor": FeatureResult(status="available"),
                }
            }
        },
    )
    current = Snapshot(
        timestamp=datetime(2026, 5, 8, tzinfo=timezone.utc),
        regions={
            "swedencentral": {
                "aks": {
                    "extensions.gitops": FeatureResult(status="available"),
                    "extensions.monitor": FeatureResult(status="unavailable"),
                }
            }
        },
    )

    diff = build_diff(previous, current, timestamp=datetime(2026, 5, 8, tzinfo=timezone.utc))

    assert [(change.feature, change.change_type) for change in diff.changes] == [
        ("extensions.gitops", "new_availability"),
        ("extensions.monitor", "regression"),
    ]


def test_run_probes_can_normalize_missing_catalog_features():
    class CatalogProbe:
        normalize_missing_features = True

        def run(self, region: str):
            if region == "eastus":
                yield ProbeResult(
                    service="aks",
                    feature="extensionTypes.microsoft.flux",
                    result=FeatureResult(status="available"),
                )

    snapshot = run_probes(["eastus", "westeurope"], [CatalogProbe()])

    assert snapshot.regions["eastus"]["aks"]["extensionTypes.microsoft.flux"].status == "available"
    assert snapshot.regions["westeurope"]["aks"]["extensionTypes.microsoft.flux"].status == "unavailable"


def test_run_probes_does_not_normalize_unknown_catalog_region():
    class CatalogProbe:
        normalize_missing_features = True

        def run(self, region: str):
            if region == "eastus":
                yield ProbeResult(
                    service="aks",
                    feature="extensionTypes.microsoft.flux",
                    result=FeatureResult(status="available"),
                )
            else:
                yield ProbeResult(
                    service="aks",
                    feature="extensionCatalog",
                    result=FeatureResult(status="unknown", error_code="AzureCliCommandFailed"),
                )

    snapshot = run_probes(["eastus", "westeurope"], [CatalogProbe()])

    assert snapshot.regions["westeurope"]["aks"]["extensionCatalog"].status == "unknown"
    assert "extensionTypes.microsoft.flux" not in snapshot.regions["westeurope"]["aks"]
