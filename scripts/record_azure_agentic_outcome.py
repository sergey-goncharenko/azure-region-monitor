"""Record verified delivery, no-change, waiting, and failure for the scheduled lane."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MARKER = "<!-- azure-agentic-failures"
MARKER_PATTERN = re.compile(r"<!--\s*azure-agentic-failures\s+count=([0-9]+)\s*-->")
BOT_LOGIN = "github-actions[bot]"
PAUSED_LABEL = "azure-paused"
DEFAULT_THRESHOLD = 3
VALID_OUTCOMES = {"success", "failure", "cancelled", "skipped"}
STATE_PATTERN = re.compile(r"^<!-- azure-agentic-state (\{[^\n]+\}) -->")
WAITING = {"waiting-for-maintainer", "evaluating-clarification"}
WRITE_PERMISSIONS = {"admin", "maintain", "write"}


def _gh_json(*args: str, payload: dict[str, Any] | None = None) -> Any:
    command = ["gh", "api", *args]
    if payload is not None:
        command.extend(["--input", "-"])
    result = subprocess.run(
        command, input=json.dumps(payload) if payload is not None else None,
        check=True, capture_output=True, text=True,
    )
    return json.loads(result.stdout)


def issue_comments(repository: str, issue_number: int) -> list[dict[str, Any]]:
    pages = _gh_json(
        f"repos/{repository}/issues/{issue_number}/comments?per_page=100",
        "--paginate", "--slurp",
    )
    return [comment for page in pages for comment in page]


def find_state(comments: list[dict[str, Any]], issue_number: int) -> dict[str, Any] | None:
    for comment in reversed(comments):
        if _login(comment.get("user") or comment.get("author")) != BOT_LOGIN:
            continue
        match = STATE_PATTERN.match(comment.get("body") or "")
        if match is None:
            continue
        state = json.loads(match.group(1))
        if (
            state.get("issue_number") != issue_number
            or state.get("status") not in WAITING | {"delivered", "no-change"}
            or not re.fullmatch(r"[0-9a-f]{40}", str(state.get("head_sha", "")))
            or not str(state.get("run_id", "")).isdigit()
            or type(state.get("run_attempt")) is not int
        ):
            raise ValueError("Malformed agentic queue state.")
        return {**state, "comment_id": comment["id"]}
    return None


def latest_clarification(
    comments: list[dict[str, Any]], repository: str,
) -> dict[str, Any]:
    permissions: dict[str, bool] = {}
    for comment in reversed(comments):
        user = comment.get("user") or {}
        login = _login(user)
        if (
            user.get("type") != "User"
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", login)
            or not str(comment.get("body") or "").strip()
        ):
            continue
        if login not in permissions:
            result = _gh_json(f"repos/{repository}/collaborators/{login}/permission")
            permissions[login] = result.get("permission") in WRITE_PERMISSIONS
        if not permissions[login]:
            continue
        digest = hashlib.sha256(
            json.dumps(
                [comment["id"], login, comment["body"]], ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()
        return {"id": comment["id"], "digest": digest}
    return {}


def queue_state(issues: list[dict[str, Any]], repository: str) -> dict[int, dict[str, Any]]:
    result = {}
    for issue in issues:
        number = issue["number"]
        comments = issue_comments(repository, number)
        state = find_state(comments, number)
        clarification = latest_clarification(comments, repository)
        waiting = bool(state and state["status"] in WAITING)
        consumed = state.get("clarification", {}) if state else {}
        # Deleting a reply is not a clarification, nor is falling back to an older reply.
        fresh = bool(
            clarification
            and clarification != consumed
            and clarification["id"] >= consumed.get("id", 0)
        )
        result[number] = {
            "waiting": waiting and not fresh,
            "state": state,
            "clarification": clarification,
            "clarification_context": next(
                (comment["body"][:2_000] for comment in comments
                 if comment["id"] == clarification.get("id")), "",
            ),
        }
    return result


def state_body(state: dict[str, Any], run_url: str) -> str:
    payload = {key: value for key, value in state.items() if key != "comment_id"}
    return "\n".join([
        f"<!-- azure-agentic-state {json.dumps(payload, sort_keys=True)} -->",
        f"Scheduled agentic outcome: **{state['status']}**.",
        "",
        f"- [Run]({run_url}) (attempt {state['run_attempt']}, commit `{state['head_sha']}`)",
        "- A comment or green workflow is not a delivered patch.",
        (
            "- Waiting for a new reply from a write-level collaborator. One reply permits "
            "one scheduled re-evaluation; its text remains untrusted context. "
            "`azure-paused` failure/manual holds still require explicit removal."
            if state["status"] in WAITING
            else "- The waiting-for-maintainer hold is cleared."
        ),
    ])


def write_state(repository: str, state: dict[str, Any], run_url: str) -> None:
    comment_id = state.get("comment_id")
    endpoint = (
        f"repos/{repository}/issues/comments/{comment_id}" if comment_id
        else f"repos/{repository}/issues/{state['issue_number']}/comments"
    )
    _gh_json(
        endpoint, "--method", "PATCH" if comment_id else "POST",
        payload={"body": state_body(state, run_url)},
    )


def reserve_selection(manifest: dict[str, Any], repository: str) -> dict[str, Any]:
    task = manifest["tasks"][0]
    prepared = task["agentic_queue"]
    selection = {
        "issue_number": task["issue_number"],
        "repository": repository,
        "run_id": os.environ["GITHUB_RUN_ID"],
        "run_attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]),
        "head_sha": os.environ["GITHUB_SHA"],
        "selected_at": datetime.now(timezone.utc).isoformat(),
        "clarification": prepared["clarification"],
    }
    state = prepared["state"]
    if state and state["status"] in WAITING:
        # Consume before the paid session, including if it crashes or its follower fails.
        write_state(repository, {
            **selection, "status": "evaluating-clarification", "comment_id": state["comment_id"],
        }, f"https://github.com/{repository}/actions/runs/{selection['run_id']}")
    return selection


def validate_selection(selection: dict[str, Any], run: dict[str, Any], repository: str) -> None:
    if (
        type(selection.get("issue_number")) is not int
        or selection["issue_number"] <= 0
        or selection.get("repository") != repository
        or str(selection.get("run_id")) != str(run["id"])
        or selection.get("run_attempt") != run["run_attempt"]
        or selection.get("head_sha") != run["head_sha"]
        or run["head_repository"]["full_name"] != repository
        or run["path"] != ".github/workflows/scheduled-agentic-backlog.lock.yml"
    ):
        raise ValueError("Malformed or mismatched agentic backlog selection provenance.")


def classify_outcome(
    conclusion: str, selection: dict[str, Any], receipts: list[dict[str, Any]],
    requests: list[dict[str, Any]], comments: list[dict[str, Any]],
    repository: str,
) -> str:
    if conclusion != "success":
        return "failure"
    number = selection["issue_number"]
    selected_at = datetime.fromisoformat(selection["selected_at"])
    for receipt in receipts:
        if receipt.get("repo") != repository:
            continue
        timestamp = datetime.fromisoformat(receipt["timestamp"].replace("Z", "+00:00"))
        if timestamp < selected_at:
            continue
        if receipt.get("type") == "create_pull_request":
            pr_number = receipt.get("number")
            if type(pr_number) is not int or pr_number <= 0:
                continue
            pull = _gh_json(f"repos/{repository}/pulls/{pr_number}")
            if (
                pull["html_url"] == receipt.get("url")
                and _login(pull["user"]) == BOT_LOGIN
                and re.fullmatch(rf"agentic/issue-{number}(?:-[0-9a-f]+)?", pull["head"]["ref"])
                and f"<!-- azure-agentic-source:issue-{number} -->" in (pull.get("body") or "")
            ):
                return "delivered"
        if receipt.get("type") == "add_comment" and receipt.get("number") == number:
            marker = f"<!-- azure-agentic-waiting:issue-{number} -->"
            for comment in comments:
                if (
                    comment.get("html_url") == receipt.get("url")
                    and _login(comment.get("user")) == BOT_LOGIN
                    and marker in (comment.get("body") or "")
                ):
                    return "waiting-for-maintainer"
    if (
        not receipts and len(requests) == 1 and requests[0].get("type") == "noop"
        and isinstance(requests[0].get("message"), str) and requests[0]["message"].strip()
    ):
        return "no-change"
    # A green workflow without an explicit, verified terminal result is not delivery.
    return "failure"


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
            "The scheduled agentic session published a verified pull request for this issue.",
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
    parser.add_argument("--issue", type=Path)
    parser.add_argument("--outcome")
    parser.add_argument("--run-url")
    parser.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--reserve-manifest", type=Path)
    parser.add_argument("--selection-output", type=Path)
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--run", type=Path)
    parser.add_argument("--receipts", type=Path)
    parser.add_argument("--requests", type=Path)
    args = parser.parse_args()

    if args.reserve_manifest:
        if args.selection_output is None:
            parser.error("--reserve-manifest requires --selection-output")
        selection = reserve_selection(_load_json(args.reserve_manifest), args.repository)
        args.selection_output.write_text(json.dumps(selection) + "\n", encoding="utf-8")
        return
    if not args.issue or not args.outcome or not args.run_url:
        parser.error("--issue, --outcome and --run-url are required")
    if not args.selection:
        parser.error("A run-proven --selection is required to record an outcome")
    issue = _load_json(args.issue)
    if not isinstance(issue, dict):
        raise ValueError("The issue payload is invalid.")
    labels = [
        str(label.get("name"))
        for label in issue.get("labels") or []
        if isinstance(label, dict) and label.get("name")
    ]
    comments = [item for item in issue.get("comments") or [] if isinstance(item, dict)]

    terminal = args.outcome
    selection = None
    if args.selection:
        if not args.run or not args.receipts or not args.requests:
            parser.error("--selection requires --run, --receipts and --requests")
        selection = _load_json(args.selection)
        validate_selection(selection, _load_json(args.run), args.repository)
        if issue.get("number") != selection["issue_number"]:
            raise ValueError("The outcome issue does not match the selected issue.")
        receipts = [
            json.loads(line) for line in args.receipts.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        requests = [
            json.loads(line) for line in args.requests.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        terminal = classify_outcome(
            args.outcome, selection, receipts, requests, comments, args.repository,
        )
        previous_state = find_state(comments, selection["issue_number"])
        if previous_state and (
            int(previous_state["run_id"]), previous_state["run_attempt"]
        ) > (int(selection["run_id"]), selection["run_attempt"]):
            raise ValueError("Refusing a stale outcome after a newer issue evaluation.")
        if terminal in WAITING | {"delivered", "no-change"}:
            write_state(args.repository, {
                **selection, "status": terminal,
                "comment_id": previous_state["comment_id"] if previous_state else None,
            }, args.run_url)

    if terminal in WAITING | {"no-change"}:
        decision = {
            "action": "none", "failure_count": find_marker_comment(comments)[1],
            "pause": False, "comment_id": None,
        }
    else:
        decision = decide(
            outcome="success" if terminal == "delivered" else terminal,
            comments=comments,
            labels=labels,
            recurring="azure-recurring" in labels,
            run_url=args.run_url,
            threshold=args.threshold,
        )

    if args.github_output is not None:
        _write_github_output(args.github_output, decision)
    print(
        f"outcome={terminal} action={decision['action']} failure_count={decision['failure_count']} "
        f"pause={decision['pause']}"
    )


if __name__ == "__main__":
    main()
