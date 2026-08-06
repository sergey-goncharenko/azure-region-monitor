from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / ".github/workflows/scheduled-agentic-backlog.md"
LOCK = REPO_ROOT / ".github/workflows/scheduled-agentic-backlog.lock.yml"
AIDER_FALLBACK = REPO_ROOT / ".github/workflows/scheduled-azure-backlog.yml"


def test_agentic_backlog_source_and_compiled_lock_are_committed():
    source = SOURCE.read_text(encoding="utf-8")
    assert SOURCE.is_file()
    assert LOCK.is_file()
    assert "compiler_version\":\"v0.81.6" in LOCK.read_text(encoding="utf-8")
    assert "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1" in source
    assert "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065" not in source
    assert ".github/workflows/*.lock.yml linguist-generated=true merge=ours" in (
        REPO_ROOT / ".gitattributes"
    ).read_text(encoding="utf-8")


def test_agentic_backlog_is_the_only_daily_issue_coding_schedule():
    source = SOURCE.read_text(encoding="utf-8")
    fallback = AIDER_FALLBACK.read_text(encoding="utf-8")

    assert 'cron: "0 7 * * *"' in source
    assert "  schedule:" not in fallback
    assert "repository_dispatch:" in fallback
    assert "workflow_dispatch:" in fallback
    assert "aider-chat==0.86.2" in fallback


def test_agentic_backlog_uses_existing_azure_o4_byok_with_secret_isolation():
    source = SOURCE.read_text(encoding="utf-8")
    lock = LOCK.read_text(encoding="utf-8")

    assert "engine:\n  id: copilot" in source
    assert 'version: "1.0.65"' in source
    assert "model: o4-mini" in source
    assert "max-continuations: 3" in source
    assert "max-turns: 80" in source
    assert "max-ai-credits: 700" in source
    assert "max-daily-ai-credits: 1400" in source
    assert "COPILOT_PROVIDER_WIRE_API: responses" in source
    assert "secrets.AZURE_CODING_OPENAI_KEY" in source
    assert "--exclude-env COPILOT_PROVIDER_API_KEY" in lock
    assert "--autopilot --max-autopilot-continues 3" in lock


def test_agentic_backlog_preserves_deterministic_selection_without_write_scope():
    source = SOURCE.read_text(encoding="utf-8")
    lock = LOCK.read_text(encoding="utf-8")

    assert "run_azure_backlog_cycle.py" in source
    assert "filter_azure_agentic_tasks.py" in source
    assert "task_b64" in source
    assert "summary_b64" in source
    assert "needs.prepare.outputs.has_task == 'true'" in source
    assert "base64 --decode > /tmp/gh-aw/agent/task.json" in source
    assert "base64 --decode > /tmp/gh-aw/agent/task-summary.md" in source
    assert '"jq:*"' in source
    assert '"python3:*"' in source
    assert '"pytest:*"' in source
    assert '"ruff:*"' in source
    assert "toolsets: [issues, repos, pull_requests]" in source
    assert "--allow-tool github" in lock
    assert "You may inspect and edit the full repository" in source
    assert "allowed-files:" not in source
    assert '"allowed_files"' not in lock
    assert "publish_azure_backlog_status.py" in source
    assert "issues: write" in source


def test_agentic_backlog_gates_prs_on_full_validation_and_safe_outputs():
    source = SOURCE.read_text(encoding="utf-8")
    lock = LOCK.read_text(encoding="utf-8")
    check_script = (REPO_ROOT / "scripts" / "check.py").read_text(encoding="utf-8")

    # Only security and patch integrity block publication. Quality findings ride along
    # with the draft PR, because a discarded run leaves the same issue at the queue head.
    assert "git apply \"$patch_file\"" in source
    assert "scripts/check.py is the gate itself and is not agent-editable" in source
    assert "python scripts/check.py > \"$RUNNER_TEMP/validation/check.log\"" in source
    assert "summarize_agentic_validation.py" in source
    assert "name: agentic-validation" in source
    assert "baseline_test_status" not in source
    assert "A source behavior change requires a focused regression test" not in source
    # The gate, PR CI, and the agent all share one entrypoint so they cannot drift.
    assert "python scripts/check.py --fix" in source
    assert '"-m", "pytest"' in check_script
    assert '"-m", "ruff", "check", "."' in check_script
    assert '"--preview", "--select", "E117"' in check_script
    assert '"--select", "B018"' in check_script
    assert '"git", "diff", "--check"' in check_script
    assert "causal chain from the source issue or exact live error" in source
    assert "do not substitute an adjacent consistency cleanup" in source
    assert "never embed literal `\\\\n` sequences" in source
    assert "an imperfect draft is reviewable and repairable" in source
    assert "this is a noop run" in source
    assert "protected-files: request_review" in source
    assert "fallback-as-issue: false" in source
    assert "if-no-changes: error" in source
    assert "data/**" in source
    assert "public/api/**" in source
    assert "public/*.html" in source
    assert '"protected_files_policy":"request_review"' in lock
    assert "GH_AW_SAFE_OUTPUTS_HANDLER_CONFIG" in lock


def test_ruff_rule_selection_is_pinned_against_tool_version_drift():
    # The gates install "ruff>=0.6,<1"; 0.16 widened the default rule set and made
    # the agentic validation gate unpassable against unchanged files. W291/W293 keep
    # `ruff check .` in parity with the `git diff --check` gate.
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "[tool.ruff.lint]" in pyproject
    assert 'select = ["E4", "E7", "E9", "F", "W291", "W293"]' in pyproject
