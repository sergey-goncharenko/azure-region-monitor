from azure_region_monitor.probes.github_models import (
    REASONING_MIN_COMPLETION_TOKENS,
    GitHubModelsClient,
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
