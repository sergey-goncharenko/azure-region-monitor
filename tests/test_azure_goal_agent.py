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


def test_disabled_goals_are_not_selected(tmp_path):
    path = tmp_path / "goals.json"
    path.write_text(
        json.dumps(
            {
                "goals": [
                    {
                        "id": "disabled",
                        "enabled": False,
                        "title": "Disabled",
                        "goal": "Do nothing",
                        "allowed_paths": ["README.md"],
                        "tests": ["tests/test_blog.py"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    context = goal_agent.build_goal_context(path)

    assert context["category"] == ""
    assert "No enabled Azure coding goals" in context["summary"]


def test_highest_priority_enabled_goal_is_selected(tmp_path):
    path = tmp_path / "goals.json"
    path.write_text(
        json.dumps(
            {
                "goals": [
                    {
                        "id": "lower-priority",
                        "enabled": True,
                        "priority": 1,
                        "title": "Lower",
                        "goal": "Small improvement",
                        "allowed_paths": ["README.md"],
                        "tests": ["tests/test_blog.py"],
                    },
                    {
                        "id": "higher-priority",
                        "enabled": True,
                        "priority": 10,
                        "title": "Higher",
                        "goal": "Important improvement",
                        "allowed_paths": ["README.md"],
                        "tests": ["tests/test_blog.py"],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    context = goal_agent.build_goal_context(path)

    assert context["category"] == "higher-priority"
    assert context["tests"] == ["tests/test_blog.py"]
    assert context["evidence"]["goal_title"] == "Higher"


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
