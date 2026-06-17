from datetime import datetime, timezone

from azure_region_monitor.latency_view import (
    build_latency_rows,
    build_latency_series,
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

