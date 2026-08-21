from __future__ import annotations

import copy
import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "manage_azure_pr_rework.py"
REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("manage_azure_pr_rework", SCRIPT_PATH)
assert SPEC is not None
pr_rework = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = pr_rework
SPEC.loader.exec_module(pr_rework)

NOW = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)
REPOSITORY = "example/azure-region-monitor"
ACTOR = "maintainer-user"


class FakeClient:
    repository = REPOSITORY

    def __init__(self) -> None:
        self.repository_payload = {
            "full_name": REPOSITORY,
            "default_branch": "main",
        }
        self.pull = {
            "number": 51,
            "state": "open",
            "user": {"login": "github-actions[bot]", "type": "Bot"},
            "head": {
                "ref": "azure-issues/issue-48",
                "repo": {"full_name": REPOSITORY},
            },
            "base": {"ref": "main", "repo": {"full_name": REPOSITORY}},
        }
        self.permission = "write"
        self.issue = {
            "number": 48,
            "state": "open",
            "labels": [{"name": "azure-backlog"}, {"name": "azure-recurring"}],
        }
        self.comments: list[dict] = []
        self.created_comments: list[tuple[int, str]] = []
        self.updated_comments: list[tuple[int, str]] = []
        self.status_comment = {
            "id": 700,
            "user": {"login": "github-actions[bot]"},
            "issue_url": f"https://api.github.com/repos/{REPOSITORY}/issues/51",
            "body": "<!-- azure-byok-rework:running request=100-1 -->\nQueued",
        }

    def get_repository(self):
        return copy.deepcopy(self.repository_payload)

    def get_pull_request(self, number):
        assert number == 51
        return copy.deepcopy(self.pull)

    def get_permission(self, login):
        assert login == ACTOR
        return self.permission

    def get_issue(self, number):
        assert number == 48
        return copy.deepcopy(self.issue)

    def list_issue_comments(self, number):
        assert number == 51
        return copy.deepcopy(self.comments)

    def get_issue_comment(self, comment_id):
        assert comment_id == 700
        return copy.deepcopy(self.status_comment)

    def create_issue_comment(self, number, body):
        self.created_comments.append((number, body))
        return {"id": 700}

    def update_issue_comment(self, comment_id, body):
        self.updated_comments.append((comment_id, body))
        self.status_comment["body"] = body
        return copy.deepcopy(self.status_comment)


def _comment_event(body: str = "/agent-rework") -> dict:
    return {
        "action": "created",
        "sender": {"login": ACTOR, "type": "User"},
        "issue": {"number": 51, "pull_request": {"url": "https://api.test/pulls/51"}},
        "comment": {"id": 900, "body": body},
    }


def _review_event(
    state: str = "changes_requested",
    body: str = "Keep the provider-specific payload behavior isolated.",
) -> dict:
    return {
        "action": "submitted",
        "sender": {"login": ACTOR, "type": "User"},
        "pull_request": {"number": 51},
        "review": {"id": 901, "state": state, "body": body},
    }


def _resolve(payload: dict, event_name: str, client: FakeClient | None = None):
    return pr_rework.resolve_rework_event(
        payload,
        event_name=event_name,
        repository=REPOSITORY,
        actor=ACTOR,
        client=client or FakeClient(),
        now=NOW,
    )


def test_slash_command_dispatches_same_repo_bot_pr():
    result = _resolve(_comment_event(), "issue_comment")

    assert result == {
        "eligible": True,
        "reason": (
            "Eligible collaborator feedback will be dispatched to the existing Azure BYOK "
            "runner."
        ),
        "trigger": "slash-command",
        "pr_number": 51,
        "target_issue": 48,
        "actor": ACTOR,
        "lane": "aider",
        "base_branch": "main",
        "head_ref": "azure-issues/issue-48",
        "rework_requirements": (
            "Address the current requested changes on this pull request within the existing "
            "derived scope. Do not report successful rework without a validated branch change."
        ),
    }


def test_slash_command_captures_only_bounded_requirement_text():
    result = _resolve(
        _comment_event("/agent-rework\nUse a provider-specific helper and retain Azure behavior."),
        "issue_comment",
    )

    assert result["rework_requirements"] == (
        "Use a provider-specific helper and retain Azure behavior."
    )


def test_slash_command_must_be_the_first_comment_token():
    result = _resolve(
        _comment_event("Please run /agent-rework after checking this."),
        "issue_comment",
    )

    assert result["eligible"] is False
    assert result["reason"] == "The comment does not begin with /agent-rework."


def test_request_changes_review_dispatches_rework():
    result = _resolve(_review_event(), "pull_request_review")

    assert result["eligible"] is True
    assert result["trigger"] == "request-changes"
    assert result["target_issue"] == 48
    assert result["rework_requirements"] == (
        "Keep the provider-specific payload behavior isolated."
    )


def test_non_blocking_review_does_not_dispatch_rework():
    result = _resolve(_review_event("commented"), "pull_request_review")

    assert result["eligible"] is False
    assert result["reason"] == "The submitted review did not request changes."


