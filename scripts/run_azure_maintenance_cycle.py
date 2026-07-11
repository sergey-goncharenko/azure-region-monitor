from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_LABEL = "azure-agent-report"
SECURITY_LABEL = "azure-security-analysis"
HYGIENE_LABEL = "azure-repository-hygiene"
MAX_REMOTE_BRANCHES = 100
MAX_PULL_REQUESTS = 100
STALE_UNASSOCIATED_DAYS = 30


def _load_backlog_cycle():
    path = REPO_ROOT / "scripts" / "run_azure_backlog_cycle.py"
    spec = importlib.util.spec_from_file_location("azure_maintenance_backlog_cycle", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load run_azure_backlog_cycle.py.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _json_command(*args: str) -> Any:
    completed = _run(*args)
    if completed.returncode != 0:
        detail = completed.stderr.strip()[:500]
        raise RuntimeError(f"Evidence command failed: {' '.join(args[:3])}. {detail}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Evidence command returned invalid JSON: {' '.join(args[:3])}.") from error


def _flatten_pages(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    flattened: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            flattened.append(item)
        elif isinstance(item, list):
            flattened.extend(entry for entry in item if isinstance(entry, dict))
    return flattened


def _login(value: object) -> str:
    if isinstance(value, dict) and isinstance(value.get("login"), str):
        return value["login"]
    return ""


def _remote_branches(repository: str) -> list[dict[str, Any]]:
    pages = _json_command(
        "gh",
        "api",
        "--paginate",
        "--slurp",
        f"repos/{repository}/branches?per_page={MAX_REMOTE_BRANCHES}",
    )
    branches = []
    for branch in _flatten_pages(pages)[:MAX_REMOTE_BRANCHES]:
        name = branch.get("name")
        commit = branch.get("commit")
        sha = commit.get("sha") if isinstance(commit, dict) else None
        if not isinstance(name, str) or not isinstance(sha, str):
            continue
        committed_at = ""
        commit_payload = _json_command("gh", "api", f"repos/{repository}/commits/{sha}")
        if isinstance(commit_payload, dict):
            detail = commit_payload.get("commit")
            committer = detail.get("committer") if isinstance(detail, dict) else None
            date = committer.get("date") if isinstance(committer, dict) else None
            committed_at = date if isinstance(date, str) else ""
        branches.append(
            {
                "name": name,
                "sha": sha,
                "protected": bool(branch.get("protected")),
                "committed_at": committed_at,
            }
        )
    return branches


def _pull_requests(repository: str) -> list[dict[str, Any]]:
    payload = _json_command(
        "gh",
        "pr",
        "list",
        "--repo",
        repository,
        "--state",
        "all",
        "--limit",
        str(MAX_PULL_REQUESTS),
        "--json",
        (
            "number,title,state,isDraft,headRefName,baseRefName,author,createdAt,"
            "updatedAt,closedAt,mergedAt,url"
        ),
    )
    if not isinstance(payload, list):
        return []
    values = []
    for pull in payload:
        if not isinstance(pull, dict) or not isinstance(pull.get("number"), int):
            continue
        values.append(
            {
                "number": pull["number"],
                "title": str(pull.get("title", ""))[:300],
                "state": str(pull.get("state", "")),
                "draft": bool(pull.get("isDraft")),
                "head": str(pull.get("headRefName", "")),
                "base": str(pull.get("baseRefName", "")),
                "author": _login(pull.get("author")),
                "created_at": str(pull.get("createdAt", "")),
                "updated_at": str(pull.get("updatedAt", "")),
                "closed_at": pull.get("closedAt"),
                "merged_at": pull.get("mergedAt"),
                "url": str(pull.get("url", "")),
            }
        )
    return values


def _worktrees() -> list[dict[str, Any]]:
    completed = _run("git", "worktree", "list", "--porcelain")
    if completed.returncode != 0:
        return [{"warning": "git worktree list failed on the workflow runner."}]
    values = []
    primary = str(REPO_ROOT.resolve()).replace("\\", "/").lower()
    for block in completed.stdout.strip().split("\n\n"):
        if not block.strip():
            continue
        item: dict[str, Any] = {}
        for line in block.splitlines():
            key, _, value = line.partition(" ")
            if key in {"worktree", "HEAD", "branch", "prunable", "locked"}:
                item[key.lower()] = value
        path = str(item.get("worktree", "")).replace("\\", "/")
        branch = str(item.get("branch", ""))
        if branch.startswith("refs/heads/"):
            branch = branch.removeprefix("refs/heads/")
        item["branch"] = branch
        item["primary"] = path.lower() == primary
        values.append(item)
    return values


def _latest_pull_by_branch(pulls: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for pull in pulls:
        branch = pull.get("head")
        if not isinstance(branch, str) or not branch:
            continue
        current = latest.get(branch)
        if current is None or str(pull.get("updated_at", "")) > str(
            current.get("updated_at", "")
        ):
            latest[branch] = pull
    return latest


def _branch_candidates(
    branches: list[dict[str, Any]],
    pulls: list[dict[str, Any]],
    default_branch: str,
    now: datetime,
) -> list[dict[str, Any]]:
    latest = _latest_pull_by_branch(pulls)
    open_heads = {str(pull.get("head")) for pull in pulls if pull.get("state") == "OPEN"}
    candidates = []
    for branch in branches:
        name = branch["name"]
        if name == default_branch or branch.get("protected") or name in open_heads:
            continue
        pull = latest.get(name)
        classification = ""
        confidence = ""
        reason = ""
        if pull and pull.get("state") == "MERGED":
            classification = "merged-pr-branch"
            confidence = "high"
            reason = f"Latest associated PR #{pull['number']} is merged."
        elif pull and pull.get("state") == "CLOSED":
            classification = "closed-unmerged-pr-branch"
            confidence = "medium"
            reason = f"Latest associated PR #{pull['number']} closed without merge."
        elif not pull:
            committed_at = str(branch.get("committed_at", ""))
            try:
                committed = datetime.fromisoformat(committed_at.replace("Z", "+00:00"))
            except ValueError:
                committed = now
            age_days = max(0, (now - committed.astimezone(timezone.utc)).days)
            if age_days >= STALE_UNASSOCIATED_DAYS:
                classification = "stale-branch-without-recent-pr"
                confidence = "low"
                reason = f"No recent PR was found and the tip is {age_days} days old."
        if classification:
            candidates.append(
                {
                    "branch": name,
                    "classification": classification,
                    "confidence": confidence,
                    "reason": reason,
                    "committed_at": branch.get("committed_at", ""),
                    "associated_pr": pull,
                }
            )
    return candidates


def _worktree_candidates(
    worktrees: list[dict[str, Any]], pulls: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    latest = _latest_pull_by_branch(pulls)
    candidates = []
    for worktree in worktrees:
        if worktree.get("primary") or worktree.get("warning"):
            continue
        branch = str(worktree.get("branch", ""))
        pull = latest.get(branch)
        if worktree.get("prunable") or (pull and pull.get("state") in {"MERGED", "CLOSED"}):
            candidates.append(
                {
                    "path": worktree.get("worktree", ""),
                    "branch": branch,
                    "prunable": worktree.get("prunable", ""),
                    "associated_pr": pull,
                    "recommendation_only": True,
                }
            )
    return candidates


def _collect_hygiene_evidence(
    repository: str, default_branch: str, now: datetime
) -> dict[str, Any]:
    branches = _remote_branches(repository)
    pulls = _pull_requests(repository)
    worktrees = _worktrees()
    return {
        "generated_at": now.isoformat(),
        "default_branch": default_branch,
        "remote_branches": branches,
        "recent_pull_requests": pulls,
        "observed_runner_worktrees": worktrees,
        "branch_deletion_candidates": _branch_candidates(
            branches, pulls, default_branch, now
        ),
        "worktree_removal_candidates": _worktree_candidates(worktrees, pulls),
        "worktree_visibility_limit": (
            "A GitHub-hosted runner can inspect only its ephemeral checkout. It cannot see "
            "developer-machine worktrees; run `git worktree list --porcelain` locally for those."
        ),
        "safety": (
            "These are recommendations only. No branch, reference, or worktree is deleted by "
            "this workflow."
        ),
    }


def _build_security_task(backlog_cycle: Any) -> dict[str, Any]:
    tracked = _run("git", "ls-files").stdout.splitlines()
    read_paths = [
        path
        for path in (
            "src/",
            "scripts/",
            ".github/workflows/",
            "infra/",
            "pyproject.toml",
            "public/staticwebapp.config.json",
        )
        if (REPO_ROOT / path).exists()
    ]
    return {
        "kind": "report",
        "category": "security-analysis",
        "summary": "Read-only static security analysis of repository code and automation.",
        "report_title": "[agent-report] Security analysis",
        "report_label": SECURITY_LABEL,
        "read_paths": read_paths,
        "evidence": {
            "objective": (
                "Identify concrete security weaknesses with repository file/line evidence and "
                "prioritized remediation. Do not edit code or claim a penetration test."
            ),
            "tracked_file_count": len(tracked),
            "dependency_files": [
                path
                for path in tracked
                if Path(path).name
                in {
                    "pyproject.toml",
                    "requirements.txt",
                    "package.json",
                    "package-lock.json",
                    "Dockerfile",
                }
            ],
            "workflow_files": [
                path for path in tracked if path.startswith(".github/workflows/")
            ],
            "recent_git_history": backlog_cycle._git_history(),
            "analysis_limit": (
                "Static repository review only; no external vulnerability database, live Azure "
                "resource, secret value, or production endpoint is inspected."
            ),
        },
    }


def _build_hygiene_task(
    repository: str, default_branch: str, now: datetime
) -> dict[str, Any]:
    return {
        "kind": "report",
        "category": "repository-hygiene",
        "summary": "Read-only branch and worktree hygiene recommendations.",
        "report_title": "[agent-report] Repository hygiene recommendations",
        "report_label": HYGIENE_LABEL,
        "read_paths": [],
        "evidence": {
            "objective": (
                "Review branch and worktree evidence, recommend safe cleanup candidates, explain "
                "uncertainty, and provide commands for a human to run. Never perform deletion."
            ),
            **_collect_hygiene_evidence(repository, default_branch, now),
        },
    }


def build_cycle(
    repository: str,
    *,
    default_branch: str = "main",
    now: datetime | None = None,
) -> dict[str, list[dict[str, Any]]]:
    if not repository or not os.environ.get("GH_TOKEN"):
        raise RuntimeError("GITHUB_REPOSITORY and GH_TOKEN are required for maintenance evidence.")
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    backlog_cycle = _load_backlog_cycle()
    return {
        "tasks": [
            backlog_cycle._build_docs_task(),
            _build_security_task(backlog_cycle),
            _build_hygiene_task(repository, default_branch, current_time),
        ]
    }


def render_cycle_markdown(cycle: dict[str, Any]) -> str:
    lines = ["## Azure BYOK maintenance sessions", ""]
    for index, task in enumerate(cycle["tasks"], start=1):
        mode = "bounded draft PR" if task["kind"] == "docs" else "report only"
        lines.extend(
            [
                f"### Session {index}: `{task['category']}`",
                "",
                f"- Mode: {mode}",
                f"- Purpose: {task['summary']}",
                "",
            ]
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build three Azure BYOK maintenance tasks.")
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--default-branch", default="main")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    cycle = build_cycle(args.repository, default_branch=args.default_branch)
    args.output.write_text(json.dumps(cycle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(render_cycle_markdown(cycle))


if __name__ == "__main__":
    main()
