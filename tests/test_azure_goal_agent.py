from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_azure_goal_agent.py"
SPEC = importlib.util.spec_from_file_location("run_azure_goal_agent", SCRIPT_PATH)
assert SPEC is not None
goal_agent = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = goal_agent
SPEC.loader.exec_module(goal_agent)


def test_non_ready_backlog_items_are_not_selected(tmp_path):
    path = tmp_path / "goals.json"
    path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "paused",
                        "status": "paused",
                        "title": "Paused work",
                        "objective": "Do nothing.",
                    },
                    {
                        "id": "deprioritized",
                        "status": "deprioritized",
                        "title": "Deferred work",
                        "objective": "Do nothing yet.",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    context = goal_agent.build_goal_context(path)

    assert context["category"] == ""
    assert "No ready Azure coding backlog items" in context["summary"]


def test_highest_priority_ready_backlog_item_is_selected_and_auto_scoped(tmp_path):
    path = tmp_path / "goals.json"
    path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "lower-priority",
                        "status": "ready",
                        "priority": 1,
                        "title": "Improve blog output",
                        "objective": "Improve social blog draft quality.",
                    },
                    {
                        "id": "higher-priority",
                        "status": "ready",
                        "priority": 10,
                        "title": "Improve blog social output",
                        "objective": "Improve social blog draft quality.",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    context = goal_agent.build_goal_context(path)

    assert context["category"] == "higher-priority"
    assert "src/azure_region_monitor/blog.py" in context["allowed_paths"]
    assert "tests/test_blog.py" in context["tests"]
    assert context["evidence"]["goal_title"] == "Improve blog social output"


def test_invalid_backlog_priority_uses_a_safe_default(tmp_path):
    path = tmp_path / "backlog.json"
    path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "blog-improvement",
                        "status": "ready",
                        "priority": "soon",
                        "title": "Improve blog output",
                        "objective": "Improve social blog draft quality.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert goal_agent._load_goals(path)[0]["priority"] == 0


def test_goal_renderer_labels_no_change_output():
    rendered = goal_agent.render_goal_markdown(
        {
            "decision": "no_change",
            "summary": "No enabled goals.",
            "category": "",
            "allowed_paths": [],
            "tests": [],
        }
    )

    assert "## Azure higher-level goal review" in rendered
    assert "No safe goal patch proposal" in rendered
