from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATUS_TITLE = "[agent-status] Scheduled Azure backlog"
STATUS_LABEL = "azure-agent-status"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=False, capture_output=True, text=True)


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"tasks": [], "status": {}}
    return value if isinstance(value, dict) else {"tasks": [], "status": {}}


def _issue_lines(items: object) -> list[str]:
    if not isinstance(items, list) or not items:
        return ["- None"]
    lines = []
    for item in items:
        if not isinstance(item, dict):
            continue
        number = item.get("number")
        title = str(item.get("title", "")).strip()
        if isinstance(number, int) and title:
            lines.append(f"- #{number}: {title}")
    return lines or ["- None"]


def render_status(manifest: dict[str, Any], run_url: str) -> str:
    status = manifest.get("status")
    status = status if isinstance(status, dict) else {}
    selected = int(status.get("selected_count", 0) or 0)
    outcome = (
        f"Selected {selected} issue session(s); inspect the latest run audit and any draft PRs."
        if selected
        else "No agent session started because no eligible backlog issue was available."
    )
    lines = [
        "<!-- azure-agent-backlog-status -->",
        "# Scheduled Azure backlog status",
        "",
        f"- Updated: `{datetime.now(timezone.utc).isoformat()}`",
        f"- Latest run: {run_url or 'not available'}",
        f"- Open backlog issues: {int(status.get('backlog_count', 0) or 0)}",
        f"- Eligible issues: {int(status.get('eligible_count', 0) or 0)}",
        f"- Paused issues: {int(status.get('paused_count', 0) or 0)}",
        f"- Selected sessions: {selected}",
        "",
        outcome,
        "",
        "## Eligible issues",
        "",
        *_issue_lines(status.get("eligible_issues")),
        "",
        "## Paused issues",
        "",
        *_issue_lines(status.get("paused_issues")),
        "",
        "This stable issue is updated by every scheduled backlog run. No-task runs also add a concise comment so maintainers receive a visible timeline instead of a silent successful workflow.",
    ]
    return "\n".join(lines) + "\n"


def _status_issue(repository: str) -> tuple[int | None, str]:
    result = _run(
        "gh",
        "issue",
        "list",
        "--repo",
        repository,
        "--state",
        "all",
        "--label",
        STATUS_LABEL,
        "--limit",
        "100",
        "--json",
        "number,title,state",
    )
    if result.returncode != 0:
        return None, ""
    try:
        issues = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None, ""
    for issue in issues if isinstance(issues, list) else []:
        if isinstance(issue, dict) and issue.get("title") == STATUS_TITLE:
            number = issue.get("number")
            state = str(issue.get("state", "")).lower()
            return (number if isinstance(number, int) else None), state
    return None, ""


def publish_status(manifest: dict[str, Any], repository: str, run_url: str) -> int:
    _run(
        "gh",
        "label",
        "create",
        STATUS_LABEL,
        "--repo",
        repository,
        "--color",
        "0E8A16",
        "--description",
        "Stable scheduled Azure backlog run status",
        "--force",
    )
    handle = tempfile.NamedTemporaryFile("w", suffix=".md", encoding="utf-8", delete=False)
    body_path = Path(handle.name)
    try:
        handle.write(render_status(manifest, run_url))
        handle.close()
        issue_number, state = _status_issue(repository)
        if issue_number is None:
            created = _run(
                "gh",
                "issue",
                "create",
                "--repo",
                repository,
                "--title",
                STATUS_TITLE,
                "--label",
                STATUS_LABEL,
                "--body-file",
                str(body_path),
            )
            if created.returncode != 0:
                return 1
            match = created.stdout.strip().rstrip("/").rsplit("/", 1)[-1]
            issue_number = int(match) if match.isdigit() else None
        else:
            if state == "closed":
                _run("gh", "issue", "reopen", str(issue_number), "--repo", repository)
            updated = _run(
                "gh",
                "issue",
                "edit",
                str(issue_number),
                "--repo",
                repository,
                "--body-file",
                str(body_path),
            )
            if updated.returncode != 0:
                return 1
        status = manifest.get("status")
        status = status if isinstance(status, dict) else {}
        if issue_number is not None and int(status.get("selected_count", 0) or 0) == 0:
            _run(
                "gh",
                "issue",
                "comment",
                str(issue_number),
                "--repo",
                repository,
                "--body",
                "No agent session started: "
                f"{int(status.get('backlog_count', 0) or 0)} backlog issue(s), "
                f"{int(status.get('paused_count', 0) or 0)} paused, "
                f"{int(status.get('eligible_count', 0) or 0)} eligible. "
                f"Run: {run_url or 'not available'}",
            )
        print(f"Published scheduled backlog status: issue #{issue_number or 'unknown'}.")
        return 0
    finally:
        if not handle.closed:
            handle.close()
        body_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish a stable scheduled backlog status issue.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-url", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    manifest = _load_manifest(args.manifest)
    if args.dry_run:
        print(render_status(manifest, args.run_url))
        raise SystemExit(0)
    raise SystemExit(publish_status(manifest, args.repository, args.run_url))


if __name__ == "__main__":
    main()
