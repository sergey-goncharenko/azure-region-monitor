from types import SimpleNamespace

from azure_region_monitor.probes.model_latency import (
    LatencyClientError,
    LatencyMeasurement,
    _aggregate_result,
    _is_rate_limited,
    _percentile,
)


def test_aggregate_result_reports_p50_latency_and_sample_count():
    target = SimpleNamespace(model="gpt-4o")
    result = _aggregate_result(
        "eastus",
        target,
        [
            LatencyMeasurement(ttft_ms=100, total_ms=400, output_tokens=40),
            LatencyMeasurement(ttft_ms=200, total_ms=800, output_tokens=80),
            LatencyMeasurement(ttft_ms=300, total_ms=1200, output_tokens=120),
        ],
        requested_samples=5,
    )

    assert result.status == "available"
    assert result.latency_ms == 800
    assert "gpt-4o from eastus" in result.message
    assert "TTFT p50 200ms" in result.message
    assert "100.0 tok/s" in result.message
    assert "3/5 samples" in result.message


def test_is_rate_limited_uses_retry_after_or_429_code():
    assert _is_rate_limited(LatencyClientError("AzureOpenAiHttp429", "rate limited"))
    assert _is_rate_limited(LatencyClientError("Quota", "retry", retry_after=7))
    assert not _is_rate_limited(LatencyClientError("AzureOpenAiHttp500", "boom"))


def test_percentile_interpolates_between_ranks():
    values = [100, 200, 300, 400]
    assert _percentile(values, 50) == 250
    assert _percentile(values, 0) == 100
    assert _percentile(values, 100) == 400
