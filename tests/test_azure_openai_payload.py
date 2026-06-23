from azure_region_monitor.probes.azure_openai import _build_azure_payload
from azure_region_monitor.probes.github_models import REASONING_MIN_COMPLETION_TOKENS


def test_azure_payload_standard_model():
    payload = _build_azure_payload("gpt-4o", "hi", 256)
    assert payload["max_tokens"] == 256
    assert payload["temperature"] == 0
    assert "max_completion_tokens" not in payload
    assert payload["stream"] is True
    # Deployment name is carried in the URL, not the body.
    assert "model" not in payload


def test_azure_payload_reasoning_model():
    for deployment in ["gpt-5.1", "gpt-5", "o3", "o4-mini"]:
        payload = _build_azure_payload(deployment, "hi", 256)
        assert "max_tokens" not in payload, deployment
        assert "temperature" not in payload, deployment
        assert payload["max_completion_tokens"] == REASONING_MIN_COMPLETION_TOKENS, deployment
        assert payload["reasoning_effort"] == "low", deployment


def test_azure_payload_gpt5_chat_is_not_reasoning():
    payload = _build_azure_payload("gpt-5-chat", "hi", 256)
    assert payload["max_tokens"] == 256
    assert payload["temperature"] == 0
