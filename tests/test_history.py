import gzip
import json
import urllib.error

import pytest

from azure_region_monitor import history
from azure_region_monitor.history import fetch_history, update_history
from azure_region_monitor.models import Change, Snapshot


def test_update_history_writes_daily_snapshot_and_recent_changes(tmp_path):
    class _NarrativeClient:
        deployment = "gpt-5.4-mini"
        generation_metadata = {
            "narrative_mcp_status": "consulted",
            "narrative_mcp_error": None,
            "narrative_grounding_status": "microsoft_learn",
            "narrative_microsoft_learn_urls": [
                "https://learn.microsoft.com/azure/aks/cluster-extensions"
            ],
        }

        def generate(self, *, system, user):
            return json.dumps(
                {
                    "narrative": (
                        "AKS extension update\n\n"
                        "The monitored extension catalog changed.\n\n"
                        "What this means for Azure users: review cluster extension placement."
                    ),
                    "excerpt": "A purpose-written AKS extension catalog summary.",
                    "linkedin": (
                        "2026-05-10 recorded 1 new availability, 0 regressions, and 0 parked unknown "
                        "transitions."
                    ),
                    "short_post": (
                        "2026-05-10 recorded 1 new availability, 0 regressions, and 0 parked unknown "
                        "transitions."
                    ),
                }
            )

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
    recent_changes = update_history(current_snapshot, history_dir, narrative_client=_NarrativeClient())

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
    assert change_day["change_modality_counts"] == {
        "AKS extensions": {
            "new_availability": 1,
            "regression": 0,
            "status_change": 0,
        }
    }
    assert change_day["narrative_model_deployment"] == "gpt-5.4-mini"
    assert change_day["editorial_excerpt"] == "A purpose-written AKS extension catalog summary."
    assert change_day["social_drafts"]["linkedin"].startswith("2026-05-10")
    assert change_day["narrative_mcp_status"] == "consulted"
    assert change_day["narrative_grounding_status"] == "microsoft_learn"
    assert change_day["narrative_microsoft_learn_urls"] == [
        "https://learn.microsoft.com/azure/aks/cluster-extensions"
    ]
    assert change_day["highlights"][0]["group"] == "microsoft"
    assert recent_changes["days"][0]["date"] == "2026-05-10"
    assert change_day["briefing"]["baseline_available"] is True
    assert change_day["briefing"]["comparison_days"] == 2
    assert change_day["briefing"]["counts"]["new_listings"] == 1
    assert len(change_day["briefing"]["records"]) == 1
    assert "records" not in index["days"][0]["briefing"]
    assert "records" not in recent_changes["days"][0]["briefing"]


def test_update_history_classifies_net_new_and_restored_availability(tmp_path):
    history_dir = tmp_path / "history"
    snapshots = {
        "2026-05-07": {
            "eastus": {"ai": {"aiModels.openai.gpt-5.2025": {"status": "unavailable"}}},
            "westus3": {"ai": {"aiModels.openai.gpt-5.2025": {"status": "available"}}},
        },
        "2026-05-08": {
            "eastus": {"ai": {"aiModels.openai.gpt-5.2025": {"status": "unavailable"}}},
            "westus3": {"ai": {"aiModels.openai.gpt-5.2025": {"status": "unavailable"}}},
        },
        "2026-05-09": {
            "eastus": {"ai": {"aiModels.openai.gpt-5.2025": {"status": "available"}}},
            "westus3": {"ai": {"aiModels.openai.gpt-5.2025": {"status": "available"}}},
        },
    }
    for date, regions in snapshots.items():
        path = tmp_path / f"{date}.json"
        path.write_text(
            json.dumps({"timestamp": f"{date}T00:00:00Z", "regions": regions}),
            encoding="utf-8",
        )
        update_history(path, history_dir)

    change_day = json.loads((history_dir / "changes" / "2026-05-09.json").read_text(encoding="utf-8"))
    classifications = {item["region"]: item["classification"] for item in change_day["highlights"]}

    assert classifications == {
        "eastus": "net_new_availability",
        "westus3": "restored_availability",
    }
    assert change_day["change_context_counts"] == {
        "net_new_availability": 1,
        "restored_availability": 1,
    }
    restored = next(item for item in change_day["highlights"] if item["region"] == "westus3")
    assert restored["prior_disappearances"] == 1
    net_new = next(item for item in change_day["highlights"] if item["region"] == "eastus")
    assert net_new["expansion_kind"] == "regional_expansion"
    assert net_new["feature_current_available_regions"] == 2
    assert net_new["feature_coverage_delta"] == 2
    assert net_new["details_url"] == "https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure#gpt-5"


