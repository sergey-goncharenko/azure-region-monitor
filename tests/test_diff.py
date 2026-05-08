from datetime import datetime, timezone

from azure_region_monitor.diff import build_diff
from azure_region_monitor.models import FeatureResult, Snapshot


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
