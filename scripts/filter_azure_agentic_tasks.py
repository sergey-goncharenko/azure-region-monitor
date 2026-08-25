from __future__ import annotations

import argparse
import base64
import json
import re
from pathlib import Path
from typing import Any

BRANCH_ISSUE_PATTERN = re.compile(r"^(?:azure-issues|agentic)/issue-([1-9][0-9]*)(?:[-/].*)?$")
BODY_ISSUE_PATTERN = re.compile(
    r"(?:<!--\s*azure-agentic-source:issue-|Source issue:\s*#)([1-9][0-9]*)",
    re.IGNORECASE,
)
MAX_TASK_OUTPUT_BYTES = 750_000
PRIORITY_NAMES = {400: "Urgent", 300: "High", 200: "Normal", 100: "Low"}


def _load_object(path: Path, description: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"The {description} JSON is invalid.") from error
    if not isinstance(payload, dict):
        raise ValueError(f"The {description} JSON is invalid.")
    return payload


def _load_array(path: Path, description: str) -> list[Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"The {description} JSON is invalid.") from error
    if not isinstance(payload, list):
        raise ValueError(f"The {description} JSON is invalid.")
    return payload


def _open_issue_numbers(pulls: list[Any]) -> set[int]:
    issue_numbers: set[int] = set()
    for pull in pulls:
        if not isinstance(pull, dict):
            continue
        head = pull.get("headRefName")
        if isinstance(head, str):
            branch_match = BRANCH_ISSUE_PATTERN.fullmatch(head)
            if branch_match:
                issue_numbers.add(int(branch_match.group(1)))
        body = pull.get("body")
        if isinstance(body, str):
            issue_numbers.update(int(value) for value in BODY_ISSUE_PATTERN.findall(body))
    return issue_numbers


def filter_manifest(
    manifest: dict[str, Any],
    open_pulls: list[Any],
) -> dict[str, Any]:
    tasks = manifest.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("The Azure backlog manifest has no valid tasks array.")

    open_issue_numbers = _open_issue_numbers(open_pulls)
    selected: list[dict[str, Any]] = []
    skipped: list[int] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        issue_number = task.get("issue_number")
        if type(issue_number) is not int or issue_number <= 0:
            continue
        if issue_number in open_issue_numbers:
            skipped.append(issue_number)
            continue
        if not selected:
            selected.append(task)

    result = dict(manifest)
    result["tasks"] = selected
    status = dict(manifest.get("status")) if isinstance(manifest.get("status"), dict) else {}
    status["selected_count"] = len(selected)
    status["selected_categories"] = [str(task.get("category", "")) for task in selected]
    eligible_items = status.get("eligible_issues")
    eligible_items = eligible_items if isinstance(eligible_items, list) else []
    skipped_numbers = set(skipped)
    blocked_items = [
        item
        for item in eligible_items
        if isinstance(item, dict) and item.get("number") in skipped_numbers
    ]
    status["blocked_open_pr_count"] = len(skipped)
    status["blocked_open_pr_issues"] = blocked_items
    result["status"] = status
    result["agentic_filter"] = {
        "open_pr_issue_numbers": sorted(open_issue_numbers),
        "skipped_open_pr_issue_numbers": skipped,
    }
    return result


