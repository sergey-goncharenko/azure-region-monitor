from __future__ import annotations

import ast
import json
import socket
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from azure_region_monitor import feature_context
from azure_region_monitor.config import (
    DEFAULT_CONTAINER_APPS_RESOURCE_FEATURES,
    DEFAULT_FUNCTION_RUNTIME_FEATURES,
    DEFAULT_LATENCY_MODELS,
)
from azure_region_monitor.feature_context import describe_feature


def _text(context: dict) -> str:
    return " ".join((context["summary"], *context["differentiators"], context["limitations"]))


@pytest.mark.parametrize("size", (2, 4, 8, 16, 32, 48, 64, 96, 128))
@pytest.mark.parametrize(
    ("family", "suffix", "ratio", "purpose", "local"),
    (
        ("d", "ns", 4, "general-purpose", False),
        ("d", "nds", 4, "general-purpose", True),
        ("d", "nls", 2, "low-memory", False),
        ("d", "nlds", 2, "low-memory", True),
        ("e", "ns", 8, "memory-optimized", False),
        ("e", "nds", 8, "memory-optimized", True),
    ),
)
def test_documented_network_optimized_vm_sizes(size, family, suffix, ratio, purpose, local):
    context = describe_feature(f"vmSkus.standard.{family}{size}{suffix}.v6")

    assert context["specificity"] == "exact"
    assert context["verified_on"] == "2026-09-06"
    assert f"{size} vCPUs and {size * ratio} GiB RAM" in _text(context)
    assert purpose in context["title"]
    assert "Network-optimized (n)" in _text(context)
    assert "Premium SSD-compatible (s)" in _text(context)
    assert ("Local temporary disks (d)" in _text(context)) == local
    assert ("No local temporary disk" in _text(context)) == (not local)
    assert context["sources"][0]["url"].endswith(f"/{family}{suffix}v6-series")
    assert "quota" in context["limitations"]
    assert "measured performance" in context["limitations"]


@pytest.mark.parametrize(
    ("feature", "ram", "processor"),
    (
        ("vmSkus.standard.d2s.v5", 8, "Intel"),
        ("vmSkus.standard.d2as.v5", 8, "AMD"),
        ("vmSkus.standard.e2s.v5", 16, "Intel"),
        ("vmSkus.standard.e96s.v5", 672, "Intel"),
    ),
)
def test_existing_documented_vm_families_and_nonuniform_memory(feature, ram, processor):
    context = describe_feature(feature)
    assert context["specificity"] == "exact"
    assert f"{ram} GiB RAM" in _text(context)
    assert processor in context["summary"]
    assert "No local temporary disk" in _text(context)
    assert "Network-optimized (n)" not in _text(context)


def test_b2s_is_burstable_not_d_series_memory_ratio_or_no_disk():
    context = describe_feature("vmSkus.standard.b2s")
    assert "2 vCPUs and 4 GiB RAM" in _text(context)
    assert "CPU credits" in _text(context)
    assert "8 GiB of local temporary storage" in _text(context)
    assert "previous-generation" in _text(context)


@pytest.mark.parametrize(
    "feature",
    (
        "vmSkus.standard.d3ns.v6",
        "vmSkus.standard.e256ns.v6",
        "vmSkus.standard.d128s.v5",
        "vmSkus.standard.e104is.v5",
        "vmSkus.standard.q128ns.v6",
        "vmSkus.standard.d2ns.v99",
        "vmSkus.standard.d2mystery.v6",
        "vmSkus.standard.e8.2s.v5",
        "vmSkus.Standard_E8-2s_v5",
        "vmSkus.standard.nc4as.t4.v3",
        "vmSkus.standard.d02ns.v6",
        "vmSkus.standard.d0ns.v6",
        "vmSkus.standard.d2ns.v6.trailing",
        "vmSkus.standard.d2ns.v6\n",
        "vmSkus.standard.d" + "9" * 5000 + "ns.v6",
        "vmSkus.",
    ),
)
def test_unsupported_and_malformed_skus_never_infer_specs(feature):
    context = describe_feature(feature)
    assert context["specificity"] == "unverified"
    assert context["verified_on"] == ""
    assert "GiB" not in _text(context)
    assert " vCPUs" not in _text(context)
    searches = [s for s in context["sources"] if "/search/?" in s["url"]]
    assert parse_qs(urlsplit(searches[0]["url"]).query)["terms"] == [feature]


