from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_azure_backlog_cycle.py"
SPEC = importlib.util.spec_from_file_location("run_azure_backlog_cycle", SCRIPT_PATH)
assert SPEC is not None
backlog_cycle = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = backlog_cycle
SPEC.loader.exec_module(backlog_cycle)


def test_max_goal_items_is_bounded_to_two_coding_slots(tmp_path):
    path = tmp_path / "backlog.json"
    path.write_text(json.dumps({"max_items_per_run": 8}), encoding="utf-8")

    assert backlog_cycle._max_goal_items(path) == 2


def test_max_goal_items_uses_safe_default_for_invalid_configuration(tmp_path):
    path = tmp_path / "backlog.json"
    path.write_text(json.dumps({"max_items_per_run": "not-a-number"}), encoding="utf-8")

    assert backlog_cycle._max_goal_items(path) == 2


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
