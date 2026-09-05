import gzip
import json
import urllib.error

import pytest

from azure_region_monitor import history
from azure_region_monitor.history import fetch_history, update_history
from azure_region_monitor.models import Change


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
    assert net_new["details_url"] == "https://learn.microsoft.com/azure/ai-foundry/openai/concepts/models"


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
