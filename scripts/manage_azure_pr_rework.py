from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

BRANCH_PATTERN = re.compile(r"^azure-issues/issue-([1-9][0-9]*)$")
# gh-aw appends a uniqueness suffix to the branch the agent asks for.
AGENTIC_BRANCH_PATTERN = re.compile(r"^agentic/issue-([1-9][0-9]*)(?:-[0-9a-f]{6,32})?$")
LANE_BRANCH_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aider", BRANCH_PATTERN),
    ("agentic", AGENTIC_BRANCH_PATTERN),
)
LOGIN_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
REQUEST_ID_PATTERN = re.compile(r"^[1-9][0-9]*-[1-9][0-9]*$")
ALLOWED_PERMISSIONS = {"admin", "maintain", "write"}
BACKLOG_LABEL = "azure-backlog"
PAUSED_LABEL = "azure-paused"
BOT_LOGIN = "github-actions[bot]"
ACTIVE_MARKER = "<!-- azure-byok-rework:running"
COMPLETED_MARKER = "<!-- azure-byok-rework:completed"
ACTIVE_REQUEST_TTL = timedelta(hours=2)
MAX_GITHUB_REQUEST_ATTEMPTS = 3
MAX_REWORK_REQUIREMENTS_CHARS = 4_000
REWORK_TRIGGERS = {"request-changes"}


class GitHubReworkClient(Protocol):
    repository: str

    def get_repository(self) -> dict[str, Any]: ...

    def get_pull_request(self, number: int) -> dict[str, Any]: ...

    def get_permission(self, login: str) -> str: ...

    def get_issue(self, number: int) -> dict[str, Any]: ...

    def list_issue_comments(self, number: int) -> list[dict[str, Any]]: ...

    def get_issue_comment(self, comment_id: int) -> dict[str, Any]: ...

    def create_issue_comment(self, number: int, body: str) -> dict[str, Any]: ...

    def update_issue_comment(self, comment_id: int, body: str) -> dict[str, Any]: ...


class GitHubApiClient:
    """Minimal GitHub client used by the deterministic PR-rework dispatcher."""

    def __init__(
        self,
        *,
        repository: str,
        token: str,
        api_url: str = "https://api.github.com",
        opener: urllib.request.OpenerDirector | None = None,
    ) -> None:
        if not re.fullmatch(r"[^/\s]+/[^/\s]+", repository):
            raise ValueError("GitHub repository must use the owner/name format.")
        if not token:
            raise ValueError("A GitHub token is required for PR rework automation.")
        self.repository = repository
        self._token = token
        self._api_url = api_url.rstrip("/")
        self._opener = opener or urllib.request.build_opener()

    @classmethod
    def from_env(cls, repository: str) -> "GitHubApiClient":
        return cls(
            repository=repository,
            token=os.environ.get("GH_TOKEN", ""),
            api_url=os.environ.get("GITHUB_API_URL", "https://api.github.com"),
        )

    def get_repository(self) -> dict[str, Any]:
        return self._get(f"/repos/{self.repository}")

    def get_pull_request(self, number: int) -> dict[str, Any]:
        return self._get(f"/repos/{self.repository}/pulls/{number}")

    def get_permission(self, login: str) -> str:
        payload = self._get(f"/repos/{self.repository}/collaborators/{login}/permission")
        permission = payload.get("permission")
        return permission.lower() if isinstance(permission, str) else ""

    def get_issue(self, number: int) -> dict[str, Any]:
        return self._get(f"/repos/{self.repository}/issues/{number}")

    def list_issue_comments(self, number: int) -> list[dict[str, Any]]:
        return self._paginate(f"/repos/{self.repository}/issues/{number}/comments")

    def get_issue_comment(self, comment_id: int) -> dict[str, Any]:
        return self._get(f"/repos/{self.repository}/issues/comments/{comment_id}")

    def create_issue_comment(self, number: int, body: str) -> dict[str, Any]:
        return self._write(
            "POST",
            f"/repos/{self.repository}/issues/{number}/comments",
            {"body": body},
        )

    def update_issue_comment(self, comment_id: int, body: str) -> dict[str, Any]:
        return self._write(
            "PATCH",
            f"/repos/{self.repository}/issues/comments/{comment_id}",
            {"body": body},
        )

    def _paginate(self, path: str) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        page = 1
        while True:
            separator = "&" if "?" in path else "?"
            payload = self._get(f"{path}{separator}per_page=100&page={page}")
            if not isinstance(payload, list):
                raise RuntimeError(f"GitHub endpoint {path} returned an invalid response.")
            values.extend(item for item in payload if isinstance(item, dict))
            if len(payload) < 100:
                return values
            page += 1

    def _get(self, path: str) -> Any:
        for attempt in range(MAX_GITHUB_REQUEST_ATTEMPTS):
            try:
                return self._request("GET", path)
            except RuntimeError:
                if attempt + 1 == MAX_GITHUB_REQUEST_ATTEMPTS:
                    raise
                time.sleep(attempt + 1)
        raise RuntimeError("GitHub request failed after retries.")

    def _write(self, method: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._request(method, path, payload)
        if not isinstance(result, dict):
            raise RuntimeError(f"GitHub endpoint {path} returned an invalid response.")
        return result

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            f"{self._api_url}{path}",
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "User-Agent": "azure-region-monitor-pr-rework",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with self._opener.open(request, timeout=30) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"GitHub PR rework request failed: HTTP {error.code}.") from error
        except (urllib.error.URLError, OSError) as error:
            raise RuntimeError(f"GitHub PR rework request failed: {error}.") from error
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as error:
            raise RuntimeError("GitHub PR rework request returned invalid JSON.") from error


