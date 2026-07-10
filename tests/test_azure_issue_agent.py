from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_azure_issue_agent.py"
SPEC = importlib.util.spec_from_file_location("run_azure_issue_agent", SCRIPT_PATH)
assert SPEC is not None
issue_agent = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = issue_agent
SPEC.loader.exec_module(issue_agent)


def _issue(number: int, *, priority: str = "Normal", labels: list[str] | None = None) -> dict:
    return {
        "number": number,
        "title": "Improve blog social output",
        "body": f"""### Priority

{priority}

### Objective

Improve social blog draft quality.

### Context or acceptance evidence

The change should remain factual.
""",
        "labels": [{"name": label} for label in labels or ["azure-backlog"]],
        "url": f"https://github.com/example/repo/issues/{number}",
    }


def test_unlabelled_and_paused_issues_are_not_selected(tmp_path):
    path = tmp_path / "issues.json"
    path.write_text(
        json.dumps(
            [
                _issue(1, labels=["enhancement"]),
                _issue(2, labels=["azure-backlog", "azure-paused"]),
            ]
        ),
        encoding="utf-8",
    )

    context = issue_agent.build_issue_context(path)

    assert context["category"] == ""
    assert "No eligible open GitHub issues" in context["summary"]


def test_highest_priority_issue_is_selected_and_auto_scoped(tmp_path):
    path = tmp_path / "issues.json"
    path.write_text(
        json.dumps([_issue(22, priority="Low"), _issue(11, priority="High")]),
        encoding="utf-8",
    )

    context = issue_agent.build_issue_context(path)

    assert context["category"] == "issue-11"
    assert context["issue_number"] == 11
    assert "src/azure_region_monitor/blog.py" in context["allowed_paths"]
    assert "tests/test_blog.py" in context["tests"]
    assert context["evidence"]["issue_url"].endswith("/11")


def test_missing_priority_defaults_to_normal(tmp_path):
    path = tmp_path / "issues.json"
    issue = _issue(11)
    issue["body"] = "### Objective\n\nImprove social blog draft quality.\n"
    path.write_text(json.dumps([issue]), encoding="utf-8")

    assert issue_agent._load_issues(path)[0]["priority"] == 200


def test_issue_renderer_labels_no_change_output():
    rendered = issue_agent.render_issue_markdown(
        {
            "decision": "no_change",
            "summary": "No eligible issues.",
            "category": "",
            "allowed_paths": [],
            "tests": [],
        }
    )

    assert "## Azure GitHub issue backlog review" in rendered
    assert "No safe issue patch proposal" in rendered