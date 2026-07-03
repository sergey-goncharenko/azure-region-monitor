import json
from types import SimpleNamespace

from azure_region_monitor.cli import _merge_snapshot


def _write_snapshot(path, regions):
    payload = {"timestamp": "2026-07-03T00:00:00+00:00", "regions": regions}
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_merge_snapshot_cli_combines_multiple_overlays_onto_local_base(tmp_path):
    # Base carries three modalities; each overlay refreshes exactly one of them.
    base = tmp_path / "base.json"
    _write_snapshot(
        base,
        {
            "eastus": {
                "aks": {"extensionTypes.old": {"status": "unavailable"}},
                "compute": {"vmSkus.standard.b2s": {"status": "unavailable"}},
                "ai-latency": {"aiLatency.openai.gpt-4o": {"status": "unavailable"}},
            }
        },
    )
    aks_overlay = tmp_path / "aks.json"
    _write_snapshot(aks_overlay, {"eastus": {"aks": {"extensionTypes.new": {"status": "available"}}}})
    vm_overlay = tmp_path / "vm.json"
    _write_snapshot(vm_overlay, {"eastus": {"compute": {"vmSkus.standard.d2s": {"status": "available"}}}})

    output = tmp_path / "out.json"
    _merge_snapshot(
        SimpleNamespace(base_file=base, base_url=None, overlays=[aks_overlay, vm_overlay], output=output)
    )

    merged = json.loads(output.read_text(encoding="utf-8"))
    aks = merged["regions"]["eastus"]["aks"]
    compute = merged["regions"]["eastus"]["compute"]
    ai = merged["regions"]["eastus"]["ai-latency"]
    # Both overlaid modalities replaced their modality features.
    assert "extensionTypes.old" not in aks and aks["extensionTypes.new"]["status"] == "available"
    assert "vmSkus.standard.b2s" not in compute and compute["vmSkus.standard.d2s"]["status"] == "available"
    # The un-overlaid modality is carried forward from the base.
    assert ai["aiLatency.openai.gpt-4o"]["status"] == "unavailable"


def test_merge_snapshot_cli_skips_missing_overlays(tmp_path):
    base = tmp_path / "base.json"
    _write_snapshot(base, {"eastus": {"compute": {"vmSkus.standard.b2s": {"status": "available"}}}})
    present = tmp_path / "present.json"
    _write_snapshot(present, {"eastus": {"compute": {"vmSkus.standard.d2s": {"status": "available"}}}})
    missing = tmp_path / "missing.json"  # never created

    output = tmp_path / "out.json"
    _merge_snapshot(
        SimpleNamespace(base_file=base, base_url=None, overlays=[missing, present], output=output)
    )

    merged = json.loads(output.read_text(encoding="utf-8"))
    compute = merged["regions"]["eastus"]["compute"]
    assert compute["vmSkus.standard.d2s"]["status"] == "available"
