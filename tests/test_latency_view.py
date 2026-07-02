from datetime import datetime, timezone

from azure_region_monitor.latency_view import (
    build_latency_rows,
    build_latency_series,
    build_regional_latency_rows,
    extract_latency_metrics,
    parse_latency_message,
)
from azure_region_monitor.models import FeatureResult, Snapshot


def test_parse_latency_message_well_formed():
    msg = (
        "openai/gpt-4o from github-global: p50 1607ms, p95 1610ms, "
        "TTFT p50 1478ms, 62.2 tok/s over 3/3 samples."
    )
    parsed = parse_latency_message(msg)
    assert parsed == {
        "p50_ms": 1607,
        "p95_ms": 1610,
        "ttft_ms": 1478,
        "tokens_per_second": 62.2,
        "samples_collected": 3,
        "samples_requested": 3,
    }


def test_parse_latency_message_partial_samples():
    msg = "openai/o4-mini from github-global: p50 3047ms, p95 3429ms, TTFT p50 2935ms, 51.1 tok/s over 2/3 samples."
    parsed = parse_latency_message(msg)
    assert parsed["samples_collected"] == 2
    assert parsed["samples_requested"] == 3
    assert parsed["tokens_per_second"] == 51.1


def test_parse_latency_message_malformed_returns_none():
    assert parse_latency_message(None) is None
    assert parse_latency_message("") is None
    assert parse_latency_message("rate limited; try again later") is None


def test_build_latency_rows_sorted_by_p50_with_metrics():
    snapshot = Snapshot(
        timestamp=datetime(2026, 6, 16, tzinfo=timezone.utc),
        regions={
            "github-global": {
                "model-latency": {
                    "modelLatency.openai.gpt-4o": FeatureResult(
                        status="available",
                        latency_ms=1607,
                        message=(
                            "openai/gpt-4o from github-global: p50 1607ms, p95 1610ms, "
                            "TTFT p50 1478ms, 62.2 tok/s over 3/3 samples."
                        ),
                    ),
                    "modelLatency.openai.gpt-5-mini": FeatureResult(
                        status="available",
                        latency_ms=3408,
                        message=(
                            "openai/gpt-5-mini from github-global: p50 3408ms, p95 3558ms, "
                            "TTFT p50 3278ms, 32.0 tok/s over 3/3 samples."
                        ),
                    ),
                }
            }
        },
    )

    rows = build_latency_rows(snapshot)

    assert [row["model"] for row in rows] == ["openai/gpt-4o", "openai/gpt-5-mini"]
    fast = rows[0]
    assert fast["latency_ms"] == 1607
    assert fast["p95_ms"] == 1610
    assert fast["ttft_ms"] == 1478
    assert fast["tokens_per_second"] == 62.2
    assert fast["samples_collected"] == 3


def test_build_latency_rows_handles_unknown_without_metrics():
    snapshot = Snapshot(
        regions={
            "github-global": {
                "model-latency": {
                    "modelLatency.openai.o4-mini": FeatureResult(
                        status="unknown", message="Too many requests."
                    ),
                }
            }
        },
    )

    rows = build_latency_rows(snapshot)

    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "unknown"
    assert row["latency_ms"] is None
    assert row["p95_ms"] is None
    assert row["tokens_per_second"] is None


def test_build_latency_rows_empty_when_no_modality():
    snapshot = Snapshot(regions={"eastus": {"ai": {"aiModels.openai.gpt-4o.2024": FeatureResult(status="available")}}})
    assert build_latency_rows(snapshot) == []


