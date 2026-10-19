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


def test_o4_mini_is_included_when_catalog_offers_regional_standard():
    by_region = {
        "eastus": [
            _model("gpt-4o", "2024-11-20", ["Standard"]),
            _model("o4-mini", "2025-04-16", ["Standard"]),
        ],
    }
    selected = select_regional_standard_models(by_region)
    names = {m["name"] for m in selected}
    assert "o4-mini" in names
    assert "gpt-4o" in names


def test_picks_newest_version_per_model():
    by_region = {
        "eastus": [
            _model("gpt-4o", "2024-05-13", ["Standard"]),
            _model("gpt-4o", "2024-11-20", ["Standard"]),
        ],
    }
    selected = select_regional_standard_models(by_region)
    assert selected[0]["version"] == "2024-11-20"


def test_prioritizes_current_models_when_capping_deployments():
    by_region = {
        "eastus": [
            _model("gpt-4o", "2024-11-20", ["Standard"]),
            _model("gpt-5.1", "2025-11-13", ["Standard"]),
            _model("gpt-5.6", "2026-08-21", ["Standard"]),
        ],
    }
    selected = select_regional_standard_models(by_region, max_models=2)
    assert [m["name"] for m in selected] == ["gpt-5.6", "gpt-5.1"]


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


def test_new_generations_and_catalog_advertised_chat_families_need_no_name_patch():
    new_gpt = _model("gpt-6.2", "2026-10-01", ["Standard"])
    new_reasoning = _model("o5-mini", "2026-10-02", ["Standard"])
    new_family = _model("nova-chat", "2026-10-03", ["Standard"])
    new_family["model"]["capabilities"] = {"chatCompletion": "true"}
    not_chat = _model("gpt-7", "2026-10-04", ["Standard"])
    not_chat["model"]["capabilities"] = {"chatCompletion": "false"}
    global_only = _model("gpt-8", "2026-10-05", ["GlobalStandard"])

    selected = select_regional_standard_models(
        {"eastus": [new_gpt, new_reasoning, new_family, not_chat, global_only]},
    )

    assert {model["name"] for model in selected} == {"gpt-6.2", "o5-mini", "nova-chat"}
    assert all(model["regions"] == ["eastus"] for model in selected)


def test_deprecated_or_retired_versions_leave_eligible_regions():
    active = _model("gpt-6", "2026-09-01", ["Standard"])
    deprecated = _model("gpt-6", "2026-10-01", ["Standard"])
    deprecated["model"]["lifecycleStatus"] = " deprecated "
    retired = _model("gpt-6", "2026-09-01", ["Standard"])
    retired["model"]["lifecycleStatus"] = "Retired"

    selected = select_regional_standard_models(
        {"eastus": [active, deprecated], "westus3": [retired]},
    )

    assert selected == [
        {
            "name": "gpt-6",
            "version": "2026-09-01",
            "deploymentName": "gpt-6",
            "regions": ["eastus"],
        }
    ]
