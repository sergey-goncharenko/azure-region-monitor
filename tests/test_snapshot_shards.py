from azure_region_monitor.snapshot_shards import (
    build_modality_shards,
    build_summary,
    modality_slug,
)

ROWS = [
    {"region": "eastus", "service": "ai", "category": "Azure AI models", "group": "openai",
     "feature": "aiModels.openai.gpt-4o.2024", "status": "available", "message": "listed"},
    {"region": "westus3", "service": "ai", "category": "Azure AI models", "group": "openai",
     "feature": "aiModels.openai.gpt-4o.2024", "status": "unavailable", "message": "not listed"},
    {"region": "eastus", "service": "compute", "category": "VM SKUs", "group": "D",
     "feature": "vmSkus.standard.d2s.v5", "status": "available", "message": "listed"},
    {"region": "github-global", "service": "model-latency", "category": "Model latency",
     "group": "openai", "feature": "modelLatency.openai.gpt-4o", "status": "available",
     "message": "p50 1607ms"},
]


def test_modality_slug_basic():
    assert modality_slug("Azure AI models") == "azure-ai-models"
    assert modality_slug("VM SKUs") == "vm-skus"
    assert modality_slug("Model latency") == "model-latency"
    assert modality_slug("   ") == "other"


def test_build_summary_counts():
    summary = build_summary("2026-06-18T00:00:00+00:00", ["eastus", "westus3", "github-global"], ROWS)
    assert summary["regions"] == 3
    assert summary["checks"] == 4
    assert summary["status_counts"]["available"] == 3
    assert summary["status_counts"]["unavailable"] == 1
    assert summary["modality_counts"]["Azure AI models"]["checks"] == 2
    assert summary["modality_counts"]["Azure AI models"]["available"] == 1
    assert summary["modality_counts"]["Model latency"]["available"] == 1


def test_build_modality_shards_splits_by_modality_with_full_fidelity():
    manifest, shards = build_modality_shards("2026-06-18T00:00:00+00:00", ["eastus", "westus3", "github-global"], ROWS)

    slugs = {m["slug"] for m in manifest["modalities"]}
    assert slugs == {"azure-ai-models", "vm-skus", "model-latency"}

    # Full fidelity: total shard rows equal input rows.
    assert sum(m["rows"] for m in manifest["modalities"]) == len(ROWS)
    assert sum(len(shard["rows"]) for shard in shards.values()) == len(ROWS)

    ai = shards["azure-ai-models"]
    assert ai["modality"] == "Azure AI models"
    assert len(ai["rows"]) == 2
    assert sorted(ai["regions"]) == ["eastus", "westus3"]
    # Rows keep the fields the heatmap needs.
    row = ai["rows"][0]
    assert set(row.keys()) == {"region", "service", "feature", "status", "message"}

    # Manifest paths point at the shard files.
    paths = {m["path"] for m in manifest["modalities"]}
    assert "modalities/azure-ai-models.json" in paths


def test_build_modality_shards_empty():
    manifest, shards = build_modality_shards("2026-06-18T00:00:00+00:00", [], [])
    assert manifest["modalities"] == []
    assert shards == {}
