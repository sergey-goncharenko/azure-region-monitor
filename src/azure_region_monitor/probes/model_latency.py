from __future__ import annotations

import statistics
from dataclasses import dataclass

from azure_region_monitor.models import FeatureResult

DEFAULT_PROMPT = "Count from 1 to 50. Output only the numbers separated by single spaces."
DEFAULT_MAX_TOKENS = 256
DEFAULT_SAMPLES = 5
DEFAULT_RATE_LIMIT_RETRIES = 5
DEFAULT_RATE_LIMIT_BACKOFF_SECONDS = 20.0
# Rate-limited inference endpoints can report a Retry-After measured in the
# seconds until a quota reset. Never sleep longer than this ceiling for one backoff.
DEFAULT_MAX_BACKOFF_SECONDS = 60.0


@dataclass(frozen=True)
class LatencyMeasurement:
    """A single timed inference call.

    ttft_ms is time-to-first-token; total_ms is the full round trip; output_tokens
    is the number of generated tokens used to derive throughput.
    """

    ttft_ms: float
    total_ms: float
    output_tokens: int


class LatencyClientError(Exception):
    def __init__(self, error_code: str, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.retry_after = retry_after


def _is_rate_limited(error: LatencyClientError) -> bool:
    return error.retry_after is not None or "429" in (error.error_code or "")


def _aggregate_result(
    region: str,
    target,
    measurements: list[LatencyMeasurement],
    requested_samples: int,
) -> FeatureResult:
    totals = [measurement.total_ms for measurement in measurements]
    ttfts = [measurement.ttft_ms for measurement in measurements]
    throughputs = [
        measurement.output_tokens / (measurement.total_ms / 1000)
        for measurement in measurements
        if measurement.total_ms > 0
    ]

    p50 = _percentile(totals, 50)
    p95 = _percentile(totals, 95)
    ttft_p50 = _percentile(ttfts, 50)
    tokens_per_second = statistics.median(throughputs) if throughputs else 0.0

    message = (
        f"{target.model} from {region}: p50 {round(p50)}ms, p95 {round(p95)}ms, "
        f"TTFT p50 {round(ttft_p50)}ms, {tokens_per_second:.1f} tok/s over "
        f"{len(measurements)}/{requested_samples} samples."
    )

    return FeatureResult(status="available", latency_ms=round(p50), message=message)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (percentile / 100) * (len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight
