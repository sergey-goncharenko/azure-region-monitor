from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
MAX_DOCS_FILE_CHARS = 2_400
DEFAULT_SNAPSHOT_URL = "https://azwatch.operator.lat/api/latest.json"
UNKNOWN_CATEGORY_SOURCE_HINTS = {
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


def _load_module(name: str, script_name: str):
    path = REPO_ROOT / "scripts" / script_name
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {script_name}.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _max_issue_items(value: object) -> int:
    try:
        return max(0, min(3, int(value)))
    except (TypeError, ValueError):
        return 3


def _current_unknown_context(snapshot_url: str) -> dict[str, Any]:
    sessions = _load_module("azure_backlog_sessions", "start_copilot_agent_sessions.py")
    snapshot_result = sessions.load_snapshot(snapshot_url, None)
    groups = (
        sessions.rank_unknown_groups(snapshot_result.snapshot)
        if snapshot_result.snapshot
        else []
    )
    if not groups:
        return {
            "category": "",
            "source_paths": [],
            "tests": [],
            "evidence": {
                "snapshot_source": snapshot_result.source,
                "snapshot_warning": snapshot_result.warning,
                "unknown_groups": [],
            },
        }

    top = groups[0]
    source_paths = [
        path
        for path in (*UNKNOWN_CATEGORY_SOURCE_HINTS.get(top.category, ()), *top.workflow_hints)
        if (REPO_ROOT / path).is_file()
    ]
    tests = [path for path in top.test_hints if (REPO_ROOT / path).is_file()]
    evidence = {
        "snapshot_source": snapshot_result.source,
        "snapshot_warning": snapshot_result.warning,
        "selected_category": top.category,
        "unknown_count": top.unknown_count,
        "regions": list(top.regions),
        "services": list(top.services),
        "features": list(top.features),
        "error_codes": list(top.error_codes),
        "messages": list(top.messages),
        "unknown_groups": [
            {"category": group.category, "unknown_count": group.unknown_count}
            for group in groups[:5]
        ],
    }
    return {
        "category": top.category,
        "source_paths": source_paths,
        "tests": tests,
        "evidence": evidence,
    }


def _build_issue_tasks(
    issues_path: Path,
    limit: int,
    repository: str,
    snapshot_url: str = DEFAULT_SNAPSHOT_URL,
    target_issue: int | None = None,
) -> list[dict[str, Any]]:
    issues = _load_module("azure_backlog_issues", "run_azure_issue_agent.py")
    if repository and not os.environ.get("GH_TOKEN"):
        raise RuntimeError("GH_TOKEN is required to fetch GitHub issue comments and sub-issues.")
    github_context_client = (
        issues.GitHubIssueContextClient.from_env(repository) if repository else None
    )
    tasks = []
    unknown_context: dict[str, Any] | None = None
    eligible_issues = issues._load_issues(issues_path)
    if target_issue is not None:
        eligible_issues = [
            issue for issue in eligible_issues if issue["number"] == target_issue
        ]
    for index, issue in enumerate(eligible_issues):
        scope_override = None
        additional_evidence = None
        if "azure-unknowns" in issue["labels"]:
            unknown_context = unknown_context or _current_unknown_context(snapshot_url)
            if not unknown_context["category"]:
                continue
            scope_override = (
                unknown_context["source_paths"],
                unknown_context["tests"],
            )
            additional_evidence = {
                "current_unknown_status": unknown_context["evidence"]
            }
        task = issues.build_issue_context(
            issues_path,
            index,
            github_context_client,
            scope_override,
            additional_evidence,
        )
        if not task["category"]:
            continue
        task["kind"] = "issue"
        if unknown_context and "azure-unknowns" in issue["labels"]:
            task["summary"] = (
                "Recurring current unknown-status investigation for "
                f"{unknown_context['category']}."
            )
        tasks.append(task)
        if len(tasks) >= limit:
            break
    return tasks


def _read_excerpt(path: str) -> str:
    target = REPO_ROOT / path
    if not target.is_file():
        return f"[missing: {path}]"
    text = target.read_text(encoding="utf-8", errors="replace")
    if len(text) <= MAX_DOCS_FILE_CHARS:
        return text
    return text[:MAX_DOCS_FILE_CHARS].rsplit("\n", 1)[0] + "\n[truncated]"


def _git_history() -> str:
    completed = subprocess.run(
        ["git", "log", "-8", "--oneline"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() or "[git history unavailable]"


def _build_docs_task() -> dict[str, Any]:
    allowed_candidates = (
        "README.md",
        ".github/copilot-instructions.md",
        "docs/agentic-sessions.md",
    )
    evidence_candidates = (
        *allowed_candidates,
        ".github/workflows/daily-scan.yml",
        ".github/workflows/scheduled-azure-backlog.yml",
        ".github/workflows/scheduled-copilot-agents.yml",
    )
    allowed_paths = [path for path in allowed_candidates if (REPO_ROOT / path).is_file()]
    evidence_paths = [path for path in evidence_candidates if (REPO_ROOT / path).is_file()]
    tests = (
        ["tests/test_static_site.py"]
        if (REPO_ROOT / "tests/test_static_site.py").is_file()
        else []
    )
    return {
        "kind": "docs",
        "category": "documentation-alignment",
        "summary": "Documentation alignment runs after all selected GitHub backlog issues.",
        "allowed_paths": allowed_paths,
        "tests": tests,
        "evidence": {
            "recent_git_history": _git_history(),
            "files": {path: _read_excerpt(path) for path in evidence_paths},
        },
    }


def build_cycle(
    issues_path: Path,
    max_issues: object,
    repository: str = "",
    snapshot_url: str = DEFAULT_SNAPSHOT_URL,
    target_issue: int | None = None,
    include_docs: bool = True,
) -> dict[str, list[dict[str, Any]]]:
    tasks = _build_issue_tasks(
        issues_path,
        _max_issue_items(max_issues),
        repository,
        snapshot_url,
        target_issue,
    )
    if include_docs:
        tasks.append(_build_docs_task())
    return {"tasks": tasks}


def render_cycle_markdown(cycle: dict[str, Any]) -> str:
    lines = ["## Azure BYOK coding backlog", ""]
    for task in cycle["tasks"]:
        prefix = {
            "issue": "GitHub backlog issue",
            "docs": "Documentation alignment",
        }[task["kind"]]
        lines.extend(
            [
                f"### {prefix}: `{task['category']}`",
                "",
                task["summary"],
                "",
                "Copilot CLI edits are validated locally before any branch or draft PR is created.",
                "",
            ]
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build bounded Azure BYOK coding tasks.")
    parser.add_argument("--issues", type=Path, required=True)
    parser.add_argument("--max-issues", type=int, default=3)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--snapshot-url", default=DEFAULT_SNAPSHOT_URL)
    parser.add_argument("--target-issue", type=int)
    parser.add_argument("--skip-docs", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    cycle = build_cycle(
        args.issues,
        args.max_issues,
        args.repository,
        args.snapshot_url,
        args.target_issue,
        not args.skip_docs,
    )
    args.output.write_text(json.dumps(cycle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(render_cycle_markdown(cycle))


if __name__ == "__main__":
    main()