def test_raw_arm_sku_alias_has_same_verified_metadata():
    assert describe_feature("vmSkus.Standard_D128nlds_v6") == describe_feature(
        "vmSkus.standard.d128nlds.v6"
    )


@pytest.mark.parametrize(
    ("feature", "phrase"),
    (
        ("extensionTypes.microsoft.flux", "reconciles"),
        ("extensionTypes.microsoft.azuremonitor.containers", "Log Analytics"),
        ("extensionTypes.microsoft.policyinsights", "Gatekeeper"),
    ),
)
def test_verified_extensions_are_differentiated(feature, phrase):
    context = describe_feature(feature)
    assert context["specificity"] == "exact"
    assert phrase in _text(context)
    assert "installation" in context["limitations"]


def test_vmware_identity_is_arc_vcenter_management_not_gitops():
    context = describe_feature("extensionTypes.microsoft.vmware")
    assert context["title"] == "Azure Arc-enabled VMware vSphere"
    assert "vCenter" in _text(context)
    assert "resource bridge" in _text(context)
    assert "reconcile" not in _text(context)
    assert "not GitOps" in context["use_cases"]
    assert context["sources"][0]["url"].endswith("/vmware-vsphere/overview")
    assert context["sources"][1]["url"].endswith("/resource-graph-samples")


def test_unverified_azurepolicy_alias_is_not_silently_claimed_as_exact():
    context = describe_feature("extensionTypes.microsoft.azurepolicy")
    assert context["specificity"] == "unverified"
    assert "microsoft.policyinsights" in _text(context)
    assert "has not been verified as an alias" in _text(context)
    assert "/search/?" in context["sources"][0]["url"]


def test_arbitrary_extension_has_specific_search_and_no_guessed_capability():
    feature = "extensionTypes.example.new-capability"
    context = describe_feature(feature)
    assert context["specificity"] == "unverified"
    assert "GitOps" not in _text(context)
    assert parse_qs(urlsplit(context["sources"][0]["url"]).query)["terms"] == [feature]


@pytest.mark.parametrize(
    ("alias", "identity"),
    (
        ("extensions.gitops", "extensionTypes.microsoft.flux"),
        ("extensions.monitor", "extensionTypes.microsoft.azuremonitor.containers"),
    ),
)
def test_configured_extension_aliases(alias, identity):
    assert describe_feature(alias) == describe_feature(identity)


def test_flex_hosting_plan_is_not_a_language_runtime():
    context = describe_feature("hostingPlans.flexConsumption")
    assert context["specificity"] == "exact"
    assert "Linux-based" in context["summary"]
    assert "virtual network" in _text(context)
    assert "always-ready" in _text(context)
    assert "trigger groups" in _text(context)
    assert "not that quota is exhausted" in context["limitations"]


def test_unknown_hosting_plan_keeps_plan_evidence_without_inheriting_flex_capabilities():
    context = describe_feature("hostingPlans.newConsumption")
    assert context["specificity"] == "unverified"
    assert "not its language" in _text(context)
    assert "always-ready" not in _text(context)
    assert "/search/?" in context["sources"][0]["url"]


@pytest.mark.parametrize(
    ("feature", "phrase"),
    (
        ("runtimes.python.3.14", "decorators"),
        ("runtimes.node.24", "JavaScript or TypeScript"),
        ("runtimes.dotnet-isolated.10", "separate"),
        ("runtimes.java.25", "annotations"),
        ("runtimes.powershell.7.4", "script parameters"),
    ),
)
def test_documented_flex_language_versions(feature, phrase):
    context = describe_feature(feature)
    assert context["specificity"] == "exact"
    assert phrase in _text(context)
    assert "hosting-plan" not in context["title"]
    assert "Linux runtime listing" in context["limitations"]


def test_in_process_dotnet_is_not_described_as_supported_flex_runtime():
    context = describe_feature("runtimes.dotnet.8")
    assert context["specificity"] == "family"
    assert "does not support" in _text(context)
    assert "same process" in _text(context)
    assert "isolated-worker migration" in context["use_cases"]


@pytest.mark.parametrize("feature", ("runtimes.python.3.99", "runtimes.node.18"))
def test_undocumented_or_old_runtime_version_only_gets_family_context(feature):
    context = describe_feature(feature)
    assert context["specificity"] == "family"
    assert "current support is not verified" in _text(context)


