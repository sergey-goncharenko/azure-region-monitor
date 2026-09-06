from __future__ import annotations

import argparse
import gzip
import json
import os
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from azure_region_monitor.config import (
    DEFAULT_REGIONS,
    parse_ai_latency_targets,
    parse_aks_extension_features,
    parse_aks_kubernetes_version_prefixes,
    parse_ai_model_features,
    parse_container_apps_resource_features,
    parse_function_runtime_features,
    parse_latency_models,
    parse_vm_skus,
)
from azure_region_monitor.diff import build_diff
from azure_region_monitor.history import fetch_history, update_history
from azure_region_monitor.probes.ai_model_latency import AzureOpenAiLatencyProbe
from azure_region_monitor.probes.aks_extension import AksExtensionCliProbe
from azure_region_monitor.probes.aks_extension_catalog import AksExtensionCatalogCliProbe
from azure_region_monitor.probes.aks_versions import AksKubernetesVersionCliProbe
from azure_region_monitor.probes.ai_models import AiModelCatalogCliProbe
from azure_region_monitor.probes.container_apps import ContainerAppsProviderCliProbe
from azure_region_monitor.probes.functions import FunctionsFlexConsumptionCliProbe
from azure_region_monitor.probes.model_latency import ModelLatencyProbe
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
            "ai-model-catalog-cli",
            "container-apps-provider-cli",
            "function-flex-cli",
            "model-latency-cli",
            "ai-model-latency-cli",
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

    social_parser = subparsers.add_parser(
        "social-drafts", help="Render review-only social post drafts from history"
    )
    social_parser.add_argument("--history", type=Path, default=Path("data/history"))
    social_parser.add_argument("--site-url", default="https://azwatch.operator.lat")
    social_parser.add_argument("--limit", type=int, default=1)
    social_parser.set_defaults(handler=_social_drafts)

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
        "merge-snapshot", help="Merge one or more focused modality snapshots into a base snapshot"
    )
    merge_parser.add_argument("--base-url", default=None)
    merge_parser.add_argument(
        "--base-file",
        type=Path,
        default=None,
        help="Local base snapshot; takes precedence over --base-url",
    )
    merge_parser.add_argument(
        "--overlay",
        type=Path,
        action="append",
        dest="overlays",
        help="Overlay snapshot to merge onto the base; repeat to merge several",
    )
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
        args.output, snapshot_path=args.snapshot, diff_path=args.diff, history_path=args.history,
    )
    print(f"Built static site in {args.output}")


def _social_drafts(args: argparse.Namespace) -> None:
    from azure_region_monitor.blog import render_social_drafts, select_blog_posts

    history_path = args.history / "index.json" if args.history.is_dir() else args.history
    history_index = {}
    if history_path.exists():
        history_index = json.loads(history_path.read_text(encoding="utf-8"))
    print(
        render_social_drafts(
            select_blog_posts(history_index),
            args.site_url,
            limit=args.limit,
        )
    )


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
        narrative_client=_build_narrative_client(),
    )
    print(
        f"Updated history in {args.history_dir} with "
        f"{len(recent_changes.get('days', []))} recent change days"
    )


