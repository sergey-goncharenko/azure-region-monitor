import http.client
import urllib.error

import pytest

from azure_region_monitor.probes.azure_openai import AzureOpenAiClient
from azure_region_monitor.probes.model_latency import LatencyClientError


class _OpenerRaising:
    def __init__(self, error):
        self._error = error

    def open(self, request, timeout=None):
        raise self._error


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
