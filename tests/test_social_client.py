import json

from azure_region_monitor.social_client import AzureOpenAiTextClient


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
