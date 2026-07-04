from azure_region_monitor.config import DEFAULT_LATENCY_MODELS, LatencyModel, parse_latency_models
from azure_region_monitor.probes.model_latency import (
    LatencyClientError,
    LatencyMeasurement,
    ModelLatencyProbe,
    _order_reasoning_last,
    _percentile,
)


def test_order_reasoning_last_keeps_reliable_models_first():
    models = [
        LatencyModel(feature="f1", model="openai/gpt-4o"),
        LatencyModel(feature="f2", model="openai/gpt-5"),  # reasoning
        LatencyModel(feature="f3", model="deepseek/DeepSeek-V3-0324"),  # anchor
        LatencyModel(feature="f4", model="openai/o1"),  # reasoning
        LatencyModel(feature="f5", model="openai/gpt-5-chat"),  # NOT reasoning
        LatencyModel(feature="f6", model="meta/Llama-3.3-70B-Instruct"),  # anchor
    ]
    ordered = [m.model for m in _order_reasoning_last(models)]
    # Non-reasoning first (stable), reasoning last (stable). Anchors are no longer
    # stranded at the tail behind slow reasoning models.
    assert ordered == [
        "openai/gpt-4o",
        "deepseek/DeepSeek-V3-0324",
        "openai/gpt-5-chat",
        "meta/Llama-3.3-70B-Instruct",
        "openai/gpt-5",
        "openai/o1",
    ]


def test_probe_measures_anchors_before_slow_reasoning_models():
    # With a tight budget, the reliable anchor is measured and a reasoning model is
    # the one that gets skipped — not the other way around.
    # deadline=15; ticks: deadline calc, anchor run-check, anchor sample-check, reason run-check.
    ticks = iter([0, 5, 6, 20])

    class _Clock:
        def __call__(self):
            try:
                return next(ticks)
            except StopIteration:
                return 999

    class _OkClient:
        def measure(self, model, *, prompt, max_tokens):
            return LatencyMeasurement(ttft_ms=100, total_ms=400, output_tokens=40)

    probe = ModelLatencyProbe(
        models=[
            LatencyModel(feature="reason", model="openai/gpt-5"),
            LatencyModel(feature="anchor", model="deepseek/DeepSeek-V3-0324"),
        ],
        client=_OkClient(),
        samples=1,
        time_budget_seconds=15,
        monotonic=_Clock(),
        sleep=lambda _s: None,
    )
    results = {r.feature: r.result.status for r in probe.run("github-global")}
    assert results["anchor"] == "available"
    assert results["reason"] == "unknown"


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
        rate_limit_retries=0,
        sleep=lambda _seconds: None,
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


def test_probe_retries_rate_limited_sample_then_succeeds():
    class _RateLimitedClient:
        def __init__(self):
            self.attempts = 0

        def measure(self, model, *, prompt, max_tokens):
            self.attempts += 1
            if self.attempts == 1:
                raise LatencyClientError("GitHubModelsHttp429", "Too many requests", retry_after=7)
            return LatencyMeasurement(ttft_ms=120, total_ms=500, output_tokens=50)

    slept = []
    probe = ModelLatencyProbe(
        models=[LatencyModel(feature="modelLatency.openai.gpt-5-mini", model="openai/gpt-5-mini")],
        client=_RateLimitedClient(),
        samples=1,
        rate_limit_retries=3,
        rate_limit_backoff_seconds=20,
        sleep=slept.append,
    )

    result = list(probe.run("github-global"))[0]

    assert result.result.status == "available"
    assert slept == [7]  # honored Retry-After, not the 20s floor


def test_probe_gives_up_after_exhausting_rate_limit_retries():
    class _AlwaysLimited:
        def measure(self, model, *, prompt, max_tokens):
            raise LatencyClientError("GitHubModelsHttp429", "Too many requests")

    slept = []
    probe = ModelLatencyProbe(
        models=[LatencyModel(feature="modelLatency.openai.o4-mini", model="openai/o4-mini")],
        client=_AlwaysLimited(),
        samples=1,
        rate_limit_retries=2,
        rate_limit_backoff_seconds=5,
        sleep=slept.append,
    )

    result = list(probe.run("github-global"))[0]

    assert result.result.status == "unknown"
    assert result.result.error_code == "GitHubModelsHttp429"
    assert slept == [5, 5]  # backoff floor used twice, then gave up


