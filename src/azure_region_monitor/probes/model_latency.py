from __future__ import annotations

import statistics
import time
from dataclasses import dataclass
from typing import Callable, Protocol

from azure_region_monitor.config import DEFAULT_LATENCY_MODELS, LatencyModel
from azure_region_monitor.models import FeatureResult
from azure_region_monitor.probes.base import ProbeResult

DEFAULT_PROMPT = "Count from 1 to 50. Output only the numbers separated by single spaces."
DEFAULT_MAX_TOKENS = 256
DEFAULT_SAMPLES = 5
DEFAULT_RATE_LIMIT_RETRIES = 5
DEFAULT_RATE_LIMIT_BACKOFF_SECONDS = 20.0
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
    def __init__(self, error_code: str, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.retry_after = retry_after


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
        rate_limit_retries: int = DEFAULT_RATE_LIMIT_RETRIES,
        rate_limit_backoff_seconds: float = DEFAULT_RATE_LIMIT_BACKOFF_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
        auto_discover: bool = False,
        catalog_fetcher: Callable[[], list[dict]] | None = None,
    ) -> None:
        self._fallback_models = models or DEFAULT_LATENCY_MODELS
        self._client = client
        self._samples = max(1, samples)
        self._prompt = prompt
        self._max_tokens = max_tokens
        self._client_factory = client_factory
        self._rate_limit_retries = max(0, rate_limit_retries)
        self._rate_limit_backoff_seconds = max(0.0, rate_limit_backoff_seconds)
        self._sleep = sleep
        self._auto_discover = auto_discover
        self._catalog_fetcher = catalog_fetcher
        self._resolved_models: list[LatencyModel] | None = None

    def run(self, region: str):
        client = self._get_client()
        for model in self._resolve_models():
            yield self._measure_model(region, model, client)

    def _resolve_models(self) -> list[LatencyModel]:
        if self._resolved_models is not None:
            return self._resolved_models
        if not self._auto_discover:
            self._resolved_models = self._fallback_models
            return self._resolved_models
        self._resolved_models = self._discover_models() or self._fallback_models
        return self._resolved_models

    def _discover_models(self) -> list[LatencyModel]:
        from azure_region_monitor.github_catalog import (
            default_catalog_fetcher,
            select_catalog_models,
        )

        fetcher = self._catalog_fetcher or default_catalog_fetcher
        try:
            discovered = select_catalog_models(fetcher())
        except Exception:
            return []
        if not discovered:
            return []
        # Keep the curated cross-publisher anchors (Phi, DeepSeek, Llama, ...) so the
        # leaderboard stays multi-publisher while OpenAI releases surface automatically.
        anchors = [
            model
            for model in self._fallback_models
            if not model.model.lower().startswith("openai/")
        ]
        seen = {model.model for model in discovered}
        return discovered + [model for model in anchors if model.model not in seen]

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
            measurement, last_error = self._collect_one_sample(client, model, last_error)
            if measurement is not None:
                measurements.append(measurement)

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

    def _collect_one_sample(
        self,
        client: InferenceLatencyClient,
        model: LatencyModel,
        last_error: LatencyClientError | None,
    ) -> tuple[LatencyMeasurement | None, LatencyClientError | None]:
        for attempt in range(self._rate_limit_retries + 1):
            try:
                measurement = client.measure(
                    model.model,
                    prompt=self._prompt,
                    max_tokens=self._max_tokens,
                )
                return measurement, last_error
            except LatencyClientError as error:
                last_error = error
                has_retries_left = attempt < self._rate_limit_retries
                if _is_rate_limited(error) and has_retries_left:
                    self._sleep(error.retry_after or self._rate_limit_backoff_seconds)
                    continue
                return None, last_error
        return None, last_error


def _is_rate_limited(error: LatencyClientError) -> bool:
    return error.retry_after is not None or "429" in (error.error_code or "")


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
