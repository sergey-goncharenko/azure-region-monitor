import json
from datetime import datetime, timedelta, timezone

from azure_region_monitor import history
from azure_region_monitor.learn_lookup import (
    LearnHttpResponse,
    LearnLookupClient,
    _GATE_VERSION,
    attach_learn_references,
    build_lookup_query,
    fresh_cached_references,
    lookup_learn_references,
    parse_json_rpc_response,
    read_reference_cache,
    select_learn_reference,
    write_reference_cache,
)


NOW = datetime(2026, 10, 4, 19, 0, tzinfo=timezone.utc)


def _briefing(*features: dict) -> dict:
    return {
        "digest": {
            "version": 1,
            "modalities": [
                {
                    "modality": "VM SKUs",
                    "features": list(features),
                }
            ],
        },
        "feature_contexts": {
            feature["feature"]: {"title": feature["label"]}
            for feature in features
        },
    }


def _feature(feature: str, label: str, modality: str = "VM SKUs") -> dict:
    return {
        "feature": feature,
        "label": label,
        "modality": modality,
        "learn_reference": None,
    }


def _result(title: str, url: str, content: str) -> dict:
    return {"title": title, "contentUrl": url, "content": content}


def _transport_for(results_by_query: dict[str, list[dict]]):
    state = {"initialized": False}

    def transport(_endpoint, payload, _headers, _timeout):
        if payload["method"] == "initialize":
            state["initialized"] = True
            body = {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {"protocolVersion": "2024-11-05", "capabilities": {}},
            }
            return LearnHttpResponse(
                status=200,
                headers={"Mcp-Session-Id": "test-session"},
                content_type="application/json",
                body=json.dumps(body).encode("utf-8"),
            )
        assert state["initialized"]
        query = payload["params"]["arguments"]["query"]
        body = {
            "jsonrpc": "2.0",
            "id": payload["id"],
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({"results": results_by_query.get(query, [])}),
                    }
                ]
            },
        }
        return LearnHttpResponse(
            status=200,
            headers={"Mcp-Session-Id": "test-session"},
            content_type="application/json",
            body=json.dumps(body).encode("utf-8"),
        )

    return transport


def test_protocol_parsing_accepts_json_and_sse():
    json_body = b'{"jsonrpc":"2.0","id":1,"result":{"ok":true}}'
    assert parse_json_rpc_response("application/json", json_body)["result"] == {"ok": True}

    sse_body = (
        'event: message\n'
        'data: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n\n'
    ).encode("utf-8")
    assert parse_json_rpc_response("text/event-stream", sse_body)["result"] == {"ok": True}


def test_relevance_gate_accepts_top_learn_result():
    entry = _feature("vmSkus.standard.d248ds.v7", "Standard D248ds V7 VM size")
    accepted = select_learn_reference(
        entry,
        [
            _result(
                "Ddsv7 sizes series",
                "https://learn.microsoft.com/azure/virtual-machines/sizes/general-purpose/ddsv7-series",
                "# Ddsv7 sizes series\nStandard_D248ds_v7 has 248 vCPUs.",
            )
        ],
    )

    assert accepted == {
        "title": "Ddsv7 sizes series",
        "url": "https://learn.microsoft.com/azure/virtual-machines/sizes/general-purpose/ddsv7-series",
        "excerpt": "Ddsv7 sizes series Standard D248ds v7 has 248 vCPUs.",
    }


def test_relevance_gate_rejects_non_learn_or_missing_token():
    entry = _feature("extensionTypes.microsoft.azurepolicy", "Azure Policy AKS extension")

    assert select_learn_reference(
        entry,
        [_result("Azure Policy", "https://example.com/azure-policy", "Azure Policy")],
    ) is None
    assert select_learn_reference(
        entry,
        [_result("Cluster extensions", "https://learn.microsoft.com/azure/aks/cluster-extensions", "Flux")],
    ) is None


def test_relevance_gate_rejects_azure_policy_backup_false_positive():
    entry = _feature("extensionTypes.microsoft.azurepolicy", "Azure Policy AKS extension")

    assert select_learn_reference(
        entry,
        [
            _result(
                "Audit and enforce backup operations for Azure Kubernetes Service clusters using Azure Policy",
                "https://learn.microsoft.com/azure/backup/azure-kubernetes-service-cluster-backup-using-azure-policy",
                "Use Azure Policy to audit and enforce backup operations for AKS clusters.",
            )
        ],
    ) is None


