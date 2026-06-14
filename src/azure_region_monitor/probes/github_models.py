from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from azure_region_monitor.probes.model_latency import (
    InferenceLatencyClient,
    LatencyClientError,
    LatencyMeasurement,
)

DEFAULT_ENDPOINT = "https://models.github.ai/inference"
DEFAULT_TIMEOUT_SECONDS = 60


class GitHubModelsClient(InferenceLatencyClient):
    """Streams chat completions from GitHub Models to measure inference latency.

    Uses a single global access endpoint, so it provides cross-model speed
    evidence from one vantage point. It does not attribute latency to an Azure
    region. Designed to be injected; the latency probe owns sampling and stats.
    """

    def __init__(
        self,
        token: str,
        endpoint: str = DEFAULT_ENDPOINT,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        opener: urllib.request.OpenerDirector | None = None,
    ) -> None:
        self._token = token
        self._endpoint = endpoint.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._opener = opener or urllib.request.build_opener()

    @classmethod
    def from_env(cls) -> "GitHubModelsClient":
        token = os.environ.get("GITHUB_MODELS_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if not token:
            raise LatencyClientError(
                "MissingGitHubModelsToken",
                "Set GITHUB_MODELS_TOKEN (or GITHUB_TOKEN) with models:read access.",
            )
        endpoint = os.environ.get("GITHUB_MODELS_ENDPOINT", DEFAULT_ENDPOINT)
        timeout_seconds = int(
            os.environ.get("MODEL_LATENCY_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))
        )
        return cls(token=token, endpoint=endpoint, timeout_seconds=timeout_seconds)

    def measure(self, model: str, *, prompt: str, max_tokens: int) -> LatencyMeasurement:
        body = json.dumps(
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0,
                "stream": True,
                "stream_options": {"include_usage": True},
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            f"{self._endpoint}/chat/completions",
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
            raise LatencyClientError(
                f"GitHubModelsHttp{error.code}",
                detail or f"GitHub Models returned HTTP {error.code} for '{model}'.",
            ) from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise LatencyClientError(
                "GitHubModelsUnreachable",
                f"GitHub Models request failed for '{model}': {error}",
            ) from error

        total_ms = (time.perf_counter() - started) * 1000
        output_tokens = usage_output_tokens if usage_output_tokens is not None else content_chunks

        if output_tokens <= 0 and ttft_ms is None:
            raise LatencyClientError(
                "GitHubModelsEmptyResponse",
                f"GitHub Models returned no streamed tokens for '{model}'.",
            )

        return LatencyMeasurement(
            ttft_ms=ttft_ms if ttft_ms is not None else total_ms,
            total_ms=total_ms,
            output_tokens=output_tokens,
        )


def _safe_json(payload: str) -> dict | None:
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _chunk_has_content(chunk: dict) -> bool:
    choices = chunk.get("choices")
    if not isinstance(choices, list):
        return False
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta")
        if isinstance(delta, dict) and delta.get("content"):
            return True
    return False


def _usage_output_tokens(chunk: dict) -> int | None:
    usage = chunk.get("usage")
    if not isinstance(usage, dict):
        return None
    tokens = usage.get("completion_tokens")
    return tokens if isinstance(tokens, int) else None
