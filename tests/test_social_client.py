import json
import io
import urllib.error

from azure_region_monitor.social_client import (
    MICROSOFT_LEARN_MCP_TOOLS,
    MICROSOFT_LEARN_MCP_URL,
    AzureOpenAiTextClient,
)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeOpener:
    def __init__(self, payload):
        self._payload = payload
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        return _FakeResponse(self._payload)


class _FailingOpener:
    def open(self, request, timeout):
        raise urllib.error.URLError("Microsoft Learn MCP unreachable")


class _RateLimitedOpener:
    def __init__(self, failures, payload):
        self._failures = failures
        self._payload = payload
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        if self._failures:
            retry_after = self._failures.pop(0)
            raise urllib.error.HTTPError(
                request.full_url,
                429,
                "Too Many Requests",
                {"Retry-After": retry_after},
                io.BytesIO(b'{"error":{"code":"rate_limit_exceeded"}}'),
            )
        return _FakeResponse(self._payload)


def test_azure_social_client_posts_responses_request_and_extracts_text():
    opener = _FakeOpener(
        {
            "output": [
                {"type": "reasoning", "summary": []},
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": '{"linkedin":"L","short_post":"S"}'}
                    ],
                },
            ]
        }
    )
    client = AzureOpenAiTextClient(
        api_key="test-key",
        endpoint="https://eastus.api.cognitive.microsoft.com/",
        deployment="codex-gpt-5-4-mini",
        opener=opener,
    )

    text = client.generate(system="system", user="facts")

    assert text == '{"linkedin":"L","short_post":"S"}'
    request, timeout = opener.requests[0]
    assert request.full_url == "https://eastus.api.cognitive.microsoft.com/openai/v1/responses"
    assert request.get_header("Api-key") == "test-key"
    assert timeout == 90
    payload = json.loads(request.data.decode("utf-8"))
    assert payload["model"] == "codex-gpt-5-4-mini"
    assert payload["instructions"] == "system"
    assert payload["input"] == "facts"
    assert payload["reasoning"] == {"effort": "low"}


def test_azure_summary_client_retries_rate_limit_and_honors_retry_after():
    opener = _RateLimitedOpener(
        ["3"],
        {"output_text": "Recovered summary."},
    )
    slept = []
    client = AzureOpenAiTextClient(
        api_key="test-key",
        endpoint="https://example.openai.azure.com",
        deployment="gpt-5.4-mini",
        opener=opener,
        sleep=slept.append,
    )

    assert client.generate(system="system", user="facts") == "Recovered summary."
    assert len(opener.requests) == 2
    assert slept == [3.0]


def test_azure_summary_client_stops_after_bounded_rate_limit_retries():
    opener = _RateLimitedOpener(
        ["", "", ""],
        {"output_text": "not reached"},
    )
    slept = []
    client = AzureOpenAiTextClient(
        api_key="test-key",
        endpoint="https://example.openai.azure.com",
        deployment="gpt-5.4-mini",
        opener=opener,
        rate_limit_retries=2,
        sleep=slept.append,
    )

    try:
        client.generate(system="system", user="facts")
    except RuntimeError as error:
        assert "HTTP 429" in str(error)
    else:
        raise AssertionError("Expected exhausted rate-limit retries to fail")

    assert len(opener.requests) == 3
    assert slept == [20.0, 40.0]


def test_azure_summary_client_records_microsoft_learn_grounding():
    learn_url = "https://learn.microsoft.com/azure/ai-foundry/openai/concepts/models"
    opener = _FakeOpener(
        {
            "output": [
                {
                    "type": "mcp_call",
                    "server_label": "microsoft_learn",
                    "result": {"url": learn_url},
                },
                {"type": "message", "content": [{"type": "output_text", "text": "Grounded text."}]},
            ]
        }
    )
    client = AzureOpenAiTextClient(
        api_key="test-key",
        endpoint="https://example.openai.azure.com",
        deployment="gpt-5.4-mini",
        enable_microsoft_learn_mcp=True,
        opener=opener,
    )

    assert client.generate(system="system", user="facts") == "Grounded text."

    payload = json.loads(opener.requests[0][0].data.decode("utf-8"))
    assert payload["tools"] == [
        {
            "type": "mcp",
            "server_label": "microsoft_learn",
            "server_url": MICROSOFT_LEARN_MCP_URL,
            "allowed_tools": list(MICROSOFT_LEARN_MCP_TOOLS),
            "require_approval": "never",
        }
    ]
    assert client.generation_metadata == {
        "narrative_mcp_status": "consulted",
        "narrative_mcp_error": None,
        "narrative_grounding_status": "microsoft_learn",
        "narrative_microsoft_learn_urls": [learn_url],
    }


def test_azure_summary_client_does_not_mislabel_responses_transport_failure_as_mcp_failure():
    client = AzureOpenAiTextClient(
        api_key="test-key",
        endpoint="https://example.openai.azure.com",
        deployment="gpt-5.4-mini",
        enable_microsoft_learn_mcp=True,
        opener=_FailingOpener(),
    )

    try:
        client.generate(system="system", user="facts")
    except RuntimeError as error:
        assert "Azure OpenAI social draft request failed" in str(error)
    else:
        raise AssertionError("Expected the Azure OpenAI request to fail")

    assert client.generation_metadata["narrative_mcp_status"] == "available"
    assert client.generation_metadata["narrative_mcp_error"] is None


def test_azure_summary_client_rejects_mcp_approval_request():
    client = AzureOpenAiTextClient(
        api_key="test-key",
        endpoint="https://example.openai.azure.com",
        deployment="gpt-5.4-mini",
        enable_microsoft_learn_mcp=True,
        opener=_FakeOpener(
            {
                "output": [
                    {
                        "type": "mcp_approval_request",
                        "server_label": "microsoft_learn",
                    }
                ]
            }
        ),
    )

    try:
        client.generate(system="system", user="facts")
    except RuntimeError as error:
        assert "Microsoft Learn MCP request failed: approval_requested" in str(error)
    else:
        raise AssertionError("Expected MCP approval request to fail")

    assert client.generation_metadata["narrative_mcp_status"] == "failed"


def test_azure_summary_client_uses_only_successful_mcp_result_urls():
    client = AzureOpenAiTextClient(
        api_key="test-key",
        endpoint="https://example.openai.azure.com",
        deployment="gpt-5.4-mini",
        enable_microsoft_learn_mcp=True,
        opener=_FakeOpener(
            {
                "output": [
                    {
                        "type": "mcp_call",
                        "server_label": "microsoft_learn",
                        "status": "completed",
                        "result": {
                            "url": "https://learn.microsoft.com/azure/aks/cluster-extensions",
                            "endpoint": MICROSOFT_LEARN_MCP_URL,
                        },
                    },
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "Ignore https://learn.microsoft.com/not-a-result",
                            }
                        ],
                    },
                ]
            }
        ),
    )

    client.generate(system="system", user="facts")

    assert client.generation_metadata["narrative_microsoft_learn_urls"] == [
        "https://learn.microsoft.com/azure/aks/cluster-extensions"
    ]