def test_relevance_gate_accepts_aks_azure_policy_result():
    entry = _feature("extensionTypes.microsoft.azurepolicy", "Azure Policy AKS extension")

    accepted = select_learn_reference(
        entry,
        [
            _result(
                "Use Azure Policy to secure your cluster",
                "https://learn.microsoft.com/azure/aks/use-azure-policy",
                "# Use Azure Policy to secure your cluster\nLearn how to apply Azure Policy to AKS.",
            )
        ],
    )

    assert accepted == {
        "title": "Use Azure Policy to secure your cluster",
        "url": "https://learn.microsoft.com/azure/aks/use-azure-policy",
        "excerpt": "Use Azure Policy to secure your cluster Learn how to apply Azure Policy to AKS.",
    }


def test_relevance_gate_picks_second_qualifying_result():
    entry = _feature("extensionTypes.microsoft.azurepolicy", "Azure Policy AKS extension")

    accepted = select_learn_reference(
        entry,
        [
            _result(
                "Audit and enforce backup operations for Azure Kubernetes Service clusters using Azure Policy",
                "https://learn.microsoft.com/azure/backup/azure-kubernetes-service-cluster-backup-using-azure-policy",
                "Backup policy content.",
            ),
            _result(
                "Use Azure Policy to secure your cluster",
                "https://learn.microsoft.com/azure/aks/use-azure-policy",
                "# Use Azure Policy to secure your cluster\nAKS policy add-on guidance.",
            ),
        ],
    )

    assert accepted["url"] == "https://learn.microsoft.com/azure/aks/use-azure-policy"


def test_relevance_gate_requires_vm_series_in_title_or_url():
    entry = _feature("vmSkus.standard.d248ds.v7", "Standard D248ds V7 VM size")

    assert select_learn_reference(
        entry,
        [
            _result(
                "Azure VM sizes",
                "https://learn.microsoft.com/azure/virtual-machines/sizes/general-purpose/overview",
                "The Ddsv7 series includes Standard_D248ds_v7.",
            )
        ],
    ) is None

    accepted = select_learn_reference(
        entry,
        [
            _result(
                "Azure VM sizes",
                "https://learn.microsoft.com/azure/virtual-machines/sizes/general-purpose/ddsv7-series",
                "Standard_D248ds_v7 has 248 vCPUs.",
            )
        ],
    )

    assert accepted["url"] == "https://learn.microsoft.com/azure/virtual-machines/sizes/general-purpose/ddsv7-series"


def test_relevance_gate_uses_token_boundaries_for_vm_series_and_model_names():
    d2_v5 = _feature("vmSkus.standard.d2.v5", "Standard D2 v5 VM size")
    assert select_learn_reference(
        d2_v5,
        [
            _result(
                "Ddv5 sizes series",
                "https://learn.microsoft.com/azure/virtual-machines/sizes/general-purpose/ddv5-series",
                "Ddv5 sizes series includes Standard_D2d_v5.",
            )
        ],
    ) is None

    d248ds_v7 = _feature("vmSkus.standard.d248ds.v7", "Standard D248ds V7 VM size")
    assert select_learn_reference(
        d248ds_v7,
        [
            _result(
                "Azure VM sizes",
                "https://learn.microsoft.com/azure/virtual-machines/sizes/general-purpose/ddsv7-series",
                "Ddsv7 sizes series includes Standard_D248ds_v7.",
            )
        ],
    )["url"].endswith("/ddsv7-series")

    o1 = _feature("aiModels.openai.o1.2024-12-17", "OpenAI o1 2024-12-17 model")
    assert select_learn_reference(
        o1,
        [
            _result(
                "o1-mini reasoning model",
                "https://learn.microsoft.com/azure/ai-services/openai/concepts/models",
                "# o1-mini reasoning model\nUse o1-mini for reasoning.",
            )
        ],
    ) is None

    gpt_41 = _feature("aiModels.openai.gpt-4.1.2025-04-14", "OpenAI gpt-4.1 2025-04-14 model")
    assert select_learn_reference(
        gpt_41,
        [
            _result(
                "GPT-4.1-mini model",
                "https://learn.microsoft.com/azure/ai-services/openai/concepts/models",
                "# GPT-4.1-mini model\nGPT-4.1-mini is a smaller model.",
            )
        ],
    ) is None
    assert select_learn_reference(
        gpt_41,
        [
            _result(
                "Azure OpenAI models",
                "https://learn.microsoft.com/azure/ai-services/openai/concepts/gpt-41-series",
                "# Azure OpenAI models\nGPT-4.1 model guidance.",
            )
        ],
    )["title"] == "Azure OpenAI models"


