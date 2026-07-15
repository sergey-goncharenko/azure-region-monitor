from __future__ import annotations

import http.client
import json
import os
import re
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
REASONING_MIN_COMPLETION_TOKENS = 512


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
        body = json.dumps(_build_request_payload(model, prompt, max_tokens)).encode("utf-8")

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
            detail = _read_error_body(error)
            retry_after = _parse_retry_after(error.headers.get("Retry-After"))
            raise LatencyClientError(
                f"GitHubModelsHttp{error.code}",
                detail or f"GitHub Models returned HTTP {error.code} for '{model}'.",
                retry_after=retry_after,
            ) from error
        except (urllib.error.URLError, http.client.HTTPException, OSError) as error:
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

    def complete(
        self,
        *,
        model: str,
        system: str,
        user: str,
        max_tokens: int = 220,
        temperature: float = 0.0,
    ) -> str:
        """Return the text of a non-streaming chat completion.

        Used for short text generation (such as a daily change digest). Reasoning
        models (gpt-5*, o-series) reject 'max_tokens' and a non-default temperature,
        so the payload adapts to the model. Raises LatencyClientError on transport or
        HTTP failures so callers can fall back.
        """

        payload: dict = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        reasoning_effort = _github_reasoning_effort(model)
        if reasoning_effort is not None:
            payload["max_completion_tokens"] = max(max_tokens, REASONING_MIN_COMPLETION_TOKENS)
            payload["reasoning_effort"] = reasoning_effort
        else:
            payload["max_tokens"] = max_tokens
            payload["temperature"] = temperature
        body = json.dumps(payload).encode("utf-8")

        request = urllib.request.Request(
            f"{self._endpoint}/chat/completions",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

        try:
            with self._opener.open(request, timeout=self._timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = _read_error_body(error)
            retry_after = _parse_retry_after(error.headers.get("Retry-After"))
            raise LatencyClientError(
                f"GitHubModelsHttp{error.code}",
                detail or f"GitHub Models returned HTTP {error.code} for '{model}'.",
                retry_after=retry_after,
            ) from error
        except (urllib.error.URLError, http.client.HTTPException, OSError, json.JSONDecodeError) as error:
            raise LatencyClientError(
                "GitHubModelsUnreachable",
                f"GitHub Models completion failed for '{model}': {error}",
            ) from error

        return _completion_text(payload)


# Preferred summary models, best in the gpt-5 family first. The narrative client
# tries these in order and uses the first that returns text, so the summary always
# uses the best AVAILABLE gpt-5-family model. gpt-4.1 is only a last-resort fallback
# so a daily digest is still produced when the whole gpt-5 family is throttled.
DEFAULT_SUMMARY_MODELS = (
    "openai/gpt-5",
    "openai/gpt-5-chat",
    "openai/gpt-5-mini",
    "openai/gpt-5-nano",
    "openai/gpt-4.1",
)


class GitHubModelsNarrativeClient:
    """Adapts GitHubModelsClient to the summary NarrativeClient protocol.

    Tries an ordered list of candidate models and returns the first that produces
    text, so the digest uses the best available gpt-5-family model and degrades
    gracefully when a model is rate-limited or unavailable.
    """

    def __init__(
        self,
        client: GitHubModelsClient,
        models: str | list[str] | tuple[str, ...] = DEFAULT_SUMMARY_MODELS,
        max_tokens: int = 700,
        temperature: float = 0.4,
    ) -> None:
        self._client = client
        if isinstance(models, str):
            models = [part.strip() for part in models.split(",") if part.strip()]
        self._models = list(models) or list(DEFAULT_SUMMARY_MODELS)
        self._max_tokens = max_tokens
        self._temperature = temperature

    def generate(self, *, system: str, user: str) -> str:
        last_error: Exception | None = None
        for model in self._models:
            try:
                text = self._client.complete(
                    model=model,
                    system=system,
                    user=user,
                    max_tokens=self._max_tokens,
                    temperature=self._temperature,
                ).strip()
            except Exception as error:  # try the next candidate model
                last_error = error
                continue
            if text:
                return text
        if last_error is not None:
            raise last_error
        return ""


def _completion_text(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    return content.strip() if isinstance(content, str) else ""


def _is_reasoning_model(model: str) -> bool:
    name = model.split("/")[-1].lower()
    if "gpt-5-chat" in name:
        return False
    if name.startswith("gpt-5"):
        return True
    return bool(re.match(r"o\d", name))


def _github_reasoning_effort(model: str) -> str | None:
    name = model.split("/")[-1].lower()
    if "gpt-5-chat" in name:
        return "medium"
    return "low" if _is_reasoning_model(model) else None


def _build_request_payload(model: str, prompt: str, max_tokens: int) -> dict:
    payload: dict = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    reasoning_effort = _github_reasoning_effort(model)
    if reasoning_effort is not None:
        # Reasoning models reject 'max_tokens' and a non-default temperature, and
        # they spend part of the budget on hidden reasoning tokens, so give them a
        # larger completion budget and the lowest supported reasoning effort.
        payload["max_completion_tokens"] = max(max_tokens, REASONING_MIN_COMPLETION_TOKENS)
        payload["reasoning_effort"] = reasoning_effort
    else:
        payload["max_tokens"] = max_tokens
        payload["temperature"] = 0
    return payload


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value.strip()))
    except (TypeError, ValueError):
        return None


def _read_error_body(error: urllib.error.HTTPError) -> str:
    """Read an HTTP error body without letting a truncated/broken read escape.

    A rate-limited or interrupted response can raise http.client.IncompleteRead
    (or another transport error) mid-read; that must not crash the probe, so any
    failure to read the body yields an empty detail string instead.
    """

    try:
        return error.read().decode("utf-8", errors="replace").strip()
    except (http.client.HTTPException, OSError):
        return ""


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
