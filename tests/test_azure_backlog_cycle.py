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


def test_cycle_markdown_identifies_docs_as_the_alignment_lane():
    rendered = backlog_cycle.render_cycle_markdown(
        {
            "proposals": [
                {
                    "kind": "docs",
                    "proposal": {
                        "category": "documentation-alignment",
                        "decision": "no_change",
                        "summary": "No drift.",
                        "pr_title": "",
                    },
                }
            ]
        }
    )

    assert "### Documentation alignment: `documentation-alignment`" in rendered
    assert "No safe patch proposal was produced." in rendered


def test_cycle_markdown_identifies_github_issue_lane():
    rendered = backlog_cycle.render_cycle_markdown(
        {
            "proposals": [
                {
                    "kind": "issue",
                    "proposal": {
                        "category": "issue-42",
                        "decision": "no_change",
                        "summary": "No patch.",
                        "pr_title": "",
                    },
                }
            ]
        }
    )

    assert "### GitHub backlog issue: `issue-42`" in rendered


def test_documentation_alignment_is_always_last(monkeypatch, tmp_path):
    monkeypatch.setattr(
        backlog_cycle,
        "_propose_issues",
        lambda client, issues_path, limit, repository: [
            {"kind": "issue", "proposal": {"category": "issue-1"}},
            {"kind": "issue", "proposal": {"category": "issue-2"}},
        ][:limit],
    )
    monkeypatch.setattr(
        backlog_cycle,
        "_propose_docs",
        lambda client: {"kind": "docs", "proposal": {"category": "documentation-alignment"}},
    )

    cycle = backlog_cycle.build_cycle(object(), tmp_path / "issues.json", 2)

    assert [item["kind"] for item in cycle["proposals"]] == ["issue", "issue", "docs"]
