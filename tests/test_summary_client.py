from azure_region_monitor.probes.github_models import (
    DEFAULT_SUMMARY_MODELS,
    GitHubModelsNarrativeClient,
)
from azure_region_monitor.probes.model_latency import LatencyClientError


class _RecordingClient:
    def __init__(self, behaviors):
        # behaviors: dict model -> str reply, or Exception to raise, or "" for empty.
        self._behaviors = behaviors
        self.calls = []

    def complete(self, *, model, system, user, max_tokens, temperature=0.0):
        self.calls.append(model)
        result = self._behaviors.get(model, "")
        if isinstance(result, Exception):
            raise result
        return result


def test_default_summary_models_are_gpt5_family_first():
    assert DEFAULT_SUMMARY_MODELS[0] == "openai/gpt-5"
    # gpt-4.1 is only the last-resort fallback.
    assert DEFAULT_SUMMARY_MODELS[-1] == "openai/gpt-4.1"
    assert all("gpt-5" in m for m in DEFAULT_SUMMARY_MODELS[:-1])


def test_narrative_client_uses_first_available_model():
    client = _RecordingClient({"openai/gpt-5": "A great headline\n\nBody."})
    narrative = GitHubModelsNarrativeClient(client)
    text = narrative.generate(system="s", user="u")
    assert text.startswith("A great headline")
    assert client.calls == ["openai/gpt-5"]  # stopped at the first success


def test_narrative_client_falls_through_to_next_on_error_or_empty():
    client = _RecordingClient(
        {
            "openai/gpt-5": LatencyClientError("GitHubModelsHttp429", "rate limited"),
            "openai/gpt-5-chat": "",  # empty -> keep trying
            "openai/gpt-5-mini": "Second-best model wrote this.",
        }
    )
    narrative = GitHubModelsNarrativeClient(client)
    text = narrative.generate(system="s", user="u")
    assert text == "Second-best model wrote this."
    assert client.calls == ["openai/gpt-5", "openai/gpt-5-chat", "openai/gpt-5-mini"]


def test_narrative_client_raises_when_all_models_fail():
    client = _RecordingClient(
        {model: LatencyClientError("GitHubModelsHttp429", "no") for model in DEFAULT_SUMMARY_MODELS}
    )
    narrative = GitHubModelsNarrativeClient(client)
    try:
        narrative.generate(system="s", user="u")
    except LatencyClientError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected LatencyClientError when every model fails")
    assert client.calls == list(DEFAULT_SUMMARY_MODELS)


def test_narrative_client_accepts_comma_separated_override():
    client = _RecordingClient({"openai/gpt-5-mini": "ok"})
    narrative = GitHubModelsNarrativeClient(client, models="openai/gpt-5-mini, openai/gpt-4.1")
    narrative.generate(system="s", user="u")
    assert client.calls == ["openai/gpt-5-mini"]