@pytest.mark.parametrize("feature", ("runtimes.go.1.99", "runtimes.python.", "runtimes.python.future"))
def test_unknown_and_malformed_runtime_gets_unverified_context(feature):
    assert describe_feature(feature)["specificity"] == "unverified"


@pytest.mark.parametrize(
    ("feature", "phrase"),
    (
        ("managedEnvironments", "Azure-managed boundary"),
        ("apps", "containerized service"),
        ("jobs", "runs to completion"),
        ("connectedEnvironments", "Azure Arc-enabled Kubernetes"),
        ("daprComponents", "not a new Dapr runtime release"),
    ),
)
def test_container_apps_resource_types_are_distinct(feature, phrase):
    context = describe_feature(f"containerApps.{feature}")
    assert context["specificity"] == "exact"
    assert phrase in _text(context)
    assert "resource type's advertised locations" in context["limitations"]


def test_unknown_container_resource_cannot_inherit_a_known_resource_profile():
    context = describe_feature("containerApps.jobsV99")
    assert context["specificity"] == "unverified"
    assert "run to completion" not in _text(context)


def test_kubernetes_version_does_not_invent_release_features_or_ga_dates():
    context = describe_feature("kubernetesVersions.1.99")
    assert context["specificity"] == "category"
    assert "1.99" in context["title"]
    assert "launch" in context["limitations"]
    assert "not inferred" in context["limitations"]


@pytest.mark.parametrize(
    ("feature", "phrase"),
    (
        ("aiModels.openai.gpt-4o.2024-08-06", "image"),
        ("aiModels.openai.gpt-4-1-mini.2025-04-14", "structured outputs"),
        ("aiModels.openai.gpt-4.1.2025-04-14", "Responses"),
        ("aiModels.openai.o3.2025-04-16", "reasoning"),
        ("aiModels.openai.gpt-6-astra.2026-09-03", "Tool calling requires the Responses API"),
    ),
)
def test_exact_documented_model_versions(feature, phrase):
    context = describe_feature(feature)
    assert context["specificity"] == "exact"
    assert phrase in _text(context)
    assert "2026-09-06" == context["verified_on"]
    assert "not a launch-date claim" in context["limitations"]


@pytest.mark.parametrize(
    "feature",
    (
        "aiModels.openai.gpt-4o.future-version",
        "aiModels.openai.gpt-6-astra.test-version",
        "aiModels.anthropic.claude-fable-5-1.1",
    ),
)
def test_known_model_unknown_catalog_version_uses_only_family_context(feature):
    context = describe_feature(feature)
    assert context["specificity"] == "family"
    assert "exact catalog version" in context["limitations"]
    assert "has not been verified" in context["limitations"]


def test_documented_new_claude_family_has_meaning_and_provider_source_not_version_guess():
    context = describe_feature("aiModels.anthropic.claude-fable-5-1.1")
    assert "Claude Fable 5.1" in context["title"]
    assert "forced tool use is not supported" in _text(context)
    assert context["sources"][0]["url"].endswith("/models/fable-5-1/overview")
    assert context["specificity"] == "family"


@pytest.mark.parametrize(
    ("name", "dimensions"),
    (("text-embedding-3-small", "1,536"), ("text-embedding-3-large", "3,072")),
)
def test_embedding_models_are_vectors_not_chat_and_version_is_not_invented(name, dimensions):
    context = describe_feature(f"aiModels.openai.{name}.1")
    assert "Embeddings API" in _text(context)
    assert dimensions in _text(context)
    assert context["specificity"] == "family"


@pytest.mark.parametrize(
    "feature",
    (
        "aiModels.openai.gpt-99-revolution.2099-01-01",
        "aiModels.anthropic.claude-future-900.1",
        "aiModels.some-provider.model-with-dots.1-2-3",
        "aiModels.meta.gpt-4o.2024-08-06",
        "aiModels.openai.gpt-4o-future-vision.1",
        "aiModels.openai.gpt@4o.2024-08-06",
        "aiModels.openai.gpt.4o.2024-08-06",
    ),
)
def test_unknown_model_never_inherits_specs_by_prefix_or_provider_confusion(feature):
    context = describe_feature(feature)
    assert context["specificity"] == "category"
    assert "No exact model capability or version is verified" in context["limitations"]
    assert "category only" in context["sources"][0]["label"]
    assert "/search/?" in context["sources"][1]["url"]
    assert "128,000" not in _text(context)
    assert "supports image" not in _text(context).lower()


