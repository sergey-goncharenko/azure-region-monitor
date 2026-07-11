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


def test_max_issue_items_is_bounded_to_three_coding_slots():
    assert backlog_cycle._max_issue_items(8) == 3


def test_max_issue_items_uses_safe_default_for_invalid_input():
    assert backlog_cycle._max_issue_items("not-a-number") == 3


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


def test_issue_backlog_excludes_documentation_alignment_by_default(monkeypatch, tmp_path):
    monkeypatch.setattr(
        backlog_cycle,
        "_build_issue_tasks",
        lambda issues_path, limit, repository, snapshot_url, target_issue: [
            {"kind": "issue", "category": "issue-1", "summary": "First task"},
            {"kind": "issue", "category": "issue-2", "summary": "Second task"},
            {"kind": "issue", "category": "issue-3", "summary": "Third task"},
        ][:limit],
    )
    monkeypatch.setattr(
        backlog_cycle,
        "_build_docs_task",
        lambda: (_ for _ in ()).throw(AssertionError("docs use the maintenance workflow")),
    )

    cycle = backlog_cycle.build_cycle(tmp_path / "issues.json", 3, "example/repo")

    assert [task["kind"] for task in cycle["tasks"]] == ["issue", "issue", "issue"]


def test_documentation_task_can_still_be_built_explicitly(monkeypatch, tmp_path):
    monkeypatch.setattr(backlog_cycle, "_build_issue_tasks", lambda *args: [])
    monkeypatch.setattr(
        backlog_cycle,
        "_build_docs_task",
        lambda: {"kind": "docs", "category": "documentation-alignment", "summary": "Docs"},
    )

    cycle = backlog_cycle.build_cycle(
        tmp_path / "issues.json",
        3,
        "example/repo",
        include_docs=True,
    )

    assert [task["kind"] for task in cycle["tasks"]] == ["docs"]


def test_targeted_rework_selects_one_issue_and_skips_docs(monkeypatch, tmp_path):
    captured = {}

    def build_tasks(issues_path, limit, repository, snapshot_url, target_issue):
        captured["target_issue"] = target_issue
        return [{"kind": "issue", "category": "issue-49", "summary": "Rework"}]

    monkeypatch.setattr(backlog_cycle, "_build_issue_tasks", build_tasks)
    monkeypatch.setattr(
        backlog_cycle,
        "_build_docs_task",
        lambda: (_ for _ in ()).throw(AssertionError("docs should be skipped")),
    )

    cycle = backlog_cycle.build_cycle(
        tmp_path / "issues.json",
        3,
        "example/repo",
        target_issue=49,
        include_docs=False,
    )

    assert captured["target_issue"] == 49
    assert [task["category"] for task in cycle["tasks"]] == ["issue-49"]


def test_current_unknown_context_selects_top_group_scope(monkeypatch):
    class SnapshotResult:
        snapshot = {"regions": {}}
        source = "https://example.test/latest.json"
        warning = None

    class Group:
        category = "aksExtensions"
        unknown_count = 39831
        regions = ("eastus", "westeurope")
        services = ("aks",)
        features = ("extensionCatalog",)
        error_codes = (("AzureCliCommandFailed", 39831),)
        messages = (("Azure CLI command timed out after 30 seconds.", 39831),)
        test_hints = ("tests/test_aks_extension_catalog_probe.py",)
        workflow_hints = (".github/workflows/aks-extension-tests.yml",)

    class Sessions:
        @staticmethod
        def load_snapshot(snapshot_url, snapshot_path):
            return SnapshotResult()

        @staticmethod
        def rank_unknown_groups(snapshot):
            return [Group()]

    monkeypatch.setattr(backlog_cycle, "_load_module", lambda name, script_name: Sessions)

    context = backlog_cycle._current_unknown_context("https://example.test/latest.json")

    assert context["category"] == "aksExtensions"
    assert context["evidence"]["unknown_count"] == 39831
    assert "src/azure_region_monitor/probes/aks_extension_catalog.py" in context["source_paths"]
    assert "tests/test_aks_extension_catalog_probe.py" in context["tests"]


def test_docs_task_keeps_workflows_as_evidence_not_edit_scope():
    task = backlog_cycle._build_docs_task()

    assert ".github/workflows/scheduled-azure-backlog.yml" not in task["allowed_paths"]
    assert ".github/workflows/scheduled-azure-backlog.yml" in task["evidence"]["files"]
