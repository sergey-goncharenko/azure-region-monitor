from __future__ import annotations

import importlib.util
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
    assert "--add-label azure-paused" in follower
    assert "persist-credentials: false" in follower
    assert "Malformed agentic backlog selection metadata." in follower
    assert "secrets." not in follower
