from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_azure_byok_task.py"
SPEC = importlib.util.spec_from_file_location("run_azure_byok_task", SCRIPT_PATH)
assert SPEC is not None
byok_task = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = byok_task
SPEC.loader.exec_module(byok_task)


def _task(**overrides):
    task = {
        "kind": "issue",
        "category": "issue-42",
        "summary": "Improve blog social output.",
        "allowed_paths": ["README.md", "tests/test_static_site.py"],
        "tests": ["tests/test_static_site.py"],
        "issue_number": 42,
        "evidence": {"issue_title": "Improve blog social output"},
    }
    task.update(overrides)
    return task


def _metadata(**overrides):
    metadata = {
        "model_id": "gpt-5.4-nano",
        "response_model": "copilot-gpt-5-4-nano",
        "deployment": "copilot-gpt-5-4-nano",
        "input_tokens": 15446,
        "cached_input_tokens": 0,
        "output_tokens": 26,
        "reasoning_output_tokens": 16,
        "total_tokens": 15472,
        "api_calls": 1,
        "session_duration_ms": 5957,
        "session_id": "session-123",
        "artifact_name": "azure-byok-chat-42",
        "transcript_file": "issue-42-chat.md",
        "run_url": "https://github.com/example/repo/actions/runs/42",
    }
    metadata.update(overrides)
    return metadata


def test_dry_run_never_invokes_commands(monkeypatch, capsys):
    monkeypatch.setattr(
        byok_task,
        "_run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("command should not run")),
    )

    result = byok_task.run_task(_task(), base_branch="main", dry_run=True, force=False)

    assert result == 0
    assert "Dry run requested" in capsys.readouterr().out


def test_invalid_scope_never_invokes_commands(monkeypatch, capsys):
    monkeypatch.setattr(
        byok_task,
        "_run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("command should not run")),
    )

    result = byok_task.run_task(
        _task(allowed_paths=["../outside.py"]), base_branch="main", dry_run=False, force=False
    )

    assert result == 0
    assert "invalid file scope" in capsys.readouterr().out


def test_byok_base_url_normalizes_direct_azure_endpoint():
    assert (
        byok_task._byok_base_url("https://eastus.api.cognitive.microsoft.com/")
        == "https://eastus.api.cognitive.microsoft.com/openai/v1"
    )
    assert (
        byok_task._byok_base_url("https://example.openai.azure.com/openai/v1")
        == "https://example.openai.azure.com/openai/v1"
    )


def test_byok_base_url_rejects_non_azure_or_insecure_endpoints():
    import pytest

    with pytest.raises(ValueError):
        byok_task._byok_base_url("http://example.openai.azure.com")
    with pytest.raises(ValueError):
        byok_task._byok_base_url("https://example.invalid")


def test_agent_environment_excludes_inherited_github_tokens(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-key")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://eastus.api.cognitive.microsoft.com")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-5.4-mini")
    monkeypatch.setenv("GH_TOKEN", "github-token")
    monkeypatch.setenv("GITHUB_TOKEN", "github-actions-token")
    monkeypatch.setattr(byok_task.tempfile, "mkdtemp", lambda prefix: "C:/temporary/copilot")

    environment = byok_task._agent_environment()

    assert environment["COPILOT_PROVIDER_API_KEY"] == "azure-key"
    assert "GH_TOKEN" not in environment
    assert "GITHUB_TOKEN" not in environment


def test_agent_environment_preserves_windows_path_name(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-key")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://eastus.api.cognitive.microsoft.com")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-5.4-mini")
    monkeypatch.delenv("PATH", raising=False)
    monkeypatch.setenv("Path", "C:/Program Files/nodejs")
    monkeypatch.setattr(byok_task.tempfile, "mkdtemp", lambda prefix: "C:/temporary/copilot")

    environment = byok_task._agent_environment()

    assert next(value for name, value in environment.items() if name.lower() == "path") == (
        "C:/Program Files/nodejs"
    )


def test_agent_environment_preserves_runtime_and_strips_secret_like_values(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-key")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://eastus.api.cognitive.microsoft.com")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-5.4-mini")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/opt/node/lib")
    monkeypatch.setenv("NPM_TOKEN", "npm-secret")
    monkeypatch.setenv("CUSTOM_PASSWORD", "password-secret")
    monkeypatch.setattr(byok_task.tempfile, "mkdtemp", lambda prefix: "C:/temporary/copilot")

    environment = byok_task._agent_environment()

    assert environment["LD_LIBRARY_PATH"] == "/opt/node/lib"
    assert "NPM_TOKEN" not in environment
    assert "CUSTOM_PASSWORD" not in environment
    assert "AZURE_OPENAI_API_KEY" not in environment


