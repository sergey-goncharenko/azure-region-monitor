from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_azure_backlog_cycle.py"
SPEC = importlib.util.spec_from_file_location("run_azure_backlog_cycle", SCRIPT_PATH)
assert SPEC is not None
backlog_cycle = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = backlog_cycle
SPEC.loader.exec_module(backlog_cycle)


def test_max_issue_items_is_bounded_to_two_coding_slots():
    assert backlog_cycle._max_issue_items(8) == 2


def test_max_issue_items_uses_safe_default_for_invalid_input():
    assert backlog_cycle._max_issue_items("not-a-number") == 2


def test_cycle_markdown_identifies_docs_as_the_final_alignment_lane():
    rendered = backlog_cycle.render_cycle_markdown(
        {
            "tasks": [
                {
                    "kind": "docs",
                    "category": "documentation-alignment",
                    "summary": "Review current documentation.",
                }
            ]
        }
    )

    assert "### Documentation alignment: `documentation-alignment`" in rendered
    assert "Copilot CLI edits are validated locally" in rendered


def test_documentation_alignment_is_always_last(monkeypatch, tmp_path):
    monkeypatch.setattr(
        backlog_cycle,
        "_build_issue_tasks",
        lambda issues_path, limit, repository: [
            {"kind": "issue", "category": "issue-1", "summary": "First task"},
            {"kind": "issue", "category": "issue-2", "summary": "Second task"},
        ][:limit],
    )
    monkeypatch.setattr(
        backlog_cycle,
        "_build_docs_task",
        lambda: {"kind": "docs", "category": "documentation-alignment", "summary": "Docs"},
    )

    cycle = backlog_cycle.build_cycle(tmp_path / "issues.json", 2, "example/repo")

    assert [task["kind"] for task in cycle["tasks"]] == ["issue", "issue", "docs"]


def test_docs_task_keeps_workflows_as_evidence_not_edit_scope():
    task = backlog_cycle._build_docs_task()

    assert ".github/workflows/scheduled-azure-backlog.yml" not in task["allowed_paths"]
    assert ".github/workflows/scheduled-azure-backlog.yml" in task["evidence"]["files"]
