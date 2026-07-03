import http.client
import urllib.error

import pytest

from azure_region_monitor.config import LatencyModel
from azure_region_monitor.probes.azure_openai import AzureOpenAiClient
from azure_region_monitor.probes.github_models import GitHubModelsClient
from azure_region_monitor.probes.model_latency import LatencyClientError, ModelLatencyProbe


class _BrokenBodyHTTPError(urllib.error.HTTPError):
    """A 429 whose body read fails mid-stream (the real crash scenario)."""

    def __init__(self):
        super().__init__(
            url="https://models.github.ai/inference/chat/completions",
            code=429,
            msg="Too Many Requests",
            hdrs={"Retry-After": "3"},
            fp=None,
        )

    def read(self, *args, **kwargs):
        raise http.client.IncompleteRead(b"", 126)


class _OpenerRaising:
    def __init__(self, error):
        self._error = error

    def open(self, request, timeout=None):
        raise self._error


class _MidStreamResponse:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return self

    def __next__(self):
        raise http.client.IncompleteRead(b"", 42)


class _OpenerMidStream:
    def open(self, request, timeout=None):
        return _MidStreamResponse()


def test_github_measure_survives_incomplete_read_on_error_body():
    # Reading the 429 body raises IncompleteRead; it must become a LatencyClientError,
    # and the Retry-After header must still be parsed so backoff works.
    client = GitHubModelsClient(token="t", opener=_OpenerRaising(_BrokenBodyHTTPError()))

    with pytest.raises(LatencyClientError) as exc:
        client.measure("openai/gpt-4o", prompt="hi", max_tokens=8)

    assert exc.value.error_code == "GitHubModelsHttp429"
    assert exc.value.retry_after == 3.0


def test_github_measure_survives_midstream_incomplete_read():
    client = GitHubModelsClient(token="t", opener=_OpenerMidStream())

    with pytest.raises(LatencyClientError) as exc:
        client.measure("openai/gpt-4o", prompt="hi", max_tokens=8)

    assert exc.value.error_code == "GitHubModelsUnreachable"


def test_azure_measure_survives_incomplete_read_on_error_body():
    class _AzureBrokenBody(urllib.error.HTTPError):
        def __init__(self):
            super().__init__(
                url="https://acct.openai.azure.com/openai/deployments/x/chat/completions",
                code=429,
                msg="Too Many Requests",
                hdrs={"Retry-After": "5"},
                fp=None,
            )

        def read(self, *args, **kwargs):
            raise http.client.IncompleteRead(b"", 10)

    client = AzureOpenAiClient(token="t", opener=_OpenerRaising(_AzureBrokenBody()))

    with pytest.raises(LatencyClientError) as exc:
        client.measure(
            "https://acct.openai.azure.com/",
            "gpt-4o",
            prompt="hi",
            max_tokens=8,
        )

    assert exc.value.error_code == "AzureOpenAiHttp429"
    assert exc.value.retry_after == 5.0


def test_probe_run_does_not_crash_on_incomplete_read():
    # End-to-end: a transport read failure must degrade to an 'unknown' result,
    # never propagate out of probe.run() and abort the whole snapshot.
    client = GitHubModelsClient(token="t", opener=_OpenerMidStream())
    probe = ModelLatencyProbe(
        models=[LatencyModel(feature="modelLatency.openai.gpt-4o", model="openai/gpt-4o")],
        client=client,
        samples=2,
        rate_limit_retries=0,
        sleep=lambda _s: None,
    )

    results = list(probe.run("github-global"))

    assert len(results) == 1
    assert results[0].result.status == "unknown"
    assert results[0].result.error_code == "GitHubModelsUnreachable"