def test_copilot_command_requires_installed_cli(monkeypatch):
    monkeypatch.setattr(byok_task.shutil, "which", lambda command: None)

    import pytest

    with pytest.raises(FileNotFoundError):
        byok_task._copilot_command()


def test_pull_request_body_closes_source_issue():
    body_path = byok_task._write_pr_body(
        _task(
            evidence={
                "issue_title": "Improve blog social output",
                "objective": "Improve social drafts.",
                "priority": 300,
            }
        ),
        "### Decision\nAdded focused coverage.",
        {"README.md"},
        _metadata(),
    )
    try:
        body = body_path.read_text(encoding="utf-8")
    finally:
        body_path.unlink(missing_ok=True)

    assert "Closes #42" in body
    assert "## Why this task was selected" in body
    assert "Queue priority: High" in body
    assert "### Decision" in body
    assert "`README.md`" in body
    assert "Input tokens: 15,446" in body
    assert "Cached input tokens (subset of input): 0" in body
    assert "cached input is not added twice" in body
    assert "copilot-gpt-5-4-nano" in body
    assert "azure-byok-chat-42" in body
    assert "actions/runs/42#artifacts" in body
    assert "git diff --check" in body


def test_recurring_pull_request_body_does_not_close_source_issue():
    body_path = byok_task._write_pr_body(
        _task(recurring=True),
        "### Decision\nAdjusted timeout handling.",
        {"README.md"},
        _metadata(),
    )
    try:
        body = body_path.read_text(encoding="utf-8")
    finally:
        body_path.unlink(missing_ok=True)

    assert "Closes #42" not in body
    assert "merging this PR will not close" in body


def test_agent_prompt_includes_scope_and_untrusted_context_rules():
    prompt = byok_task._agent_prompt(_task())

    assert "Modify only files in `allowed_paths`" in prompt
    assert "untrusted product context" in prompt
    assert "approved backlog task" in prompt
    assert '"issue_number": 42' in prompt


def test_model_task_manifest_excludes_raw_file_excerpts_and_bounds_rich_context(monkeypatch):
    monkeypatch.setattr(byok_task, "MAX_AGENT_EVIDENCE_CHARS", 40)
    task = _task(
        evidence={
            "issue_title": "Improve API",
            "objective": "Add API tests.",
            "file_excerpts": {"src/api.py": "sensitive implementation text"},
            "github_issue_context": {"comments": [{"body": "x" * 200}]},
        }
    )

    manifest = byok_task._model_task_manifest(task)
    prompt = byok_task._agent_prompt(task)

    assert manifest["objective"] == "Add API tests."
    assert "file_excerpts" not in manifest["evidence"]
    assert isinstance(manifest["evidence"]["github_issue_context"], str)
    assert "context truncated for model rate budget" in manifest["evidence"]["github_issue_context"]
    assert "sensitive implementation text" not in prompt


def test_model_task_manifest_includes_current_unknown_status(monkeypatch):
    monkeypatch.setattr(byok_task, "MAX_AGENT_EVIDENCE_CHARS", 200)
    task = _task(
        recurring=True,
        evidence={
            "objective": "Investigate current unknown regressions.",
            "current_unknown_status": {
                "selected_category": "aksExtensions",
                "unknown_count": 39831,
            },
        },
    )

    manifest = byok_task._model_task_manifest(task)

    assert manifest["recurring"] is True
    assert manifest["evidence"]["current_unknown_status"]["selected_category"] == (
        "aksExtensions"
    )


def test_model_task_manifest_includes_pull_request_feedback(monkeypatch):
    monkeypatch.setattr(byok_task, "MAX_AGENT_EVIDENCE_CHARS", 300)
    task = _task(
        evidence={
            "objective": "Address requested API changes.",
            "github_pull_request_feedback": {
                "number": 50,
                "reviews": [
                    {"state": "CHANGES_REQUESTED", "body": "Avoid global state."}
                ],
            },
        }
    )

    manifest = byok_task._model_task_manifest(task)

    feedback = manifest["evidence"]["github_pull_request_feedback"]
    assert feedback["number"] == 50
    assert feedback["reviews"][0]["state"] == "CHANGES_REQUESTED"


def test_agent_environment_uses_reduced_provider_token_limits(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-key")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://eastus.api.cognitive.microsoft.com")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-5.4-mini")
    monkeypatch.setattr(byok_task.tempfile, "mkdtemp", lambda prefix: "C:/temporary/copilot")

    environment = byok_task._agent_environment()

    assert environment["COPILOT_PROVIDER_MAX_PROMPT_TOKENS"] == "5500"
    assert environment["COPILOT_PROVIDER_MAX_OUTPUT_TOKENS"] == "500"