def test_update_history_classifies_deprecation_and_recurring_regression(tmp_path):
    history_dir = tmp_path / "history"
    snapshots = {
        "2026-05-07": {
            "eastus": {"compute": {"vmSkus.standard.d2as.v5": {"status": "available"}}},
            "westus3": {"compute": {"vmSkus.standard.d2as.v5": {"status": "available"}}},
        },
        "2026-05-08": {
            "eastus": {"compute": {"vmSkus.standard.d2as.v5": {"status": "available"}}},
            "westus3": {"compute": {"vmSkus.standard.d2as.v5": {"status": "unavailable"}}},
        },
        "2026-05-09": {
            "eastus": {"compute": {"vmSkus.standard.d2as.v5": {"status": "available"}}},
            "westus3": {"compute": {"vmSkus.standard.d2as.v5": {"status": "available"}}},
        },
        "2026-05-10": {
            "eastus": {"compute": {"vmSkus.standard.d2as.v5": {"status": "unavailable"}}},
            "westus3": {"compute": {"vmSkus.standard.d2as.v5": {"status": "unavailable"}}},
        },
    }
    for date, regions in snapshots.items():
        path = tmp_path / f"{date}.json"
        path.write_text(
            json.dumps({"timestamp": f"{date}T00:00:00Z", "regions": regions}),
            encoding="utf-8",
        )
        update_history(path, history_dir)

    change_day = json.loads((history_dir / "changes" / "2026-05-10.json").read_text(encoding="utf-8"))
    classifications = {item["region"]: item["classification"] for item in change_day["highlights"]}

    assert classifications == {
        "eastus": "deprecation_candidate",
        "westus3": "recurring_regression",
    }
    recurring = next(item for item in change_day["highlights"] if item["region"] == "westus3")
    assert recurring["prior_disappearances"] == 1
    deprecation = next(item for item in change_day["highlights"] if item["region"] == "eastus")
    assert deprecation["feature_previous_available_regions"] == 2
    assert deprecation["feature_current_available_regions"] == 0
    assert deprecation["feature_deprecated_coverage_pct"] == 100.0
    assert deprecation["still_available_regions"] == []


def test_update_history_marks_first_region_in_geography(tmp_path):
    history_dir = tmp_path / "history"
    snapshots = {
        "2026-05-07": {
            "eastus": {"compute": {"vmSkus.standard.ncads.h100.v5": {"status": "available"}}},
            "westeurope": {"compute": {"vmSkus.standard.ncads.h100.v5": {"status": "unavailable"}}},
        },
        "2026-05-08": {
            "eastus": {"compute": {"vmSkus.standard.ncads.h100.v5": {"status": "available"}}},
            "westeurope": {"compute": {"vmSkus.standard.ncads.h100.v5": {"status": "available"}}},
        },
    }
    for date, regions in snapshots.items():
        path = tmp_path / f"{date}.json"
        path.write_text(
            json.dumps({"timestamp": f"{date}T00:00:00Z", "regions": regions}),
            encoding="utf-8",
        )
        update_history(path, history_dir)

    change_day = json.loads((history_dir / "changes" / "2026-05-08.json").read_text(encoding="utf-8"))
    highlight = change_day["highlights"][0]

    assert highlight["region_group"] == "Europe"
    assert highlight["expansion_kind"] == "region_group_first"
    assert highlight["expansion_label"] == "first observed in Europe"
    assert highlight["region_group_previous_available_regions"] == 0
    assert highlight["region_group_current_available_regions"] == 1


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