def test_cache_ttl_reuses_positive_for_30_days_and_negative_for_7_days(tmp_path):
    cache_path = tmp_path / "feature-references.json"
    write_reference_cache(
        cache_path,
        {
            "features": {
                "vmSkus.standard.d2s.v5": {
                    "checked_at": (NOW - timedelta(days=29)).isoformat(),
                    "gate_version": _GATE_VERSION,
                    "query": "Dsv5 series Azure virtual machine size",
                    "reference": {
                        "title": "Dsv5 sizes series",
                        "url": "https://learn.microsoft.com/azure/virtual-machines/sizes/general-purpose/dsv5-series",
                        "excerpt": "Dsv5 sizes series",
                    },
                },
                "vmSkus.standard.d4s.v5": {
                    "checked_at": (NOW - timedelta(days=31)).isoformat(),
                    "gate_version": _GATE_VERSION,
                    "query": "Dsv5 series Azure virtual machine size",
                    "reference": {
                        "title": "Dsv5 sizes series",
                        "url": "https://learn.microsoft.com/azure/virtual-machines/sizes/general-purpose/dsv5-series",
                        "excerpt": "Dsv5 sizes series",
                    },
                },
                "vmSkus.standard.d8s.v5": {
                    "checked_at": (NOW - timedelta(days=6)).isoformat(),
                    "gate_version": _GATE_VERSION,
                    "query": "Dsv5 series Azure virtual machine size",
                    "reference": None,
                },
                "vmSkus.standard.d16s.v5": {
                    "checked_at": (NOW - timedelta(days=8)).isoformat(),
                    "gate_version": _GATE_VERSION,
                    "query": "Dsv5 series Azure virtual machine size",
                    "reference": None,
                },
            }
        },
        now=NOW,
    )

    assert fresh_cached_references(cache_path, now=NOW) == {
        "vmSkus.standard.d2s.v5": {
            "title": "Dsv5 sizes series",
            "url": "https://learn.microsoft.com/azure/virtual-machines/sizes/general-purpose/dsv5-series",
            "excerpt": "Dsv5 sizes series",
        }
    }
    cache = read_reference_cache(cache_path)
    assert "vmSkus.standard.d8s.v5" in cache["features"]


def test_cache_gate_version_mismatch_expires_entry(tmp_path):
    cache_path = tmp_path / "feature-references.json"
    write_reference_cache(
        cache_path,
        {
            "features": {
                "vmSkus.standard.d2s.v5": {
                    "checked_at": (NOW - timedelta(days=1)).isoformat(),
                    "gate_version": _GATE_VERSION - 1,
                    "query": "Dsv5 series Azure virtual machine size",
                    "reference": {
                        "title": "Dsv5 sizes series",
                        "url": "https://learn.microsoft.com/azure/virtual-machines/sizes/general-purpose/dsv5-series",
                        "excerpt": "Dsv5 sizes series",
                    },
                },
                "vmSkus.standard.d4s.v5": {
                    "checked_at": (NOW - timedelta(days=1)).isoformat(),
                    "query": "Dsv5 series Azure virtual machine size",
                    "reference": {
                        "title": "Dsv5 sizes series",
                        "url": "https://learn.microsoft.com/azure/virtual-machines/sizes/general-purpose/dsv5-series",
                        "excerpt": "Dsv5 sizes series",
                    },
                },
            }
        },
        now=NOW,
    )

    assert fresh_cached_references(cache_path, now=NOW) == {}


def test_reference_cache_invalid_encoding_or_malformed_entries_returns_empty(tmp_path):
    cache_path = tmp_path / "feature-references.json"
    cache_path.write_text(
        json.dumps({"version": 1, "features": {"bad": []}}),
        encoding="utf-16",
    )

    assert read_reference_cache(cache_path) == {"version": 1, "features": {}}

    cache_path.write_text(
        json.dumps({"version": 1, "features": {"bad": [], "good": {"query": "Dsv5"}}}),
        encoding="utf-8",
    )

    assert read_reference_cache(cache_path) == {
        "version": 1,
        "features": {"good": {"query": "Dsv5"}},
    }


def test_budget_limit_stops_network_lookups(tmp_path):
    features = [
        _feature(f"vmSkus.standard.d{size}s.v5", f"Standard D{size}s v5 VM size")
        for size in (2, 4)
    ]
    briefing = _briefing(*features)
    first_query = build_lookup_query(features[0]).query
    client = LearnLookupClient(
        transport=_transport_for({
            first_query: [
                _result(
                    "Dsv5 sizes series",
                    "https://learn.microsoft.com/azure/virtual-machines/sizes/general-purpose/dsv5-series",
                    "Dsv5 sizes series includes Standard_D2s_v5.",
                )
            ]
        })
    )

    metadata = lookup_learn_references(
        briefing,
        tmp_path / "feature-references.json",
        enabled=True,
        client=client,
        now=NOW,
        max_lookups=1,
    )

    assert metadata["status"] == "partial"
    assert metadata["looked_up"] == 1
    assert metadata["matched"] == 1
    assert briefing["digest"]["modalities"][0]["features"][0]["learn_reference"]["title"] == "Dsv5 sizes series"


