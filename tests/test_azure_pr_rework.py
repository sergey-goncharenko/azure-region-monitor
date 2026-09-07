from __future__ import annotations

import copy
import importlib.util
import json
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
        if number == 52:
            return {
                "number": 52,
                "html_url": f"https://github.com/{REPOSITORY}/issues/52",
                "user": {"login": "github-actions[bot]"},
            }
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


def _comment_event(body: str = "Please retain provider-specific behavior.") -> dict:
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


def test_pr_comment_is_context_only_and_does_not_dispatch():
    result = _resolve(_comment_event(), "issue_comment")

    assert result["eligible"] is False
    assert result["reason"] == (
        "PR comments are context only; submit a Request changes review to rework."
    )


def test_request_changes_review_dispatches_rework():
    result = _resolve(_review_event(), "pull_request_review")

    assert result["eligible"] is True
    assert result["trigger"] == "request-changes"
    assert result["target_issue"] == 48
    assert result["rework_requirements"] == (
        "Keep the provider-specific payload behavior isolated."
    )


def test_commented_review_does_not_dispatch_rework():
    result = _resolve(
        _review_event(
            "commented",
            "Fix the failing RSS authored-excerpt regression.",
        ),
        "pull_request_review",
    )

    assert result["eligible"] is False


@pytest.mark.parametrize("state", ["commented", "approved", "dismissed"])
def test_non_blocking_review_does_not_dispatch_rework(state):
    result = _resolve(_review_event(state), "pull_request_review")

    assert result["eligible"] is False
    assert result["reason"] == "The submitted review did not request changes."


@pytest.mark.parametrize("permission", ["read", "triage", "none", ""])
def test_requester_requires_write_level_permission(permission: str):
    client = FakeClient()
    client.permission = permission

    result = _resolve(_review_event(), "pull_request_review", client)

    assert result["eligible"] is False
    assert "write-level" in result["reason"]


