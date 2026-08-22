import json
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
        }
    ]
    assert client.generation_metadata == {
        "narrative_mcp_status": "consulted",
        "narrative_mcp_error": None,
        "narrative_grounding_status": "microsoft_learn",
        "narrative_microsoft_learn_urls": [learn_url],
    }


def test_azure_summary_client_records_mcp_transport_failure():
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

    assert client.generation_metadata["narrative_mcp_status"] == "failed"
    assert client.generation_metadata["narrative_mcp_error"] == "URLError"
