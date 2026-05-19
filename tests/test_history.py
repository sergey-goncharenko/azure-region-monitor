import gzip
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

    snapshot_history = history_dir / "snapshots" / "2026-05-10.json.gz"
    assert snapshot_history.exists()
    with gzip.open(snapshot_history, "rt", encoding="utf-8") as stream:
        assert json.loads(stream.read())["timestamp"] == "2026-05-10T00:00:00Z"
    assert index["latest_date"] == "2026-05-10"
    assert index["latest_snapshot_path"] == "snapshots/2026-05-10.json.gz"
    assert [day["date"] for day in index["days"]] == ["2026-05-10", "2026-05-08"]
    assert change_day["previous_date"] == "2026-05-08"
    assert change_day["total_changes"] == 1
    assert change_day["change_type_counts"]["new_availability"] == 1
    assert change_day["parked_unknown_changes"] == 0
    assert change_day["summary_counts"] == {"regions": 1, "features": 1, "checks": 1}
    assert change_day["highlights"][0]["group"] == "microsoft"
    assert recent_changes["days"][0]["date"] == "2026-05-10"


def test_update_history_migrates_legacy_json_snapshots(tmp_path):
    history_dir = tmp_path / "history"
    legacy_snapshot_path = history_dir / "snapshots" / "2026-05-08.json"
    legacy_snapshot_path.parent.mkdir(parents=True)
    legacy_snapshot_path.write_text(
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
    (history_dir / "index.json").write_text(
        json.dumps(
            {
                "latest_date": "2026-05-08",
                "latest_snapshot_path": "snapshots/2026-05-08.json",
                "days": [
                    {
                        "date": "2026-05-08",
                        "snapshot_path": "snapshots/2026-05-08.json",
                        "change_path": "changes/2026-05-08.json",
                        "total_changes": 0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    current_snapshot = tmp_path / "current.json"
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

    update_history(current_snapshot, history_dir)

    index = json.loads((history_dir / "index.json").read_text(encoding="utf-8"))
    change_day = json.loads((history_dir / "changes" / "2026-05-10.json").read_text(encoding="utf-8"))

    assert not legacy_snapshot_path.exists()
    assert (history_dir / "snapshots" / "2026-05-08.json.gz").exists()
    assert index["days"][1]["snapshot_path"] == "snapshots/2026-05-08.json.gz"
    assert change_day["previous_snapshot_path"] == "snapshots/2026-05-08.json.gz"
    assert change_day["total_changes"] == 1


def test_update_history_parks_unknown_transitions_out_of_highlights(tmp_path):
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
                            "extensions.gitops": {"status": "unknown"},
                            "extensions.monitor": {"status": "available"},
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
                            "extensions.gitops": {"status": "available"},
                            "extensions.monitor": {"status": "unknown"},
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    update_history(previous_snapshot, history_dir)
    update_history(current_snapshot, history_dir)

    change_day = json.loads((history_dir / "changes" / "2026-05-10.json").read_text(encoding="utf-8"))

    assert change_day["total_changes"] == 2
    assert change_day["change_type_counts"] == {
        "new_availability": 0,
        "regression": 0,
        "status_change": 2,
    }
    assert change_day["parked_unknown_changes"] == 2
    assert change_day["highlights"] == []


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


def test_recent_changes_skip_previous_unknown_only_days(tmp_path):
    history_dir = tmp_path / "history"
    (history_dir / "index.json").parent.mkdir(parents=True)
    (history_dir / "index.json").write_text(
        json.dumps(
            {
                "days": [
                    {
                        "date": "2026-05-09",
                        "total_changes": 4,
                        "change_type_counts": {
                            "new_availability": 0,
                            "regression": 0,
                            "status_change": 4,
                        },
                    },
                    {
                        "date": "2026-05-08",
                        "total_changes": 1,
                        "change_type_counts": {
                            "new_availability": 1,
                            "regression": 0,
                            "status_change": 0,
                        },
                    },
                ]
            }
        ),
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

    assert [day["date"] for day in recent_changes["days"]] == ["2026-05-10", "2026-05-08"]
