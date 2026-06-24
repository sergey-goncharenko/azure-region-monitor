from azure_region_monitor.config import LatencyModel
from azure_region_monitor.github_catalog import select_catalog_models
from azure_region_monitor.probes.model_latency import LatencyMeasurement, ModelLatencyProbe


def _catalog():
    return [
        {"id": "openai/gpt-4o", "publisher": "OpenAI", "supported_input_modalities": ["text", "image"], "supported_output_modalities": ["text"]},
        {"id": "openai/gpt-5", "publisher": "OpenAI", "supported_input_modalities": ["text"], "supported_output_modalities": ["text"]},
        {"id": "openai/gpt-4o-audio-preview", "publisher": "OpenAI", "supported_input_modalities": ["text", "audio"], "supported_output_modalities": ["text"]},
        {"id": "openai/gpt-5-codex", "publisher": "OpenAI", "supported_input_modalities": ["text"], "supported_output_modalities": ["text"]},
        {"id": "openai/text-embedding-3-large", "publisher": "OpenAI", "supported_input_modalities": ["text"], "supported_output_modalities": ["embeddings"]},
        {"id": "meta/Llama-3.3-70B-Instruct", "publisher": "Meta", "supported_input_modalities": ["text"], "supported_output_modalities": ["text"]},
    ]


def test_select_catalog_models_filters_and_keys():
    models = select_catalog_models(_catalog())
    ids = {m.model for m in models}
    # OpenAI text chat models kept; audio/codex/embeddings and non-OpenAI dropped.
    assert ids == {"openai/gpt-4o", "openai/gpt-5"}
    features = {m.feature for m in models}
    assert "modelLatency.openai.gpt-4o" in features
    assert "modelLatency.openai.gpt-5" in features


def test_select_catalog_models_respects_publisher_allowlist_and_cap():
    models = select_catalog_models(_catalog(), publishers=("openai", "meta"), max_models=2)
    assert len(models) == 2
    # Deterministic by model id sort.
    assert [m.model for m in models] == sorted(m.model for m in models)


def test_select_catalog_models_handles_garbage_entries():
    catalog = [None, {"id": ""}, {"id": "openai/gpt-4o", "publisher": "OpenAI", "supported_input_modalities": ["text"], "supported_output_modalities": ["text"]}]
    models = select_catalog_models(catalog)
    assert [m.model for m in models] == ["openai/gpt-4o"]


class _FakeClient:
    def measure(self, model, *, prompt, max_tokens):
        return LatencyMeasurement(ttft_ms=100, total_ms=500, output_tokens=50)


def test_probe_auto_discover_uses_catalog():
    # Fallback with no non-OpenAI anchors so the result is exactly the discovered set.
    probe = ModelLatencyProbe(
        models=[LatencyModel(feature="modelLatency.openai.gpt-4o", model="openai/gpt-4o")],
        client=_FakeClient(),
        samples=1,
        auto_discover=True,
        catalog_fetcher=_catalog,
    )
    features = {r.feature for r in probe.run("github-global")}
    assert features == {"modelLatency.openai.gpt-4o", "modelLatency.openai.gpt-5"}


def test_probe_auto_discover_keeps_non_openai_anchors():
    anchors = [
        LatencyModel(feature="modelLatency.meta.llama", model="meta/Llama-3.3-70B-Instruct"),
        LatencyModel(feature="modelLatency.openai.gpt-4o-mini", model="openai/gpt-4o-mini"),
    ]
    probe = ModelLatencyProbe(
        models=anchors,
        client=_FakeClient(),
        samples=1,
        auto_discover=True,
        catalog_fetcher=_catalog,
    )
    models = {r.feature for r in probe.run("github-global")}
    # Discovered OpenAI models plus the non-OpenAI anchor; the OpenAI anchor is not duplicated.
    assert "modelLatency.openai.gpt-4o" in models
    assert "modelLatency.openai.gpt-5" in models
    assert "modelLatency.meta.llama" in models


def test_probe_auto_discover_falls_back_on_fetch_failure():
    def boom():
        raise RuntimeError("catalog down")

    fallback = [LatencyModel(feature="modelLatency.openai.gpt-4o", model="openai/gpt-4o")]
    probe = ModelLatencyProbe(
        models=fallback,
        client=_FakeClient(),
        samples=1,
        auto_discover=True,
        catalog_fetcher=boom,
    )
    features = {r.feature for r in probe.run("github-global")}
    assert features == {"modelLatency.openai.gpt-4o"}


def test_probe_auto_discover_falls_back_on_empty_catalog():
    fallback = [LatencyModel(feature="modelLatency.openai.gpt-4o", model="openai/gpt-4o")]
    probe = ModelLatencyProbe(
        models=fallback,
        client=_FakeClient(),
        samples=1,
        auto_discover=True,
        catalog_fetcher=lambda: [],
    )
    features = {r.feature for r in probe.run("github-global")}
    assert features == {"modelLatency.openai.gpt-4o"}
