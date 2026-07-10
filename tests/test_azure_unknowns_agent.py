from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_azure_unknowns_agent.py"
SPEC = importlib.util.spec_from_file_location("run_azure_unknowns_agent", SCRIPT_PATH)
assert SPEC is not None
unknowns_agent = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = unknowns_agent
SPEC.loader.exec_module(unknowns_agent)


CONTEXT = {
    "category": "functions",
    "allowed_paths": [
        "src/azure_region_monitor/probes/functions.py",
        "tests/test_functions_probe.py",
    ],
    "tests": ["tests/test_functions_probe.py"],
}


def test_parse_proposal_accepts_patch_with_allowed_paths():
    raw = """{
  "decision": "patch",
  "summary": "Timeout handling lacks a bounded case.",
  "pr_title": "fix: improve functions unknown classification",
  "pr_body": "Adds a regression test and bounded handling.",
  "patch": "diff --git a/tests/test_functions_probe.py b/tests/test_functions_probe.py\\n--- a/tests/test_functions_probe.py\\n+++ b/tests/test_functions_probe.py\\n@@ -1 +1 @@\\n-old\\n+new\\n"
}"""

    proposal = unknowns_agent._parse_proposal(raw, CONTEXT)

    assert proposal["decision"] == "patch"
    assert proposal["category"] == "functions"
    assert proposal["tests"] == ["tests/test_functions_probe.py"]


def test_parse_proposal_rejects_out_of_scope_patch():
    raw = """{
  "decision": "patch",
  "summary": "Unsafe change.",
  "pr_title": "fix: unsafe",
  "pr_body": "Unsafe.",
  "patch": "diff --git a/README.md b/README.md\\n--- a/README.md\\n+++ b/README.md\\n@@ -1 +1 @@\\n-old\\n+new\\n"
}"""

    proposal = unknowns_agent._parse_proposal(raw, CONTEXT)

    assert proposal["decision"] == "no_change"
    assert "outside the allowed paths" in proposal["summary"]


def test_parse_proposal_fails_closed_for_invalid_json():
    proposal = unknowns_agent._parse_proposal("not JSON", CONTEXT)

    assert proposal["decision"] == "no_change"
    assert proposal["patch"] == ""


def test_missing_snapshot_warning_is_reported_in_no_change_context(monkeypatch):
    class Sessions:
        @staticmethod
        def load_snapshot(snapshot_url, snapshot_path):
            return type(
                "SnapshotResult",
                (),
                {"snapshot": None, "warning": "request timed out"},
            )()

        @staticmethod
        def rank_unknown_groups(snapshot):
            raise AssertionError("no snapshot should not be ranked")

    monkeypatch.setattr(unknowns_agent, "_load_sessions_module", lambda: Sessions)

    context = unknowns_agent.build_proposal_context("https://example.invalid/latest.json")

    assert context["category"] == ""
    assert "Snapshot warning: request timed out" in context["summary"]
