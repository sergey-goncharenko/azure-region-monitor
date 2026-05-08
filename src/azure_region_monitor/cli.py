from __future__ import annotations

import argparse
import os
from datetime import datetime
from pathlib import Path

from azure_region_monitor.config import DEFAULT_REGIONS, parse_aks_extension_features
from azure_region_monitor.diff import build_diff
from azure_region_monitor.probes.aks_extension import AksExtensionCliProbe
from azure_region_monitor.probes.sample import SampleAksExtensionProbe
from azure_region_monitor.runner import run_probes
from azure_region_monitor.storage import load_snapshot, write_diff, write_snapshot


def main() -> None:
    parser = argparse.ArgumentParser(prog="azure-region-monitor")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run synthetic probes and write a snapshot")
    run_parser.add_argument("--region", action="append", dest="regions", help="Azure region to test")
    run_parser.add_argument(
        "--probe",
        choices=["sample-aks-extension", "aks-extension-cli"],
        default="sample-aks-extension",
        help="Synthetic probe implementation to run",
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

    args = parser.parse_args()
    args.handler(args)


def _run(args: argparse.Namespace) -> None:
    regions = args.regions or DEFAULT_REGIONS
    snapshot = run_probes(regions, [_build_probe(args.probe)], timestamp=args.timestamp)
    write_snapshot(args.output, snapshot)
    print(f"Wrote snapshot for {len(regions)} regions to {args.output}")


def _diff(args: argparse.Namespace) -> None:
    diff = build_diff(load_snapshot(args.previous), load_snapshot(args.current))
    write_diff(args.output, diff)
    print(f"Wrote {len(diff.changes)} changes to {args.output}")


def _serve(args: argparse.Namespace) -> None:
    import uvicorn

    uvicorn.run("azure_region_monitor.api:app", host=args.host, port=args.port, reload=args.reload)


def _parse_timestamp(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _build_probe(probe_name: str):
    if probe_name == "sample-aks-extension":
        return SampleAksExtensionProbe()
    if probe_name == "aks-extension-cli":
        return AksExtensionCliProbe(
            features=parse_aks_extension_features(os.environ.get("AKS_EXTENSION_FEATURES"))
        )
    raise ValueError(f"Unsupported probe: {probe_name}")


if __name__ == "__main__":
    main()
