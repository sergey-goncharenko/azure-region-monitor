from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_azure_maintenance_cycle.py"
REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("run_azure_maintenance_cycle", SCRIPT_PATH)
assert SPEC is not None
maintenance = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = maintenance
SPEC.loader.exec_module(maintenance)

NOW = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)


def _branch(name: str, *, days_old: int = 1, protected: bool = False):
    return {
        "name": name,
        "sha": f"sha-{name}",
        "protected": protected,
        "committed_at": (NOW - timedelta(days=days_old)).isoformat(),
    }


def _pull(number: int, branch: str, state: str):
    return {
        "number": number,
        "title": f"PR {number}",
        "state": state,
        "head": branch,
        "base": "main",
        "updated_at": (NOW - timedelta(days=1)).isoformat(),
        "url": f"https://example.test/pull/{number}",
    }


def test_branch_candidates_prioritize_merged_and_preserve_open_or_protected_branches():
    branches = [
        _branch("main"),
        _branch("merged-work"),
        _branch("closed-work"),
        _branch("open-work"),
        _branch("protected-work", protected=True),
        _branch("old-no-pr", days_old=45),
        _branch("recent-no-pr", days_old=2),
    ]
    pulls = [
        _pull(10, "merged-work", "MERGED"),
        _pull(11, "closed-work", "CLOSED"),
        _pull(12, "open-work", "OPEN"),
    ]

    candidates = maintenance._branch_candidates(branches, pulls, "main", NOW)

    by_name = {candidate["branch"]: candidate for candidate in candidates}
    assert by_name["merged-work"]["confidence"] == "high"
    assert by_name["merged-work"]["classification"] == "merged-pr-branch"
    assert "Recommend deleting" in by_name["merged-work"]["recommended_action"]
    assert by_name["closed-work"]["confidence"] == "medium"
    assert "Preserve by default" in by_name["closed-work"]["recommended_action"]
    assert by_name["old-no-pr"]["confidence"] == "low"
    assert "main" not in by_name
    assert "open-work" not in by_name
    assert "protected-work" not in by_name
    assert "recent-no-pr" not in by_name


def test_worktree_candidates_are_recommendations_only():
    worktrees = [
        {"worktree": "/repo", "branch": "main", "primary": True},
        {"worktree": "/repo.wt/merged", "branch": "merged-work", "primary": False},
        {"worktree": "/repo.wt/open", "branch": "open-work", "primary": False},
        {
            "worktree": "/repo.wt/prunable",
            "branch": "old-work",
            "primary": False,
            "prunable": "gitdir file points to non-existent location",
        },
    ]
    pulls = [_pull(10, "merged-work", "MERGED"), _pull(12, "open-work", "OPEN")]

    candidates = maintenance._worktree_candidates(worktrees, pulls)

    assert [candidate["branch"] for candidate in candidates] == [
        "merged-work",
        "old-work",
    ]
    assert all(candidate["recommendation_only"] for candidate in candidates)


def test_pull_request_evidence_normalizes_rest_merged_state(monkeypatch):
    monkeypatch.setattr(
        maintenance,
        "_source_api",
        lambda repository, path: [
            {
                "number": 50,
                "title": "Merged work",
                "state": "closed",
                "draft": False,
                "head": {"ref": "feature"},
                "base": {"ref": "main"},
                "user": {"login": "bot"},
                "created_at": "2026-07-10T00:00:00Z",
                "updated_at": "2026-07-11T00:00:00Z",
                "closed_at": "2026-07-11T00:00:00Z",
                "merged_at": "2026-07-11T00:00:00Z",
                "html_url": "https://example.test/pull/50",
            }
        ],
    )

    pulls = maintenance._pull_requests("example/repo")

    assert pulls[0]["state"] == "MERGED"
    assert pulls[0]["head"] == "feature"


def test_hygiene_evidence_never_authorizes_deletion(monkeypatch):
    monkeypatch.setattr(maintenance, "_remote_branches", lambda repository: [_branch("main")])
    monkeypatch.setattr(maintenance, "_pull_requests", lambda repository: [])
    monkeypatch.setattr(
        maintenance,
        "_worktrees",
        lambda: [{"worktree": "/repo", "branch": "main", "primary": True}],
    )

    evidence = maintenance._collect_hygiene_evidence("example/repo", "main", NOW)

    assert "No branch" in evidence["safety"]
    assert "cannot see developer-machine worktrees" in evidence["worktree_visibility_limit"]
    assert evidence["branch_deletion_candidates"] == []


def test_security_surfaces_are_bounded_and_line_numbered(monkeypatch, tmp_path):
    source = maintenance.REPO_ROOT / "scripts" / "security-surface-test.py"
    source.write_text("safe = True\nsubprocess.run(['tool'])\n", encoding="utf-8")
    try:
        snippets = maintenance._security_surface_evidence(
            ["scripts/security-surface-test.py"]
        )
    finally:
        source.unlink(missing_ok=True)

    assert snippets == [
        {
            "path": "scripts/security-surface-test.py",
            "start_line": 1,
            "lines": ["safe = True", "subprocess.run(['tool'])"],
        }
    ]


