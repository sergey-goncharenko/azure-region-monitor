from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from azure_region_monitor.probes.github_models import (
    _chunk_has_content,
    _parse_retry_after,
    _safe_json,
    _usage_output_tokens,
)
from azure_region_monitor.probes.model_latency import (
    LatencyClientError,
    LatencyMeasurement,
)

DEFAULT_API_VERSION = "2024-10-21"
DEFAULT_TIMEOUT_SECONDS = 60


class AzureOpenAiClient:
    """Streams chat completions from a regional Azure OpenAI deployment.

    Each Azure OpenAI account is created in one region with a single-region
    Standard deployment, so the measured latency is attributable to that region
    (the request is processed there). Authentication is keyless: the caller
    supplies a Microsoft Entra access token for the Cognitive Services data plane.
    """

    def __init__(
        self,
        token: str,
        api_version: str = DEFAULT_API_VERSION,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        opener: urllib.request.OpenerDirector | None = None,
    ) -> None:
        self._token = token
        self._api_version = api_version
        self._timeout_seconds = timeout_seconds
        self._opener = opener or urllib.request.build_opener()

    @classmethod
    def from_env(cls) -> "AzureOpenAiClient":
        token = os.environ.get("AZURE_OPENAI_TOKEN")
        if not token:
            raise LatencyClientError(
                "MissingAzureOpenAiToken",
                "Set AZURE_OPENAI_TOKEN with a Cognitive Services data-plane access token.",
            )
        api_version = os.environ.get("AZURE_OPENAI_API_VERSION", DEFAULT_API_VERSION)
        timeout_seconds = int(
            os.environ.get("AI_LATENCY_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))
        )
        return cls(token=token, api_version=api_version, timeout_seconds=timeout_seconds)

    def measure(
        self, endpoint: str, deployment: str, *, prompt: str, max_tokens: int
    ) -> LatencyMeasurement:
        url = (
            f"{endpoint.rstrip('/')}/openai/deployments/{deployment}/chat/completions"
            f"?api-version={self._api_version}"
        )
        body = json.dumps(
            {
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0,
                "stream": True,
                "stream_options": {"include_usage": True},
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
        )

        started = time.perf_counter()
        ttft_ms: float | None = None
        content_chunks = 0
        usage_output_tokens: int | None = None

        try:
            with self._opener.open(request, timeout=self._timeout_seconds) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[len("data:") :].strip()
                    if payload == "[DONE]":
                        break
                    chunk = _safe_json(payload)
                    if chunk is None:
                        continue
                    if _chunk_has_content(chunk):
                        content_chunks += 1
                        if ttft_ms is None:
                            ttft_ms = (time.perf_counter() - started) * 1000
                    tokens = _usage_output_tokens(chunk)
                    if tokens is not None:
                        usage_output_tokens = tokens
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace").strip()
            retry_after = _parse_retry_after(error.headers.get("Retry-After"))
            raise LatencyClientError(
                f"AzureOpenAiHttp{error.code}",
                detail or f"Azure OpenAI returned HTTP {error.code} for '{deployment}'.",
                retry_after=retry_after,
            ) from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise LatencyClientError(
                "AzureOpenAiUnreachable",
                f"Azure OpenAI request failed for '{deployment}': {error}",
            ) from error

        total_ms = (time.perf_counter() - started) * 1000
        output_tokens = usage_output_tokens if usage_output_tokens is not None else content_chunks
        if output_tokens <= 0 and ttft_ms is None:
            raise LatencyClientError(
                "AzureOpenAiEmptyResponse",
                f"Azure OpenAI returned no streamed tokens for '{deployment}'.",
            )
        return LatencyMeasurement(
            ttft_ms=ttft_ms if ttft_ms is not None else total_ms,
            total_ms=total_ms,
            output_tokens=output_tokens,
        )
