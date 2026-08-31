from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
MAX_DOCS_FILE_CHARS = 2_400
MAX_REWORK_REQUIREMENTS_CHARS = 4_000
DEFAULT_SNAPSHOT_URL = "https://azwatch.operator.lat/api/latest.json"
REWORK_ACTOR_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")
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


def _load_rework_context(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("The automated PR rework context is invalid.") from error
    if not isinstance(payload, dict):
        raise ValueError("The automated PR rework context is invalid.")
    pull_request = payload.get("pull_request")
    trigger = payload.get("trigger")
    requested_by = payload.get("requested_by")
    requirements = payload.get("requirements")
    if (
        type(pull_request) is not int
        or pull_request <= 0
        or trigger != "request-changes"
        or not isinstance(requested_by, str)
        or REWORK_ACTOR_PATTERN.fullmatch(requested_by) is None
        or not isinstance(requirements, str)
        or not requirements.strip()
        or len(requirements) > MAX_REWORK_REQUIREMENTS_CHARS
    ):
        raise ValueError("The automated PR rework context is invalid.")
    return {
        "pull_request": pull_request,
        "trigger": trigger,
        "requested_by": requested_by,
        "requirements": requirements.strip(),
    }


def _backlog_status(issues_path: Path, tasks: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        payload = json.loads(issues_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = []
    issues = payload if isinstance(payload, list) else []
    backlog = []
    paused = []
    eligible = []
    malformed = []
    issue_parser = _load_module("azure_backlog_status_issues", "run_azure_issue_agent.py")
    parsed_numbers = {
        issue["number"] for issue in issue_parser._load_issues(issues_path)
    }
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        labels = issue.get("labels")
        names = {
            str(label.get("name", "")).lower()
            for label in labels if isinstance(label, dict)
        } if isinstance(labels, list) else set()
        if "azure-backlog" not in names:
            continue
        number = issue.get("number")
        title = issue.get("title")
        if not isinstance(number, int) or not isinstance(title, str):
            continue
        item = {"number": number, "title": title}
        backlog.append(item)
        if "azure-paused" in names:
            paused.append(item)
        else:
            eligible.append(item)
            if number not in parsed_numbers:
                malformed.append(item)
    return {
        "backlog_count": len(backlog),
        "paused_count": len(paused),
        "eligible_count": len(eligible),
        "malformed_issue_count": len(malformed),
        "selected_count": len(tasks),
        "paused_issues": paused,
        "eligible_issues": eligible,
        "malformed_issues": malformed,
        "selected_categories": [str(task.get("category", "")) for task in tasks],
    }


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
    rework_context: dict[str, Any] | None = None,
    selection_notes: dict[str, list[dict[str, Any]]] | None = None,
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
                if selection_notes is not None:
                    selection_notes.setdefault("deferred_no_unknown_evidence_issues", []).append(
                        {"number": issue["number"], "title": issue["title"]}
                    )
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
            0 if target_issue is not None else index,
            github_context_client,
            scope_override,
            additional_evidence,
            issue if target_issue is not None else None,
        )
        if not task["category"]:
            continue
        task["kind"] = "issue"
        if unknown_context and "azure-unknowns" in issue["labels"]:
            task["summary"] = (
                "Recurring current unknown-status investigation for "
                f"{unknown_context['category']}."
            )
        if rework_context is not None:
            task["rework"] = dict(rework_context)
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
        "summary": "Documentation alignment runs as a separate scheduled maintenance session.",
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
    include_docs: bool = False,
    rework_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if rework_context is not None and target_issue is None:
        raise ValueError("Automated PR rework requires one targeted source issue.")
    issue_args = (
        issues_path,
        _max_issue_items(max_issues),
        repository,
        snapshot_url,
        target_issue,
    )
    selection_notes: dict[str, list[dict[str, Any]]] = {}
    tasks = (
        _build_issue_tasks(
            *issue_args,
            rework_context=rework_context,
            selection_notes=selection_notes,
        )
        if rework_context is not None
        else _build_issue_tasks(*issue_args, selection_notes=selection_notes)
    )
    if include_docs:
        tasks.append(_build_docs_task())
    status = _backlog_status(issues_path, tasks)
    deferred = selection_notes.get("deferred_no_unknown_evidence_issues", [])
    status["deferred_no_unknown_evidence_count"] = len(deferred)
    status["deferred_no_unknown_evidence_issues"] = deferred
    return {"tasks": tasks, "status": status}


def render_cycle_markdown(cycle: dict[str, Any]) -> str:
    lines = ["## Azure BYOK coding backlog", ""]
    status = cycle.get("status")
    if isinstance(status, dict):
        lines.extend(
            [
                f"- Open backlog issues: {int(status.get('backlog_count', 0))}",
                f"- Eligible issues: {int(status.get('eligible_count', 0))}",
                f"- Paused issues: {int(status.get('paused_count', 0))}",
                f"- Selected sessions: {int(status.get('selected_count', 0))}",
                "",
            ]
        )
    if not cycle["tasks"]:
        malformed = int(status.get("malformed_issue_count", 0)) if isinstance(status, dict) else 0
        deferred = int(status.get("deferred_no_unknown_evidence_count", 0)) if isinstance(status, dict) else 0
        reason = (
            f"{malformed} queue-eligible issue(s) are missing the required `### Objective` "
            "template field."
            if malformed
            else f"{deferred} queue-eligible issue(s) require current `unknown` evidence, but the "
            "live snapshot has no unknown group to investigate."
            if deferred
            else "No runnable issue was selected. Review `azure-paused` labels or add a new "
            "one-off `azure-backlog` issue."
        )
        lines.extend(
            [
                "### No agent session started",
                "",
                reason,
                "",
            ]
        )
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
                "Coding-agent edits are validated locally before any branch or draft PR is created.",
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
    parser.add_argument("--rework-context", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    rework_context = _load_rework_context(args.rework_context)

    cycle = build_cycle(
        args.issues,
        args.max_issues,
        args.repository,
        args.snapshot_url,
        args.target_issue,
        False,
        rework_context,
    )
    args.output.write_text(json.dumps(cycle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(render_cycle_markdown(cycle))


if __name__ == "__main__":
    main()
