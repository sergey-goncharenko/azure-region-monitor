from __future__ import annotations

import importlib.util
import sys
from datetime import date, datetime, timezone
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "start_copilot_agent_sessions.py"
SPEC = importlib.util.spec_from_file_location("start_copilot_agent_sessions", SCRIPT_PATH)
assert SPEC is not None
agent_sessions = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = agent_sessions
SPEC.loader.exec_module(agent_sessions)

CODEX_PROMPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_azure_codex_docs_prompt.py"
CODEX_SPEC = importlib.util.spec_from_file_location("build_azure_codex_docs_prompt", CODEX_PROMPT_PATH)
assert CODEX_SPEC is not None
codex_prompt = importlib.util.module_from_spec(CODEX_SPEC)
assert CODEX_SPEC.loader is not None
sys.modules[CODEX_SPEC.name] = codex_prompt
CODEX_SPEC.loader.exec_module(codex_prompt)


def test_rank_unknown_groups_selects_largest_modality():
    snapshot = {
        "regions": {
            "eastus": {
                "ai": {
                    "aiModels.gpt-4o.2024-11-20": {
                        "status": "unknown",
                        "error_code": "timeout",
                        "message": "command timed out after 120 seconds",
                    },
                    "aiModels.gpt-4o-mini.2024-07-18": {
                        "status": "unknown",
                        "error_code": "timeout",
                        "message": "command timed out after 120 seconds",
                    },
                },
                "compute": {
                    "vmSkus.Standard_D2s_v5": {
                        "status": "unknown",
                        "error_code": "cli_error",
                        "message": "provider error",
                    }
                },
            },
            "westeurope": {
                "ai": {
                    "aiModels.gpt-4o.2024-11-20": {
                        "status": "unknown",
                        "error_code": "timeout",
                        "message": "command timed out after 120 seconds",
                    }
                }
            },
        }
    }

    groups = agent_sessions.rank_unknown_groups(snapshot)

    assert groups[0].category == "aiModels"
    assert groups[0].unknown_count == 3
    assert groups[0].regions == ("eastus", "westeurope")
    assert groups[0].test_hints == ("tests/test_ai_models_probe.py",)
    assert groups[1].category == "vmSkus"


def test_unknowns_session_includes_precomputed_candidate_context():
    snapshot_result = agent_sessions.SnapshotLoadResult(
        snapshot=None,
        source="https://example.test/latest.json",
    )
    group = agent_sessions.UnknownGroup(
        category="functions",
        unknown_count=7,
        regions=("eastus", "westeurope"),
        services=("functions",),
        features=("hostingPlans.flexConsumption",),
        error_codes=(("timeout", 7),),
        messages=(("command timed out", 7),),
    )

    session = agent_sessions.build_unknowns_session(
        datetime(2026, 7, 5, tzinfo=timezone.utc),
        snapshot_result,
        [group],
        force_without_candidates=False,
    )

    assert session is not None
    assert "Top candidate: `functions` with 7 unknown checks" in session.body
    assert "python -m pytest tests/test_functions_probe.py" in session.body
    assert session.title == "[agent/unknowns] Investigate parked unknowns: functions"


def test_planned_sessions_leave_docs_for_azure_codex_by_default():
    snapshot_result = agent_sessions.SnapshotLoadResult(snapshot={"regions": {}}, source="local")

    sessions = agent_sessions.planned_sessions(
        "both",
        now=datetime(2026, 7, 5, tzinfo=timezone.utc),
        snapshot_result=snapshot_result,
        unknown_groups=[],
        force_unknowns_without_candidates=False,
    )

    assert sessions == []


def test_planned_sessions_can_force_unknowns_without_candidates():
    snapshot_result = agent_sessions.SnapshotLoadResult(snapshot={"regions": {}}, source="local")

    sessions = agent_sessions.planned_sessions(
        "unknowns",
        now=datetime(2026, 7, 5, tzinfo=timezone.utc),
        snapshot_result=snapshot_result,
        unknown_groups=[],
        force_unknowns_without_candidates=True,
    )

    assert [session.key for session in sessions] == ["unknowns"]
    assert "No current `unknown` statuses" in sessions[0].body


def test_azure_codex_docs_prompt_preserves_status_semantics():
    prompt = codex_prompt.build_prompt(date(2026, 7, 8))

    assert "Scheduled Azure Codex task" in prompt
    assert "Run date: 2026-07-08" in prompt
    assert "do not describe unavailable as quota, capacity, deployment failure, or SLA impact" in prompt
    assert "Do not run Azure create/delete probes" in prompt
    assert "Read at most six files total" in prompt
    assert "Never use `cat`" in prompt