def _login(value: object) -> str:
    if isinstance(value, dict) and isinstance(value.get("login"), str):
        return value["login"]
    return ""


def _repo_name(value: object) -> str:
    if isinstance(value, dict) and isinstance(value.get("full_name"), str):
        return value["full_name"]
    return ""


def _labels(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()
    labels = set()
    for label in value:
        if isinstance(label, str):
            labels.add(label.lower())
        elif isinstance(label, dict) and isinstance(label.get("name"), str):
            labels.add(label["name"].lower())
    return labels


def _bounded_rework_requirements(value: object) -> str:
    text = value if isinstance(value, str) else ""
    text = "".join(
        character for character in text.replace("\r\n", "\n")
        if character in "\n\t" or ord(character) >= 32
    ).strip()
    if not text:
        text = (
            "Address the current requested changes on this pull request within the existing "
            "derived scope. Do not report successful rework without a validated branch change."
        )
    return text[:MAX_REWORK_REQUIREMENTS_CHARS]


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _active_rework_exists(comments: list[dict[str, Any]], now: datetime) -> bool:
    for comment in comments:
        body = comment.get("body")
        if _login(comment.get("user")).lower() != BOT_LOGIN or not isinstance(body, str):
            continue
        if ACTIVE_MARKER not in body:
            continue
        created_at = _parse_timestamp(comment.get("created_at"))
        if created_at is None or now - created_at <= ACTIVE_REQUEST_TTL:
            return True
    return False


def _result(reason: str, *, eligible: bool = False, **values: Any) -> dict[str, Any]:
    return {"eligible": eligible, "reason": reason, **values}


def _match_lane_branch(head_ref: Any) -> tuple[str, int] | None:
    if not isinstance(head_ref, str):
        return None
    for lane, pattern in LANE_BRANCH_PATTERNS:
        match = pattern.fullmatch(head_ref)
        if match is not None:
            return lane, int(match.group(1))
    return None


def _trigger_details(
    payload: dict[str, Any], event_name: str
) -> tuple[str, int, str] | dict[str, Any]:
    if event_name == "issue_comment":
        return _result("PR comments are context only; submit a Request changes review to rework.")

    if event_name == "pull_request_review":
        if payload.get("action") != "submitted":
            return _result("Only submitted reviews can request rework.")
        review = payload.get("review")
        pull = payload.get("pull_request")
        state = review.get("state", "") if isinstance(review, dict) else ""
        body = review.get("body", "") if isinstance(review, dict) else ""
        if not isinstance(state, str) or state.lower() != "changes_requested":
            return _result("The submitted review did not request changes.")
        number = pull.get("number") if isinstance(pull, dict) else None
        if not isinstance(number, int) or number <= 0:
            return _result("The pull request number is invalid.")
        return "request-changes", number, body if isinstance(body, str) else ""

    return _result("This GitHub event is not supported for PR rework.")


def resolve_rework_event(
    payload: dict[str, Any],
    *,
    event_name: str,
    repository: str,
    actor: str,
    client: GitHubReworkClient,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Resolve an untrusted GitHub event into a bounded targeted-rework request."""

    trigger = _trigger_details(payload, event_name)
    if isinstance(trigger, dict):
        return trigger
    trigger_kind, pr_number, feedback = trigger

    sender = payload.get("sender")
    sender_login = _login(sender)
    sender_type = sender.get("type", "") if isinstance(sender, dict) else ""
    if not LOGIN_PATTERN.fullmatch(actor) or sender_login.lower() != actor.lower():
        return _result("The event actor does not match the authenticated sender.")
    if str(sender_type).lower() == "bot" or actor.lower().endswith("[bot]"):
        return _result("Bot-authored events cannot request PR rework.")

    repository_payload = client.get_repository()
    canonical_repository = _repo_name(repository_payload)
    default_branch = repository_payload.get("default_branch")
    if canonical_repository.lower() != repository.lower() or not isinstance(
        default_branch, str
    ):
        return _result("The repository metadata is invalid.")

    pull = client.get_pull_request(pr_number)
    if pull.get("state") != "open":
        return _result("Only open pull requests can be reworked.")
    head = pull.get("head")
    base = pull.get("base")
    head_repo = _repo_name(head.get("repo") if isinstance(head, dict) else None)
    base_repo = _repo_name(base.get("repo") if isinstance(base, dict) else None)
    if head_repo.lower() != repository.lower() or base_repo.lower() != repository.lower():
        return _result("Forked or cross-repository pull requests cannot trigger rework.")
    base_ref = base.get("ref") if isinstance(base, dict) else None
    if base_ref != default_branch:
        return _result("The pull request must target the repository default branch.")
    if _login(pull.get("user")).lower() != BOT_LOGIN:
        return _result("Only Azure backlog pull requests created by GitHub Actions are eligible.")

    head_ref = head.get("ref") if isinstance(head, dict) else None
    lane_branch = _match_lane_branch(head_ref)
    if lane_branch is None:
        return _result("The pull request branch is not an Azure issue branch.")
    lane, target_issue = lane_branch

    permission = client.get_permission(actor)
    if permission not in ALLOWED_PERMISSIONS:
        return _result("The requester does not have write-level repository permission.")

    issue = client.get_issue(target_issue)
    labels = _labels(issue.get("labels"))
    if (
        issue.get("state") != "open"
        or BACKLOG_LABEL not in labels
        or PAUSED_LABEL in labels
    ):
        return _result("The source issue is not currently eligible for Azure backlog work.")

    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if _active_rework_exists(client.list_issue_comments(pr_number), current_time):
        return _result("An Azure BYOK rework request is already active for this pull request.")

    return _result(
        "Eligible collaborator feedback will be dispatched to the existing Azure BYOK runner.",
        eligible=True,
        trigger=trigger_kind,
        pr_number=pr_number,
        target_issue=target_issue,
        actor=actor,
        lane=lane,
        base_branch=default_branch,
        head_ref=head_ref,
        rework_requirements=_bounded_rework_requirements(feedback),
    )


def _validate_request_id(request_id: str) -> None:
    if REQUEST_ID_PATTERN.fullmatch(request_id) is None:
        raise ValueError("The PR rework request ID is invalid.")


def _validate_run_url(run_url: str, repository: str) -> None:
    expected = rf"https://github\.com/{re.escape(repository)}/actions/runs/[1-9][0-9]*"
    if re.fullmatch(expected, run_url) is None:
        raise ValueError("The PR rework workflow URL is invalid.")


def running_status_body(result: dict[str, Any], request_id: str, run_url: str) -> str:
    if result.get("eligible") is not True:
        raise ValueError("Cannot create a running status for an ineligible event.")
    _validate_request_id(request_id)
    actor = result.get("actor")
    trigger = result.get("trigger")
    if not isinstance(actor, str) or LOGIN_PATTERN.fullmatch(actor) is None:
        raise ValueError("The PR rework actor is invalid.")
    if trigger not in REWORK_TRIGGERS:
        raise ValueError("The PR rework trigger is invalid.")
    return "\n".join(
        [
            f"{ACTIVE_MARKER} request={request_id} -->",
            "Azure BYOK rework was queued.",
            "",
            f"- Trigger: `{trigger}`",
            f"- Requested by: @{actor}",
            f"- [Dispatcher run]({run_url})",
            "",
            "The existing PR branch will be updated only after bounded scope and validation checks pass.",
        ]
    )


def completed_status_body(request_id: str, outcome: str, run_url: str) -> str:
    _validate_request_id(request_id)
    if outcome not in {"success", "failure", "cancelled", "dispatch-failed"}:
        raise ValueError("The PR rework outcome is invalid.")
    return "\n".join(
        [
            f"{COMPLETED_MARKER} request={request_id} -->",
            f"Azure BYOK rework finished with status **{outcome}**.",
            "",
            f"- [Workflow run]({run_url})",
            "",
            "Review the same PR branch and its refreshed rationale, validation, model, token, and chat-artifact metadata.",
        ]
    )


def queue_rework_status(
    client: GitHubReworkClient,
    result: dict[str, Any],
    *,
    request_id: str,
    run_url: str,
) -> int:
    _validate_run_url(run_url, client.repository)
    pr_number = result.get("pr_number")
    if not isinstance(pr_number, int) or pr_number <= 0:
        raise ValueError("The PR rework pull request number is invalid.")
    comment = client.create_issue_comment(
        pr_number,
        running_status_body(result, request_id, run_url),
    )
    comment_id = comment.get("id")
    if not isinstance(comment_id, int) or comment_id <= 0:
        raise RuntimeError("GitHub did not return a valid PR status comment ID.")
    return comment_id


def finalize_rework_status(
    client: GitHubReworkClient,
    *,
    pr_number: int,
    comment_id: int,
    request_id: str,
    outcome: str,
    run_url: str,
) -> None:
    _validate_request_id(request_id)
    _validate_run_url(run_url, client.repository)
    if pr_number <= 0 or comment_id <= 0:
        raise ValueError("The PR rework status identifiers must be positive integers.")
    comment = client.get_issue_comment(comment_id)
    body = comment.get("body")
    issue_url = comment.get("issue_url")
    expected_issue_suffix = f"/repos/{client.repository}/issues/{pr_number}"
    request_marker = f"request={request_id}"
    if _login(comment.get("user")).lower() != BOT_LOGIN:
        raise RuntimeError("Refusing to replace a PR status comment not owned by GitHub Actions.")
    if not isinstance(issue_url, str) or not issue_url.endswith(expected_issue_suffix):
        raise RuntimeError("Refusing to replace a PR status comment from another pull request.")
    if not isinstance(body, str) or request_marker not in body:
        raise RuntimeError("Refusing to replace a PR status comment for another request.")
    if COMPLETED_MARKER in body:
        return
    if ACTIVE_MARKER not in body:
        raise RuntimeError("Refusing to replace a PR status comment that is not active.")
    client.update_issue_comment(
        comment_id,
        completed_status_body(request_id, outcome, run_url),
    )


def _write_github_outputs(path: Path, values: dict[str, Any]) -> None:
    safe_keys = (
        "eligible",
        "reason",
        "trigger",
        "pr_number",
        "target_issue",
        "actor",
        "lane",
        "base_branch",
        "head_ref",
        "comment_id",
    )
    lines = []
    for key in safe_keys:
        value = values.get(key, "")
        if isinstance(value, bool):
            value = str(value).lower()
        lines.append(f"{key}={value}")
    with path.open("a", encoding="utf-8") as output:
        output.write("\n".join(lines) + "\n")


def render_resolution_markdown(result: dict[str, Any]) -> str:
    lines = ["## Azure BYOK PR rework", "", f"- Eligible: `{str(result['eligible']).lower()}`"]
    lines.append(f"- Decision: {result['reason']}")
    if result["eligible"]:
        lines.extend(
            [
                f"- Pull request: `#{result['pr_number']}`",
                f"- Source issue: `#{result['target_issue']}`",
                f"- Trigger: `{result['trigger']}`",
                f"- Lane: `{result['lane']}`",
                "- Bounded review requirements: captured",
            ]
        )
    return "\n".join(lines) + "\n"


def _result_file(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("The PR rework resolution file is invalid.")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage Azure BYOK PR rework events.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    resolve = subparsers.add_parser("resolve")
    resolve.add_argument("--event", type=Path, required=True)
    resolve.add_argument("--event-name", required=True)
    resolve.add_argument("--repository", required=True)
    resolve.add_argument("--actor", required=True)
    resolve.add_argument("--output", type=Path, required=True)
    resolve.add_argument("--github-output", type=Path, required=True)

    queue = subparsers.add_parser("queue-status")
    queue.add_argument("--result", type=Path, required=True)
    queue.add_argument("--repository", required=True)
    queue.add_argument("--request-id", required=True)
    queue.add_argument("--run-url", required=True)
    queue.add_argument("--github-output", type=Path, required=True)

    finalize = subparsers.add_parser("finalize-status")
    finalize.add_argument("--repository", required=True)
    finalize.add_argument("--pr-number", type=int, required=True)
    finalize.add_argument("--comment-id", type=int, required=True)
    finalize.add_argument("--request-id", required=True)
    finalize.add_argument("--outcome", required=True)
    finalize.add_argument("--run-url", required=True)

    args = parser.parse_args()

    client = GitHubApiClient.from_env(args.repository)

    if args.command == "resolve":
        payload = json.loads(args.event.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("The GitHub event payload is invalid.")
        result = resolve_rework_event(
            payload,
            event_name=args.event_name,
            repository=args.repository,
            actor=args.actor,
            client=client,
        )
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        _write_github_outputs(args.github_output, result)
        print(render_resolution_markdown(result), end="")
        return

    if args.command == "queue-status":
        result = _result_file(args.result)
        comment_id = queue_rework_status(
            client,
            result,
            request_id=args.request_id,
            run_url=args.run_url,
        )
        _write_github_outputs(args.github_output, {"comment_id": comment_id})
        return

    finalize_rework_status(
        client,
        pr_number=args.pr_number,
        comment_id=args.comment_id,
        request_id=args.request_id,
        outcome=args.outcome,
        run_url=args.run_url,
    )


if __name__ == "__main__":
    main()
