from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "apply_azure_proposal.py"
SPEC = importlib.util.spec_from_file_location("apply_azure_proposal", SCRIPT_PATH)
assert SPEC is not None
proposal_applier = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = proposal_applier
SPEC.loader.exec_module(proposal_applier)


def _proposal(**overrides):
    proposal = {
        "category": "documentation-alignment",
        "decision": "patch",
        "summary": "Confirmed drift.",
        "pr_title": "docs: align documentation",
        "pr_body": "Correct a confirmed documentation statement.",
        "patch": "--- a/README.md\n+++ b/README.md\n@@\n-old\n+new\n",
        "allowed_paths": ["README.md"],
        "tests": [],
    }
    proposal.update(overrides)
    return proposal


def test_no_change_never_runs_commands(monkeypatch, capsys):
    monkeypatch.setattr(
        proposal_applier,
        "_run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("command should not run")),
    )

    result = proposal_applier.apply_proposal(
        _proposal(decision="no_change"),
        branch_prefix="azure-docs",
        base_branch="main",
        dry_run=False,
        force=False,
    )

    assert result == 0
    assert "No patch proposal" in capsys.readouterr().out


def test_dry_run_never_runs_commands(monkeypatch, capsys):
    monkeypatch.setattr(
        proposal_applier,
        "_run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("command should not run")),
    )

    result = proposal_applier.apply_proposal(
        _proposal(),
        branch_prefix="azure-docs",
        base_branch="main",
        dry_run=True,
        force=False,
    )

    assert result == 0
    assert "Dry run requested" in capsys.readouterr().out


def test_invalid_tests_scope_never_runs_commands(monkeypatch, capsys):
    monkeypatch.setattr(
        proposal_applier,
        "_run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("command should not run")),
    )

    result = proposal_applier.apply_proposal(
        _proposal(tests=["", 1]),
        branch_prefix="azure-docs",
        base_branch="main",
        dry_run=False,
        force=False,
    )

    assert result == 0
    assert "Invalid patch test scope" in capsys.readouterr().out