def test_agent_environment_uses_nano_token_limits(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-key")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://eastus.api.cognitive.microsoft.com")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "copilot-gpt-5-4-nano")
    monkeypatch.setenv("COPILOT_BYOK_MODEL_ID", "gpt-5.4-nano")
    monkeypatch.setattr(byok_task.tempfile, "mkdtemp", lambda prefix: "C:/temporary/copilot")

    environment = byok_task._agent_environment()

    assert environment["COPILOT_PROVIDER_MAX_PROMPT_TOKENS"] == "32000"
    assert environment["COPILOT_PROVIDER_MAX_OUTPUT_TOKENS"] == "4000"


def test_agent_invocation_enables_internal_autopilot_but_denies_shell(monkeypatch):
    captured = {}
    monkeypatch.setattr(byok_task, "_copilot_command", lambda: ["copilot"])
    monkeypatch.setattr(
        byok_task,
        "_agent_environment",
        lambda: {"COPILOT_PROVIDER_MODEL_ID": "gpt-5.4-mini"},
    )
    monkeypatch.setattr(
        byok_task,
        "_run",
        lambda *args, **kwargs: captured.update(args=args, kwargs=kwargs)
        or subprocess.CompletedProcess(args, 0, "", ""),
    )

    byok_task._run_agent(_task())

    assert "--autopilot" in captured["args"]
    assert "--max-autopilot-continues" in captured["args"]
    assert "--deny-tool=powershell" in captured["args"]
    assert "--deny-tool=shell" in captured["args"]
    assert "--no-ask-user" in captured["args"]
    assert not any(argument.startswith("--available-tools=") for argument in captured["args"])
    output_index = captured["args"].index("--output-format")
    assert captured["args"][output_index + 1] == "json"


def test_extract_agent_rationale_uses_only_final_assistant_message_and_redacts():
    output = "\n".join(
        [
            json.dumps({"type": "assistant.reasoning", "data": {"content": "private"}}),
            json.dumps(
                {
                    "type": "assistant.message",
                    "data": {"content": "### Decision\nOld draft"},
                }
            ),
            json.dumps(
                {
                    "type": "assistant.message",
                    "data": {
                        "content": "### Decision\nUse the focused fix.\nToken: ghp_abcdefghijklmnop"
                    },
                }
            ),
            json.dumps({"type": "result", "data": {"exitCode": 0}}),
        ]
    )

    rationale = byok_task._extract_agent_rationale(output)

    assert "Use the focused fix" in rationale
    assert "Old draft" not in rationale
    assert "private" not in rationale
    assert "ghp_abcdefghijklmnop" not in rationale
    assert "[REDACTED]" in rationale