@pytest.mark.parametrize("permission", ["read", "triage", "none", ""])
def test_requester_requires_write_level_permission(permission: str):
    client = FakeClient()
    client.permission = permission

    result = _resolve(_comment_event(), "issue_comment", client)

    assert result["eligible"] is False
    assert "write-level" in result["reason"]


def test_bot_or_confused_deputy_event_is_rejected():
    bot_event = _comment_event()
    bot_event["sender"] = {"login": "github-actions[bot]", "type": "Bot"}
    bot_result = pr_rework.resolve_rework_event(
        bot_event,
        event_name="issue_comment",
        repository=REPOSITORY,
        actor="github-actions[bot]",
        client=FakeClient(),
        now=NOW,
    )
    mismatched_result = pr_rework.resolve_rework_event(
        _comment_event(),
        event_name="issue_comment",
        repository=REPOSITORY,
        actor="different-user",
        client=FakeClient(),
        now=NOW,
    )

    assert bot_result["eligible"] is False
    assert mismatched_result["eligible"] is False


@pytest.mark.parametrize(
    ("mutation", "reason_fragment"),
    [
        (lambda pull: pull.update(state="closed"), "open pull requests"),
        (
            lambda pull: pull["head"].update(repo={"full_name": "fork/repository"}),
            "Forked or cross-repository",
        ),
        (lambda pull: pull["base"].update(ref="release"), "default branch"),
        (lambda pull: pull.update(user={"login": "human"}), "GitHub Actions"),
        (lambda pull: pull["head"].update(ref="feature/arbitrary"), "Azure issue branch"),
    ],
)
def test_only_expected_bot_pull_request_shape_is_eligible(mutation, reason_fragment):
    client = FakeClient()
    mutation(client.pull)

    result = _resolve(_comment_event(), "issue_comment", client)

    assert result["eligible"] is False
    assert reason_fragment in result["reason"]


@pytest.mark.parametrize(
    "issue_update",
    [
        {"state": "closed"},
        {"labels": [{"name": "bug"}]},
        {"labels": [{"name": "azure-backlog"}, {"name": "azure-paused"}]},
    ],
)
def test_source_issue_must_remain_eligible(issue_update):
    client = FakeClient()
    client.issue.update(issue_update)

    result = _resolve(_comment_event(), "issue_comment", client)

    assert result["eligible"] is False
    assert "source issue" in result["reason"].lower()


def test_recent_running_status_deduplicates_but_stale_status_does_not():
    client = FakeClient()
    client.comments = [
        {
            "user": {"login": "github-actions[bot]"},
            "body": "<!-- azure-byok-rework:running request=99-1 -->",
            "created_at": (NOW - timedelta(minutes=10)).isoformat(),
        }
    ]

    active_result = _resolve(_comment_event(), "issue_comment", client)
    client.comments[0]["created_at"] = (NOW - timedelta(hours=3)).isoformat()
    stale_result = _resolve(_comment_event(), "issue_comment", client)

    assert active_result["eligible"] is False
    assert "already active" in active_result["reason"]
    assert stale_result["eligible"] is True


def test_status_comment_is_created_and_finalized_idempotently():
    client = FakeClient()
    result = _resolve(_comment_event(), "issue_comment", client)
    dispatcher_url = f"https://github.com/{REPOSITORY}/actions/runs/100"
    task_url = f"https://github.com/{REPOSITORY}/actions/runs/101"

    comment_id = pr_rework.queue_rework_status(
        client,
        result,
        request_id="100-1",
        run_url=dispatcher_url,
    )
    pr_rework.finalize_rework_status(
        client,
        pr_number=51,
        comment_id=comment_id,
        request_id="100-1",
        outcome="success",
        run_url=task_url,
    )
    pr_rework.finalize_rework_status(
        client,
        pr_number=51,
        comment_id=comment_id,
        request_id="100-1",
        outcome="success",
        run_url=task_url,
    )

    assert comment_id == 700
    assert client.created_comments[0][0] == 51
    assert "azure-byok-rework:running" in client.created_comments[0][1]
    assert len(client.updated_comments) == 1
    assert "azure-byok-rework:completed" in client.updated_comments[0][1]
    assert "**success**" in client.updated_comments[0][1]


def test_status_finalizer_refuses_another_pr_or_request():
    client = FakeClient()
    client.status_comment["issue_url"] = (
        f"https://api.github.com/repos/{REPOSITORY}/issues/52"
    )

    with pytest.raises(RuntimeError, match="another pull request"):
        pr_rework.finalize_rework_status(
            client,
            pr_number=51,
            comment_id=700,
            request_id="100-1",
            outcome="failure",
            run_url=f"https://github.com/{REPOSITORY}/actions/runs/101",
        )


