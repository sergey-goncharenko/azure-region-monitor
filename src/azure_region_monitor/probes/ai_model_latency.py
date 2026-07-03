from __future__ import annotations

import time
from typing import Callable, Protocol

from azure_region_monitor.config import AiLatencyTarget
from azure_region_monitor.models import FeatureResult
from azure_region_monitor.probes.base import ProbeResult
from azure_region_monitor.probes.model_latency import (
    DEFAULT_MAX_BACKOFF_SECONDS,
    DEFAULT_MAX_TOKENS,
    DEFAULT_PROMPT,
    DEFAULT_RATE_LIMIT_BACKOFF_SECONDS,
    DEFAULT_RATE_LIMIT_RETRIES,
    DEFAULT_SAMPLES,
    LatencyClientError,
    LatencyMeasurement,
    _aggregate_result,
    _is_rate_limited,
)

SERVICE = "ai-latency"


class AzureLatencyClient(Protocol):
    def measure(
        self, endpoint: str, deployment: str, *, prompt: str, max_tokens: int
    ) -> LatencyMeasurement:
        """Run one timed Azure OpenAI inference call or raise LatencyClientError."""


ClientFactory = Callable[[], AzureLatencyClient]


class AzureOpenAiLatencyProbe:
    """Measures Azure OpenAI inference latency per region.

    Each configured target is a single-region Standard deployment, so a successful
    timed call is attributable to that region. The probe only emits a result when
    the runner asks for a region it has a target for, which lets the runner drive
    it with the same per-region loop used by the other modalities.
    """

    name = "ai-model-latency-cli"

    def __init__(
        self,
        targets: list[AiLatencyTarget] | None = None,
        client: AzureLatencyClient | None = None,
        samples: int = DEFAULT_SAMPLES,
        prompt: str = DEFAULT_PROMPT,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        client_factory: ClientFactory | None = None,
        rate_limit_retries: int = DEFAULT_RATE_LIMIT_RETRIES,
        rate_limit_backoff_seconds: float = DEFAULT_RATE_LIMIT_BACKOFF_SECONDS,
        max_backoff_seconds: float = DEFAULT_MAX_BACKOFF_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._targets_by_region: dict[str, list[AiLatencyTarget]] = {}
        for target in targets or []:
            self._targets_by_region.setdefault(target.region, []).append(target)
        self._client = client
        self._samples = max(1, samples)
        self._prompt = prompt
        self._max_tokens = max_tokens
        self._client_factory = client_factory
        self._rate_limit_retries = max(0, rate_limit_retries)
        self._rate_limit_backoff_seconds = max(0.0, rate_limit_backoff_seconds)
        self._max_backoff_seconds = max(0.0, max_backoff_seconds)
        self._sleep = sleep

    def run(self, region: str):
        targets = self._targets_by_region.get(region)
        if not targets:
            return
        client = self._get_client()
        for target in targets:
            yield self._measure_target(region, target, client)

    def _get_client(self) -> AzureLatencyClient:
        if self._client is None:
            factory = self._client_factory or _default_client_factory
            self._client = factory()
        return self._client

    def _measure_target(
        self, region: str, target: AiLatencyTarget, client: AzureLatencyClient
    ) -> ProbeResult:
        feature = f"aiLatency.openai.{target.model}"
        measurements: list[LatencyMeasurement] = []
        last_error: LatencyClientError | None = None
        for _ in range(self._samples):
            measurement, last_error = self._collect_one_sample(client, target, last_error)
            if measurement is not None:
                measurements.append(measurement)

        if not measurements:
            return ProbeResult(
                service=SERVICE,
                feature=feature,
                result=FeatureResult(
                    status="unknown",
                    error_code=last_error.error_code if last_error else "LatencyNoSamples",
                    message=(
                        last_error.message
                        if last_error
                        else f"No latency samples were collected for '{target.model}' in {region}."
                    ),
                ),
            )

        return ProbeResult(
            service=SERVICE,
            feature=feature,
            result=_aggregate_result(region, target, measurements, self._samples),
        )

    def _collect_one_sample(
        self,
        client: AzureLatencyClient,
        target: AiLatencyTarget,
        last_error: LatencyClientError | None,
    ) -> tuple[LatencyMeasurement | None, LatencyClientError | None]:
        for attempt in range(self._rate_limit_retries + 1):
            try:
                measurement = client.measure(
                    target.endpoint,
                    target.deployment,
                    prompt=self._prompt,
                    max_tokens=self._max_tokens,
                )
                return measurement, last_error
            except LatencyClientError as error:
                last_error = error
                has_retries_left = attempt < self._rate_limit_retries
                if _is_rate_limited(error) and has_retries_left:
                    requested = error.retry_after or self._rate_limit_backoff_seconds
                    self._sleep(min(requested, self._max_backoff_seconds))
                    continue
                return None, last_error
        return None, last_error


def _default_client_factory() -> AzureLatencyClient:
    from azure_region_monitor.probes.azure_openai import AzureOpenAiClient

    return AzureOpenAiClient.from_env()