def test_agent_metadata_parses_exact_otel_token_usage(tmp_path, monkeypatch):
    monkeypatch.setenv("COPILOT_BYOK_MODEL_ID", "gpt-5.4-nano")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "copilot-gpt-5-4-nano")
    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text(
        json.dumps(
            {
                "type": "span",
                "spanId": "span-1",
                "attributes": {
                    "gen_ai.operation.name": "chat",
                    "gen_ai.usage.input_tokens": 15446,
                    "gen_ai.usage.output_tokens": 26,
                    "gen_ai.usage.reasoning.output_tokens": 16,
                    "gen_ai.response.model": "copilot-gpt-5-4-nano",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    stdout = "\n".join(
        [
            json.dumps(
                {
                    "type": "assistant.message",
                    "data": {"model": "copilot-gpt-5-4-nano", "outputTokens": 26},
                }
            ),
            json.dumps(
                {
                    "type": "result",
                    "sessionId": "session-123",
                    "usage": {"sessionDurationMs": 5957, "totalApiDurationMs": 2383},
                }
            ),
        ]
    )

    metadata = byok_task._agent_metadata(stdout, telemetry, _task())

    assert metadata["input_tokens"] == 15446
    assert metadata["output_tokens"] == 26
    assert metadata["reasoning_output_tokens"] == 16
    assert metadata["total_tokens"] == 15472
    assert metadata["api_calls"] == 1
    assert metadata["session_id"] == "session-123"


def test_sanitize_transcript_redacts_secret_like_text(tmp_path):
    transcript = tmp_path / "chat.md"
    transcript.write_text(
        "# Chat\n"
        "Token: ghp_abcdefghijklmnop\n"
        "github_pat_abcdefghijklmnopqrstuv\n"
        "Authorization: Bearer eyJabcdefgh.ijklmnop.qrstuvwx\n"
        "https://storage.example/blob?sv=1&sig=azure-signature&sp=r\n"
        "AccountKey=connection-secret;EndpointSuffix=core.windows.net\n"
        "API_KEY=secret-value\n",
        encoding="utf-8",
    )

    byok_task._sanitize_transcript(transcript)

    sanitized = transcript.read_text(encoding="utf-8")
    assert "ghp_abcdefghijklmnop" not in sanitized
    assert "github_pat_abcdefghijklmnopqrstuv" not in sanitized
    assert "eyJabcdefgh.ijklmnop.qrstuvwx" not in sanitized
    assert "azure-signature" not in sanitized
    assert "connection-secret" not in sanitized
    assert "secret-value" not in sanitized
    assert "[REDACTED]" in sanitized


def test_selection_summary_includes_live_unknown_evidence_and_recurring_semantics():
    summary = byok_task._selection_summary(
        _task(
            recurring=True,
            evidence={
                "issue_title": "Investigate unknowns",
                "objective": "Preserve trustworthy status evidence.",
                "priority": 400,
                "current_unknown_status": {
                    "selected_category": "aksExtensions",
                    "unknown_count": 39831,
                    "error_codes": [["AzureCliCommandFailed", 39831]],
                },
            },
        )
    )

    assert "Queue priority: Urgent" in summary
    assert "aksExtensions` (39831 checks)" in summary
    assert "AzureCliCommandFailed" in summary
    assert "will not close" in summary


def test_copilot_command_wraps_windows_batch_shim(monkeypatch):
    monkeypatch.setattr(byok_task.shutil, "which", lambda command: "C:/tools/copilot.bat")
    monkeypatch.setenv("COMSPEC", "C:/Windows/System32/cmd.exe")

    command = byok_task._copilot_command()

    assert command == ["C:/Windows/System32/cmd.exe", "/d", "/s", "/c", "C:/tools/copilot.bat"]


def test_failure_detail_filters_noise_and_redacts_secrets():
    detail = byok_task._safe_failure_detail(
        "normal output\nError: invalid provider api_key=secret-value\n"
        "Authorization: Bearer ghp_abcdefghijklmnop\n"
    )

    assert "normal output" not in detail
    assert "invalid provider" in detail
    assert "secret-value" not in detail
    assert "ghp_abcdefghijklmnop" not in detail
    assert "[REDACTED]" in detail


def test_force_rework_updates_existing_pr_branch_and_body(monkeypatch, tmp_path):
    calls = []
    transcript = tmp_path / "issue-42-chat.md"
    telemetry = tmp_path / "issue-42-telemetry.jsonl"
    metadata_path = tmp_path / "issue-42-metadata.json"
    monkeypatch.setattr(byok_task, "_existing_pr", lambda branch: "50")
    monkeypatch.setattr(
        byok_task,
        "_audit_paths",
        lambda task: (transcript, telemetry, metadata_path),
    )
    monkeypatch.setattr(
        byok_task,
        "_run_agent",
        lambda task, transcript_path, telemetry_path: subprocess.CompletedProcess(
            ["copilot"],
            0,
            json.dumps(
                {
                    "type": "assistant.message",
                    "data": {"content": "### Decision\nApplied requested changes."},
                }
            ),
            "",
        ),
    )
    monkeypatch.setattr(byok_task, "_changed_paths", lambda: {"README.md"})
    monkeypatch.setattr(byok_task, "_sanitize_transcript", lambda path: None)
    monkeypatch.setattr(
        byok_task,
        "_agent_metadata",
        lambda stdout, telemetry_path, task: _metadata(),
    )
    monkeypatch.setattr(byok_task, "_artifact_metadata", lambda path: {})
    monkeypatch.setattr(byok_task, "_write_metadata", lambda path, metadata: None)

    def run(*args, **kwargs):
        calls.append(args)
        stdout = "README.md\n" if args[:3] == ("git", "diff", "--name-only") else ""
        return subprocess.CompletedProcess(args, 0, stdout, "")

    monkeypatch.setattr(byok_task, "_run", run)

    result = byok_task.run_task(
        _task(tests=[]),
        base_branch="main",
        dry_run=False,
        force=True,
    )

    assert result == 0
    assert (
        "git",
        "fetch",
        "origin",
        "azure-issues/issue-42:refs/remotes/origin/azure-issues/issue-42",
        "--depth",
        "50",
    ) in calls
    assert ("git", "checkout", "-B", "azure-issues/issue-42", "origin/azure-issues/issue-42") in calls
    assert any(args[:4] == ("gh", "pr", "edit", "50") for args in calls)
    assert any(args[:4] == ("gh", "pr", "comment", "50") for args in calls)
    assert not any(args[:3] == ("gh", "pr", "create") for args in calls)
