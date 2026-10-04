from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "record_azure_agentic_outcome.py"
SPEC = importlib.util.spec_from_file_location("record_azure_agentic_outcome", SCRIPT_PATH)
assert SPEC is not None
outcome = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = outcome
SPEC.loader.exec_module(outcome)

RUN_URL = "https://github.com/example/repo/actions/runs/1"
REPOSITORY = "example/repo"
SELECTION = {
    "issue_number": 132,
    "repository": REPOSITORY,
    "run_id": "1",
    "run_attempt": 1,
    "head_sha": "a" * 40,
    "selected_at": "2026-10-04T06:23:00+00:00",
    "clarification": {},
}


def _comment(comment_id, body, login="github-actions[bot]", user_type="Bot"):
    return {
        "id": comment_id,
        "html_url": f"https://github.com/{REPOSITORY}/issues/132#issuecomment-{comment_id}",
        "user": {"login": login, "type": user_type},
        "body": body,
    }


def _receipt(kind="add_comment", number=132):
    return {
        "type": kind,
        "number": number,
        "repo": REPOSITORY,
        "url": (
            f"https://github.com/{REPOSITORY}/pull/{number}" if kind == "create_pull_request"
            else f"https://github.com/{REPOSITORY}/issues/132#issuecomment-20"
        ),
        "timestamp": "2026-10-04T06:30:00Z",
    }


def _classify(conclusion="success", receipts=None, requests=None, comments=None):
    return outcome.classify_outcome(
        conclusion, SELECTION, receipts or [], requests or [], comments or [], REPOSITORY,
    )


def _waiting_comment():
    return _comment(20, "<!-- azure-agentic-waiting:issue-132 -->\nWhich integration should a human own?")


def _mock_github(monkeypatch, comments):
    def api(endpoint, *args, payload=None):
        if "/collaborators/" in endpoint:
            return {"permission": "write" if "/maintainer/" in endpoint else "read"}
        if payload is not None:
            if "PATCH" in args:
                number = int(endpoint.rsplit("/", 1)[1])
                next(item for item in comments if item["id"] == number)["body"] = payload["body"]
            else:
                comments.append(_comment(max([item["id"] for item in comments] or [0]) + 1, payload["body"]))
            return {}
        if "/comments?" in endpoint:
            return [comments]
        raise AssertionError(endpoint)
    monkeypatch.setattr(outcome, "_gh_json", api)


def test_green_question_receipt_waits_and_unchanged_issue_stays_ineligible(monkeypatch):
    comments = [_waiting_comment()]
    _mock_github(monkeypatch, comments)
    terminal = _classify(receipts=[_receipt()], comments=comments)
    assert terminal == "waiting-for-maintainer"
    outcome.write_state(REPOSITORY, {**SELECTION, "status": terminal}, RUN_URL)

    for _ in range(13):
        prepared = outcome.queue_state([{"number": 132}], REPOSITORY)[132]
        assert prepared["waiting"] is True
    assert outcome.find_marker_comment(comments) == (None, 0)


def test_new_maintainer_reply_is_consumed_once_before_evaluation(monkeypatch):
    comments = [_comment(21, outcome.state_body({**SELECTION, "status": "waiting-for-maintainer"}, RUN_URL))]
    comments.append(_comment(22, "Implement the independent code slice; leave integration to me.", "maintainer", "User"))
    _mock_github(monkeypatch, comments)
    prepared = outcome.queue_state([{"number": 132}], REPOSITORY)[132]
    assert prepared["waiting"] is False
    assert prepared["clarification"]["id"] == 22
    assert len(prepared["clarification"]["digest"]) == 64
    assert "independent code slice" in prepared["clarification_context"]
    for key, value in {"GITHUB_RUN_ID": "2", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SHA": "b" * 40}.items():
        monkeypatch.setenv(key, value)
    selection = outcome.reserve_selection(
        {"tasks": [{"issue_number": 132, "agentic_queue": prepared}]}, REPOSITORY,
    )
    assert selection["clarification"] == prepared["clarification"]
    assert outcome.queue_state([{"number": 132}], REPOSITORY)[132]["waiting"] is True
    # Crashes and missing followers do not spend the same reply twice.
    assert outcome.find_state(comments, 132)["status"] == "evaluating-clarification"
    comments[-1]["body"] = "Another concrete clarification."
    assert outcome.queue_state([{"number": 132}], REPOSITORY)[132]["waiting"] is False


@pytest.mark.parametrize("login,user_type", [("github-actions[bot]", "Bot"), ("outsider", "User")])
def test_bot_and_unauthorized_replies_do_not_requeue(monkeypatch, login, user_type):
    comments = [
        _comment(21, outcome.state_body({**SELECTION, "status": "waiting-for-maintainer"}, RUN_URL)),
        _comment(22, "<!-- azure-agentic-waiting:issue-132 --> please retry", login, user_type),
    ]
    _mock_github(monkeypatch, comments)
    assert outcome.queue_state([{"number": 132}], REPOSITORY)[132]["waiting"] is True


def test_untrusted_state_marker_does_not_clear_the_wait(monkeypatch):
    comments = [
        _comment(21, outcome.state_body({**SELECTION, "status": "waiting-for-maintainer"}, RUN_URL)),
        _comment(22, outcome.state_body({**SELECTION, "status": "delivered"}, RUN_URL), "outsider", "User"),
    ]
    _mock_github(monkeypatch, comments)
    assert outcome.queue_state([{"number": 132}], REPOSITORY)[132]["waiting"] is True


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "skipped", "timed_out"])
def test_failed_workflow_never_becomes_waiting_or_delivered(conclusion):
    assert _classify(conclusion, [_receipt()], comments=[_waiting_comment()]) == "failure"


