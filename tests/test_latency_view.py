from datetime import datetime, timezone

from azure_region_monitor.latency_view import build_latency_rows, parse_latency_message
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
