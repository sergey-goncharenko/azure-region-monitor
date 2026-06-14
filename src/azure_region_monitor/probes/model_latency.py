from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Callable, Protocol

from azure_region_monitor.config import DEFAULT_LATENCY_MODELS, LatencyModel
from azure_region_monitor.models import FeatureResult
from azure_region_monitor.probes.base import ProbeResult

DEFAULT_PROMPT = "Count from 1 to 50. Output only the numbers separated by single spaces."
DEFAULT_MAX_TOKENS = 256
DEFAULT_SAMPLES = 5
SERVICE = "model-latency"


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
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


class InferenceLatencyClient(Protocol):
    def measure(self, model: str, *, prompt: str, max_tokens: int) -> LatencyMeasurement:
        """Run one timed inference call or raise LatencyClientError."""


ClientFactory = Callable[[], InferenceLatencyClient]


class ModelLatencyProbe:
    """Measures inference response latency for a fixed set of models.

    The probe is vantage-aware but not Azure-region aware: it measures the
    endpoint the injected client targets (GitHub Models global access by
    default) and labels results with the logical region passed by the runner.
    Latency is a measurement, not an availability verdict.
    """

    name = "model-latency-cli"

    def __init__(
        self,
        models: list[LatencyModel] | None = None,
        client: InferenceLatencyClient | None = None,
        samples: int = DEFAULT_SAMPLES,
        prompt: str = DEFAULT_PROMPT,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._models = models or DEFAULT_LATENCY_MODELS
        self._client = client
        self._samples = max(1, samples)
        self._prompt = prompt
        self._max_tokens = max_tokens
        self._client_factory = client_factory

    def run(self, region: str):
        client = self._get_client()
        for model in self._models:
            yield self._measure_model(region, model, client)

    def _get_client(self) -> InferenceLatencyClient:
        if self._client is None:
            factory = self._client_factory or _default_client_factory
            self._client = factory()
        return self._client

    def _measure_model(
        self,
        region: str,
        model: LatencyModel,
        client: InferenceLatencyClient,
    ) -> ProbeResult:
        measurements: list[LatencyMeasurement] = []
        last_error: LatencyClientError | None = None
        for _ in range(self._samples):
            try:
                measurements.append(
                    client.measure(
                        model.model,
                        prompt=self._prompt,
                        max_tokens=self._max_tokens,
                    )
                )
            except LatencyClientError as error:
                last_error = error

        if not measurements:
            return ProbeResult(
                service=SERVICE,
                feature=model.feature,
                result=FeatureResult(
                    status="unknown",
                    error_code=last_error.error_code if last_error else "LatencyNoSamples",
                    message=(
                        last_error.message
                        if last_error
                        else f"No latency samples were collected for '{model.model}' in {region}."
                    ),
                ),
            )

        return ProbeResult(
            service=SERVICE,
            feature=model.feature,
            result=_aggregate_result(region, model, measurements, self._samples),
        )


def _aggregate_result(
    region: str,
    model: LatencyModel,
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
        f"{model.model} from {region}: p50 {round(p50)}ms, p95 {round(p95)}ms, "
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


def _default_client_factory() -> InferenceLatencyClient:
    from azure_region_monitor.probes.github_models import GitHubModelsClient

    return GitHubModelsClient.from_env()
