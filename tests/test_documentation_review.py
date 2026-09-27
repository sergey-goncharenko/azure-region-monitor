from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "prepare_documentation_review.py"
SPEC = importlib.util.spec_from_file_location("prepare_documentation_review", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
review = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(review)
NOW = datetime(2026, 9, 27, 8, 41, tzinfo=timezone.utc)


def _git(root, *args):
    return subprocess.run(
        ("git", *args), cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()


def _commit(root, path, content):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _git(root, "add", "--", path)
    _git(root, "-c", "user.name=Test", "-c", "user.email=test@example.test", "commit", "-m", "Change")


@pytest.fixture
def repository(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _commit(root, "src/feature.py", "TIMEOUT = 30\n")
    original = review._command
    pulls = []
    calls = []

    def command(root, *args):
        if args[0] == "gh":
            calls.append(args)
            return json.dumps(pulls if args[1] == "pr" else [])
        return original(root, *args)

    monkeypatch.setattr(review, "_command", command)
    state = tmp_path / "checkpoint.json"
    result = tmp_path / "result.json"
    return root, state, result, pulls, calls


def _prepare(repository, now=NOW):
    root, state, *_ = repository
    return review.prepare_review(root, state, "example/repo", "main", now=now)


def _seed(repository):
    _, state, result, *_ = repository
    plan = _prepare(repository)
    assert review.complete_review(plan, result, state)
    return state.read_text(encoding="utf-8")


def test_bootstrap_and_cache_loss_establish_weekly_baseline_without_inference(repository):
    _, state, _, _, calls = repository
    plan = _prepare(repository)
    assert not plan["run_agent"]
    assert plan["outcome"] == "baseline"
    assert not state.exists()
    _seed(repository)
    assert not _prepare(repository)["run_agent"]
    state.unlink()
    assert _prepare(repository)["outcome"] == "baseline"
    assert not calls


@pytest.mark.parametrize("path", [
    "README.md", "docs/agentic-sessions.md", ".github/copilot-instructions.md",
    "data/latest.json", "public/api/latest.json", "tests/test_feature.py",
    ".github/workflows/scheduled-agentic-backlog.lock.yml",
])
def test_docs_tests_and_generated_changes_do_not_invoke_model(repository, path):
    root, state, _, _, calls = repository
    previous = _seed(repository)
    _commit(root, path, "documentation or generated content\n")
    assert not _prepare(repository)["run_agent"]
    assert not calls
    assert state.read_text(encoding="utf-8") == previous


def test_workflow_clock_comments_and_prompt_only_changes_are_ignored(repository):
    root, *_ = repository
    path = ".github/workflows/example.md"
    before = '---\non:\n  schedule:\n    - cron: "0 10 * * *"\n---\nMaintain docs.\n'
    _commit(root, path, before)
    _seed(repository)
    after = before.replace("0 10", "52 9").replace("Maintain docs.", "Align docs.")
    _commit(root, path, after.replace("\non:", "\n# Better wording\non:"))
    assert not _prepare(repository)["run_agent"]
    _commit(root, path, after.replace("\non:", '\ntimeout-minutes: 10\non:'))
    assert _prepare(repository)["run_agent"]


@pytest.mark.parametrize("cron", ["0 10 * * 1", "0 */6 * * *"])
def test_workflow_cadence_changes_are_not_ignored(repository, cron):
    root, *_ = repository
    path = ".github/workflows/example.yml"
    before = 'on:\n  schedule:\n    - cron: "0 10 * * *"\n'
    _commit(root, path, before)
    _seed(repository)
    _commit(root, path, before.replace("0 10 * * *", cron))
    assert _prepare(repository)["run_agent"]


def test_new_source_delta_contains_exact_revision_paths_and_patch(repository):
    root, state, _, _, calls = repository
    _seed(repository)
    baseline = review.read_state(state)["head_sha"]
    _commit(root, "src/feature.py", "TIMEOUT = 120\n")
    plan = _prepare(repository)
    assert plan["run_agent"]
    assert plan["base_sha"] == baseline
    assert plan["head_sha"] == _git(root, "rev-parse", "HEAD")
    assert plan["changed_paths"] == ["src/feature.py"]
    assert "-TIMEOUT = 30" in plan["diff"]
    assert "+TIMEOUT = 120" in plan["diff"]
    assert len(calls) == 2
    assert review.read_state(state)["head_sha"] == baseline


@pytest.mark.parametrize("outcome", ["no-change", "needs-evidence", "published", "failed"])
def test_attempt_checkpoint_prevents_repeat_after_noop_or_pr_closure(repository, outcome):
    root, state, result, _, _ = repository
    _seed(repository)
    _commit(root, "src/feature.py", "TIMEOUT = 120\n")
    plan = _prepare(repository)
    result.write_text(json.dumps({"outcome": outcome}), encoding="utf-8")
    assert review.complete_review(plan, result, state)
    _commit(root, "README.md", "Merged documentation or a later wording change.\n")
    repeated = _prepare(repository)
    assert not repeated["run_agent"]
    assert outcome in repeated["reason"]
    _commit(root, "src/feature.py", "TIMEOUT = 180\n")
    assert _prepare(repository)["run_agent"]


def test_open_pr_does_not_consume_new_source_and_then_allows_review(repository):
    root, state, result, pulls, _ = repository
    previous = _seed(repository)
    _commit(root, "src/feature.py", "TIMEOUT = 120\n")
    pulls.append({"number": 139})
    plan = _prepare(repository)
    assert not plan["run_agent"]
    assert "#139" in plan["reason"]
    assert not review.complete_review(plan, result, state)
    assert state.read_text(encoding="utf-8") == previous
    pulls.clear()
    assert _prepare(repository)["run_agent"]


@pytest.mark.parametrize("outcome", ["skipped-open-pr", "stale-source"])
def test_runner_race_skips_do_not_advance_checkpoint(repository, outcome):
    root, state, result, *_ = repository
    previous = _seed(repository)
    _commit(root, "src/feature.py", "TIMEOUT = 120\n")
    result.write_text(json.dumps({"outcome": outcome}), encoding="utf-8")
    assert not review.complete_review(_prepare(repository), result, state)
    assert state.read_text(encoding="utf-8") == previous


def test_incomplete_attempt_is_recorded_as_failed_not_retried(repository):
    root, state, result, *_ = repository
    _seed(repository)
    _commit(root, "src/feature.py", "TIMEOUT = 120\n")
    assert review.complete_review(_prepare(repository), result, state)
    assert review.read_state(state)["outcome"] == "failed"
    assert "failed" in _prepare(repository)["reason"]


def test_oversized_source_delta_bounds_context_without_blocking_augmentation(repository):
    root, state, result, *_ = repository
    _seed(repository)
    _commit(root, "src/feature.py", "value = '" + "x" * review.MAX_DIFF_CHARS + "'\n")
    plan = _prepare(repository)
    assert plan["run_agent"]
    assert plan["diff_truncated"]
    assert len(plan["diff"]) == review.MAX_DIFF_CHARS
    assert review.complete_review(plan, result, state)
    assert not _prepare(repository)["run_agent"]


def test_too_many_source_files_bound_context_instead_of_blocking_review(repository):
    root, *_ = repository
    _seed(repository)
    for index in range(review.MAX_DIFF_PATHS + 1):
        _commit(root, f"src/feature_{index}.py", "NEW = True\n")
    plan = _prepare(repository)
    assert plan["run_agent"]
    assert plan["diff_truncated"]
    assert len(plan["changed_paths"]) == review.MAX_DIFF_PATHS
    assert plan["changed_path_count"] == review.MAX_DIFF_PATHS + 1


def test_weekly_review_runs_with_no_source_changes(repository):
    _seed(repository)
    assert not _prepare(repository, NOW + timedelta(days=7, seconds=-1))["run_agent"]
    weekly = _prepare(repository, NOW + timedelta(days=7))
    assert weekly["run_agent"]
    assert weekly["review_kind"] == "weekly-augmentation"
    assert weekly["changed_paths"] == []
    assert weekly["diff"] == ""
    assert "external changes" in weekly["reason"]


@pytest.mark.parametrize("outcome", ["published", "no-change", "needs-evidence", "failed"])
def test_weekly_outcomes_prevent_daily_retry_but_allow_next_week(repository, outcome):
    _, state, result, *_ = repository
    _seed(repository)
    weekly = _prepare(repository, NOW + timedelta(days=7))
    result.write_text(json.dumps({"outcome": outcome}), encoding="utf-8")
    assert review.complete_review(weekly, result, state)
    assert not _prepare(repository, NOW + timedelta(days=8))["run_agent"]
    assert _prepare(repository, NOW + timedelta(days=14))["run_agent"]


def test_source_reviews_do_not_postpone_independent_weekly_augmentation(repository):
    root, state, result, *_ = repository
    _seed(repository)
    _commit(root, "src/feature.py", "TIMEOUT = 120\n")
    source = _prepare(repository, NOW + timedelta(days=6))
    assert source["review_kind"] == "source-change"
    assert review.complete_review(source, result, state)
    assert review.read_state(state)["last_augmentation_at"] == NOW.isoformat()
    assert _prepare(repository, NOW + timedelta(days=7))["review_kind"] == "weekly-augmentation"


def test_open_pr_does_not_consume_weekly_opportunity(repository):
    _, state, result, pulls, _ = repository
    previous = _seed(repository)
    pulls.append({"number": 139})
    weekly = _prepare(repository, NOW + timedelta(days=7))
    assert not weekly["run_agent"]
    assert not review.complete_review(weekly, result, state)
    assert state.read_text(encoding="utf-8") == previous
    pulls.clear()
    assert _prepare(repository, NOW + timedelta(days=8))["review_kind"] == "weekly-augmentation"


def test_reader_context_is_fresh_bounded_and_keeps_issue_links(repository, monkeypatch):
    root, *_ = repository
    issues = [
        {"number": index, "title": "New reader use case " * 30, "body": "context " * 300,
         "url": f"https://github.com/example/repo/issues/{index}", "state": "OPEN"}
        for index in range(1, 8)
    ]
    calls = []
    monkeypatch.setattr(
        review, "_command", lambda *args: calls.append(args) or json.dumps(issues)
    )
    context = review._reader_context(root, "example/repo")
    assert len(context) == 5
    assert len(context[0]["title"]) == 200
    assert len(context[0]["body_excerpt"]) == 1_000
    assert context[0]["url"] == issues[0]["url"]
    assert "sort:updated-desc" in calls[0]


def test_invalid_or_future_weekly_timestamp_fails_closed(repository):
    _, state, *_ = repository
    _seed(repository)
    payload = json.loads(state.read_text(encoding="utf-8"))
    payload["last_augmentation_at"] = "not a timestamp"
    state.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        _prepare(repository)
    payload["last_augmentation_at"] = (NOW + timedelta(days=1)).isoformat()
    state.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="future"):
        _prepare(repository)


def test_deleted_source_file_is_part_of_delta(repository):
    root, *_ = repository
    _seed(repository)
    _git(root, "rm", "src/feature.py")
    _git(root, "-c", "user.name=Test", "-c", "user.email=test@example.test", "commit", "-m", "Remove")
    plan = _prepare(repository)
    assert plan["run_agent"]
    assert "src/feature.py" in plan["changed_paths"]
    assert "deleted file" in plan["diff"]


def test_invalid_checkpoint_and_pr_query_failure_fail_closed(repository, monkeypatch):
    root, state, *_ = repository
    state.write_text('{"version": 0}', encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid documentation review checkpoint"):
        _prepare(repository)
    state.unlink()
    _seed(repository)
    _commit(root, "src/feature.py", "TIMEOUT = 120\n")
    original = review._command

    def command(root, *args):
        if args[0] == "gh":
            raise RuntimeError("GitHub unavailable")
        return original(root, *args)

    monkeypatch.setattr(review, "_command", command)
    with pytest.raises(RuntimeError, match="GitHub unavailable"):
        _prepare(repository)


def test_corrupted_source_fingerprint_fails_closed(repository):
    _, state, *_ = repository
    _seed(repository)
    payload = json.loads(state.read_text(encoding="utf-8"))
    payload["fingerprint"] = "a" * 64
    state.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid documentation review checkpoint"):
        _prepare(repository)


def test_failed_completion_sets_cache_output_and_fails_workflow(repository, tmp_path, monkeypatch):
    root, state, result, *_ = repository
    _seed(repository)
    _commit(root, "src/feature.py", "TIMEOUT = 120\n")
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(_prepare(repository)), encoding="utf-8")
    outputs = tmp_path / "outputs"
    monkeypatch.setattr(sys, "argv", [
        "prepare_documentation_review.py", "complete", "--repository", "example/repo",
        "--state", str(state), "--plan", str(plan_path), "--result", str(result),
        "--github-output", str(outputs),
    ])
    with pytest.raises(SystemExit, match="attempt failed"):
        review.main()
    assert outputs.read_text(encoding="utf-8") == "save_state=true\n"
    assert review.read_state(state)["outcome"] == "failed"
