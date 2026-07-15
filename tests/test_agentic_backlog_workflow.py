from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / ".github/workflows/scheduled-agentic-backlog.md"
LOCK = REPO_ROOT / ".github/workflows/scheduled-agentic-backlog.lock.yml"
AIDER_FALLBACK = REPO_ROOT / ".github/workflows/scheduled-azure-backlog.yml"


def test_agentic_backlog_source_and_compiled_lock_are_committed():
    assert SOURCE.is_file()
    assert LOCK.is_file()
    assert "compiler_version\":\"v0.81.6" in LOCK.read_text(encoding="utf-8")
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
    assert "max-turns: 50" in source
    assert "max-ai-credits: 400" in source
    assert "max-daily-ai-credits: 800" in source
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
    assert "github: false" in source
    assert "--allow-tool github" not in lock
    assert "GITHUB_TOOLSETS" not in lock
    assert "You may inspect and edit the full repository" in source
    assert "allowed-files:" not in source
    assert '"allowed_files"' not in lock
    assert "publish_azure_backlog_status.py" in source
    assert "issues: write" in source


def test_agentic_backlog_gates_prs_on_full_validation_and_safe_outputs():
    source = SOURCE.read_text(encoding="utf-8")
    lock = LOCK.read_text(encoding="utf-8")

    assert "python -m pytest" in source
    assert "python -m ruff check ." in source
    assert "python -m ruff check --preview --select E117 ." in source
    assert "git diff --check" in source
    assert "git apply \"$patch_file\"" in source
    assert "deterministic code validation is not required for noop" in source
    assert "protected-files: request_review" in source
    assert "fallback-as-issue: false" in source
    assert "if-no-changes: error" in source
    assert "data/**" in source
    assert "public/api/**" in source
    assert "public/*.html" in source
    assert '"protected_files_policy":"request_review"' in lock
    assert "GH_AW_SAFE_OUTPUTS_HANDLER_CONFIG" in lock
