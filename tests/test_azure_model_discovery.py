from azure_region_monitor.azure_model_discovery import select_regional_standard_models


def _model(name, version, skus):
    return {"kind": "OpenAI", "model": {"name": name, "version": version, "skus": [{"name": s} for s in skus]}}


def test_selects_only_regional_standard_openai_models():
    by_region = {
        "eastus": [
            _model("gpt-4o", "2024-11-20", ["Standard", "GlobalStandard"]),
            _model("gpt-5.1", "2025-11-13", ["Standard", "GlobalStandard"]),
            _model("gpt-5.2", "2025-12-11", ["GlobalStandard"]),  # global-only -> dropped
            _model("gpt-4o-audio-preview", "2024-12-17", ["Standard"]),  # excluded by name
            _model("text-embedding-3-large", "1", ["Standard"]),  # not in include
            {"kind": "OpenAI", "model": {"name": "gpt-4o-mini", "version": "2024-07-18", "skus": [{"name": "GlobalStandard"}]}},
        ],
        "westus3": [
            _model("gpt-4o", "2024-11-20", ["Standard"]),
            _model("gpt-5.1", "2025-11-13", ["Standard"]),
        ],
        "uksouth": [
            _model("gpt-4o", "2024-11-20", ["Standard"]),
        ],
    }

    selected = select_regional_standard_models(by_region)

    by_name = {m["name"]: m for m in selected}
    assert set(by_name) == {"gpt-4o", "gpt-5.1"}
    assert by_name["gpt-4o"]["version"] == "2024-11-20"
    assert by_name["gpt-4o"]["regions"] == ["eastus", "uksouth", "westus3"]
    assert by_name["gpt-5.1"]["regions"] == ["eastus", "westus3"]
    assert by_name["gpt-5.1"]["deploymentName"] == "gpt-5.1"
    # gpt-5.2 is GlobalStandard-only -> not region-attributable -> excluded.
    assert "gpt-5.2" not in by_name


def test_picks_newest_version_per_model():
    by_region = {
        "eastus": [
            _model("gpt-4o", "2024-05-13", ["Standard"]),
            _model("gpt-4o", "2024-11-20", ["Standard"]),
        ],
    }
    selected = select_regional_standard_models(by_region)
    assert selected[0]["version"] == "2024-11-20"


def test_respects_max_models_and_is_deterministic():
    by_region = {
        "eastus": [
            _model("gpt-4o", "2024-11-20", ["Standard"]),
            _model("gpt-4.1", "2025-04-14", ["Standard"]),
            _model("gpt-5", "2025-08-07", ["Standard"]),
        ],
    }
    selected = select_regional_standard_models(by_region, max_models=2)
    assert [m["name"] for m in selected] == ["gpt-4.1", "gpt-4o"]  # sorted by name, capped


def test_handles_empty_and_garbage():
    assert select_regional_standard_models({}) == []
    assert select_regional_standard_models({"eastus": "not a list"}) == []
    assert select_regional_standard_models({"eastus": [None, {"kind": "OpenAI"}]}) == []


def test_skips_deprecated_lifecycle():
    deprecated = _model("gpt-4o", "2024-05-13", ["Standard"])
    deprecated["model"]["lifecycleStatus"] = "Deprecated"
    by_region = {
        "eastus": [
            deprecated,
            _model("gpt-4o", "2024-11-20", ["Standard"]),
        ],
    }
    selected = select_regional_standard_models(by_region)
    assert selected == [
        {
            "name": "gpt-4o",
            "version": "2024-11-20",
            "deploymentName": "gpt-4o",
            "regions": ["eastus"],
        }
    ]