def agent_task_summary(manifest: dict[str, Any]) -> str:
    tasks = manifest.get("tasks")
    task = tasks[0] if isinstance(tasks, list) and tasks else None
    if not isinstance(task, dict):
        return "# Agent task summary\n\nNo issue task was selected.\n"

    evidence = task.get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    issue_number = task.get("issue_number", "unknown")
    title = str(evidence.get("issue_title") or task.get("summary") or "Untitled issue")
    objective = str(evidence.get("objective") or "No objective was provided.")
    priority = PRIORITY_NAMES.get(evidence.get("priority"), str(evidence.get("priority") or "Unknown"))
    labels = evidence.get("issue_labels")
    labels = [str(value) for value in labels] if isinstance(labels, list) else []
    recurring = bool(task.get("recurring"))
    unknown_status = evidence.get("current_unknown_status")
    unknown_status = unknown_status if isinstance(unknown_status, dict) else None

    lines = [
        "# Agent task summary",
        "",
        # Repeated here because the agent reads this file first and has skipped the
        # equivalent prompt rules on several runs.
        "## Publication gate — read before editing",
        "",
        "Only two things stop your work from being published: a security finding, and a "
        "patch that does not apply or that edits `scripts/check.py`. Everything else is "
        "advisory and is reported on the pull request, so publish the work rather than "
        "abandoning it.",
        "",
        "Aim for all of the following anyway, because they are what a reviewer checks:",
        "",
        "- every `src/**/*.py` change ships with a `tests/test_*.py` change, including "
        "presentation-only changes such as generated CSS or HTML, whose assertion "
        "belongs in `tests/test_static_site.py`;",
        "- `python scripts/check_css.py` and `git diff --check` pass. `pytest` and `ruff` are "
        "not importable from your sandbox; the gate runs them for you afterwards;",
        "- you commit the work on `agentic/issue-<number>` before calling "
        "`create_pull_request`, staging source and tests together. The safe output is "
        "rejected with \"no commits were found\" if you leave the tree dirty.",
        "",
        "## Issue queue selection",
        "",
        f"- Source issue: #{issue_number}",
        f"- Title: {title}",
        f"- Queue priority: {priority}",
        f"- Labels: {', '.join(labels) if labels else 'not reported'}",
        f"- Recurring: {'yes' if recurring else 'no'}",
        "- Selection reason: this open issue was selected from the `azure-backlog` queue; "
        "live unknown evidence never creates a task by itself.",
        "",
        "## Trusted Objective",
        "",
        objective,
    ]
    if unknown_status is not None:
        lines.extend(
            [
                "",
                "## Live evidence enrichment requested by the source issue",
                "",
                "The source issue carries `azure-unknowns`; this evidence narrows its current "
                "investigation but did not bypass issue selection.",
                f"- Category: {unknown_status.get('selected_category') or 'unknown'}",
                f"- Unknown checks: {unknown_status.get('unknown_count', 0)}",
                "- Features: "
                + ", ".join(str(value) for value in unknown_status.get("features", [])[:10]),
                "- Error codes: "
                + json.dumps(unknown_status.get("error_codes", []), ensure_ascii=False),
                "- Representative messages: "
                + json.dumps(unknown_status.get("messages", [])[:5], ensure_ascii=False)[:2_000],
            ]
        )

    lines.extend(
        [
            "",
            "## Relevance hints",
            "",
            "- Suggested paths: " + ", ".join(str(value) for value in task.get("allowed_paths", [])),
            "- Suggested tests: " + ", ".join(str(value) for value in task.get("tests", [])),
            "",
            "Use `/tmp/gh-aw/agent/task.json` only when this summary lacks necessary evidence. "
            "Do not dump or reread the entire JSON manifest.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_github_output(path: Path, manifest: dict[str, Any]) -> None:
    tasks = manifest.get("tasks")
    task = tasks[0] if isinstance(tasks, list) and tasks else {}
    issue_number = task.get("issue_number", "") if isinstance(task, dict) else ""
    category = task.get("category", "") if isinstance(task, dict) else ""
    task_json = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    task_b64 = base64.b64encode(task_json).decode("ascii")
    summary_b64 = base64.b64encode(agent_task_summary(manifest).encode("utf-8")).decode("ascii")
    if len(task_b64) > MAX_TASK_OUTPUT_BYTES:
        raise ValueError("The selected task manifest exceeds the GitHub Actions output budget.")
    with path.open("a", encoding="utf-8") as output:
        output.write(f"has_task={'true' if task else 'false'}\n")
        output.write(f"issue_number={issue_number}\n")
        output.write(f"category={category}\n")
        output.write(f"task_b64={task_b64}\n")
        output.write(f"summary_b64={summary_b64}\n")


def render_summary(manifest: dict[str, Any]) -> str:
    tasks = manifest.get("tasks")
    tasks = tasks if isinstance(tasks, list) else []
    agentic_filter = manifest.get("agentic_filter")
    agentic_filter = agentic_filter if isinstance(agentic_filter, dict) else {}
    lines = [
        "## GitHub Agentic Workflows issue selection",
        "",
        f"- Selected issue tasks: {len(tasks)}",
        "- Skipped because an issue PR is already open: "
        + str(len(agentic_filter.get("skipped_open_pr_issue_numbers", []))),
    ]
    if tasks:
        task = tasks[0]
        lines.append(f"- Selected source issue: #{task['issue_number']}")
        lines.append(f"- Task category: `{task['category']}`")
    else:
        lines.extend(["", "No coding-agent session should start for this run."])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove Azure backlog tasks that already have an open issue PR."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--open-pulls", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    manifest = _load_object(args.manifest, "Azure backlog manifest")
    open_pulls = _load_array(args.open_pulls, "open pull request list")
    filtered = filter_manifest(manifest, open_pulls)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(filtered, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.github_output is not None:
        _write_github_output(args.github_output, filtered)
    print(render_summary(filtered), end="")


if __name__ == "__main__":
    main()
