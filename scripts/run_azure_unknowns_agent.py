from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

from azure_region_monitor.social_client import AzureOpenAiTextClient

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT_URL = "https://azwatch.operator.lat/api/latest.json"
MAX_FILE_CHARS = 3_600
MAX_EVIDENCE_FILES = 5

CATEGORY_SOURCE_HINTS = {
    "aksExtensions": (
        "src/azure_region_monitor/probes/aks_extension_catalog.py",
        "src/azure_region_monitor/probes/aks_extension.py",
    ),
    "aksKubernetesVersions": ("src/azure_region_monitor/probes/aks_versions.py",),
    "functions": ("src/azure_region_monitor/probes/functions.py",),
    "aiModels": ("src/azure_region_monitor/probes/ai_models.py",),
    "modelLatency": (
        "src/azure_region_monitor/probes/model_latency.py",
        "src/azure_region_monitor/probes/github_models.py",
    ),
    "aiLatency": (
        "src/azure_region_monitor/probes/ai_model_latency.py",
        "src/azure_region_monitor/probes/azure_openai.py",
    ),
    "containerApps": ("src/azure_region_monitor/probes/container_apps.py",),
    "vmSkus": ("src/azure_region_monitor/probes/vm_skus.py",),
}

_SYSTEM_PROMPT = """You are a cautious Azure platform engineer proposing a small, evidence-backed fix for one unknown-status probe category.

Use only the supplied bounded evidence. Preserve the monitor's status semantics: unknown means missing trustworthy evidence; unavailable means a successful read-only catalog/list/provider-metadata response where the feature was absent. Never convert unknown to unavailable without evidence. Do not add lifecycle create/delete probes, modify generated snapshots, weaken tests, or claim quota/capacity/SLA conclusions.

Return only this JSON object:
{
  "decision": "patch" or "no_change",
  "summary": "concise factual conclusion",
  "pr_title": "fix: ...",
  "pr_body": "why the patch is justified and tests to run",
  "patch": "unified diff or empty string"
}

Set decision=no_change unless the snapshot error and bounded source/test/workflow evidence prove a small repository fix. Before proposing a patch, verify that the alleged remedy is not already implemented in the supplied excerpts; if it is, choose no_change and explain why. For a patch, include only standard unified diff text for the supplied allowed paths, with exact unchanged context taken from the excerpts. Do not include prose outside the JSON object."""