def test_probe_does_not_retry_non_rate_limit_errors():
    class _ServerError:
        def __init__(self):
            self.attempts = 0

        def measure(self, model, *, prompt, max_tokens):
            self.attempts += 1
            raise LatencyClientError("GitHubModelsHttp500", "boom")

    client = _ServerError()
    slept = []
    probe = ModelLatencyProbe(
        models=[LatencyModel(feature="modelLatency.openai.gpt-4o", model="openai/gpt-4o")],
        client=client,
        samples=1,
        rate_limit_retries=3,
        sleep=slept.append,
    )

    result = list(probe.run("github-global"))[0]

    assert result.result.status == "unknown"
    assert client.attempts == 1  # no retry for non-429
    assert slept == []


def test_probe_caps_backoff_at_max_ignoring_huge_retry_after():
    # GitHub can report a Retry-After of hours (seconds until a daily-quota reset).
    # The probe must never sleep longer than max_backoff_seconds for one backoff.
    class _HugeRetryAfter:
        def measure(self, model, *, prompt, max_tokens):
            raise LatencyClientError("GitHubModelsHttp429", "slow down", retry_after=86400)

    slept = []
    probe = ModelLatencyProbe(
        models=[LatencyModel(feature="modelLatency.openai.o4-mini", model="openai/o4-mini")],
        client=_HugeRetryAfter(),
        samples=1,
        rate_limit_retries=2,
        rate_limit_backoff_seconds=20,
        max_backoff_seconds=60,
        time_budget_seconds=None,
        sleep=slept.append,
    )

    result = list(probe.run("github-global"))[0]

    assert result.result.status == "unknown"
    assert slept == [60, 60]  # capped, not 86400


def test_probe_stops_calling_once_time_budget_is_exhausted():
    # Fake clock: deadline=15. Model a is measured (clock still < 15 at its calls);
    # by model b the clock has passed the deadline, so it's emitted without a call.
    ticks = iter([0, 5, 6, 20])

    class _Clock:
        def __call__(self):
            try:
                return next(ticks)
            except StopIteration:
                return 999

    class _OkClient:
        def __init__(self):
            self.calls = 0

        def measure(self, model, *, prompt, max_tokens):
            self.calls += 1
            return LatencyMeasurement(ttft_ms=100, total_ms=400, output_tokens=40)

    client = _OkClient()
    probe = ModelLatencyProbe(
        models=[
            LatencyModel(feature="modelLatency.openai.a", model="openai/a"),
            LatencyModel(feature="modelLatency.openai.b", model="openai/b"),
        ],
        client=client,
        samples=1,
        time_budget_seconds=15,
        monotonic=_Clock(),
        sleep=lambda _s: None,
    )

    results = list(probe.run("github-global"))

    assert results[0].result.status == "available"
    assert results[1].result.status == "unknown"
    assert results[1].result.error_code == "LatencyTimeBudgetExhausted"
    assert client.calls == 1  # the second model was never called


def test_probe_gives_up_backoff_when_it_would_exceed_budget():
    # If waiting out a throttle would blow the budget, don't sleep; fail the sample.
    clock = {"t": 0.0}

    def monotonic():
        return clock["t"]

    def sleep(seconds):
        clock["t"] += seconds

    class _AlwaysLimited:
        def measure(self, model, *, prompt, max_tokens):
            raise LatencyClientError("GitHubModelsHttp429", "no", retry_after=60)

    slept = []
    probe = ModelLatencyProbe(
        models=[LatencyModel(feature="modelLatency.openai.a", model="openai/a")],
        client=_AlwaysLimited(),
        samples=1,
        rate_limit_retries=5,
        max_backoff_seconds=60,
        time_budget_seconds=30,  # smaller than one 60s backoff
        monotonic=monotonic,
        sleep=lambda s: (slept.append(s), sleep(s)),
    )

    result = list(probe.run("github-global"))[0]

    assert result.result.status == "unknown"
    assert slept == []  # never slept because the backoff would exceed the budget


def test_percentile_interpolates_between_ranks():
    values = [100, 200, 300, 400]
    assert _percentile(values, 50) == 250
    assert _percentile(values, 0) == 100
    assert _percentile(values, 100) == 400


def test_parse_latency_models_defaults_and_overrides():
    assert parse_latency_models(None) == DEFAULT_LATENCY_MODELS
    parsed = parse_latency_models("modelLatency.openai.gpt-4o=openai/gpt-4o")
    assert parsed == [LatencyModel(feature="modelLatency.openai.gpt-4o", model="openai/gpt-4o")]