def test_recent_changes_include_latest_daily_records(tmp_path):
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


def test_recent_changes_keep_previous_unknown_only_days(tmp_path):
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

    assert [day["date"] for day in recent_changes["days"]] == [
        "2026-05-10",
        "2026-05-09",
        "2026-05-08",
    ]


def test_highlights_represent_each_direction_and_modality_before_repeating():
    changes = [
        *[
            Change(
                region=f"region-{index}",
                service="ai",
                feature="aiModels.openai.gpt-5.2025",
                previous="available",
                current="unavailable",
                change_type="regression",
            )
            for index in range(5)
        ],
        Change(
            region="eastus",
            service="compute",
            feature="vmSkus.standard.d2s.v5",
            previous="available",
            current="unavailable",
            change_type="regression",
        ),
        Change(
            region="eastus2",
            service="ai",
            feature="aiModels.openai.gpt-6.1",
            previous="unavailable",
            current="available",
            change_type="new_availability",
        ),
        Change(
            region="westus3",
            service="compute",
            feature="vmSkus.standard.d4s.v6",
            previous="unavailable",
            current="available",
            change_type="new_availability",
        ),
    ]

    highlights = history._highlight_changes(changes)

    assert [
        (change.change_type, history._feature_category(change.feature))
        for change in highlights[:4]
    ] == [
        ("regression", "Azure AI models"),
        ("regression", "VM SKUs"),
        ("new_availability", "Azure AI models"),
        ("new_availability", "VM SKUs"),
    ]


def _latency_snapshot(date, p50, timestamp=None):
    return {
        "timestamp": timestamp or f"{date}T00:00:00Z",
        "regions": {
            "github-global": {
                "model-latency": {
                    "modelLatency.openai.gpt-4o": {
                        "status": "available",
                        "latency_ms": p50,
                        "message": (
                            f"openai/gpt-4o from github-global: p50 {p50}ms, p95 {p50 + 50}ms, "
                            f"TTFT p50 {p50 - 100}ms, 60.0 tok/s over 3/3 samples."
                        ),
                    }
                }
            }
        },
    }


def test_update_history_writes_latency_history(tmp_path):
    history_dir = tmp_path / "history"
    snap = tmp_path / "s.json"
    snap.write_text(json.dumps(_latency_snapshot("2026-06-16", 1600)), encoding="utf-8")

    update_history(snap, history_dir)

    latency = json.loads((history_dir / "latency-history.json").read_text(encoding="utf-8"))
    assert latency["days"][0]["date"] == "2026-06-16"
    assert latency["days"][0]["models"]["openai/gpt-4o"]["p50_ms"] == 1600


def test_update_history_retains_multiple_latency_snapshots_per_day(tmp_path):
    history_dir = tmp_path / "history"
    snap1 = tmp_path / "s1.json"
    snap1.write_text(
        json.dumps(_latency_snapshot("2026-06-16", 1600, "2026-06-16T08:00:00Z")),
        encoding="utf-8",
    )
    snap2 = tmp_path / "s2.json"
    snap2.write_text(
        json.dumps(_latency_snapshot("2026-06-16", 1900, "2026-06-16T12:00:00Z")),
        encoding="utf-8",
    )

    update_history(snap1, history_dir)
    update_history(snap2, history_dir)

    latency = json.loads((history_dir / "latency-history.json").read_text(encoding="utf-8"))
    assert [day["timestamp"] for day in latency["days"]] == [
        "2026-06-16T12:00:00+00:00",
        "2026-06-16T08:00:00+00:00",
    ]
    assert [day["models"]["openai/gpt-4o"]["p50_ms"] for day in latency["days"]] == [
        1900,
        1600,
    ]


