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
        return max(0, min(2, int(value)))
    except (TypeError, ValueError):
        return 2


def _build_issue_tasks(issues_path: Path, limit: int, repository: str) -> list[dict[str, Any]]:
    issues = _load_module("azure_backlog_issues", "run_azure_issue_agent.py")
    if repository and not os.environ.get("GH_TOKEN"):
        raise RuntimeError("GH_TOKEN is required to fetch GitHub issue comments and sub-issues.")
    github_context_client = (
        issues.GitHubIssueContextClient.from_env(repository) if repository else None
    )
    tasks = []
    for index in range(limit):
        task = issues.build_issue_context(issues_path, index, github_context_client)
        if not task["category"]:
            continue
        task["kind"] = "issue"
        tasks.append(task)
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
) -> dict[str, list[dict[str, Any]]]:
    tasks = _build_issue_tasks(issues_path, _max_issue_items(max_issues), repository)
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
    parser.add_argument("--max-issues", type=int, default=2)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    cycle = build_cycle(args.issues, args.max_issues, args.repository)
    args.output.write_text(json.dumps(cycle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(render_cycle_markdown(cycle))


if __name__ == "__main__":
    main()