@pytest.mark.parametrize("receipts,comments", [
    ([], [_waiting_comment()]),
    ([_receipt()], [_comment(20, "A question without a machine marker")]),
    ([_receipt()], [_comment(20, "<!-- azure-agentic-waiting:issue-132 -->", "outsider", "User")]),
    ([_receipt(number=133)], [_waiting_comment()]),
    ([{**_receipt(), "repo": "other/repo"}], [_waiting_comment()]),
    ([{**_receipt(), "timestamp": "2026-10-03T06:30:00Z"}], [_waiting_comment()]),
])
def test_unproven_or_wrong_issue_comment_is_failure(receipts, comments):
    assert _classify(receipts=receipts, comments=comments) == "failure"


def test_explicit_noop_is_no_change_not_delivery():
    assert _classify(requests=[{"type": "noop", "message": "Already implemented."}]) == "no-change"
    assert _classify() == "failure"
    assert _classify(requests=[{"type": "noop"}]) == "failure"


def test_verified_pr_delivery_clears_wait_and_failure_streak(monkeypatch):
    receipt = _receipt("create_pull_request", 150)
    monkeypatch.setattr(outcome, "_gh_json", lambda *args, **kwargs: {
        "html_url": receipt["url"], "user": {"login": "github-actions[bot]"},
        "head": {"ref": "agentic/issue-132-abcdef"},
        "body": "<!-- azure-agentic-source:issue-132 -->",
    })
    assert _classify(receipts=[receipt]) == "delivered"
    comments = [_comment(21, outcome.state_body({**SELECTION, "status": "waiting-for-maintainer"}, RUN_URL))]
    _mock_github(monkeypatch, comments)
    outcome.write_state(REPOSITORY, {**SELECTION, "status": "delivered", "comment_id": 21}, RUN_URL)
    assert outcome.queue_state([{"number": 132}], REPOSITORY)[132]["waiting"] is False
    assert _decide("success", [_marker(2)])["failure_count"] == 0


@pytest.mark.parametrize("field,value", [
    ("issue_number", "132"), ("repository", "other/repo"), ("run_id", "2"),
    ("run_attempt", 2), ("head_sha", "b" * 40),
])
def test_selection_provenance_must_match_source_run(field, value):
    run = {
        "id": 1, "run_attempt": 1, "head_sha": "a" * 40,
        "head_repository": {"full_name": REPOSITORY},
        "path": ".github/workflows/scheduled-agentic-backlog.lock.yml",
    }
    outcome.validate_selection(SELECTION, run, REPOSITORY)
    with pytest.raises(ValueError, match="provenance"):
        outcome.validate_selection({**SELECTION, field: value}, run, REPOSITORY)


@pytest.mark.parametrize("terminal,conclusion,action,count", [
    ("waiting-for-maintainer", "success", "none", 2),
    ("no-change", "success", "none", 2),
    ("delivered", "success", "reset", 0),
    ("failure", "failure", "record", 3),
])
def test_cli_preserves_delivery_waiting_and_failure_semantics(
    monkeypatch, tmp_path, terminal, conclusion, action, count,
):
    comments = [
        _marker(2), _waiting_comment(),
        _comment(21, outcome.state_body({**SELECTION, "status": "evaluating-clarification"}, RUN_URL)),
    ]
    _mock_github(monkeypatch, comments)
    api = outcome._gh_json
    def with_pull(endpoint, *args, **kwargs):
        if endpoint.endswith("/pulls/150"):
            return {
                "html_url": _receipt("create_pull_request", 150)["url"],
                "user": {"login": "github-actions[bot]"}, "head": {"ref": "agentic/issue-132"},
                "body": "<!-- azure-agentic-source:issue-132 -->",
            }
        return api(endpoint, *args, **kwargs)
    monkeypatch.setattr(outcome, "_gh_json", with_pull)
    payloads = {
        "issue.json": {"number": 132, "labels": [{"name": "azure-paused"}], "comments": comments},
        "selection.json": SELECTION,
        "run.json": {
            "id": 1, "run_attempt": 1, "head_sha": "a" * 40,
            "head_repository": {"full_name": REPOSITORY},
            "path": ".github/workflows/scheduled-agentic-backlog.lock.yml",
        },
    }
    for filename, payload in payloads.items():
        (tmp_path / filename).write_text(json.dumps(payload), encoding="utf-8")
    receipts = [] if terminal == "no-change" else [
        _receipt("create_pull_request", 150) if terminal == "delivered" else _receipt()
    ]
    request = (
        {"type": "noop", "message": "Already satisfied."} if terminal == "no-change"
        else {"type": "add_comment", "item_number": 132, "body": _waiting_comment()["body"]}
    )
    (tmp_path / "receipts.jsonl").write_text("\n".join(json.dumps(item) for item in receipts), encoding="utf-8")
    (tmp_path / "requests.jsonl").write_text(json.dumps(request), encoding="utf-8")
    output = tmp_path / "output.txt"
    monkeypatch.setattr(sys, "argv", [
        "record", "--issue", str(tmp_path / "issue.json"), "--outcome", conclusion,
        "--run-url", RUN_URL, "--repository", REPOSITORY,
        "--selection", str(tmp_path / "selection.json"), "--run", str(tmp_path / "run.json"),
        "--receipts", str(tmp_path / "receipts.jsonl"), "--requests", str(tmp_path / "requests.jsonl"),
        "--github-output", str(output),
    ])
    outcome.main()
    assert f"action={action}" in output.read_text()
    assert f"failure_count={count}" in output.read_text()
    assert "pause=false" in output.read_text()
    expected_status = "evaluating-clarification" if terminal == "failure" else terminal
    assert outcome.find_state(comments, 132)["status"] == expected_status