def test_model_label_handles_dotted_versions():
    snapshot = Snapshot(
        regions={
            "github-global": {
                "model-latency": {
                    "modelLatency.openai.gpt-4.1": FeatureResult(
                        status="available",
                        latency_ms=900,
                        message="openai/gpt-4.1 from github-global: p50 900ms, p95 950ms, TTFT p50 800ms, 70.0 tok/s over 3/3 samples.",
                    ),
                    "modelLatency.meta.llama-3.3-70b": FeatureResult(status="unknown", message="boom"),
                }
            }
        }
    )
    rows = build_latency_rows(snapshot)
    models = {row["model"] for row in rows}
    assert "openai/gpt-4.1" in models
    assert "meta/llama-3.3-70b" in models


def test_extract_latency_metrics_keys_by_model():
    snapshot = Snapshot(
        regions={
            "github-global": {
                "model-latency": {
                    "modelLatency.openai.gpt-4o": FeatureResult(
                        status="available",
                        latency_ms=1607,
                        message="openai/gpt-4o from github-global: p50 1607ms, p95 1610ms, TTFT p50 1478ms, 62.2 tok/s over 3/3 samples.",
                    ),
                    "modelLatency.openai.o4-mini": FeatureResult(status="unknown", message="429"),
                }
            }
        }
    )
    metrics = extract_latency_metrics(snapshot)
    assert metrics["openai/gpt-4o"]["p50_ms"] == 1607
    assert metrics["openai/gpt-4o"]["status"] == "available"
    assert metrics["openai/o4-mini"]["status"] == "unknown"
    assert metrics["openai/o4-mini"]["p50_ms"] is None


def test_build_latency_series_orders_and_filters():
    history = {
        "days": [
            {"date": "2026-06-17", "models": {"openai/gpt-4o": {"p50_ms": 1500}, "openai/o4-mini": {"p50_ms": None}}},
            {"date": "2026-06-15", "models": {"openai/gpt-4o": {"p50_ms": 1700}}},
            {"date": "2026-06-16", "models": {"openai/gpt-4o": {"p50_ms": 1600}}},
            {"not": "a dict day"},
        ]
    }
    series = build_latency_series(history)
    assert [point["p50_ms"] for point in series["openai/gpt-4o"]] == [1700, 1600, 1500]
    assert [point["date"] for point in series["openai/gpt-4o"]] == ["2026-06-15", "2026-06-16", "2026-06-17"]
    assert "openai/o4-mini" not in series


def test_build_latency_series_empty_for_missing_history():
    assert build_latency_series(None) == {}
    assert build_latency_series({}) == {}


def test_build_regional_latency_rows_sorted_fastest_region_first():
    snapshot = Snapshot(
        regions={
            "eastus": {
                "ai-latency": {
                    "aiLatency.openai.gpt-4o": FeatureResult(
                        status="available",
                        latency_ms=2238,
                        message="gpt-4o from eastus: p50 2238ms, p95 3035ms, TTFT p50 1935ms, 45.0 tok/s over 3/3 samples.",
                    )
                }
            },
            "uksouth": {
                "ai-latency": {
                    "aiLatency.openai.gpt-4o": FeatureResult(
                        status="available",
                        latency_ms=1026,
                        message="gpt-4o from uksouth: p50 1026ms, p95 1100ms, TTFT p50 900ms, 60.0 tok/s over 3/3 samples.",
                    )
                }
            },
            "germanywestcentral": {
                "ai": {"aiModels.openai.gpt-4o.2024": FeatureResult(status="available")}
            },
        }
    )

    rows = build_regional_latency_rows(snapshot)

    assert [row["region"] for row in rows] == ["uksouth", "eastus"]
    assert rows[0]["model"] == "gpt-4o"
    assert rows[0]["latency_ms"] == 1026
    assert rows[0]["p95_ms"] == 1100
    assert rows[0]["tokens_per_second"] == 60.0


def test_build_regional_latency_rows_empty_without_modality():
    snapshot = Snapshot(regions={"eastus": {"ai": {"aiModels.x.y.1": FeatureResult(status="available")}}})
    assert build_regional_latency_rows(snapshot) == []


