from __future__ import annotations

import base64
import importlib.util
import json
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "filter_azure_agentic_tasks.py"
SPEC = importlib.util.spec_from_file_location("filter_azure_agentic_tasks", SCRIPT_PATH)
assert SPEC is not None
agentic_filter = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = agentic_filter
SPEC.loader.exec_module(agentic_filter)


def _manifest(*issue_numbers: int):
    tasks = [
        {
            "kind": "issue",
            "category": f"issue-{number}",
            "issue_number": number,
            "summary": f"Issue {number}",
        }
        for number in issue_numbers
    ]
    return {
        "tasks": tasks,
        "status": {
            "selected_count": len(tasks),
            "selected_categories": [task["category"] for task in tasks],
        },
    }


def test_filter_manifest_skips_existing_aider_and_agentic_issue_prs():
    filtered = agentic_filter.filter_manifest(
        _manifest(43, 48, 53),
        [
            {"headRefName": "azure-issues/issue-43", "body": ""},
            {"headRefName": "agentic/issue-48-a1b2c3", "body": ""},
        ],
    )

    assert [task["issue_number"] for task in filtered["tasks"]] == [53]
    assert filtered["status"]["selected_count"] == 1
    assert filtered["status"]["selected_categories"] == ["issue-53"]
    assert filtered["agentic_filter"]["skipped_open_pr_issue_numbers"] == [43, 48]


def test_filter_manifest_recognizes_source_issue_markers_in_pr_body():
    filtered = agentic_filter.filter_manifest(
        _manifest(48, 55),
        [
            {
                "headRefName": "unrelated-branch",
                "body": "<!-- azure-agentic-source:issue-48 -->\nSource issue: #48",
            }
        ],
    )

    assert [task["issue_number"] for task in filtered["tasks"]] == [55]
    assert filtered["agentic_filter"]["open_pr_issue_numbers"] == [48]


def test_filter_manifest_keeps_empty_status_observable():
    filtered = agentic_filter.filter_manifest(
        _manifest(48),
        [{"headRefName": "azure-issues/issue-48", "body": ""}],
    )

    assert filtered["tasks"] == []
    assert filtered["status"]["selected_count"] == 0
    rendered = agentic_filter.render_summary(filtered)
    assert "Selected issue tasks: 0" in rendered
    assert "No coding-agent session should start" in rendered


def test_filter_manifest_selects_only_one_available_fallback_task():
    filtered = agentic_filter.filter_manifest(_manifest(43, 53, 54), [])

    assert [task["issue_number"] for task in filtered["tasks"]] == [43]
    assert filtered["status"]["selected_count"] == 1


def test_github_output_reports_selected_task(tmp_path):
    path = tmp_path / "github-output.txt"

    agentic_filter._write_github_output(path, _manifest(53))

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[:3] == ["has_task=true", "issue_number=53", "category=issue-53"]
    encoded = lines[3].removeprefix("task_b64=")
    decoded = json.loads(base64.b64decode(encoded).decode("utf-8"))
    assert decoded["tasks"][0]["issue_number"] == 53
    summary = base64.b64decode(lines[4].removeprefix("summary_b64=")).decode("utf-8")
    assert "Source issue: #53" in summary
    assert "selected from the `azure-backlog` queue" in summary


def test_agent_summary_explains_unknown_evidence_is_issue_enrichment():
    manifest = _manifest(48)
    manifest["tasks"][0].update(
        recurring=True,
        allowed_paths=["src/probe.py"],
        tests=["tests/test_probe.py"],
        evidence={
            "issue_title": "Investigate unknowns",
            "objective": "Investigate the current largest unknown regression.",
            "priority": 400,
            "issue_labels": ["azure-backlog", "azure-recurring", "azure-unknowns"],
            "current_unknown_status": {
                "selected_category": "modelLatency",
                "unknown_count": 3,
                "features": ["modelLatency.openai.o1"],
                "error_codes": [["GitHubModelsHttp400", 2]],
                "messages": [["unsupported parameter", 2]],
            },
        },
    )

    summary = agentic_filter.agent_task_summary(manifest)

    assert "Queue priority: Urgent" in summary
    assert "live unknown evidence never creates a task by itself" in summary
    assert "evidence narrows its current investigation" in summary
    assert "modelLatency" in summary