def test_bot_or_confused_deputy_event_is_rejected():
    bot_event = _review_event()
    bot_event["sender"] = {"login": "github-actions[bot]", "type": "Bot"}
    bot_result = pr_rework.resolve_rework_event(
        bot_event,
        event_name="pull_request_review",
        repository=REPOSITORY,
        actor="github-actions[bot]",
        client=FakeClient(),
        now=NOW,
    )
    mismatched_result = pr_rework.resolve_rework_event(
        _review_event(),
        event_name="pull_request_review",
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

    result = _resolve(_review_event(), "pull_request_review", client)

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

    result = _resolve(_review_event(), "pull_request_review", client)

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

    active_result = _resolve(_review_event(), "pull_request_review", client)
    client.comments[0]["created_at"] = (NOW - timedelta(hours=3)).isoformat()
    stale_result = _resolve(_review_event(), "pull_request_review", client)

    assert active_result["eligible"] is False
    assert "already active" in active_result["reason"]
    assert stale_result["eligible"] is True


def test_status_comment_is_created_and_finalized_idempotently():
    client = FakeClient()
    result = _resolve(_review_event(), "pull_request_review", client)
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


def test_dispatcher_wires_request_changes_without_azure_secrets():
    workflow = (REPO_ROOT / ".github/workflows/azure-pr-rework.yml").read_text(
        encoding="utf-8"
    )

    assert "issue_comment:" not in workflow
    assert "pull_request_review:" in workflow
    assert "types: [submitted]" in workflow
    assert "azure-byok-pr-rework-${{ github.event.pull_request.number" in workflow
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

    result = _resolve(_review_event(), "pull_request_review", client)

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

    result = _resolve(_review_event(), "pull_request_review", client)

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
    assert 'bots: ["github-actions[bot]"]' in source
    assert "Malformed agentic PR rework dispatch metadata." in source
    assert '"${#REWORK_REQUIREMENTS}" -gt 4000' in source
    assert '^agentic/issue-[1-9][0-9]*(-[0-9a-f]{6,32})?$' in source
    assert "push-to-pull-request-branch:" in source
    assert 'required-title-prefix: "[agentic] "' in source
    assert "required-labels: [scheduled-agent]" in source
    assert "request-changes) ;;" in source
    assert "slash-command" not in source
    assert "validation-failure" not in source
    assert "if-no-changes: error" in source
    assert "protected-files: fallback-to-issue" in source
    assert "create-pull-request" not in source
    assert "allowed-files:" not in source
    assert "A rework that changes nothing is a failure, not a success." in source
    assert "A source behavior change requires a focused regression test" in source
    assert "Run `pytest`, `ruff check .`, and `git diff --check` directly" in source
    assert "independent publication gate" in source
    assert "conclusion:" in source
    assert "Finalize the rework status comment" in source
    assert "SAFE_OUTPUTS_RESULT: ${{ needs.safe_outputs.result }}" in source
    assert "scripts/manage_azure_pr_rework.py finalize-agentic-status" in source
    assert "detection:\n    needs: [prepare]" in source
    assert "      - prepare\n" in lock
    assert "secrets.AZURE_CODING_OPENAI_KEY" in source
    rework_agent = source.split("\nmodel: ", 1)[1].split("\nsandbox:", 1)[0]
    scheduled_agent = scheduled.split("\nmodel: ", 1)[1].split("\nsandbox:", 1)[0]
    assert rework_agent == scheduled_agent
    assert '"agent_model":"${{ vars.AZWATCH_AGENTIC_MODEL }}"' in lock
    assert 'GH_AW_ALLOWED_BOTS: "github-actions[bot]"' in lock
    assert '\\"protected_files_policy\\":\\"fallback-to-issue\\"' in lock


def test_agentic_rework_can_file_follow_up_backlog_work_without_a_code_change():
    source = (REPO_ROOT / ".github/workflows/agentic-pr-rework.md").read_text(encoding="utf-8")
    lock = (REPO_ROOT / ".github/workflows/agentic-pr-rework.lock.yml").read_text(encoding="utf-8")

    assert "create-issue:" in source
    assert 'title-prefix: "[azure-backlog] "' in source
    assert "labels: [azure-backlog, scheduled-agent]" in source
    assert "max: 1" in source
    assert '\\"title_prefix\\":\\"[azure-backlog] \\"' in lock
    # A no-code rework still fails unless the reviewer's request was filed as an issue.
    assert 'select(.type == "create_issue")' in source
    assert "A rework that changes nothing is a failure, not a success." in source
    assert "call `create_issue` exactly once instead of pushing" in source
    assert "The scheduled selector parses a strict issue template." in source
    assert "### Priority" in source
    assert "### Objective" in source
    assert "### Context or acceptance evidence" in source


def test_no_dead_workflow_run_follower_for_the_bot_dispatched_rework():
    # workflow_run never fires for a run attributed to github-actions[bot], and the
    # conclusion job finalizes the status comment instead.
    assert not (REPO_ROOT / ".github/workflows/agentic-pr-rework-status.yml").exists()


def _agentic_publication():
    client = FakeClient()
    client.pull["head"].update(ref="agentic/issue-48-abcdef", sha="b" * 40)
    status = {
        "pr_number": "51",
        "comment_id": "700",
        "request_id": "100-1",
        "head_ref": "agentic/issue-48-abcdef",
        "head_sha": "a" * 40,
        "base_ref": "main",
    }
    evidence = {
        "AGENT_RESULT": "success",
        "DETECTION_RESULT": "success",
        "DETECTION_CONCLUSION": "success",
        "DETECTION_SUCCESS": "true",
        "DETECTION_REASON": "",
        "SAFE_OUTPUTS_RESULT": "success",
        "PUBLICATION_STATUS": "success",
        "PUBLICATION_FAILURES": "0",
        "PUSH_COMMIT_SHA": "b" * 40,
    }
    publication = [{
        "type": "push_to_pull_request_branch",
        "number": 51,
        "url": f"https://github.com/{REPOSITORY}/pull/51",
    }]
    return client, status, evidence, publication


def _evaluate_publication(client, status, evidence, publication):
    return pr_rework.evaluate_agentic_publication(
        client, status=status, evidence=evidence, publication=publication,
    )


def test_same_branch_update_requires_the_live_safe_output_commit():
    client, status, evidence, publication = _agentic_publication()
    outcome, details = _evaluate_publication(client, status, evidence, publication)
    assert outcome == "success"
    assert "on the same [PR #51]" in details
    assert f"/commit/{'b' * 40}" in details


@pytest.mark.parametrize(
    ("live_sha", "push_sha"),
    [
        ("a" * 40, "b" * 40),  # Original branch was not updated.
        ("c" * 40, "b" * 40),  # An unrelated concurrent update is not our publication.
        ("b" * 40, ""),  # Live movement alone is not evidence of a safe-output push.
        ("a" * 40, "a" * 40),  # No new commit.
        ("b" * 40, "not-a-commit"),
    ],
)
def test_green_jobs_do_not_prove_a_same_pr_update(live_sha, push_sha):
    client, status, evidence, publication = _agentic_publication()
    client.pull["head"]["sha"] = live_sha
    evidence["PUSH_COMMIT_SHA"] = push_sha
    outcome, details = _evaluate_publication(client, status, evidence, publication)
    assert outcome == "blocked"
    assert "No new safe-output commit" in details


@pytest.mark.parametrize(
    "evidence_update",
    [
        # The exact PR119/120 failure: detector installation failed, but jobs were green.
        {"DETECTION_CONCLUSION": "warning", "DETECTION_SUCCESS": "false",
         "DETECTION_REASON": "agent_failure"},
        # Explicit fail-closed installation failure.
        {"DETECTION_RESULT": "failure", "DETECTION_CONCLUSION": "failure",
         "DETECTION_SUCCESS": "false", "DETECTION_REASON": "agent_failure",
         "SAFE_OUTPUTS_RESULT": "skipped"},
        {"DETECTION_RESULT": "failure"},  # Independent validation failed after detection.
        {"DETECTION_SUCCESS": ""},
        {"DETECTION_CONCLUSION": "skipped"},  # A code update cannot skip detection.
        {"PUBLICATION_STATUS": "completed_with_warnings"},
        {"PUBLICATION_STATUS": "completed_with_skips"},
        {"PUBLICATION_FAILURES": "1"},
        {"PUBLICATION_FAILURES": ""},
        {"SAFE_OUTPUTS_RESULT": "failure"},
        {"AGENT_RESULT": "failure"},
    ],
)
def test_failed_or_unverified_gates_block_even_when_a_commit_is_reported(evidence_update):
    client, status, evidence, publication = _agentic_publication()
    evidence.update(evidence_update)
    outcome, _ = _evaluate_publication(client, status, evidence, publication)
    assert outcome == "blocked"


@pytest.mark.parametrize(
    "publication",
    [
        [],
        [{"type": "push_to_pull_request_branch"}],  # Runtime review-PR diversion manifest.
        [{"type": "push_to_pull_request_branch", "number": 52,
          "url": f"https://github.com/{REPOSITORY}/pull/52"}],
        [{"type": "create_pull_request", "number": 52,
          "url": f"https://github.com/{REPOSITORY}/pull/52"}],
    ],
)
def test_missing_or_review_pr_publication_is_not_same_pr_success(publication):
    client, status, evidence, _ = _agentic_publication()
    outcome, _ = _evaluate_publication(client, status, evidence, publication)
    assert outcome == "blocked"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda pull: pull.update(state="closed"),
        lambda pull: pull["head"].update(ref="agentic/issue-48-abcdef-review-123"),
        lambda pull: pull["head"].update(repo={"full_name": "other/repository"}),
        lambda pull: pull["base"].update(ref="release"),
    ],
)
def test_finalizer_revalidates_live_pull_request_identity(mutation):
    client, status, evidence, publication = _agentic_publication()
    mutation(client.pull)
    outcome, details = _evaluate_publication(client, status, evidence, publication)
    assert outcome == "blocked"
    assert "no longer matches" in details