def test_dispatcher_wires_both_review_paths_without_azure_secrets():
    workflow = (REPO_ROOT / ".github/workflows/azure-pr-rework.yml").read_text(
        encoding="utf-8"
    )

    assert "issue_comment:" in workflow
    assert "pull_request_review:" in workflow
    assert "types: [submitted]" in workflow
    assert "azure-byok-pr-rework-${{ github.event.issue.number" in workflow
    assert "persist-credentials: false" in workflow
    assert "pull-requests: write" in workflow
    assert 'aider) event_type="azure-byok-pr-rework" ;;' in workflow
    assert 'agentic) event_type="azure-agentic-pr-rework" ;;' in workflow
    assert 'echo "Unsupported rework lane: $LANE" >&2; exit 1' in workflow
    assert "rework_requirements" in workflow
    assert "azure-pr-rework.json" in workflow
    assert "AZURE_OPENAI" not in workflow
    assert "secrets." not in workflow


def test_scheduled_workflow_accepts_only_targeted_rework_dispatch_metadata():
    workflow = (REPO_ROOT / ".github/workflows/scheduled-azure-backlog.yml").read_text(
        encoding="utf-8"
    )

    assert "repository_dispatch:" in workflow
    assert "types: [azure-byok-pr-rework]" in workflow
    assert "github.event.client_payload.target_issue" in workflow
    assert "github.event_name == 'repository_dispatch' || inputs.force" in workflow
    assert "Malformed automated PR rework dispatch metadata." in workflow
    assert '[[ ! "$TARGET_ISSUE" =~ ^[1-9][0-9]*$ ]]' in workflow
    assert '"${#REWORK_REQUIREMENTS}" -gt 4000' in workflow
    assert '--rework-context "$RUNNER_TEMP/azure-pr-rework-context.json"' in workflow
    assert 'args+=(--require-pr "$REWORK_PR")' in workflow
    assert "finalize-status" in workflow


@pytest.mark.parametrize(
    "head_ref,lane",
    [
        ("azure-issues/issue-48", "aider"),
        ("agentic/issue-48", "agentic"),
        ("agentic/issue-48-b4ed6f09bc21294c", "agentic"),
    ],
)
def test_both_lanes_resolve_to_their_own_runner(head_ref: str, lane: str):
    client = FakeClient()
    client.pull["head"]["ref"] = head_ref

    result = _resolve(_comment_event(), "issue_comment", client)

    assert result["eligible"] is True
    assert result["lane"] == lane
    assert result["target_issue"] == 48
    assert result["head_ref"] == head_ref


@pytest.mark.parametrize(
    "head_ref",
    [
        "agentic/issue-48-NOTHEX",
        "agentic/issue-0",
        "agentic/issue-48/extra",
        "agentic/main",
        "azure-issues/issue-48-b4ed6f09bc21294c",
        "feature/issue-48",
    ],
)
def test_branches_outside_either_lane_are_rejected(head_ref: str):
    client = FakeClient()
    client.pull["head"]["ref"] = head_ref

    result = _resolve(_comment_event(), "issue_comment", client)

    assert result["eligible"] is False
    assert result["reason"] == "The pull request branch is not an Azure issue branch."


def test_agentic_rework_workflow_bounds_pushes_to_the_reviewed_pull_request():
    source = (REPO_ROOT / ".github/workflows/agentic-pr-rework.md").read_text(
        encoding="utf-8"
    )
    scheduled = (REPO_ROOT / ".github/workflows/scheduled-agentic-backlog.md").read_text(
        encoding="utf-8"
    )
    lock = (REPO_ROOT / ".github/workflows/agentic-pr-rework.lock.yml").read_text(
        encoding="utf-8"
    )

    assert "types: [azure-agentic-pr-rework]" in source
    assert "Malformed agentic PR rework dispatch metadata." in source
    assert '"${#REWORK_REQUIREMENTS}" -gt 4000' in source
    assert '^agentic/issue-[1-9][0-9]*(-[0-9a-f]{6,32})?$' in source
    assert "push-to-pull-request-branch:" in source
    assert 'required-title-prefix: "[agentic] "' in source
    assert "required-labels: [scheduled-agent]" in source
    assert "if-no-changes: error" in source
    assert "protected-files: fallback-to-issue" in source
    assert "create-pull-request" not in source
    assert "allowed-files:" not in source
    assert "A rework that changes nothing is a failure, not a success." in source
    assert "A source behavior change requires a focused regression test" in source
    assert "secrets.AZURE_CODING_OPENAI_KEY" in source
    rework_agent = source.split("\nmodel: ", 1)[1].split("\nsandbox:", 1)[0]
    scheduled_agent = scheduled.split("\nmodel: ", 1)[1].split("\nsandbox:", 1)[0]
    assert rework_agent == scheduled_agent
    assert '"agent_model":"gpt-5.6-terra"' in lock
    assert '"protected_files_policy":"fallback-to-issue"' in lock


def test_agentic_rework_status_follower_closes_the_dispatcher_comment():
    follower = (REPO_ROOT / ".github/workflows/agentic-pr-rework-status.yml").read_text(
        encoding="utf-8"
    )

    assert 'workflows: ["Agentic PR rework"]' in follower
    assert "persist-credentials: false" in follower
    assert "agentic-rework-status" in follower
    assert "Malformed agentic rework status identifiers." in follower
    assert "finalize-status" in follower
    assert "secrets." not in follower
