from azure_region_monitor.config import DEFAULT_LATENCY_MODELS, LatencyModel, parse_latency_models
from azure_region_monitor.probes.model_latency import (
    LatencyClientError,
    LatencyMeasurement,
    ModelLatencyProbe,
    _percentile,
)


class _FakeClient:
    def __init__(self, measurements=None, error=None):
        self._measurements = measurements or {}
        self._error = error
        self.calls = []

    def measure(self, model, *, prompt, max_tokens):
        self.calls.append((model, prompt, max_tokens))
        if self._error is not None:
            raise self._error
        sample = self._measurements.get(model)
        if sample is None:
            raise LatencyClientError("FakeMissing", f"no canned sample for {model}")
        return sample


def test_probe_yields_one_available_result_per_model_with_p50_latency():
    client = _FakeClient(
        measurements={
            "openai/gpt-4o-mini": LatencyMeasurement(ttft_ms=200, total_ms=800, output_tokens=80),
        }
    )
    probe = ModelLatencyProbe(
        models=[LatencyModel(feature="modelLatency.openai.gpt-4o-mini", model="openai/gpt-4o-mini")],
        client=client,
        samples=3,
    )

    results = list(probe.run("github-global"))

    assert len(results) == 1
    result = results[0]
    assert result.service == "model-latency"
    assert result.feature == "modelLatency.openai.gpt-4o-mini"
    assert result.result.status == "available"
    assert result.result.latency_ms == 800
    assert "tok/s" in result.result.message
    assert "3/3 samples" in result.result.message
    assert len(client.calls) == 3


def test_probe_marks_model_unknown_when_all_samples_fail():
    client = _FakeClient(error=LatencyClientError("GitHubModelsHttp429", "rate limited"))
    probe = ModelLatencyProbe(
        models=[LatencyModel(feature="modelLatency.openai.gpt-4o", model="openai/gpt-4o")],
        client=client,
        samples=2,
    )

    result = list(probe.run("github-global"))[0]

    assert result.result.status == "unknown"
    assert result.result.error_code == "GitHubModelsHttp429"
    assert result.result.message == "rate limited"


def test_probe_keeps_partial_samples_and_reports_count():
    class _FlakyClient:
        def __init__(self):
            self.count = 0

        def measure(self, model, *, prompt, max_tokens):
            self.count += 1
            if self.count == 1:
                raise LatencyClientError("GitHubModelsUnreachable", "boom")
            return LatencyMeasurement(ttft_ms=150, total_ms=600, output_tokens=60)

    probe = ModelLatencyProbe(
        models=[LatencyModel(feature="modelLatency.openai.o4-mini", model="openai/o4-mini")],
        client=_FlakyClient(),
        samples=3,
    )

    result = list(probe.run("github-global"))[0]

    assert result.result.status == "available"
    assert "2/3 samples" in result.result.message


def test_percentile_interpolates_between_ranks():
    values = [100, 200, 300, 400]
    assert _percentile(values, 50) == 250
    assert _percentile(values, 0) == 100
    assert _percentile(values, 100) == 400


def test_parse_latency_models_defaults_and_overrides():
    assert parse_latency_models(None) == DEFAULT_LATENCY_MODELS
    parsed = parse_latency_models("modelLatency.openai.gpt-4o=openai/gpt-4o")
    assert parsed == [LatencyModel(feature="modelLatency.openai.gpt-4o", model="openai/gpt-4o")]
