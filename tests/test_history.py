import json

from azure_region_monitor.history import update_history


def test_update_history_writes_daily_snapshot_and_recent_changes(tmp_path):
    history_dir = tmp_path / "history"
    previous_snapshot = tmp_path / "previous.json"
    current_snapshot = tmp_path / "current.json"
    previous_snapshot.write_text(
        json.dumps(
            {
                "timestamp": "2026-05-08T00:00:00Z",
                "regions": {
                    "eastus": {
                        "aks": {
                            "extensionTypes.microsoft.flux": {"status": "unavailable"},
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    current_snapshot.write_text(
        json.dumps(
            {
                "timestamp": "2026-05-10T00:00:00Z",
                "regions": {
                    "eastus": {
                        "aks": {
                            "extensionTypes.microsoft.flux": {"status": "available"},
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    update_history(previous_snapshot, history_dir)
    recent_changes = update_history(current_snapshot, history_dir)

    index = json.loads((history_dir / "index.json").read_text(encoding="utf-8"))
    change_day = json.loads((history_dir / "changes" / "2026-05-10.json").read_text(encoding="utf-8"))

    assert (history_dir / "snapshots" / "2026-05-10.json").exists()
    assert index["latest_date"] == "2026-05-10"
    assert [day["date"] for day in index["days"]] == ["2026-05-10", "2026-05-08"]
    assert change_day["previous_date"] == "2026-05-08"
    assert change_day["total_changes"] == 1
    assert change_day["change_type_counts"]["new_availability"] == 1
    assert change_day["highlights"][0]["group"] == "microsoft"
    assert recent_changes["days"][0]["date"] == "2026-05-10"


def test_recent_changes_include_today_and_previous_change_days(tmp_path):
    history_dir = tmp_path / "history"
    previous_change_days = []
    for index in range(12):
        day = f"2026-04-{index + 1:02d}"
        previous_change_days.append(
            {
                "date": day,
                "snapshot_path": f"snapshots/{day}.json",
                "change_path": f"changes/{day}.json",
                "total_changes": 1,
                "change_type_counts": {
                    "new_availability": 1,
                    "regression": 0,
                    "status_change": 0,
                },
                "highlights": [],
            }
        )

    (history_dir / "index.json").parent.mkdir(parents=True)
    (history_dir / "index.json").write_text(
        json.dumps({"days": list(reversed(previous_change_days))}),
        encoding="utf-8",
    )
    snapshot_path = tmp_path / "current.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "timestamp": "2026-05-10T00:00:00Z",
                "regions": {
                    "eastus": {
                        "aks": {
                            "extensionTypes.microsoft.flux": {"status": "available"},
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    recent_changes = update_history(snapshot_path, history_dir)

    assert len(recent_changes["days"]) == 10
    assert recent_changes["days"][0]["date"] == "2026-05-10"
    assert recent_changes["days"][0]["total_changes"] == 0
    assert [day["date"] for day in recent_changes["days"][1:]] == [
        "2026-04-12",
        "2026-04-11",
        "2026-04-10",
        "2026-04-09",
        "2026-04-08",
        "2026-04-07",
        "2026-04-06",
        "2026-04-05",
        "2026-04-04",
    ]