def test_update_history_latency_skips_snapshot_without_latency(tmp_path):
    history_dir = tmp_path / "history"
    latency_snap = tmp_path / "lat.json"
    latency_snap.write_text(json.dumps(_latency_snapshot("2026-06-15", 1500)), encoding="utf-8")
    update_history(latency_snap, history_dir)

    plain_snap = tmp_path / "plain.json"
    plain_snap.write_text(
        json.dumps(
            {
                "timestamp": "2026-06-16T00:00:00Z",
                "regions": {"eastus": {"ai": {"aiModels.openai.gpt-4o.2024": {"status": "available"}}}},
            }
        ),
        encoding="utf-8",
    )
    update_history(plain_snap, history_dir)

    latency = json.loads((history_dir / "latency-history.json").read_text(encoding="utf-8"))
    dates = [day["date"] for day in latency["days"]]
    assert dates == ["2026-06-15"]


def test_update_history_backfills_latency_from_existing_snapshots(tmp_path):
    history_dir = tmp_path / "history"
    snapshots_dir = history_dir / "snapshots"
    snapshots_dir.mkdir(parents=True)
    for date, p50 in [("2026-06-14", 1400), ("2026-06-15", 1550)]:
        with gzip.open(snapshots_dir / f"{date}.json.gz", "wt", encoding="utf-8") as stream:
            stream.write(json.dumps(_latency_snapshot(date, p50)))

    today = tmp_path / "today.json"
    today.write_text(json.dumps(_latency_snapshot("2026-06-16", 1600)), encoding="utf-8")
    update_history(today, history_dir)

    latency = json.loads((history_dir / "latency-history.json").read_text(encoding="utf-8"))
    dates = sorted(day["date"] for day in latency["days"])
    assert dates == ["2026-06-14", "2026-06-15", "2026-06-16"]


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_exc_info):
        return False

    def read(self):
        return self._payload


def _bad_gateway(url):
    return urllib.error.HTTPError(url, 502, "Bad Gateway", {}, None)