def test_latency_modalities_preserve_path_and_scope_not_catalog_claims():
    github = describe_feature("modelLatency.openai.gpt-4.1")
    azure = describe_feature("aiLatency.openai.gpt-4.1")
    assert "GitHub Models endpoint" in github["summary"]
    assert "not an Azure regional" in github["summary"]
    assert "retired" in github["limitations"]
    assert "configured Azure OpenAI deployment" in azure["summary"]
    assert "runner network path only" in azure["limitations"]
    assert github["specificity"] == azure["specificity"] == "family"
    assert "GPT-4.1" in github["title"]
    assert "GitHub" not in azure["summary"]


def test_unknown_latency_model_describes_inference_observation_not_catalog_presence():
    context = describe_feature("modelLatency.some-provider.never-seen")
    assert "inference request" in context["differentiators"][0]
    assert "Catalog presence" not in context["differentiators"][0]
    assert context["specificity"] == "category"


@pytest.mark.parametrize("feature", ("vmSkuCatalog", "extensionCatalog", "aiModelCatalog"))
def test_catalog_error_markers_do_not_become_product_features(feature):
    context = describe_feature(feature)
    assert context["specificity"] == "category"
    assert "catalog-level probe result" in context["summary"]
    assert "no reliable evidence of product absence" in _text(context)


def test_arbitrary_feature_search_encodes_untrusted_identifier():
    feature = 'anything.&terms=wrong#<script>" / café'
    context = describe_feature(feature)
    url = urlsplit(context["sources"][0]["url"])
    assert url.scheme == "https"
    assert url.hostname == "learn.microsoft.com"
    assert not url.fragment
    assert parse_qs(url.query) == {"terms": [feature]}
    assert context["specificity"] == "unverified"
    assert context["verified_on"] == ""


def test_all_profiles_and_defaults_satisfy_contract_offline(monkeypatch):
    def network_forbidden(*args, **kwargs):
        pytest.fail("Feature descriptions must not access the network.")

    monkeypatch.setattr(socket, "socket", network_forbidden)
    features = [
        "unknown", "", "hostingPlans.flexConsumption", "kubernetesVersions.1.35",
        "vmSkus.standard.b2s", "vmSkus.standard.e96s.v5", "vmSkus.standard.e2ns.v6",
        "extensionTypes.microsoft.vmware", "extensionTypes.microsoft.azurepolicy",
        "extensionTypes.example.unknown", "vmSkuCatalog", "extensionCatalog", "aiModelCatalog",
        "aiModels.openai.gpt-6-astra.2026-09-03",
        "aiModels.openai.text-embedding-3-large.1",
        "aiModels.anthropic.claude-fable-5-1.1",
        *[item.feature for item in DEFAULT_FUNCTION_RUNTIME_FEATURES],
        *[item.feature for item in DEFAULT_CONTAINER_APPS_RESOURCE_FEATURES],
        *[item.feature for item in DEFAULT_LATENCY_MODELS],
    ]
    fields = {
        "title", "summary", "differentiators", "use_cases", "sources", "specificity",
        "verified_on", "limitations",
    }
    hosts = {"learn.microsoft.com", "platform.claude.com", "docs.github.com"}
    for feature in features:
        context = describe_feature(feature)
        assert context == describe_feature(feature)
        assert set(context) == fields
        assert context["specificity"] in {"exact", "family", "category", "unverified"}
        assert 2 <= len(context["differentiators"]) <= 4
        assert all(isinstance(fact, str) and fact for fact in context["differentiators"])
        assert all(context[key] for key in ("title", "summary", "use_cases", "limitations"))
        assert context == json.loads(json.dumps(context))
        for source in context["sources"]:
            assert set(source) == {"label", "url"}
            url = urlsplit(source["url"])
            assert url.scheme == "https" and url.hostname in hosts
            assert not url.username and not url.password


def test_callers_cannot_mutate_later_results():
    feature = "vmSkus.standard.d2ns.v6"
    original = describe_feature(feature)
    mutated = describe_feature(feature)
    mutated["sources"][0]["url"] = "https://example.invalid"
    mutated["differentiators"].clear()
    assert describe_feature(feature) == original


def test_module_is_leaf_without_history_or_summary_imports():
    tree = ast.parse(Path(feature_context.__file__).read_text(encoding="utf-8"))
    package_imports = [
        node.module for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("azure_region_monitor")
    ]
    assert package_imports == ["azure_region_monitor.display"]
