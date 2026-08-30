from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

QUESTION_MARKER = "<!-- azure-agentic-objective-question -->"
BOT_LOGIN = "github-actions[bot]"
MAX_COMMENT_PAGES = 10


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=False, capture_output=True, text=True)


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("The Azure backlog manifest is invalid.") from error
    if not isinstance(payload, dict):
        raise ValueError("The Azure backlog manifest is invalid.")
    return payload


def objective_question(repository: str, run_url: str) -> str:
    owner = repository.split("/", 1)[0]
    lines = [
        QUESTION_MARKER,
        f"@{owner}",
        "",
        "## Scheduled-agent objective needed",
        "",
        "This issue is labelled `azure-backlog`, but the scheduler could not find a "
        "parseable `### Objective` section, so it cannot start coding work.",
        "",
        "**Question for a maintainer:** What concrete, observable outcome should the "
        "scheduled agent deliver for this issue?",
        "",
        "Please edit the issue body and add or expand these exact sections:",
        "",
        "```markdown",
        "### Priority",
        "",
        "Normal",
        "",
        "### Objective",
        "",
        "<the outcome the agent should deliver>",
        "",
        "### Context or acceptance evidence",
        "",
        "<facts and observable success conditions>",
        "```",
        "",
        "If the issue currently uses `Requested outcome`, move and expand that content "
        "under `### Objective`. A later scheduled run can consider it after the body is updated.",
    ]
    if run_url:
        lines.extend(["", f"[Run that detected the missing objective]({run_url})"])
    return "\n".join(lines) + "\n"


def _malformed_issues(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    status = manifest.get("status")
    status = status if isinstance(status, dict) else {}
    items = status.get("malformed_issues")
    if not isinstance(items, list):
        return []
    return [
        item
        for item in items
        if isinstance(item, dict)
        and type(item.get("number")) is int
        and item["number"] > 0
    ]


def _issue_comments(repository: str, issue_number: int) -> list[dict[str, Any]]:
    comments: list[dict[str, Any]] = []
    for page in range(1, MAX_COMMENT_PAGES + 1):
        result = _run(
            "gh",
            "api",
            f"repos/{repository}/issues/{issue_number}/comments?per_page=100&page={page}",
        )
        if result.returncode != 0:
            raise RuntimeError(f"Could not read comments for issue #{issue_number}.")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise RuntimeError(
                f"GitHub returned invalid comments for issue #{issue_number}."
            ) from error
        if not isinstance(payload, list):
            raise RuntimeError(f"GitHub returned invalid comments for issue #{issue_number}.")
        page_comments = [comment for comment in payload if isinstance(comment, dict)]
        comments.extend(page_comments)
        if len(payload) < 100:
            return comments
    return comments


def _has_objective_question(comments: list[dict[str, Any]]) -> bool:
    return any(
        isinstance(comment.get("body"), str)
        and QUESTION_MARKER in comment["body"]
        and isinstance(comment.get("user"), dict)
        and str(comment["user"].get("login", "")).lower() == BOT_LOGIN
        for comment in comments
    )


def request_objectives(
    manifest: dict[str, Any], repository: str, run_url: str
) -> int:
    if re.fullmatch(r"[^/\s]+/[^/\s]+", repository) is None:
        raise ValueError("GitHub repository must use the owner/name format.")

    malformed_issues = _malformed_issues(manifest)
    requested = 0
    for issue in malformed_issues:
        issue_number = issue["number"]
        if _has_objective_question(_issue_comments(repository, issue_number)):
            print(f"Issue #{issue_number} already has an objective clarification question.")
            continue

        with tempfile.NamedTemporaryFile(
            "w", suffix=".md", encoding="utf-8", delete=False
        ) as handle:
            path = Path(handle.name)
            handle.write(objective_question(repository, run_url))
        try:
            result = _run(
                "gh",
                "issue",
                "comment",
                str(issue_number),
                "--repo",
                repository,
                "--body-file",
                str(path),
            )
        finally:
            path.unlink(missing_ok=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"Could not publish the objective question on issue #{issue_number}."
            )
        requested += 1
        print(f"Asked for a concrete Objective on issue #{issue_number}.")
    if not malformed_issues:
        print("No malformed backlog issue needs an objective clarification question.")
    return requested


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ask maintainers to clarify malformed Azure backlog objectives."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-url", default="")
    args = parser.parse_args()
    request_objectives(
        _load_manifest(args.manifest),
        args.repository,
        args.run_url,
    )


if __name__ == "__main__":
    main()