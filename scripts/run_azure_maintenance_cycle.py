from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
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
MAX_SECURITY_SNIPPETS = 240
MAX_SECURITY_SNIPPETS_PER_FILE = 24
_SECURITY_SURFACE = (
    "permission",
    "secret",
    "token",
    "credential",
    "password",
    "subprocess",
    "shell=true",
    "os.system",
    "eval(",
    "exec(",
    "urllib",
    "request(",
    "yaml.load",
    "json.loads",
    "repository_dispatch",
    "pull_request_target",
    "workflow_run",
    "persist-credentials",
    "uses:",
    "run:",
)


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


def _source_api(repository: str, path: str) -> Any:
    token = os.environ.get("SOURCE_GITHUB_TOKEN", "").strip()
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "azure-region-monitor-private-analysis",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/{path.lstrip('/')}",
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Source GitHub API request failed: HTTP {error.code}.") from error
    except (urllib.error.URLError, OSError) as error:
        raise RuntimeError(f"Source GitHub API request failed: {error}.") from error
    except json.JSONDecodeError as error:
        raise RuntimeError("Source GitHub API returned invalid JSON.") from error


def _login(value: object) -> str:
    if isinstance(value, dict) and isinstance(value.get("login"), str):
        return value["login"]
    return ""


def _remote_branches(repository: str) -> list[dict[str, Any]]:
    payload = _source_api(repository, f"branches?per_page={MAX_REMOTE_BRANCHES}")
    branches = []
    if not isinstance(payload, list):
        return branches
    for branch in payload[:MAX_REMOTE_BRANCHES]:
        if not isinstance(branch, dict):
            continue
        name = branch.get("name")
        commit = branch.get("commit")
        sha = commit.get("sha") if isinstance(commit, dict) else None
        if not isinstance(name, str) or not isinstance(sha, str):
            continue
        committed_at = ""
        commit_payload = _source_api(repository, f"commits/{sha}")
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
    payload = _source_api(
        repository,
        f"pulls?state=all&sort=updated&direction=desc&per_page={MAX_PULL_REQUESTS}",
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
                "state": "MERGED"
                if pull.get("merged_at")
                else str(pull.get("state", "")).upper(),
                "draft": bool(pull.get("draft")),
                "head": str((pull.get("head") or {}).get("ref", "")),
                "base": str((pull.get("base") or {}).get("ref", "")),
                "author": _login(pull.get("user")),
                "created_at": str(pull.get("created_at", "")),
                "updated_at": str(pull.get("updated_at", "")),
                "closed_at": pull.get("closed_at"),
                "merged_at": pull.get("merged_at"),
                "url": str(pull.get("html_url", "")),
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
        recommended_action = ""
        if pull and pull.get("state") == "MERGED":
            classification = "merged-pr-branch"
            confidence = "high"
            reason = f"Latest associated PR #{pull['number']} is merged."
            recommended_action = (
                "Recommend deleting the remote branch after a final human check that no open "
                "PR or protected-branch policy depends on it."
            )
        elif pull and pull.get("state") == "CLOSED":
            classification = "closed-unmerged-pr-branch"
            confidence = "medium"
            reason = f"Latest associated PR #{pull['number']} closed without merge."
            recommended_action = (
                "Preserve by default; ask the owner to confirm the unmerged work is abandoned "
                "or backed up before deletion."
            )
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
                recommended_action = (
                    "Investigate ownership and unique commits; do not delete solely because of age."
                )
        if classification:
            candidates.append(
                {
                    "branch": name,
                    "classification": classification,
                    "confidence": confidence,
                    "reason": reason,
                    "recommended_action": recommended_action,
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


def _security_surface_evidence(tracked: list[str]) -> list[dict[str, Any]]:
    snippets = []
    allowed_suffixes = {".py", ".yml", ".yaml", ".json", ".toml", ".bicep"}
    allowed_roots = ("src/", "scripts/", ".github/workflows/", "infra/", "public/")
    for path in tracked:
        if Path(path).suffix.lower() not in allowed_suffixes and path != "Dockerfile":
            continue
        if not path.startswith(allowed_roots) and path not in {"pyproject.toml", "Dockerfile"}:
            continue
        target = REPO_ROOT / path
        if not target.is_file():
            continue
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        file_count = 0
        for index, line in enumerate(lines):
            lowered = line.lower()
            if not any(pattern in lowered for pattern in _SECURITY_SURFACE):
                continue
            start = max(0, index - 1)
            end = min(len(lines), index + 2)
            snippets.append(
                {
                    "path": path,
                    "start_line": start + 1,
                    "lines": lines[start:end],
                }
            )
            file_count += 1
            if file_count >= MAX_SECURITY_SNIPPETS_PER_FILE or len(snippets) >= MAX_SECURITY_SNIPPETS:
                break
        if len(snippets) >= MAX_SECURITY_SNIPPETS:
            break
    return snippets


def _build_security_task(backlog_cycle: Any) -> dict[str, Any]:
    tracked = _run("git", "ls-files").stdout.splitlines()
    return {
        "kind": "report",
        "category": "security-analysis",
        "summary": "Read-only static security analysis of repository code and automation.",
        "report_title": "[agent-report] Security analysis",
        "report_label": SECURITY_LABEL,
        "read_paths": [],
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
            "line_numbered_security_surfaces": _security_surface_evidence(tracked),
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
    session_set: str = "all",
) -> dict[str, list[dict[str, Any]]]:
    if not re.fullmatch(r"[^/\s]+/[^/\s]+", repository):
        raise RuntimeError("The source repository must use the owner/name format.")
    if session_set not in {"all", "docs", "reports"}:
        raise RuntimeError("Unsupported maintenance session set.")
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    backlog_cycle = _load_backlog_cycle()
    tasks = []
    if session_set in {"all", "docs"}:
        tasks.append(backlog_cycle._build_docs_task())
    if session_set in {"all", "reports"}:
        tasks.extend(
            [
                _build_security_task(backlog_cycle),
                _build_hygiene_task(repository, default_branch, current_time),
            ]
        )
    return {"tasks": tasks}


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
    parser.add_argument("--session-set", choices=("all", "docs", "reports"), default="all")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    cycle = build_cycle(
        args.repository,
        default_branch=args.default_branch,
        session_set=args.session_set,
    )
    args.output.write_text(json.dumps(cycle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(render_cycle_markdown(cycle))


if __name__ == "__main__":
    main()