def _regional_snapshot():
    def result(region, p50):
        return FeatureResult(
            status="available",
            latency_ms=p50,
            message=f"m from {region}: p50 {p50}ms, p95 {p50 + 40}ms, TTFT p50 {p50 - 50}ms, 50.0 tok/s over 3/3 samples.",
        )

    return Snapshot(
        regions={
            "eastus": {"ai-latency": {"aiLatency.openai.gpt-4o": result("eastus", 1090)}},
            "westus3": {"ai-latency": {"aiLatency.openai.gpt-4o": result("westus3", 658)}},
        }
    )


def test_extract_regional_latency_metrics_keyed_by_model_and_region():
    from azure_region_monitor.latency_view import extract_regional_latency_metrics

    metrics = extract_regional_latency_metrics(_regional_snapshot())
    assert metrics == {
        "gpt-4o": {
            "eastus": {"status": "available", "p50_ms": 1090},
            "westus3": {"status": "available", "p50_ms": 658},
        }
    }


def test_annotate_rank_changes_up_down_same_new_none():
    from azure_region_monitor.latency_view import annotate_rank_changes

    rows = [
        {"model": "a", "latency_ms": 100},  # now #1
        {"model": "b", "latency_ms": 200},  # now #2
        {"model": "c", "latency_ms": 300},  # now #3
        {"model": "d", "latency_ms": None},  # unranked this snapshot
    ]
    # Previously: a #2, b #2->wait distinct; use a=#3, b=#2, c=#3? keep simple:
    previous = {"a": 3, "b": 2, "c": 3}
    annotate_rank_changes(rows, previous, key_field="model")

    by_model = {r["model"]: r for r in rows}
    assert by_model["a"]["rank"] == 1 and by_model["a"]["rank_delta"] == 2
    assert by_model["a"]["rank_state"] == "up"
    assert by_model["b"]["rank"] == 2 and by_model["b"]["rank_state"] == "same"
    assert by_model["c"]["rank"] == 3 and by_model["c"]["rank_state"] == "same"
    # "d" has no numeric latency -> unranked this snapshot.
    assert by_model["d"]["rank"] is None and by_model["d"]["rank_state"] == "none"


def test_annotate_rank_changes_marks_new_when_absent_before():
    from azure_region_monitor.latency_view import annotate_rank_changes

    rows = [{"model": "x", "latency_ms": 100}]
    annotate_rank_changes(rows, {}, key_field="model")
    assert rows[0]["rank"] == 1
    assert rows[0]["rank_state"] == "new"
    assert rows[0]["rank_delta"] is None


def test_previous_leaderboard_and_regional_ranks_from_history():
    from azure_region_monitor.latency_view import (
        previous_leaderboard_ranks,
        previous_regional_ranks,
    )

    history = {
        "days": [
            {  # newest day (ignored as "previous")
                "date": "2026-06-18",
                "models": {"openai/gpt-4o": {"p50_ms": 900}},
                "regional": {"gpt-4o": {"eastus": {"p50_ms": 900}}},
            },
            {  # this is the "previous" snapshot used for deltas
                "date": "2026-06-17",
                "models": {"openai/gpt-4o": {"p50_ms": 1500}, "openai/o4-mini": {"p50_ms": 1200}},
                "regional": {
                    "gpt-4o": {"eastus": {"p50_ms": 1100}, "westus3": {"p50_ms": 700}}
                },
            },
        ]
    }
    assert previous_leaderboard_ranks(history) == {"openai/o4-mini": 1, "openai/gpt-4o": 2}
    assert previous_regional_ranks(history) == {"gpt-4o": {"westus3": 1, "eastus": 2}}


def test_previous_ranks_empty_without_enough_history():
    from azure_region_monitor.latency_view import (
        previous_leaderboard_ranks,
        previous_regional_ranks,
    )

    assert previous_leaderboard_ranks(None) == {}
    assert previous_regional_ranks({"days": [{"date": "2026-06-18", "models": {}}]}) == {}