def _build_narrative_client():
    if os.environ.get("AI_SUMMARY_ENABLED", "1") == "0":
        return None

    azure_error: Exception | None = None
    try:
        from azure_region_monitor.social_client import AzureOpenAiTextClient

        return AzureOpenAiTextClient.from_env(
            max_output_tokens=int(os.environ.get("AI_SUMMARY_MAX_TOKENS", "900")),
            enable_microsoft_learn_mcp=True,
        )
    except (ImportError, ValueError) as error:
        azure_error = error

    token = os.environ.get("GITHUB_MODELS_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token or os.environ.get("AI_SUMMARY_ALLOW_GITHUB_FALLBACK", "0") != "1":
        return _UnavailableNarrativeClient(str(azure_error) if azure_error else "Azure OpenAI unavailable")
    try:
        from azure_region_monitor.probes.github_models import (
            DEFAULT_SUMMARY_MODELS,
            GitHubModelsClient,
            GitHubModelsNarrativeClient,
            LatencyClientError,
        )

        # AI_SUMMARY_MODEL may be a single model or a comma-separated preference list;
        # the client tries them in order. Default is the best-first gpt-5 family.
        models = os.environ.get("AI_SUMMARY_MODEL") or ",".join(DEFAULT_SUMMARY_MODELS)
        return GitHubModelsNarrativeClient(GitHubModelsClient.from_env(), models=models)
    except (ImportError, LatencyClientError, ValueError) as error:
        return _UnavailableNarrativeClient(str(error))


class _UnavailableNarrativeClient:
    """Preserve client-initialization failures in the published fallback metadata."""

    def __init__(self, reason: str) -> None:
        self._reason = reason

    def generate(self, *, system: str, user: str) -> str:
        raise RuntimeError(self._reason)


def _merge_snapshot(args: argparse.Namespace) -> None:
    if args.base_file is not None:
        base = load_snapshot(args.base_file)
    elif args.base_url:
        base = load_snapshot_from_text(_fetch_url_text(args.base_url))
    else:
        raise SystemExit("merge-snapshot requires --base-url or --base-file")

    overlay_paths = args.overlays or [Path("data/snapshots/latest.json")]
    merged = 0
    for overlay_path in overlay_paths:
        if not overlay_path.exists():
            print(f"Skipping missing overlay {overlay_path}")
            continue
        base = merge_snapshot_overlay(base, load_snapshot(overlay_path))
        merged += 1
    write_snapshot(args.output, base)
    print(f"Merged {merged} overlay(s) into {args.output}")


def _fetch_url_text(url: str, attempts: int = 4, timeout: int = 60) -> str:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers={"Accept-Encoding": "gzip"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read()
                if response.headers.get("Content-Encoding") == "gzip":
                    payload = gzip.decompress(payload)
                return payload.decode("utf-8")
        except Exception as error:  # noqa: BLE001 - retried below, re-raised if final
            last_error = error
            if attempt < attempts - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Failed to fetch {url} after {attempts} attempts: {last_error}")


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
    if probe_name == "ai-model-catalog-cli":
        return AiModelCatalogCliProbe(
            model_features=parse_ai_model_features(os.environ.get("AI_MODEL_FEATURES"))
        )
    if probe_name == "container-apps-provider-cli":
        return ContainerAppsProviderCliProbe(
            resource_features=parse_container_apps_resource_features(
                os.environ.get("CONTAINER_APPS_RESOURCE_FEATURES")
            )
        )
    if probe_name == "function-flex-cli":
        return FunctionsFlexConsumptionCliProbe(
            runtime_features=parse_function_runtime_features(
                os.environ.get("FUNCTION_RUNTIME_FEATURES")
            )
        )
    if probe_name == "vm-sku-cli":
        return VmSkuCliProbe(skus=parse_vm_skus(os.environ.get("AZURE_VM_SKUS")))
    if probe_name == "model-latency-cli":
        models_env = os.environ.get("MODEL_LATENCY_MODELS")
        auto_discover = (models_env or "").strip().lower() == "auto"
        return ModelLatencyProbe(
            models=parse_latency_models(None if auto_discover else models_env),
            samples=int(os.environ.get("MODEL_LATENCY_SAMPLES", "5")),
            rate_limit_retries=int(os.environ.get("MODEL_LATENCY_RATE_LIMIT_RETRIES", "5")),
            rate_limit_backoff_seconds=float(
                os.environ.get("MODEL_LATENCY_RATE_LIMIT_BACKOFF_SECONDS", "20")
            ),
            max_backoff_seconds=float(
                os.environ.get("MODEL_LATENCY_MAX_BACKOFF_SECONDS", "60")
            ),
            time_budget_seconds=float(
                os.environ.get("MODEL_LATENCY_BUDGET_SECONDS", "1500")
            ),
            auto_discover=auto_discover,
        )
    if probe_name == "ai-model-latency-cli":
        return AzureOpenAiLatencyProbe(
            targets=parse_ai_latency_targets(os.environ.get("AI_LATENCY_TARGETS")),
            samples=int(os.environ.get("AI_LATENCY_SAMPLES", "5")),
        )
    raise ValueError(f"Unsupported probe: {probe_name}")


if __name__ == "__main__":
    main()