@pytest.mark.parametrize("detection_conclusion", ["success", "skipped"])
def test_follow_up_issue_is_distinct_from_branch_update(detection_conclusion):
    client, status, evidence, _ = _agentic_publication()
    client.pull["head"]["sha"] = status["head_sha"]
    evidence.update(PUSH_COMMIT_SHA="", DETECTION_CONCLUSION=detection_conclusion)
    publication = [{
        "type": "create_issue", "number": 52,
        "url": f"https://github.com/{REPOSITORY}/issues/52",
    }]
    outcome, details = _evaluate_publication(client, status, evidence, publication)
    assert outcome == "follow-up-created"
    assert "[follow-up issue #52]" in details
    assert "was not updated" in details


def test_protected_file_issue_is_reported_as_blocked_not_a_branch_update():
    client, status, evidence, publication = _agentic_publication()
    client.pull["head"]["sha"] = status["head_sha"]
    evidence["PUSH_COMMIT_SHA"] = ""
    publication[0].update(number=52, url=f"https://github.com/{REPOSITORY}/issues/52")
    outcome, details = _evaluate_publication(client, status, evidence, publication)
    assert outcome == "blocked"
    assert "Protected-file changes" in details
    assert "[issue #52]" in details
    assert "was not updated" in details


def test_follow_up_must_be_a_real_issue_not_a_pull_request(monkeypatch):
    client, status, evidence, _ = _agentic_publication()
    client.pull["head"]["sha"] = status["head_sha"]
    evidence["PUSH_COMMIT_SHA"] = ""
    issue = client.get_issue(52)
    issue["pull_request"] = {"url": f"https://api.github.com/repos/{REPOSITORY}/pulls/52"}
    monkeypatch.setattr(client, "get_issue", lambda number: issue)
    publication = [{
        "type": "create_issue", "number": 52,
        "url": f"https://github.com/{REPOSITORY}/issues/52",
    }]
    outcome, details = _evaluate_publication(client, status, evidence, publication)
    assert outcome == "blocked"
    assert "verified as a bot-created issue" in details


