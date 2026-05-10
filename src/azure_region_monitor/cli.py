from __future__ import annotations

import argparse
import os
import urllib.request
from datetime import datetime
from pathlib import Path

from azure_region_monitor.config import (
    DEFAULT_REGIONS,
    parse_aks_extension_features,
    parse_aks_kubernetes_version_prefixes,
    parse_vm_skus,
)
from azure_region_monitor.diff import build_diff
from azure_region_monitor.history import fetch_history, update_history
from azure_region_monitor.probes.aks_extension import AksExtensionCliProbe
from azure_region_monitor.probes.aks_extension_catalog import AksExtensionCatalogCliProbe
from azure_region_monitor.probes.aks_versions import AksKubernetesVersionCliProbe
from azure_region_monitor.probes.sample import SampleAksExtensionProbe
from azure_region_monitor.probes.vm_skus import VmSkuCliProbe
from azure_region_monitor.runner import run_probes
from azure_region_monitor.snapshot_merge import merge_snapshot_overlay
from azure_region_monitor.storage import load_snapshot, write_diff, write_snapshot
from azure_region_monitor.static_site import build_static_site


def main() -> None:
    parser = argparse.ArgumentParser(prog="azure-region-monitor")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run synthetic probes and write a snapshot")
    run_parser.add_argument("--region", action="append", dest="regions", help="Azure region to test")
    run_parser.add_argument(
        "--probe",
        action="append",
        choices=[
            "sample-aks-extension",
            "aks-extension-cli",
            "aks-extension-catalog-cli",
            "aks-version-cli",
            "vm-sku-cli",
        ],
        dest="probes",
        help="Synthetic probe implementation to run; repeat to run multiple probes",
    )
    run_parser.add_argument("--output", type=Path, default=Path("data/snapshots/latest.json"))
    run_parser.add_argument("--timestamp", type=_parse_timestamp)
    run_parser.set_defaults(handler=_run)

    diff_parser = subparsers.add_parser("diff", help="Compare two snapshots and write a diff")
    diff_parser.add_argument("previous", type=Path)
    diff_parser.add_argument("current", type=Path)
    diff_parser.add_argument("--output", type=Path, default=Path("data/diffs/latest.json"))
    diff_parser.set_defaults(handler=_diff)

    serve_parser = subparsers.add_parser("serve", help="Run the local API server")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)
    serve_parser.add_argument("--reload", action="store_true")
    serve_parser.set_defaults(handler=_serve)

    static_parser = subparsers.add_parser("build-static", help="Build static dashboard and JSON API files")
    static_parser.add_argument("--output", type=Path, default=Path("public"))
    static_parser.add_argument("--snapshot", type=Path, default=Path("data/snapshots/latest.json"))
    static_parser.add_argument("--diff", type=Path, default=Path("data/diffs/latest.json"))
    static_parser.add_argument("--history", type=Path, default=Path("data/history"))
    static_parser.set_defaults(handler=_build_static)

    fetch_history_parser = subparsers.add_parser(
        "fetch-history", help="Fetch existing static dashboard history files"
    )
    fetch_history_parser.add_argument("--base-url", required=True)
    fetch_history_parser.add_argument("--output", type=Path, default=Path("data/history"))
    fetch_history_parser.set_defaults(handler=_fetch_history)

    update_history_parser = subparsers.add_parser(
        "update-history", help="Store the latest snapshot and update compact changelog JSON"
    )
    update_history_parser.add_argument("--snapshot", type=Path, default=Path("data/snapshots/latest.json"))
    update_history_parser.add_argument("--history-dir", type=Path, default=Path("data/history"))
    update_history_parser.add_argument("--base-url", default="")
    update_history_parser.set_defaults(handler=_update_history)

    merge_parser = subparsers.add_parser(
        "merge-snapshot", help="Merge a focused modality snapshot into an existing snapshot"
    )
    merge_parser.add_argument("--base-url", required=True)
    merge_parser.add_argument("--overlay", type=Path, default=Path("data/snapshots/latest.json"))
    merge_parser.add_argument("--output", type=Path, default=Path("data/snapshots/latest.json"))
    merge_parser.set_defaults(handler=_merge_snapshot)

    args = parser.parse_args()
    args.handler(args)


def _run(args: argparse.Namespace) -> None:
    regions = args.regions or DEFAULT_REGIONS
    snapshot = run_probes(regions, _build_probes(args.probes), timestamp=args.timestamp)
    write_snapshot(args.output, snapshot)
    print(f"Wrote snapshot for {len(regions)} regions to {args.output}")


def _diff(args: argparse.Namespace) -> None:
    diff = build_diff(load_snapshot(args.previous), load_snapshot(args.current))
    write_diff(args.output, diff)
    print(f"Wrote {len(diff.changes)} changes to {args.output}")


def _serve(args: argparse.Namespace) -> None:
    import uvicorn

    uvicorn.run("azure_region_monitor.api:app", host=args.host, port=args.port, reload=args.reload)


def _build_static(args: argparse.Namespace) -> None:
    build_static_site(
        args.output, snapshot_path=args.snapshot, diff_path=args.diff, history_path=args.history
    )
    print(f"Built static site in {args.output}")


def _fetch_history(args: argparse.Namespace) -> None:
    fetched = fetch_history(args.output, args.base_url)
    if fetched:
        print(f"Fetched dashboard history from {args.base_url} to {args.output}")
    else:
        print(f"No existing dashboard history found at {args.base_url}")


def _update_history(args: argparse.Namespace) -> None:
    recent_changes = update_history(
        snapshot_path=args.snapshot,
        history_dir=args.history_dir,
        base_url=args.base_url or None,
    )
    print(
        f"Updated history in {args.history_dir} with "
        f"{len(recent_changes.get('days', []))} recent change days"
    )


def _merge_snapshot(args: argparse.Namespace) -> None:
    with urllib.request.urlopen(args.base_url, timeout=30) as response:
        base = load_snapshot_from_text(response.read().decode("utf-8"))
    overlay = load_snapshot(args.overlay)
    write_snapshot(args.output, merge_snapshot_overlay(base, overlay))
    print(f"Merged focused snapshot into {args.output}")


def load_snapshot_from_text(raw: str):
    from azure_region_monitor.models import Snapshot

    return Snapshot.model_validate_json(raw)


def _parse_timestamp(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _build_probes(probe_names: list[str] | None):
    return [_build_probe(probe_name) for probe_name in (probe_names or ["sample-aks-extension"])]


def _build_probe(probe_name: str):
    if probe_name == "sample-aks-extension":
        return SampleAksExtensionProbe()
    if probe_name == "aks-extension-cli":
        return AksExtensionCliProbe(
            features=parse_aks_extension_features(os.environ.get("AKS_EXTENSION_FEATURES"))
        )
    if probe_name == "aks-extension-catalog-cli":
        return AksExtensionCatalogCliProbe()
    if probe_name == "aks-version-cli":
        return AksKubernetesVersionCliProbe(
            version_prefixes=parse_aks_kubernetes_version_prefixes(
                os.environ.get("AKS_KUBERNETES_VERSION_PREFIXES")
            )
        )
    if probe_name == "vm-sku-cli":
        return VmSkuCliProbe(skus=parse_vm_skus(os.environ.get("AZURE_VM_SKUS")))
    raise ValueError(f"Unsupported probe: {probe_name}")


if __name__ == "__main__":
    main()
