from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "start_copilot_agent_sessions.py"
SPEC = importlib.util.spec_from_file_location("start_copilot_agent_sessions", SCRIPT_PATH)
assert SPEC is not None
agent_sessions = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = agent_sessions
SPEC.loader.exec_module(agent_sessions)

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


def test_model_latency_scope_includes_provider_payload_contracts():
    assert agent_sessions.CATEGORY_TEST_HINTS["modelLatency"] == (
        "tests/test_model_latency.py",
        "tests/test_latency_client_resilience.py",
        "tests/test_github_models_payload.py",
        "tests/test_azure_openai_payload.py",
    )


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