def test_failed_detector_finalizes_blocked_with_patch_artifact_link(tmp_path):
    client, status, evidence, _ = _agentic_publication()
    evidence.update(DETECTION_RESULT="failure", DETECTION_CONCLUSION="failure",
                    DETECTION_SUCCESS="false", DETECTION_REASON="agent_failure",
                    SAFE_OUTPUTS_RESULT="skipped", PUSH_COMMIT_SHA="")
    outcome = pr_rework.finalize_agentic_rework_status(
        client, status=status, publication_path=tmp_path / "missing.jsonl",
        evidence=evidence, run_url=f"https://github.com/{REPOSITORY}/actions/runs/101",
    )
    assert outcome == "blocked"
    body = client.updated_comments[0][1]
    assert "**blocked**" in body
    assert "agent_failure" in body
    assert "agentic-rework-patch" in body
    assert "/actions/runs/101#artifacts" in body
    assert "No replacement PR is authorized" in body
    assert "refreshed rationale" not in body


def test_verified_publication_finalizer_is_idempotent(tmp_path):
    client, status, evidence, publication = _agentic_publication()
    path = tmp_path / "safe-output-items.jsonl"
    path.write_text(json.dumps(publication[0]) + "\n", encoding="utf-8")
    for _ in range(2):
        outcome = pr_rework.finalize_agentic_rework_status(
            client, status=status, publication_path=path, evidence=evidence,
            run_url=f"https://github.com/{REPOSITORY}/actions/runs/101",
        )
        assert outcome == "success"
    assert len(client.updated_comments) == 1
    assert "Verified commit" in client.updated_comments[0][1]


@pytest.mark.parametrize(
    "contents", ["invalid JSON", "[]\n", " " * 65_537], ids=["invalid-json", "array", "oversize"],
)
def test_malformed_publication_evidence_fails_closed(tmp_path, contents):
    client, status, evidence, _ = _agentic_publication()
    path = tmp_path / "safe-output-items.jsonl"
    path.write_text(contents, encoding="utf-8")
    outcome = pr_rework.finalize_agentic_rework_status(
        client, status=status, publication_path=path, evidence=evidence,
        run_url=f"https://github.com/{REPOSITORY}/actions/runs/101",
    )
    assert outcome == "blocked"
    assert "**blocked**" in client.updated_comments[0][1]


def test_live_target_read_failure_is_reported_as_blocked(tmp_path, monkeypatch):
    client, status, evidence, publication = _agentic_publication()
    path = tmp_path / "safe-output-items.jsonl"
    path.write_text(json.dumps(publication[0]) + "\n", encoding="utf-8")

    def unavailable(number):
        raise RuntimeError("GitHub read failed")

    monkeypatch.setattr(client, "get_pull_request", unavailable)
    outcome = pr_rework.finalize_agentic_rework_status(
        client, status=status, publication_path=path, evidence=evidence,
        run_url=f"https://github.com/{REPOSITORY}/actions/runs/101",
    )
    assert outcome == "blocked"
    assert "live target could not be verified" in client.updated_comments[0][1]


