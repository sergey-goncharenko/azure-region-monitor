from azure_region_monitor.config import AiLatencyTarget, parse_ai_latency_targets
from azure_region_monitor.probes.ai_model_latency import AzureOpenAiLatencyProbe
from azure_region_monitor.probes.model_latency import LatencyClientError, LatencyMeasurement


class _FakeClient:
    def __init__(self, measurement=None, error=None):
        self._measurement = measurement
        self._error = error
        self.calls = []

    def measure(self, endpoint, deployment, *, prompt, max_tokens):
        self.calls.append((endpoint, deployment, prompt, max_tokens))
        if self._error is not None:
            raise self._error
        return self._measurement


def _targets():
    return [
        AiLatencyTarget(region="eastus", endpoint="https://e.openai.azure.com", deployment="gpt-4o", model="gpt-4o"),
        AiLatencyTarget(region="westus3", endpoint="https://w.openai.azure.com", deployment="gpt-4o", model="gpt-4o"),
    ]


def test_probe_measures_matching_region_and_attributes_it():
    client = _FakeClient(measurement=LatencyMeasurement(ttft_ms=200, total_ms=900, output_tokens=80))
    probe = AzureOpenAiLatencyProbe(targets=_targets(), client=client, samples=3)

    results = list(probe.run("eastus"))

    assert len(results) == 1
    result = results[0]
    assert result.service == "ai-latency"
    assert result.feature == "aiLatency.openai.gpt-4o"
    assert result.result.status == "available"
    assert result.result.latency_ms == 900
    assert "gpt-4o from eastus" in result.result.message
    assert "3/3 samples" in result.result.message
    # Only the eastus endpoint was called.
    assert all(call[0] == "https://e.openai.azure.com" for call in client.calls)
    assert len(client.calls) == 3


def test_probe_yields_nothing_for_unconfigured_region():
    client = _FakeClient(measurement=LatencyMeasurement(ttft_ms=200, total_ms=900, output_tokens=80))
    probe = AzureOpenAiLatencyProbe(targets=_targets(), client=client, samples=1)

    assert list(probe.run("germanywestcentral")) == []
    assert client.calls == []


def test_probe_marks_unknown_when_all_samples_fail():
    client = _FakeClient(error=LatencyClientError("AzureOpenAiHttp401", "auth failed"))
    probe = AzureOpenAiLatencyProbe(
        targets=_targets(), client=client, samples=2, rate_limit_retries=0, sleep=lambda _s: None
    )

    result = list(probe.run("westus3"))[0]

    assert result.result.status == "unknown"
    assert result.result.error_code == "AzureOpenAiHttp401"
    assert result.result.message == "auth failed"


def test_probe_retries_rate_limited_then_succeeds():
    class _Flaky:
        def __init__(self):
            self.n = 0

        def measure(self, endpoint, deployment, *, prompt, max_tokens):
            self.n += 1
            if self.n == 1:
                raise LatencyClientError("AzureOpenAiHttp429", "rate", retry_after=3)
            return LatencyMeasurement(ttft_ms=100, total_ms=500, output_tokens=50)

    slept = []
    probe = AzureOpenAiLatencyProbe(
        targets=_targets(), client=_Flaky(), samples=1, rate_limit_retries=2, sleep=slept.append
    )
    result = list(probe.run("eastus"))[0]
    assert result.result.status == "available"
    assert slept == [3]


def test_parse_ai_latency_targets_from_infra_json():
    raw = (
        '[{"region":"eastus","endpoint":"https://e.openai.azure.com","deployment":"gpt-4o","model":"gpt-4o"},'
        '{"region":"westus3","endpoint":"https://w.openai.azure.com","deployment":"gpt-4o"}]'
    )
    targets = parse_ai_latency_targets(raw)
    assert [t.region for t in targets] == ["eastus", "westus3"]
    assert targets[0].endpoint == "https://e.openai.azure.com"
    # model falls back to deployment when omitted.
    assert targets[1].model == "gpt-4o"


def test_parse_ai_latency_targets_empty_and_invalid():
    assert parse_ai_latency_targets(None) == []
    assert parse_ai_latency_targets("") == []
    try:
        parse_ai_latency_targets("{not json")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