def _marker(count: int, comment_id: int = 10) -> dict:
    return {
        "id": comment_id,
        "author": {"login": "github-actions[bot]"},
        "body": f"<!-- azure-agentic-failures count={count} -->\nfailed",
    }


def _decide(outcome_name: str, comments=None, labels=None, recurring=False, threshold=3):
    return outcome.decide(
        outcome=outcome_name,
        comments=comments or [],
        labels=labels or [],
        recurring=recurring,
        run_url=RUN_URL,
        threshold=threshold,
    )


def test_first_failure_records_without_pausing():
    result = _decide("failure")

    assert result["action"] == "record"
    assert result["failure_count"] == 1
    assert result["pause"] is False
    assert result["comment_id"] is None
    assert "count=1" in result["body"]


def test_repeated_failures_pause_the_issue_at_the_threshold():
    result = _decide("failure", comments=[_marker(2)])

    assert result["failure_count"] == 3
    assert result["pause"] is True
    assert result["comment_id"] == 10
    assert "azure-paused" in result["body"]


def test_recurring_issues_are_counted_but_never_paused():
    result = _decide("failure", comments=[_marker(5)], recurring=True)

    assert result["failure_count"] == 6
    assert result["pause"] is False
    assert "azure-paused" not in result["body"]


def test_an_already_paused_issue_is_not_relabelled():
    result = _decide("failure", comments=[_marker(4)], labels=["azure-paused"])

    assert result["failure_count"] == 5
    assert result["pause"] is False


def test_success_clears_an_existing_failure_streak():
    result = _decide("success", comments=[_marker(2)])

    assert result["action"] == "reset"
    assert result["failure_count"] == 0
    assert result["comment_id"] == 10
    assert "count=0" in result["body"]


def test_success_without_a_streak_does_nothing():
    result = _decide("success")

    assert result["action"] == "none"
    assert "body" not in result


def test_only_bot_marker_comments_are_counted():
    spoofed = {
        "id": 99,
        "author": {"login": "someone-else"},
        "body": "<!-- azure-agentic-failures count=99 -->",
    }

    result = _decide("failure", comments=[spoofed])

    assert result["failure_count"] == 1
    assert result["comment_id"] is None


def test_unsupported_outcome_is_rejected():
    with pytest.raises(ValueError):
        _decide("exploded")


def test_outcome_follower_records_against_the_source_issue():
    follower = (REPO_ROOT / ".github/workflows/agentic-backlog-outcome.yml").read_text(
        encoding="utf-8"
    )
    source = (REPO_ROOT / ".github/workflows/scheduled-agentic-backlog.md").read_text(
        encoding="utf-8"
    )

    assert 'workflows: ["Scheduled agentic backlog"]' in follower
    assert "agentic-backlog-selection" in follower
    assert "agentic-backlog-selection" in source
    assert "record_azure_agentic_outcome.py" in follower
    assert 'issues/$ISSUE_NUMBER/comments?per_page=100' in follower
    assert 'comments: ($pages[0] | add // [])' in follower
    assert "gh issue view" not in follower
    assert "--add-label azure-paused" in follower
    assert "persist-credentials: false" in follower
    assert "Malformed agentic backlog selection metadata." in follower
    assert "contents: write" in follower
    assert "<!-- azure-agentic-draft-review -->" in follower
    assert "Generated REQUEST_CHANGES review pending" in follower
    assert "before marking the draft ready" in follower
    assert "do not start a run" in follower
    assert "Queue one automatic repair pass for failed validation" not in follower
    assert 'rework_trigger: "validation-failure"' not in follower
    assert "fromdateiso8601" not in follower
    assert "secrets." not in follower