@pytest.mark.parametrize("updated", [True, False])
def test_agentic_finalizer_cli_fails_visibly_after_posting_blocked_status(
    tmp_path, monkeypatch, updated,
):
    client, status, evidence, publication = _agentic_publication()
    if not updated:
        client.pull["head"]["sha"] = status["head_sha"]
    status_path = tmp_path / "status.json"
    publication_path = tmp_path / "safe-output-items.jsonl"
    status_path.write_text(json.dumps(status), encoding="utf-8")
    publication_path.write_text(json.dumps(publication[0]) + "\n", encoding="utf-8")
    monkeypatch.setattr(pr_rework.GitHubApiClient, "from_env", lambda repository: client)
    for name, value in evidence.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(sys, "argv", [
        "manage_azure_pr_rework.py", "finalize-agentic-status",
        "--repository", REPOSITORY, "--status", str(status_path),
        "--publication", str(publication_path),
        "--run-url", f"https://github.com/{REPOSITORY}/actions/runs/101",
    ])
    if updated:
        pr_rework.main()
        assert "**success**" in client.updated_comments[0][1]
    else:
        with pytest.raises(SystemExit) as error:
            pr_rework.main()
        assert error.value.code == 1
        assert "**blocked**" in client.updated_comments[0][1]


def test_agentic_rework_lock_fails_closed_and_retains_only_the_candidate_patch():
    source = (REPO_ROOT / ".github/workflows/agentic-pr-rework.md").read_text(encoding="utf-8")
    lock = (REPO_ROOT / ".github/workflows/agentic-pr-rework.lock.yml").read_text(encoding="utf-8")
    assert "threat-detection:\n    continue-on-error: false" in source
    assert "fallback-as-pull-request: false" in source
    assert '\\"fallback_as_pull_request\\":false' in lock
    detection = lock.split("\n  detection:\n", 1)[1].split("\n  pre_activation:\n", 1)[0]
    assert 'GH_AW_DETECTION_CONTINUE_ON_ERROR: "false"' in detection
    assert 'GH_AW_DETECTION_CONTINUE_ON_ERROR: "true"' not in detection
    conclusion = detection.split("- name: Conclude threat detection", 1)[1]
    assert "continue-on-error: true" not in conclusion
    retention = detection.split("- name: Retain candidate patch for blocked rework", 1)[1]
    retention = retention.split("\n      - ", 1)[0]
    assert "if: ${{ always() }}" in retention
    assert "name: agentic-rework-patch" in retention
    assert "path: /tmp/gh-aw/threat-detection/aw*.patch" in retention
    assert "retention-days: 7" in retention
    assert detection.index("Retain candidate patch") < detection.index("Apply candidate patch")
    safe_outputs = lock.split("\n  safe_outputs:\n", 1)[1]
    gate = safe_outputs.split("- name: Require semantic detection success before publication", 1)[1]
    assert gate.index('case "$DETECTION_CONCLUSION/$DETECTION_SUCCESS"') < gate.index(
        "id: process_safe_outputs"
    )
    assert "success/true) ;;" in gate
    assert '*) echo "Rework publication blocked:' in gate
    assert "(.items | length == 1)" in gate
    assert "(.pull_request_number | tostring) == $pr" in gate
    assert "(.repo == null or .repo == $repo)" in gate
    assert "REWORK_PR: ${{ needs.prepare.outputs.pr_number }}" in gate
    assert "      - prepare\n" in safe_outputs.split("\n    steps:\n", 1)[0]
    assert "protected-files: fallback-to-issue" in source
    assert "create-issue:" in source
    for name in ("DETECTION_CONCLUSION", "DETECTION_SUCCESS", "PUBLICATION_STATUS",
                 "PUBLICATION_FAILURES", "PUSH_COMMIT_SHA"):
        assert f"{name}: ${{{{ needs." in source
    assert '--arg head_sha "$HEAD_SHA"' in source
    assert "finalize-agentic-status" in lock
    finalizer = lock.split("\n  conclusion:\n", 1)[1].split("\n  detection:\n", 1)[0]
    assert "pull-requests: read" in finalizer
