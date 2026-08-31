from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / ".github/workflows/scheduled-agentic-backlog.md"
LOCK = REPO_ROOT / ".github/workflows/scheduled-agentic-backlog.lock.yml"
AIDER_FALLBACK = REPO_ROOT / ".github/workflows/scheduled-azure-backlog.yml"


def test_agentic_backlog_source_and_compiled_lock_are_committed():
    source = SOURCE.read_text(encoding="utf-8")
    assert SOURCE.is_file()
    assert LOCK.is_file()
    assert "compiler_version\":\"v0.87.10" in LOCK.read_text(encoding="utf-8")
    assert "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1" in source
    assert "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065" not in source
    # gh-aw v0.86 stopped setting merge=ours on generated locks, so a lock conflict is
    # now surfaced rather than silently resolved in favour of the local side.
    assert ".github/workflows/*.lock.yml linguist-generated=true" in (
        REPO_ROOT / ".gitattributes"
    ).read_text(encoding="utf-8")


def test_agentic_backlog_is_the_only_daily_issue_coding_schedule():
    source = SOURCE.read_text(encoding="utf-8")
    fallback = AIDER_FALLBACK.read_text(encoding="utf-8")

    assert 'cron: "23 6 * * *"' in source
    assert "  schedule:" not in fallback
    assert "repository_dispatch:" in fallback
    assert "workflow_dispatch:" in fallback
    assert "aider-chat==0.86.2" in fallback


def test_agentic_backlog_uses_existing_azure_byok_with_secret_isolation():
    source = SOURCE.read_text(encoding="utf-8")
    lock = LOCK.read_text(encoding="utf-8")

    assert "engine:\n  id: copilot" in source
    assert "version: ${{ vars.AZWATCH_AGENTIC_COPILOT_VERSION }}" in source
    assert "model: ${{ vars.AZWATCH_AGENTIC_MODEL }}" in source
    assert "secrets.AZWATCH_AGENTIC_AZURE_BASE_URL" in source
    assert '"*.openai.azure.com"' in source
    assert "max-continuations: 3" in source
    assert "max-turns: ${{ vars.AZWATCH_AGENTIC_MAX_TURNS }}" in source
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
    assert "request_azure_backlog_objectives.py" in source
    assert "Ask maintainers to clarify malformed issue objectives" in source
    assert "id: objective-questions" in source
    assert "steps.objective-questions.outcome == 'failure'" in source
    assert "a later run will retry" in source
    assert "issues: write" in source


def test_agentic_backlog_gates_prs_on_full_validation_and_safe_outputs():
    source = SOURCE.read_text(encoding="utf-8")
    lock = LOCK.read_text(encoding="utf-8")
    check_script = (REPO_ROOT / "scripts" / "check.py").read_text(encoding="utf-8")
    policy = (
        REPO_ROOT / ".github/workflows/shared/agentic-policy.md"
    ).read_text(encoding="utf-8")

    # Findings ride along with the draft PR, because discarding reviewable work leaves
    # the same issue at the queue head. Only transport/integrity failures stop publication.
    assert "git apply \"$patch_file\"" in source
    assert "git ls-files --others --exclude-standard" in source
    assert "sort -u > \"$RUNNER_TEMP/validation/changed-files.txt\"" in source
    assert "The scripts/check*.py validators are the gate itself" in source
    assert "python scripts/check.py > \"$RUNNER_TEMP/validation/check.log\"" in source
    assert "summarize_agentic_validation.py" in source
    assert "name: agentic-validation" in source
    assert "baseline_test_status" not in source
    assert "A source behavior change requires a focused regression test" not in source
    # The gate, PR CI, and the agent all share one entrypoint so they cannot drift.
    # create_pull_request is rejected with "no commits were found", so the agent must be
    # able to branch and commit; run 32006961427 finished the work and lost it without this.
    assert '"git checkout:*"' in source
    assert '"git add:*"' in source
    assert '"git commit:*"' in source
    assert "no commits were found" in source
    assert "`pytest` and `ruff` are not importable" in source or "not importable from your sandbox" in source
    assert "Publish even when validation or threat detection reports findings" in source
    assert "Never weaken a check or hide a finding" in source
    assert '"-m", "pytest"' in check_script
    assert '"-m", "ruff", "check", "."' in check_script
    assert '"--preview", "--select", "E117"' in check_script
    assert '"--select", "B018"' in check_script
    assert '"git", "diff", "--check"' in check_script
    assert "Identify a causal chain from the Objective or exact observed failure" in policy
    assert "Do not substitute adjacent cleanup" in policy
    assert "draft PR, warning label, and generated `REQUEST_CHANGES` review" in source
    assert "this is a noop run" in source
    assert "protected-files: request_review" in source
    assert "continue-on-error: true" in source
    assert "add-comment:" in source
    assert 'target: "*"' in source
    assert "required-labels: [azure-backlog]" in source
    assert "call `add_comment` exactly once" in source
    assert "no command is required" in source
    assert "not configured to publish `.github/workflows/**`" in source
    assert "fallback-as-issue: false" in source
    assert "if-no-changes: error" in source
    assert "data/**" in source
    assert "public/api/**" in source
    assert "public/*.html" in source
    assert '\\"protected_files_policy\\":\\"request_review\\"' in lock
    assert (
        '\\"add_comment\\":{\\"max\\":1,\\"required_labels\\":[\\"azure-backlog\\"],'
        '\\"target\\":\\"*\\"}' in lock
    )
    assert 'GH_AW_DETECTION_CONTINUE_ON_ERROR: "true"' in lock
    assert "GH_AW_SAFE_OUTPUTS_HANDLER_CONFIG" in lock


def test_agentic_backlog_pins_ripgrep_before_generated_installers():
    source = SOURCE.read_text(encoding="utf-8")
    lock = LOCK.read_text(encoding="utf-8")

    assert source.count("Install pinned ripgrep") == 2
    assert "steps.detection_guard.outputs.run_detection == 'true'" in source
    assert "ripgrep-15.2.0-x86_64-unknown-linux-musl.tar.gz" not in source
    assert "33e15bcf1624b25cdd2a55813a47a2f95dbe126268203e76aa6a585d1e7b149c" in source
    assert "--retry 3" in source
    assert "--max-time 60" in source
    assert "apt-get" not in source
    preflights = [
        index
        for index in range(len(lock))
        if lock.startswith("- name: Install pinned ripgrep", index)
    ]
    generated_installers = [
        index
        for index in range(len(lock))
        if lock.startswith("- name: Install ripgrep\n", index)
    ]
    assert len(preflights) == 2
    assert generated_installers == []


def test_ruff_rule_selection_is_pinned_against_tool_version_drift():
    # The gates install "ruff>=0.6,<1"; 0.16 widened the default rule set and made
    # the agentic validation gate unpassable against unchanged files. W291/W293 keep
    # `ruff check .` in parity with the `git diff --check` gate.
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "[tool.ruff.lint]" in pyproject
    assert 'select = ["E4", "E7", "E9", "F", "W291", "W293"]' in pyproject