def _load_sessions_module():
    path = REPO_ROOT / "scripts" / "start_copilot_agent_sessions.py"
    spec = importlib.util.spec_from_file_location("azure_unknowns_sessions", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load unknowns session helper.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _read_excerpt(path: str) -> str:
    target = REPO_ROOT / path
    if not target.exists():
        return f"[missing: {path}]"
    text = target.read_text(encoding="utf-8", errors="replace")
    if len(text) <= MAX_FILE_CHARS:
        return text
    half = MAX_FILE_CHARS // 2
    head = text[:half].rsplit("\n", 1)[0]
    tail = text[-half:].split("\n", 1)[-1]
    return head + "\n[...middle truncated...]\n" + tail


def build_proposal_context(snapshot_url: str) -> dict[str, Any]:
    sessions = _load_sessions_module()
    snapshot_result = sessions.load_snapshot(snapshot_url, None)
    groups = sessions.rank_unknown_groups(snapshot_result.snapshot) if snapshot_result.snapshot else []
    if not groups:
        summary = "No current unknown-status candidate was found in the published snapshot."
        if snapshot_result.warning:
            summary += f" Snapshot warning: {snapshot_result.warning}"
        return {
            "category": "",
            "summary": summary,
            "allowed_paths": [],
            "tests": [],
            "evidence": {},
        }

    group = groups[0]
    candidates = [
        *CATEGORY_SOURCE_HINTS.get(group.category, ()),
        *group.test_hints,
        *group.workflow_hints,
    ]
    allowed_paths = []
    for path in candidates:
        if path not in allowed_paths and (REPO_ROOT / path).exists():
            allowed_paths.append(path)
        if len(allowed_paths) >= MAX_EVIDENCE_FILES:
            break

    evidence = {
        "snapshot_source": snapshot_result.source,
        "snapshot_warning": snapshot_result.warning,
        "category": group.category,
        "unknown_count": group.unknown_count,
        "regions": list(group.regions),
        "services": list(group.services),
        "features": list(group.features),
        "error_codes": list(group.error_codes),
        "messages": list(group.messages),
        "allowed_paths": allowed_paths,
        "tests": list(group.test_hints),
        "workflows": list(group.workflow_hints),
        "file_excerpts": {path: _read_excerpt(path) for path in allowed_paths},
    }
    return {
        "category": group.category,
        "summary": "Top unknown-status candidate selected from the current published snapshot.",
        "allowed_paths": allowed_paths,
        "tests": list(group.test_hints),
        "evidence": evidence,
    }


def _patch_paths(patch: str) -> set[str]:
    paths: set[str] = set()
    for line in patch.splitlines():
        if line.startswith("+++ b/") or line.startswith("--- a/"):
            path = line[6:].strip()
            if path != "/dev/null":
                paths.add(path)
    return paths


def _parse_proposal(raw: str, context: dict[str, Any]) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return _no_change(context, "Azure unknowns reviewer returned non-JSON output.")
    if not isinstance(payload, dict):
        return _no_change(context, "Azure unknowns reviewer returned an invalid response shape.")

    decision = str(payload.get("decision", "no_change"))
    summary = str(payload.get("summary", "No actionable proposal was returned.")).strip()
    if decision != "patch":
        return _no_change(context, summary)

    patch = payload.get("patch")
    title = payload.get("pr_title")
    body = payload.get("pr_body")
    if not all(isinstance(value, str) and value.strip() for value in (patch, title, body)):
        return _no_change(context, "Azure unknowns reviewer proposed an incomplete patch response.")
    if len(patch) > 24_000:
        return _no_change(context, "Azure unknowns reviewer proposed a patch above the safe size limit.")
    paths = _patch_paths(patch)
    allowed_paths = set(context["allowed_paths"])
    if not paths or not paths.issubset(allowed_paths):
        return _no_change(context, "Azure unknowns reviewer proposed changes outside the allowed paths.")

    return {
        "category": context["category"],
        "decision": "patch",
        "summary": summary,
        "pr_title": title.strip()[:120],
        "pr_body": body.strip()[:4_000],
        "patch": patch,
        "allowed_paths": context["allowed_paths"],
        "tests": context["tests"],
    }


def _no_change(context: dict[str, Any], summary: str) -> dict[str, Any]:
    return {
        "category": context["category"],
        "decision": "no_change",
        "summary": summary,
        "pr_title": "",
        "pr_body": "",
        "patch": "",
        "allowed_paths": context["allowed_paths"],
        "tests": context["tests"],
    }


def render_proposal_markdown(proposal: dict[str, Any]) -> str:
    lines = ["## Azure unknowns coding review", "", proposal["summary"], ""]
    if proposal["decision"] != "patch":
        lines.append("No safe patch proposal was produced; no branch or PR will be created.")
        return "\n".join(lines) + "\n"
    lines.extend(
        [
            f"- Category: `{proposal['category']}`",
            f"- Proposed PR: `{proposal['pr_title']}`",
            f"- Allowed paths: {', '.join(f'`{path}`' for path in proposal['allowed_paths'])}",
            f"- Focused tests: {', '.join(f'`{path}`' for path in proposal['tests']) or 'none'}",
            "",
            "Patch output is validated locally before any branch or draft PR is created.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a bounded Azure unknowns patch proposal.")
    parser.add_argument("--snapshot-url", default=DEFAULT_SNAPSHOT_URL)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    context = build_proposal_context(args.snapshot_url)
    if not context["category"]:
        proposal = _no_change(context, context["summary"])
    else:
        client = AzureOpenAiTextClient.from_env(max_output_tokens=1_600)
        raw = client.generate(
            system=_SYSTEM_PROMPT,
            user="Bounded unknown-status evidence:\n" + json.dumps(
                context["evidence"], ensure_ascii=False, sort_keys=True
            ),
        )
        proposal = _parse_proposal(raw, context)

    args.output.write_text(json.dumps(proposal, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(render_proposal_markdown(proposal))


if __name__ == "__main__":
    main()