def _script_urlopen(monkeypatch, results):
    calls = []

    def fake_urlopen(url, timeout=None):
        calls.append(url)
        result = results.pop(0)
        if isinstance(result, Exception):
            raise result
        return _FakeResponse(result)

    monkeypatch.setattr(history.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(history, "HISTORY_RETRY_BACKOFF_SECONDS", 0)
    return calls


def test_fetch_history_retries_transient_server_error(tmp_path, monkeypatch):
    base_url = "https://example.test/api/history"
    index_url = f"{base_url}/index.json"
    calls = _script_urlopen(
        monkeypatch,
        [
            _bad_gateway(index_url),
            json.dumps({"generated_at": "2026-07-29T00:00:00Z", "days": []}).encode("utf-8"),
            b"{}",
        ],
    )

    history_dir = tmp_path / "history"
    assert fetch_history(history_dir, base_url) is True
    assert calls == [index_url, index_url, f"{base_url}/recent-changes.json"]
    assert json.loads((history_dir / "index.json").read_text(encoding="utf-8"))["days"] == []


def test_fetch_history_raises_when_server_error_persists(tmp_path, monkeypatch):
    base_url = "https://example.test/api/history"
    index_url = f"{base_url}/index.json"
    calls = _script_urlopen(
        monkeypatch,
        [_bad_gateway(index_url) for _ in range(history.HISTORY_FETCH_ATTEMPTS)],
    )

    with pytest.raises(urllib.error.HTTPError):
        fetch_history(tmp_path / "history", base_url)
    assert len(calls) == history.HISTORY_FETCH_ATTEMPTS


def _briefing_snapshot(date, status, additions=0):
    return Snapshot.model_validate({
        "timestamp": f"{date}T00:00:00Z",
        "regions": {
            "eastus": {
                "compute": {
                    "vmSkus.standard.base": {"status": "available"},
                    "vmSkus.standard.target": {"status": status},
                    "vmSkus.standard.old-absence": {"status": "unavailable"},
                    **{
                        f"vmSkus.standard.new-{number}": {"status": "available"}
                        for number in range(additions)
                    },
                },
            },
        },
    })


def _legacy_reader_history(history_dir):
    snapshots = [
        _briefing_snapshot("2026-05-08", "available"),
        _briefing_snapshot("2026-05-09", "unavailable"),
        _briefing_snapshot("2026-05-10", "unavailable", additions=65),
    ]
    days = []
    for number, current in enumerate(snapshots):
        date = current.timestamp.date().isoformat()
        entry = {
            "date": date,
            "snapshot_timestamp": current.timestamp.isoformat(),
            "snapshot_path": f"snapshots/{date}.json.gz",
            "change_path": f"changes/{date}.json",
            "previous_date": days[-1]["date"] if days else None,
            "previous_snapshot_path": days[-1]["snapshot_path"] if days else None,
            "total_changes": 65 if number == 2 else number,
            "highlights": [],
            "narrative": f"Keep original narrative {date}.",
        }
        history._write_snapshot_gzip(history_dir / entry["snapshot_path"], current)
        history._write_json(history_dir / entry["change_path"], entry)
        days.append(entry)
    index = {
        "latest_date": days[-1]["date"],
        "latest_snapshot_path": days[-1]["snapshot_path"],
        "generated_at": "2026-05-10T01:00:00+00:00",
        "recent_changes_path": "recent-changes.json",
        "days": list(reversed(days)),
    }
    history._write_json(history_dir / "index.json", index)
    history._write_json(history_dir / "recent-changes.json", {
        "generated_at": index["generated_at"], "days": index["days"],
    })
    return snapshots[-1]


def test_prepare_reader_history_rebuilds_full_latest_facts_without_mutating_inputs(
    tmp_path, monkeypatch
):
    history_dir = tmp_path / "history"
    output_dir = tmp_path / "public" / "api" / "history"
    current = _legacy_reader_history(history_dir)
    index = history._read_json(history_dir / "index.json")
    # Older metadata must not cause a scan of the retained snapshot archive.
    index["days"].extend({
        "date": f"2025-{month:02d}-{day:02d}",
        "snapshot_path": f"snapshots/2025-{month:02d}-{day:02d}.json.gz",
        "change_path": f"changes/2025-{month:02d}-{day:02d}.json",
    } for month in range(1, 5) for day in range(1, 29))
    history._write_json(history_dir / "index.json", index)
    original = {
        path.relative_to(history_dir): path.read_bytes()
        for path in history_dir.rglob("*") if path.is_file()
    }
    history.copy_history_to_api(history_dir, output_dir)
    loaded = []
    original_load = history._load_history_snapshot

    def tracked_load(path):
        loaded.append(path.name)
        return original_load(path)

    monkeypatch.setattr(history, "_load_history_snapshot", tracked_load)
    reader_index, reader_recent = history.prepare_reader_history(history_dir, output_dir, current)
    assert loaded == ["2026-05-09.json.gz", "2026-05-08.json.gz"]
    assert len(reader_index["days"]) == 115
    assert len(reader_recent["days"]) == history.RECENT_CHANGE_DAYS
    compact = reader_index["days"][0]["briefing"]
    assert compact["version"] == 1
    assert compact["counts"]["new_listings"] == 65
    assert compact["counts"]["continuing_absences"] == 1
    assert compact["tracking"] == {
        "since": "2026-05-08", "complete": False, "mode": "tracked_absences",
    }
    assert "records" not in compact
    assert "records" not in reader_recent["days"][0]["briefing"]
    assert reader_index["days"][1]["briefing"] == {"version": 0, "legacy": True}
    full_day = history._read_json(output_dir / "changes" / "2026-05-10.json")
    assert full_day["narrative"] == "Keep original narrative 2026-05-10."
    assert len(full_day["briefing"]["records"]) == 66
    assert reader_index == history._read_json(output_dir / "index.json")
    assert reader_recent == history._read_json(output_dir / "recent-changes.json")
    assert (output_dir / "changes" / "2026-05-09.json").read_bytes() == original[
        history_dir.joinpath("changes", "2026-05-09.json").relative_to(history_dir)
    ]
    assert original == {
        path.relative_to(history_dir): path.read_bytes()
        for path in history_dir.rglob("*") if path.is_file()
    }


def test_update_history_persists_continuing_records_and_restorations(tmp_path):
    history_dir = tmp_path / "history"
    for date, status in [
        ("2026-05-07", "available"),
        ("2026-05-08", "unavailable"),
        ("2026-05-09", "unavailable"),
        ("2026-05-10", "available"),
    ]:
        snapshot_path = tmp_path / "current.json"
        snapshot_path.write_text(_briefing_snapshot(date, status).model_dump_json(), encoding="utf-8")
        update_history(snapshot_path, history_dir)

    initial = history._read_json(history_dir / "changes" / "2026-05-07.json")["briefing"]
    continuing = history._read_json(history_dir / "changes" / "2026-05-09.json")["briefing"]
    restored = history._read_json(history_dir / "changes" / "2026-05-10.json")["briefing"]
    assert initial["baseline_available"] is False
    assert initial["records"] == []
    assert continuing["counts"]["continuing_absences"] == 1
    assert len(continuing["records"]) == 1
    assert restored["counts"]["restorations"] == 1
    assert restored["counts"]["new_listings"] == 0
    assert all(
        "records" not in day["briefing"]
        for day in history._read_json(history_dir / "index.json")["days"]
    )


def test_prepare_reader_history_reuses_full_prior_records_with_only_one_baseline_load(
    tmp_path, monkeypatch
):
    history_dir = tmp_path / "history"
    output_dir = tmp_path / "api"
    current = _legacy_reader_history(history_dir)
    previous = history._load_history_snapshot(history_dir / "snapshots" / "2026-05-09.json.gz")
    older = history._load_history_snapshot(history_dir / "snapshots" / "2026-05-08.json.gz")
    prior_path = history_dir / "changes" / "2026-05-09.json"
    prior_day = history._read_json(prior_path)
    prior_day["briefing"] = history.build_briefing(previous, older)
    history._write_json(prior_path, prior_day)
    history.copy_history_to_api(history_dir, output_dir)
    loaded = []
    original_load = history._load_history_snapshot

    def tracked_load(path):
        loaded.append(path.name)
        return original_load(path)

    monkeypatch.setattr(history, "_load_history_snapshot", tracked_load)
    index, _ = history.prepare_reader_history(history_dir, output_dir, current)
    assert loaded == ["2026-05-09.json.gz"]
    assert index["days"][0]["briefing"]["counts"]["continuing_absences"] == 1


def test_prepare_reader_history_preserves_restoration_from_older_historical_context(
    tmp_path, monkeypatch
):
    history_dir = tmp_path / "history"
    output_dir = tmp_path / "api"
    _legacy_reader_history(history_dir)
    current = _briefing_snapshot("2026-05-11", "available", additions=65)
    snapshot_path = tmp_path / "current.json"
    snapshot_path.write_text(current.model_dump_json(), encoding="utf-8")
    update_history(snapshot_path, history_dir)
    original_path = history_dir / "changes" / "2026-05-11.json"
    original_bytes = original_path.read_bytes()
    full_day = history._read_json(original_path)
    assert full_day["briefing"]["counts"]["restorations"] == 1
    assert full_day["briefing"]["records"][0]["last_available_date"] == "2026-05-08"
    prior = history._briefing_prior_day(
        history_dir,
        history._read_json(history_dir / "index.json"),
        history._read_json(history_dir / "changes" / "2026-05-10.json"),
        history._load_history_snapshot(history_dir / "snapshots" / "2026-05-10.json.gz"),
    )
    assert not any(
        record["feature"] == "vmSkus.standard.target" for record in prior["briefing"]["records"]
    )
    history.copy_history_to_api(history_dir, output_dir)

    def unexpected_reconstruction(*args, **kwargs):
        pytest.fail("Matching full daily facts must retain their historical context")

    monkeypatch.setattr(history, "_briefing_prior_day", unexpected_reconstruction)
    index, recent = history.prepare_reader_history(history_dir, output_dir, current)
    assert index["days"][0]["briefing"]["counts"]["restorations"] == 1
    assert recent["days"][0]["briefing"]["counts"]["new_listings"] == 0
    assert history._read_json(output_dir / "changes" / "2026-05-11.json") == full_day
    assert original_path.read_bytes() == original_bytes


@pytest.mark.parametrize("field,value", [
    ("current_timestamp", "2026-05-10T01:00:00+00:00"),
    ("previous_timestamp", "2026-05-09T01:00:00+00:00"),
    ("records", None),
    ("records", []),
    ("counts", {}),
    ("groups", None),
    ("version", 0),
    ("baseline_available", False),
])
def test_prepare_reader_history_recomputes_stale_or_incomplete_full_facts(tmp_path, field, value):
    history_dir = tmp_path / "history"
    output_dir = tmp_path / "api"
    current = _legacy_reader_history(history_dir)
    previous = history._load_history_snapshot(history_dir / "snapshots" / "2026-05-09.json.gz")
    day_path = history_dir / "changes" / "2026-05-10.json"
    full_day = history._read_json(day_path)
    full_day["briefing"] = history.build_briefing(current, previous)
    full_day["briefing"][field] = value
    history._write_json(day_path, full_day)
    history.copy_history_to_api(history_dir, output_dir)

    index, _ = history.prepare_reader_history(history_dir, output_dir, current)
    briefing = index["days"][0]["briefing"]
    assert briefing["counts"]["new_listings"] == 65
    assert briefing["counts"]["continuing_absences"] == 1
    assert briefing["current_timestamp"] == current.timestamp.isoformat()
    assert briefing["previous_timestamp"] == previous.timestamp.isoformat()
    assert briefing["baseline_available"] is True
    assert briefing["version"] == 1


def test_prepare_reader_history_missing_baseline_is_explicit(tmp_path, caplog):
    history_dir = tmp_path / "history"
    output_dir = tmp_path / "api"
    current = _legacy_reader_history(history_dir)
    (history_dir / "snapshots" / "2026-05-09.json.gz").unlink()
    history.copy_history_to_api(history_dir, output_dir)
    index, _ = history.prepare_reader_history(history_dir, output_dir, current)
    briefing = index["days"][0]["briefing"]
    assert briefing["baseline_available"] is False
    assert briefing["counts"]["new_listings"] == 0
    assert briefing["counts"]["continuing_absences"] == 0
    assert briefing["comparison_days"] is None
    assert "2026-05-09.json.gz" in caplog.text
    assert "is missing" in caplog.text
    assert "comparison baseline is unavailable" in caplog.text


def test_prepare_reader_history_without_history_returns_existing_optional_values(tmp_path):
    assert history.prepare_reader_history(
        tmp_path / "missing", tmp_path / "api", _briefing_snapshot("2026-05-10", "available")
    ) == (None, None)


def test_prepare_reader_history_refuses_input_as_output(tmp_path):
    history_dir = tmp_path / "history"
    current = _legacy_reader_history(history_dir)
    with pytest.raises(ValueError, match="outside input"):
        history.prepare_reader_history(history_dir, history_dir, current)
    with pytest.raises(ValueError, match="outside input"):
        history.prepare_reader_history(history_dir, history_dir / "child", current)


@pytest.mark.parametrize("unsafe", [
    "", ".", "../outside.json", r"..\outside.json", "/outside.json", r"\outside.json",
    "C:/outside.json", r"C:\outside.json", "//server/share/file.json",
    r"\\server\share\file.json", "https://example.test/file.json",
    "changes/file.json:stream", "changes/../../file.json",
])
def test_history_paths_reject_traversal_windows_roots_and_external_urls(tmp_path, unsafe):
    assert history._is_safe_relative_path(unsafe) is False
    with pytest.raises(ValueError, match="Unsafe history path"):
        history._safe_history_path(tmp_path / "history", unsafe)


def test_prepare_reader_history_does_not_follow_unsafe_stored_paths(tmp_path, caplog):
    history_dir = tmp_path / "history"
    output_dir = tmp_path / "api"
    current = _legacy_reader_history(history_dir)
    index = history._read_json(history_dir / "index.json")
    index["days"][0]["change_path"] = "../outside.json"
    index["days"][0]["previous_snapshot_path"] = "../outside.json"
    history._write_json(history_dir / "index.json", index)
    outside_path = tmp_path / "outside.json"
    outside_path.write_text("Must not read or overwrite", encoding="utf-8")
    history.copy_history_to_api(history_dir, output_dir)
    reader_index, _ = history.prepare_reader_history(history_dir, output_dir, current)
    assert outside_path.read_text(encoding="utf-8") == "Must not read or overwrite"
    assert reader_index["days"][0]["briefing"]["baseline_available"] is False
    assert reader_index["days"][0]["change_path"] == "changes/2026-05-10.json"
    assert (output_dir / "changes" / "2026-05-10.json").exists()
    assert "cannot load snapshot" in caplog.text
    assert "cannot load daily changes" in caplog.text
    assert "Unsafe history path" in caplog.text
    assert all(record.levelname == "WARNING" for record in caplog.records)


@pytest.mark.parametrize("error", [
    PermissionError("Access denied"), ValueError("Invalid snapshot JSON"), EOFError(),
])
def test_reader_snapshot_logs_unreadable_evidence(tmp_path, monkeypatch, caplog, error):
    def unreadable(*args, **kwargs):
        raise error

    monkeypatch.setattr(history, "_load_previous_snapshot", unreadable)
    assert history._reader_snapshot(tmp_path, {"snapshot_path": "snapshots/baseline.json.gz"}) is None
    assert "cannot load snapshot" in caplog.text
    assert "snapshots/baseline.json.gz" in caplog.text
    assert type(error).__name__ in caplog.text


@pytest.mark.parametrize("error", [
    PermissionError("Access denied"), ValueError("Invalid daily JSON"),
])
def test_reader_change_day_logs_unreadable_evidence(tmp_path, monkeypatch, caplog, error):
    def unreadable(*args, **kwargs):
        raise error

    monkeypatch.setattr(history, "_read_json", unreadable)
    assert history._reader_change_day(tmp_path, {"change_path": "changes/day.json"}) is None
    assert "cannot load daily changes" in caplog.text
    assert "changes/day.json" in caplog.text
    assert type(error).__name__ in caplog.text


@pytest.mark.parametrize("payload,reason", [(None, "is missing"), ([], "must contain a JSON object")])
def test_reader_change_day_logs_missing_or_invalid_documents(tmp_path, caplog, payload, reason):
    if payload is not None:
        (tmp_path / "day.json").write_text(json.dumps(payload), encoding="utf-8")
    assert history._reader_change_day(tmp_path, {"change_path": "day.json"}) is None
    assert "daily changes" in caplog.text
    assert reason in caplog.text


def test_fetch_history_retains_full_briefing_records_through_change_path(tmp_path, monkeypatch):
    index = {
        "days": [{
            "date": "2026-05-10",
            "change_path": "changes/2026-05-10.json",
            "briefing": {"version": 1, "counts": {"new_listings": 65}},
        }],
    }
    full_day = {
        **index["days"][0],
        "briefing": {
            "version": 1,
            "records": [{"feature": f"vmSkus.standard.new-{i}"} for i in range(65)],
        },
    }
    payloads = {
        "index.json": index,
        "changes/2026-05-10.json": full_day,
        "recent-changes.json": index,
    }
    calls = []

    def fake_urlopen(url, timeout=None):
        calls.append(url)
        relative = url.removeprefix("https://example.test/api/history/")
        return _FakeResponse(json.dumps(payloads[relative]).encode("utf-8"))

    monkeypatch.setattr(history.urllib.request, "urlopen", fake_urlopen)
    history_dir = tmp_path / "history"
    assert fetch_history(history_dir, "https://example.test/api/history")
    assert len(calls) == 3
    assert history._read_json(history_dir / "changes" / "2026-05-10.json") == full_day
