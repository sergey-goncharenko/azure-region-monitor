from azure_region_monitor.probes.github_models import (
    REASONING_MIN_COMPLETION_TOKENS,
    GitHubModelsClient,
    LatencyClientError,
    _build_request_payload,
    _is_reasoning_model,
)


class _CapturingResponse:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._payload


class _CapturingOpener:
    def __init__(self):
        self.body = None

    def open(self, request, timeout=None):
        import json

        self.body = json.loads(request.data.decode("utf-8"))
        reply = json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode("utf-8")
        return _CapturingResponse(reply)


class _EmptyStreamThenCompletionOpener:
    def __init__(self, completion):
        self.requests = []
        self._completion = completion

    def open(self, request, timeout=None):
        import json

        self.requests.append(json.loads(request.data.decode("utf-8")))
        if len(self.requests) == 1:
            return _StreamingResponse(
                [
                    b'data: {"choices":[{"delta":{"role":"assistant"}}]}\n',
                    b"data: [DONE]\n",
                ]
            )
        return _CapturingResponse(json.dumps(self._completion).encode("utf-8"))


class _StreamingResponse:
    def __init__(self, lines):
        self._lines = iter(lines)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._lines)


def test_complete_uses_max_tokens_and_temperature_for_standard_models():
    opener = _CapturingOpener()
    client = GitHubModelsClient(token="t", opener=opener)
    client.complete(model="openai/gpt-4.1", system="s", user="u", max_tokens=500, temperature=0.4)
    assert opener.body["max_tokens"] == 500
    assert opener.body["temperature"] == 0.4
    assert "max_completion_tokens" not in opener.body
    assert "reasoning_effort" not in opener.body


def test_complete_uses_reasoning_payload_for_gpt5_models():
    opener = _CapturingOpener()
    client = GitHubModelsClient(token="t", opener=opener)
    client.complete(model="openai/gpt-5", system="s", user="u", max_tokens=500, temperature=0.4)
    assert opener.body["max_completion_tokens"] == max(500, REASONING_MIN_COMPLETION_TOKENS)
    assert opener.body["reasoning_effort"] == "low"
    assert "max_tokens" not in opener.body
    assert "temperature" not in opener.body


def test_complete_uses_gpt5_chat_payload_supported_by_github_models():
    opener = _CapturingOpener()
    client = GitHubModelsClient(token="t", opener=opener)
    client.complete(
        model="openai/gpt-5-chat",
        system="s",
        user="u",
        max_tokens=500,
        temperature=0.4,
    )
    assert opener.body["max_completion_tokens"] == REASONING_MIN_COMPLETION_TOKENS
    assert opener.body["reasoning_effort"] == "medium"
    assert "max_tokens" not in opener.body
    assert "temperature" not in opener.body


def test_standard_models_use_max_tokens_and_temperature():
    payload = _build_request_payload("openai/gpt-4o-mini", "hi", 256)

    assert payload["max_tokens"] == 256
    assert payload["temperature"] == 0
    assert "max_completion_tokens" not in payload
    assert "reasoning_effort" not in payload
    assert payload["stream"] is True


def test_reasoning_models_use_max_completion_tokens_without_temperature():
    for model in ["openai/o4-mini", "openai/o1", "openai/gpt-5-mini"]:
        payload = _build_request_payload(model, "hi", 256)

        assert "max_tokens" not in payload, model
        assert "temperature" not in payload, model
        assert payload["max_completion_tokens"] == REASONING_MIN_COMPLETION_TOKENS, model
        assert payload["reasoning_effort"] == "low", model


def test_gpt5_chat_uses_github_models_specific_reasoning_payload():
    payload = _build_request_payload("openai/gpt-5-chat", "hi", 256)

    assert "max_tokens" not in payload
    assert "temperature" not in payload
    assert payload["max_completion_tokens"] == REASONING_MIN_COMPLETION_TOKENS
    assert payload["reasoning_effort"] == "medium"


def test_reasoning_budget_respects_larger_requested_max_tokens():
    payload = _build_request_payload("openai/o4-mini", "hi", 1024)
    assert payload["max_completion_tokens"] == 1024


def test_is_reasoning_model_classification():
    assert _is_reasoning_model("openai/o4-mini")
    assert _is_reasoning_model("openai/o1")
    assert _is_reasoning_model("openai/gpt-5-mini")
    assert not _is_reasoning_model("openai/gpt-4o")
    assert not _is_reasoning_model("openai/gpt-4o-mini")
    assert not _is_reasoning_model("openai/gpt-5-chat")


def test_measure_falls_back_to_non_streaming_response_after_empty_stream():
    opener = _EmptyStreamThenCompletionOpener(
        {
            "choices": [{"message": {"content": "one two three"}}],
            "usage": {"completion_tokens": 3},
        }
    )
    client = GitHubModelsClient(token="t", opener=opener)

    measurement = client.measure("openai/gpt-4o", prompt="hi", max_tokens=8)

    assert measurement.output_tokens == 3
    assert len(opener.requests) == 2
    assert opener.requests[0]["stream"] is True
    assert "stream" not in opener.requests[1]


def test_measure_keeps_empty_response_unknown_when_fallback_has_no_tokens():
    opener = _EmptyStreamThenCompletionOpener({"choices": []})
    client = GitHubModelsClient(token="t", opener=opener)

    try:
        client.measure("openai/gpt-4o", prompt="hi", max_tokens=8)
    except LatencyClientError as error:
        assert error.error_code == "GitHubModelsEmptyResponse"
    else:
        raise AssertionError("Expected an empty fallback response to remain unknown.")