def test_cycle_contains_three_isolated_sessions_in_required_order(monkeypatch):
    class BacklogCycle:
        @staticmethod
        def _build_docs_task():
            return {
                "kind": "docs",
                "category": "documentation-alignment",
                "summary": "Docs",
            }

        @staticmethod
        def _git_history():
            return "abc123 docs"

    monkeypatch.setenv("GH_TOKEN", "token")
    monkeypatch.setattr(maintenance, "_load_backlog_cycle", lambda: BacklogCycle)
    monkeypatch.setattr(
        maintenance,
        "_collect_hygiene_evidence",
        lambda repository, default_branch, now: {
            "safety": "No deletion.",
            "branch_deletion_candidates": [],
        },
    )

    cycle = maintenance.build_cycle(
        "example/repo",
        default_branch="main",
        now=NOW,
    )

    assert [task["category"] for task in cycle["tasks"]] == [
        "documentation-alignment",
        "security-analysis",
        "repository-hygiene",
    ]
    assert [task["kind"] for task in cycle["tasks"]] == ["docs", "report", "report"]
    assert cycle["tasks"][1]["read_paths"] == []
    assert "Never perform deletion" in cycle["tasks"][2]["evidence"]["objective"]


def test_cycle_can_build_docs_or_reports_separately(monkeypatch):
    class BacklogCycle:
        @staticmethod
        def _build_docs_task():
            return {
                "kind": "docs",
                "category": "documentation-alignment",
                "summary": "Docs",
            }

        @staticmethod
        def _git_history():
            return "abc123 docs"

    monkeypatch.setattr(maintenance, "_load_backlog_cycle", lambda: BacklogCycle)
    monkeypatch.setattr(
        maintenance,
        "_collect_hygiene_evidence",
        lambda repository, default_branch, now: {"safety": "No deletion."},
    )

    docs = maintenance.build_cycle("example/repo", session_set="docs", now=NOW)
    reports = maintenance.build_cycle("example/repo", session_set="reports", now=NOW)

    assert [task["kind"] for task in docs["tasks"]] == ["docs"]
    assert [task["kind"] for task in reports["tasks"]] == ["report", "report"]


def test_cycle_markdown_marks_analysis_sessions_report_only():
    rendered = maintenance.render_cycle_markdown(
        {
            "tasks": [
                {
                    "kind": "docs",
                    "category": "documentation-alignment",
                    "summary": "Docs",
                },
                {
                    "kind": "report",
                    "category": "security-analysis",
                    "summary": "Security",
                },
                {
                    "kind": "report",
                    "category": "repository-hygiene",
                    "summary": "Hygiene",
                },
            ]
        }
    )

    assert "Session 1: `documentation-alignment`" in rendered
    assert rendered.count("Mode: report only") == 2


def test_public_maintenance_workflow_runs_documentation_only():
    workflow = (REPO_ROOT / ".github/workflows/scheduled-azure-maintenance.yml").read_text(
        encoding="utf-8"
    )

    assert 'cron: "0 9 * * *"' in workflow
    assert "run_azure_maintenance_cycle.py" in workflow
    assert "run_azure_byok_task.py" in workflow
    assert "--session-set docs" in workflow
    assert "run_azure_byok_report.py" not in workflow
    assert "persist-credentials: false" in workflow
    assert "azure-byok-chat-${{ github.run_id }}" in workflow
    assert "*-metadata.json" in workflow
    assert "*-telemetry.jsonl" not in workflow
    assert 'BYOK_AGENT_TIMEOUT_SECONDS: "600"' in workflow


def test_private_analysis_template_keeps_reports_out_of_public_repository():
    workflow = (
        REPO_ROOT / ".github/private-reporting/scheduled-private-analysis.yml"
    ).read_text(encoding="utf-8")

    assert 'cron: "0 10 * * *"' in workflow
    assert "repository: sergey-goncharenko/azure-region-monitor" in workflow
    assert "--session-set reports" in workflow
    assert "run_azure_byok_report.py" in workflow
    assert 'BYOK_REPORT_TRUST_CHECKOUT: "true"' in workflow
    assert "issues: write" in workflow
    assert "pull-requests: write" not in workflow
    assert "private-azure-analysis-${{ github.run_id }}" in workflow
    assert "*-telemetry.jsonl" not in workflow
    assert "git worktree remove" not in workflow
    assert "git push --delete" not in workflow
    assert "git worktree remove" not in workflow
    assert "git push --delete" not in workflow
    assert "gh api --method DELETE" not in workflow


def test_issue_backlog_workflow_no_longer_runs_documentation_lane():
    workflow = (REPO_ROOT / ".github/workflows/scheduled-azure-backlog.yml").read_text(
        encoding="utf-8"
    )

    assert "run_azure_maintenance_cycle.py" not in workflow
    assert "--skip-docs" not in workflow
    assert "persist-credentials: false" in workflow
    assert "*-metadata.json" in workflow
    assert "*-telemetry.jsonl" not in workflow
    assert 'BYOK_AGENT_TIMEOUT_SECONDS: "300"' in workflow
    assert 'BYOK_MAX_AUTOPILOT_CONTINUES: "1"' in workflow
