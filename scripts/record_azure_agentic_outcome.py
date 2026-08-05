"""Record the outcome of one scheduled agentic backlog run against its source issue.

The agentic lane previously had no failure feedback: a source issue that failed the
publication gate was re-selected every day, so one stuck task consumed the whole
daily budget. This mirrors the Aider lane's `azure-paused` behaviour, but the count
lives in a marker comment because a gh-aw custom job cannot observe its own outcome.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
from pathlib import Path
from typing import Any

MARKER = "<!-- azure-agentic-failures"
MARKER_PATTERN = re.compile(r"<!--\s*azure-agentic-failures\s+count=([0-9]+)\s*-->")
BOT_LOGIN = "github-actions[bot]"
PAUSED_LABEL = "azure-paused"
DEFAULT_THRESHOLD = 3
VALID_OUTCOMES = {"success", "failure", "cancelled", "skipped"}


def _login(value: Any) -> str:
    if isinstance(value, dict):
        login = value.get("login")
        return login if isinstance(login, str) else ""
    return value if isinstance(value, str) else ""


def find_marker_comment(comments: list[dict[str, Any]]) -> tuple[int | None, int]:
    """Return the id of the newest bot failure-marker comment and its recorded count."""

    for comment in reversed(comments):
        if not isinstance(comment, dict):
            continue
        if _login(comment.get("author") or comment.get("user")).lower() != BOT_LOGIN:
            continue
        body = comment.get("body")
        if not isinstance(body, str):
            continue
        match = MARKER_PATTERN.search(body)
        if match is not None:
            comment_id = comment.get("id")
            return (comment_id if isinstance(comment_id, int) else None), int(match.group(1))
    return None, 0


def marker_body(count: int, run_url: str, paused: bool) -> str:
    lines = [
        f"{MARKER} count={count} -->",
        f"The scheduled agentic session failed the publication gate {count} time(s) in a row "
        "for this issue.",
        "",
        f"- [Latest run]({run_url})",
    ]
    if paused:
        lines.extend(
            [
                "",
                f"Labelled `{PAUSED_LABEL}` so the daily queue moves to another issue. "
                "Refine, close, or remove the label to retry.",
            ]
        )
    return "\n".join(lines)


def cleared_body(run_url: str) -> str:
    return "\n".join(
        [
            f"{MARKER} count=0 -->",
            "The scheduled agentic session reached the publication gate cleanly for this issue.",
            "",
            f"- [Latest run]({run_url})",
        ]
    )


def decide(
    *,
    outcome: str,
    comments: list[dict[str, Any]],
    labels: list[str],
    recurring: bool,
    run_url: str,
    threshold: int = DEFAULT_THRESHOLD,
) -> dict[str, Any]:
    if outcome not in VALID_OUTCOMES:
        raise ValueError(f"Unsupported run outcome: {outcome}")
    if threshold < 1:
        raise ValueError("The failure threshold must be at least one.")

    comment_id, previous = find_marker_comment(comments)

    if outcome == "success":
        if comment_id is None and previous == 0:
            return {"action": "none", "failure_count": 0, "pause": False, "comment_id": None}
        return {
            "action": "reset",
            "failure_count": 0,
            "pause": False,
            "comment_id": comment_id,
            "body": cleared_body(run_url),
        }

    count = previous + 1
    already_paused = PAUSED_LABEL in labels
    pause = count >= threshold and not recurring and not already_paused
    return {
        "action": "record",
        "failure_count": count,
        "pause": pause,
        "comment_id": comment_id,
        "body": marker_body(count, run_url, pause or (already_paused and not recurring)),
    }


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_github_output(path: Path, decision: dict[str, Any]) -> None:
    body = decision.get("body")
    encoded = base64.b64encode(body.encode("utf-8")).decode("ascii") if body else ""
    lines = [
        f"action={decision['action']}",
        f"failure_count={decision['failure_count']}",
        f"pause={'true' if decision['pause'] else 'false'}",
        f"comment_id={decision.get('comment_id') or ''}",
        f"body_b64={encoded}",
    ]
    with path.open("a", encoding="utf-8") as output:
        output.write("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue", type=Path, required=True)
    parser.add_argument("--outcome", required=True)
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    issue = _load_json(args.issue)
    if not isinstance(issue, dict):
        raise ValueError("The issue payload is invalid.")
    labels = [
        str(label.get("name"))
        for label in issue.get("labels") or []
        if isinstance(label, dict) and label.get("name")
    ]
    comments = [item for item in issue.get("comments") or [] if isinstance(item, dict)]

    decision = decide(
        outcome=args.outcome,
        comments=comments,
        labels=labels,
        recurring="azure-recurring" in labels,
        run_url=args.run_url,
        threshold=args.threshold,
    )

    if args.github_output is not None:
        _write_github_output(args.github_output, decision)
    print(
        f"action={decision['action']} failure_count={decision['failure_count']} "
        f"pause={decision['pause']}"
    )


if __name__ == "__main__":
    main()
