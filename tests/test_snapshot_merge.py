from datetime import datetime, timezone

from azure_region_monitor.models import FeatureResult, Snapshot
from azure_region_monitor.snapshot_merge import merge_snapshot_overlay


def test_merge_snapshot_overlay_replaces_only_matching_modality_features():
    base = Snapshot(
        timestamp=datetime(2026, 5, 8, tzinfo=timezone.utc),
        regions={
            "eastus": {
                "aks": {
                    "extensionTypes.old": FeatureResult(status="available"),
                    "kubernetesVersions.1.33": FeatureResult(status="available"),
                },
                "compute": {
                    "vmSkus.standard.b2s": FeatureResult(status="available"),
                },
            }
        },
    )
    overlay = Snapshot(
        timestamp=datetime(2026, 5, 9, tzinfo=timezone.utc),
        regions={
            "eastus": {
                "aks": {
                    "extensionTypes.new": FeatureResult(status="available"),
                }
            }
        },
    )

    merged = merge_snapshot_overlay(base, overlay)

    assert "extensionTypes.old" not in merged.regions["eastus"]["aks"]
    assert merged.regions["eastus"]["aks"]["extensionTypes.new"].status == "available"
    assert merged.regions["eastus"]["aks"]["kubernetesVersions.1.33"].status == "available"
    assert merged.regions["eastus"]["compute"]["vmSkus.standard.b2s"].status == "available"
    assert merged.timestamp == overlay.timestamp


def test_merge_snapshot_overlay_replaces_only_vm_sku_features():
    base = Snapshot(
        regions={
            "eastus": {
                "compute": {
                    "vmSkus.standard.b2s": FeatureResult(status="available"),
                    "otherCompute.signal": FeatureResult(status="unknown"),
                }
            }
        },
    )
    overlay = Snapshot(
        regions={
            "eastus": {
                "compute": {
                    "vmSkus.standard.d2s.v5": FeatureResult(status="available"),
                }
            }
        },
    )

    merged = merge_snapshot_overlay(base, overlay)

    assert "vmSkus.standard.b2s" not in merged.regions["eastus"]["compute"]
    assert merged.regions["eastus"]["compute"]["vmSkus.standard.d2s.v5"].status == "available"
    assert merged.regions["eastus"]["compute"]["otherCompute.signal"].status == "unknown"


def test_merge_snapshot_overlay_replaces_vm_sku_rows_when_catalog_fails():
    base = Snapshot(
        regions={
            "eastus": {
                "compute": {
                    "vmSkus.standard.b2s": FeatureResult(status="available"),
                    "vmSkus.standard.d2s.v5": FeatureResult(status="unknown"),
                }
            }
        },
    )
    overlay = Snapshot(
        regions={
            "eastus": {
                "compute": {
                    "vmSkuCatalog": FeatureResult(
                        status="unknown",
                        error_code="AzureCliCommandFailed",
                        message="catalog failed",
                    ),
                }
            }
        },
    )

    merged = merge_snapshot_overlay(base, overlay)

    assert "vmSkus.standard.b2s" not in merged.regions["eastus"]["compute"]
    assert "vmSkus.standard.d2s.v5" not in merged.regions["eastus"]["compute"]
    assert merged.regions["eastus"]["compute"]["vmSkuCatalog"].status == "unknown"


def test_merge_snapshot_overlay_replaces_functions_features_as_one_modality():
    base = Snapshot(
        regions={
            "eastus": {
                "functions": {
                    "hostingPlans.flexConsumption": FeatureResult(status="available"),
                    "runtimes.python.3.11": FeatureResult(status="available"),
                    "otherFunctions.signal": FeatureResult(status="unknown"),
                }
            }
        },
    )
    overlay = Snapshot(
        regions={
            "eastus": {
                "functions": {
                    "runtimes.python.3.12": FeatureResult(status="available"),
                }
            }
        },
    )

    merged = merge_snapshot_overlay(base, overlay)

    assert "hostingPlans.flexConsumption" not in merged.regions["eastus"]["functions"]
    assert "runtimes.python.3.11" not in merged.regions["eastus"]["functions"]
    assert merged.regions["eastus"]["functions"]["runtimes.python.3.12"].status == "available"
    assert merged.regions["eastus"]["functions"]["otherFunctions.signal"].status == "unknown"


def test_merge_snapshot_overlay_replaces_container_apps_features_as_one_modality():
    base = Snapshot(
        regions={
            "eastus": {
                "containerApps": {
                    "containerApps.managedEnvironments": FeatureResult(status="available"),
                    "containerApps.daprComponents": FeatureResult(status="available"),
                    "otherContainerApps.signal": FeatureResult(status="unknown"),
                }
            }
        },
    )
    overlay = Snapshot(
        regions={
            "eastus": {
                "containerApps": {
                    "containerApps.apps": FeatureResult(status="available"),
                }
            }
        },
    )

    merged = merge_snapshot_overlay(base, overlay)

    assert "containerApps.managedEnvironments" not in merged.regions["eastus"]["containerApps"]
    assert "containerApps.daprComponents" not in merged.regions["eastus"]["containerApps"]
    assert merged.regions["eastus"]["containerApps"]["containerApps.apps"].status == "available"
    assert merged.regions["eastus"]["containerApps"]["otherContainerApps.signal"].status == "unknown"


def test_merge_snapshot_overlay_replaces_ai_model_features_as_one_modality():
    base = Snapshot(
        regions={
            "eastus": {
                "ai": {
                    "aiModels.openai.gpt-4o.2024-08-06": FeatureResult(status="available"),
                    "aiModels.openai.gpt-4o-mini.2024-07-18": FeatureResult(status="available"),
                    "otherAi.signal": FeatureResult(status="unknown"),
                }
            }
        },
    )
    overlay = Snapshot(
        regions={
            "eastus": {
                "ai": {
                    "aiModels.openai.gpt-5.2025-08-07": FeatureResult(status="available"),
                }
            }
        },
    )

    merged = merge_snapshot_overlay(base, overlay)

    assert "aiModels.openai.gpt-4o.2024-08-06" not in merged.regions["eastus"]["ai"]
    assert "aiModels.openai.gpt-4o-mini.2024-07-18" not in merged.regions["eastus"]["ai"]
    assert merged.regions["eastus"]["ai"]["aiModels.openai.gpt-5.2025-08-07"].status == "available"
    assert merged.regions["eastus"]["ai"]["otherAi.signal"].status == "unknown"