def test_attach_noop_without_digest():
    briefing = {"feature_contexts": {"vmSkus.standard.d2s.v5": {"title": "D2s"}}}

    attach_learn_references(
        briefing,
        {"vmSkus.standard.d2s.v5": {"title": "Dsv5", "url": "https://learn.microsoft.com/x", "excerpt": "Dsv5"}},
    )

    assert briefing["feature_contexts"]["vmSkus.standard.d2s.v5"]["learn_reference"]["title"] == "Dsv5"


def test_attach_sets_digest_and_feature_context_references():
    briefing = _briefing(_feature("vmSkus.standard.d2s.v5", "Standard D2s v5 VM size"))
    reference = {
        "title": "Dsv5 sizes series",
        "url": "https://learn.microsoft.com/azure/virtual-machines/sizes/general-purpose/dsv5-series",
        "excerpt": "Dsv5 sizes series",
    }

    attach_learn_references(briefing, {"vmSkus.standard.d2s.v5": reference})

    assert briefing["digest"]["modalities"][0]["features"][0]["learn_reference"] == reference
    assert briefing["feature_contexts"]["vmSkus.standard.d2s.v5"]["learn_reference"] == reference


def test_disabled_env_skips_lookup(tmp_path, monkeypatch):
    monkeypatch.setenv("LEARN_LOOKUP_ENABLED", "0")
    briefing = _briefing(_feature("vmSkus.standard.d2s.v5", "Standard D2s v5 VM size"))

    metadata = lookup_learn_references(briefing, tmp_path / "feature-references.json")

    assert metadata == {
        "status": "disabled",
        "looked_up": 0,
        "cached": 0,
        "matched": 0,
        "error": None,
    }


def test_update_history_records_lookup_failure_without_failing(tmp_path, monkeypatch):
    class FailingClient:
        def search(self, _query):
            raise RuntimeError("network unavailable")

    def enriched(briefing):
        briefing = dict(briefing)
        briefing["digest"] = {
            "version": 1,
            "modalities": [
                {
                    "modality": "VM SKUs",
                    "features": [
                        _feature("vmSkus.standard.d2s.v5", "Standard D2s v5 VM size"),
                    ],
                }
            ],
        }
        briefing["feature_contexts"] = {
            "vmSkus.standard.d2s.v5": {"title": "Standard D2s v5 VM size"}
        }
        return briefing

    monkeypatch.setattr(history, "enrich_briefing_features", enriched)
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(
        json.dumps(
            {
                "timestamp": "2026-10-04T00:00:00Z",
                "regions": {
                    "eastus": {
                        "compute": {
                            "vmSkus.standard.d2s.v5": {"status": "available"},
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    history.update_history(
        snapshot,
        tmp_path / "history",
        learn_lookup_enabled=True,
        learn_lookup_client=FailingClient(),
    )

    change_day = json.loads((tmp_path / "history" / "changes" / "2026-10-04.json").read_text())
    assert change_day["learn_lookup"]["status"] == "failed"
    assert change_day["learn_lookup"]["error"] == "network unavailable"


def test_update_history_persists_reference_cache_and_copies_to_api(tmp_path, monkeypatch):
    def enriched(briefing):
        briefing = dict(briefing)
        briefing["digest"] = {
            "version": 1,
            "modalities": [
                {
                    "modality": "VM SKUs",
                    "features": [
                        _feature("vmSkus.standard.d2s.v5", "Standard D2s v5 VM size"),
                    ],
                }
            ],
        }
        briefing["feature_contexts"] = {
            "vmSkus.standard.d2s.v5": {"title": "Standard D2s v5 VM size"}
        }
        return briefing

    monkeypatch.setattr(history, "enrich_briefing_features", enriched)
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(
        json.dumps(
            {
                "timestamp": "2026-10-04T00:00:00Z",
                "regions": {
                    "eastus": {
                        "compute": {
                            "vmSkus.standard.d2s.v5": {"status": "available"},
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    query = "Dsv5 series Azure virtual machine size"
    client = LearnLookupClient(
        transport=_transport_for({
            query: [
                _result(
                    "Dsv5 sizes series",
                    "https://learn.microsoft.com/azure/virtual-machines/sizes/general-purpose/dsv5-series",
                    "Dsv5 sizes series includes Standard_D2s_v5.",
                )
            ]
        })
    )
    history_dir = tmp_path / "history"

    history.update_history(
        snapshot,
        history_dir,
        learn_lookup_enabled=True,
        learn_lookup_client=client,
    )
    api_dir = tmp_path / "api-history"
    history.copy_history_to_api(history_dir, api_dir)

    index = json.loads((history_dir / "index.json").read_text(encoding="utf-8"))
    assert index["feature_references_path"] == "feature-references.json"
    assert (history_dir / "feature-references.json").is_file()
    assert (api_dir / "feature-references.json").is_file()
