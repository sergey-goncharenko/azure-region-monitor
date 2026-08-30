from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "publish_azure_backlog_status.py"
SPEC = importlib.util.spec_from_file_location("publish_azure_backlog_status", SCRIPT_PATH)
assert SPEC is not None
backlog_status = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = backlog_status
SPEC.loader.exec_module(backlog_status)


def _manifest(selected: int = 0):
    return {
        "tasks": [],
        "status": {
            "backlog_count": 8,
            "paused_count": 8 - selected,
            "eligible_count": selected,
            "malformed_issue_count": 0,
            "malformed_issues": [],
            "selected_count": selected,
            "eligible_issues": ([{"number": 55, "title": "Improve filters"}] if selected else []),
            "deferred_no_unknown_evidence_count": 0,
            "deferred_no_unknown_evidence_issues": [],
            "blocked_open_pr_count": 0,
            "blocked_open_pr_issues": [],
            "paused_issues": [{"number": 48, "title": "Investigate unknowns"}],
        },
    }


def test_render_status_explains_no_task_run():
    rendered = backlog_status.render_status(_manifest(), "https://example.test/run/1")

    assert "No agent session started" in rendered
    assert "Open backlog issues: 8" in rendered
    assert "Queue-eligible issues: 0" in rendered
    assert "Paused issues: 8" in rendered
    assert "#48: Investigate unknowns" in rendered
    assert "https://example.test/run/1" in rendered


def test_render_status_explains_unknown_evidence_defer():
    manifest = _manifest()
    manifest["status"].update(
        eligible_count=1,
        eligible_issues=[{"number": 48, "title": "Investigate unknowns"}],
        deferred_no_unknown_evidence_count=1,
        deferred_no_unknown_evidence_issues=[
            {"number": 48, "title": "Investigate unknowns"}
        ],
    )

    rendered = backlog_status.render_status(manifest, "https://example.test/run/3")

    assert "1 issue awaits current `unknown` evidence" in rendered
    assert "Deferred without current unknown evidence: 1" in rendered
    assert "#48: Investigate unknowns" in rendered


def test_render_status_explains_malformed_issue_template():
    manifest = _manifest()
    manifest["status"].update(
        eligible_count=1,
        eligible_issues=[{"number": 107, "title": "Add visual evidence"}],
        malformed_issue_count=1,
        malformed_issues=[{"number": 107, "title": "Add visual evidence"}],
    )

    rendered = backlog_status.render_status(manifest, "https://example.test/run/4")

    assert "1 issue is missing the required `### Objective` field" in rendered
    assert "Malformed issue templates: 1" in rendered
    assert "#107: Add visual evidence" in rendered


def test_render_status_points_selected_runs_to_audit():
    rendered = backlog_status.render_status(
        _manifest(selected=1), "https://example.test/run/2"
    )

    assert "inspect the latest run audit and any draft PRs" in rendered


def test_publish_status_updates_stable_issue_and_comments_for_no_task(monkeypatch):
    calls = []
    captured_body = {}
    monkeypatch.setattr(backlog_status, "_status_issue", lambda repository: (99, "open"))

    def run(*args):
        calls.append(args)
        if args[:3] == ("gh", "issue", "edit"):
            path = Path(args[args.index("--body-file") + 1])
            captured_body["text"] = path.read_text(encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(backlog_status, "_run", run)

    result = backlog_status.publish_status(
        _manifest(), "example/repo", "https://example.test/run/1"
    )

    assert result == 0
    assert "No agent session started" in captured_body["text"]
    assert any(args[:3] == ("gh", "issue", "comment") for args in calls)
    assert any(args[:3] == ("gh", "label", "create") for args in calls)


def test_publish_status_does_not_comment_when_task_selected(monkeypatch):
    calls = []
    monkeypatch.setattr(backlog_status, "_status_issue", lambda repository: (99, "open"))
    monkeypatch.setattr(
        backlog_status,
        "_run",
        lambda *args: calls.append(args) or subprocess.CompletedProcess(args, 0, "", ""),
    )

    result = backlog_status.publish_status(
        _manifest(selected=1), "example/repo", "https://example.test/run/2"
    )

    assert result == 0
    assert not any(args[:3] == ("gh", "issue", "comment") for args in calls)
