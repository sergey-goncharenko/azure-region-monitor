from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "request_azure_backlog_objectives.py"
)
SPEC = importlib.util.spec_from_file_location("request_azure_backlog_objectives", SCRIPT_PATH)
assert SPEC is not None
objectives = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = objectives
SPEC.loader.exec_module(objectives)


def _manifest():
    return {
        "tasks": [],
        "status": {
            "malformed_issue_count": 1,
            "malformed_issues": [
                {"number": 107, "title": "[azure-backlog] Add visual evidence"}
            ],
        },
    }


def test_objective_question_asks_for_observable_outcome_and_exact_template():
    body = objectives.objective_question(
        "example-owner/repo", "https://example.test/runs/1"
    )

    assert body.startswith(objectives.QUESTION_MARKER)
    assert "@example-owner" in body
    assert "Question for a maintainer" in body
    assert "concrete, observable outcome" in body
    assert "### Priority" in body
    assert "### Objective" in body
    assert "### Context or acceptance evidence" in body
    assert "Requested outcome" in body
    assert "https://example.test/runs/1" in body


def test_request_objectives_comments_once(monkeypatch, tmp_path):
    calls = []
    captured = {}

    def run(*args):
        calls.append(args)
        if args[:2] == ("gh", "api"):
            return subprocess.CompletedProcess(args, 0, "[]", "")
        if args[:3] == ("gh", "issue", "comment"):
            path = Path(args[args.index("--body-file") + 1])
            captured["body"] = path.read_text(encoding="utf-8")
            return subprocess.CompletedProcess(args, 0, "https://example.test/comment", "")
        raise AssertionError(args)

    monkeypatch.setattr(objectives, "_run", run)

    requested = objectives.request_objectives(
        _manifest(), "example/repo", "https://example.test/runs/1"
    )

    assert requested == 1
    assert objectives.QUESTION_MARKER in captured["body"]
    assert not Path(calls[-1][calls[-1].index("--body-file") + 1]).exists()


def test_request_objectives_does_not_duplicate_bot_question(monkeypatch):
    existing = json.dumps(
        [
            {
                "user": {"login": "github-actions[bot]"},
                "body": f"{objectives.QUESTION_MARKER}\nAlready asked.",
            }
        ]
    )
    calls = []

    def run(*args):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, existing, "")

    monkeypatch.setattr(objectives, "_run", run)

    requested = objectives.request_objectives(
        _manifest(), "example/repo", "https://example.test/runs/2"
    )

    assert requested == 0
    assert len(calls) == 1
    assert calls[0][:2] == ("gh", "api")


def test_request_objectives_ignores_invalid_manifest_items(monkeypatch):
    monkeypatch.setattr(
        objectives,
        "_run",
        lambda *args: (_ for _ in ()).throw(AssertionError(args)),
    )
    manifest = {
        "status": {
            "malformed_issues": [
                {"number": "107", "title": "wrong type"},
                {"number": 0, "title": "not positive"},
            ]
        }
    }

    assert objectives.request_objectives(manifest, "example/repo", "") == 0