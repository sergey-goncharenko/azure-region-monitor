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
        "harness": "copilot",
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


def test_opencode_command_requires_installed_cli(monkeypatch):
    monkeypatch.setattr(byok_task.shutil, "which", lambda command: None)

    import pytest

    with pytest.raises(FileNotFoundError):
        byok_task._opencode_command()


def test_opencode_environment_isolates_key_and_enforces_scope(monkeypatch, tmp_path):
    home = tmp_path / "opencode-home"
    monkeypatch.setenv("AZURE_CODING_API_KEY", "azure-coding-key")
    monkeypatch.setenv("AZURE_CODING_RESOURCE_NAME", "coding-resource")
    monkeypatch.setenv("AZURE_CODING_MODEL", "o4-mini")
    monkeypatch.setenv("GH_TOKEN", "github-token")
    monkeypatch.setattr(byok_task.tempfile, "mkdtemp", lambda prefix: str(home))

    environment = byok_task._opencode_environment(_task())
    config = json.loads(environment["OPENCODE_CONFIG_CONTENT"])
    auth = json.loads(
        (home / "data" / "opencode" / "auth.json").read_text(encoding="utf-8")
    )

    assert environment["AZURE_RESOURCE_NAME"] == "coding-resource"
    assert "AZURE_CODING_API_KEY" not in environment
    assert "GH_TOKEN" not in environment
    assert all("azure-coding-key" not in value for value in environment.values())
    assert auth == {"azure": {"type": "api", "key": "azure-coding-key"}}
    assert config["model"] == "azure/o4-mini"
    assert config["compaction"]["prune"] is True
    agent = config["agent"]["azure-issue"]
    assert agent["steps"] == 24
    assert agent["permission"]["read"]["*"] == "allow"
    assert agent["permission"]["edit"]["*"] == "deny"
    assert agent["permission"]["edit"]["README.md"] == "allow"
    assert agent["permission"]["edit"]["**/README.md"] == "allow"
    assert agent["permission"]["bash"] == "deny"
    assert agent["permission"]["webfetch"] == "deny"
    assert agent["permission"]["external_directory"] == "deny"


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
    assert "complete at most one coherent implementation slice" in prompt
    assert "Bias toward action" in prompt
    assert "2-4 item decomposition proposal" in prompt
    assert "full repository" in prompt
    assert "Use line-numbered `source_excerpts` as starting hints" in prompt
    assert "scripts/agent_inspect.py PATH START_LINE END_LINE" in prompt
    assert "four successful calls" in prompt
    assert '"issue_number": 42' in prompt


def test_opencode_prompt_treats_objective_as_acceptance_target():
    prompt = byok_task._opencode_prompt(_task())

    assert "Treat concrete behavior named by the Objective" in prompt
    assert "Begin the smallest justified edit by step 12" in prompt
    assert "Modify only trusted `allowed_paths`" in prompt
    assert '"issue_number": 42' in prompt


def test_model_task_manifest_bounds_rich_context_and_source_excerpts(monkeypatch):
    monkeypatch.setattr(byok_task, "MAX_AGENT_EVIDENCE_CHARS", 40)
    monkeypatch.setattr(byok_task, "MAX_SOURCE_EXCERPT_CHARS", 20)
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
    assert isinstance(manifest["evidence"]["source_excerpts"], str)
    assert "context truncated for model rate budget" in manifest["evidence"]["github_issue_context"]
    assert "source_excerpts" in prompt


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


def test_agent_environment_uses_mini_coding_token_limits(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-key")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://eastus.api.cognitive.microsoft.com")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-5.4-mini")
    monkeypatch.setattr(byok_task.tempfile, "mkdtemp", lambda prefix: "C:/temporary/copilot")

    environment = byok_task._agent_environment()

    assert environment["COPILOT_PROVIDER_MAX_PROMPT_TOKENS"] == "32000"
    assert environment["COPILOT_PROVIDER_MAX_OUTPUT_TOKENS"] == "4000"
    assert environment["BYOK_AGENT_INSPECTION_BUDGET"] == "4"


def test_agent_environment_uses_nano_token_limits(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-key")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://eastus.api.cognitive.microsoft.com")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "copilot-gpt-5-4-nano")
    monkeypatch.setenv("COPILOT_BYOK_MODEL_ID", "gpt-5.4-nano")
    monkeypatch.setattr(byok_task.tempfile, "mkdtemp", lambda prefix: "C:/temporary/copilot")

    environment = byok_task._agent_environment()

    assert environment["COPILOT_PROVIDER_MAX_PROMPT_TOKENS"] == "32000"
    assert environment["COPILOT_PROVIDER_MAX_OUTPUT_TOKENS"] == "4000"


def test_agent_invocation_enables_local_shell_but_denies_remote_operations(monkeypatch):
    captured = {}
    monkeypatch.setattr(byok_task, "_copilot_command", lambda: ["copilot"])
    monkeypatch.setattr(
        byok_task,
        "_agent_environment",
        lambda: {"COPILOT_PROVIDER_MODEL_ID": "gpt-5.4-mini"},
    )
    monkeypatch.setattr(
        byok_task,
        "_run_with_graceful_timeout",
        lambda *args, **kwargs: captured.update(args=args, kwargs=kwargs)
        or subprocess.CompletedProcess(args, 0, "", ""),
    )

    byok_task._run_agent(_task())

    assert "--autopilot" in captured["args"]
    assert "--max-autopilot-continues" in captured["args"]
    continuation_index = captured["args"].index("--max-autopilot-continues")
    assert captured["args"][continuation_index + 1] == "3"
    assert "--deny-tool=powershell" in captured["args"]
    assert "--deny-tool=shell" not in captured["args"]
    assert "--deny-tool=shell(git push)" in captured["args"]
    assert "--deny-tool=shell(gh:*)" in captured["args"]
    assert "--deny-tool=shell(az:*)" in captured["args"]
    assert "--deny-tool=shell(pip)" in captured["args"]
    assert "--deny-tool=shell(python)" in captured["args"]
    assert "--deny-tool=shell(cat)" in captured["args"]
    assert "--deny-tool=shell(git show)" in captured["args"]
    assert "--no-ask-user" in captured["args"]
    assert "--no-custom-instructions" not in captured["args"]
    assert "--excluded-tools=view" in captured["args"]
    assert "--excluded-tools=read" not in captured["args"]
    assert not any(argument.startswith("--available-tools=") for argument in captured["args"])
    output_index = captured["args"].index("--output-format")
    assert captured["args"][output_index + 1] == "json"


def test_issue_agent_invocation_uses_bounded_opencode(monkeypatch, tmp_path):
    captured = {}
    transcript = tmp_path / "issue-42-chat.md"
    private_home = tmp_path / "opencode-home"
    (private_home / "data").mkdir(parents=True)
    monkeypatch.setenv("BYOK_AGENT_HARNESS", "opencode")
    monkeypatch.setenv("AZURE_CODING_MODEL", "o4-mini")
    monkeypatch.setattr(byok_task, "_opencode_command", lambda: ["opencode"])
    monkeypatch.setattr(
        byok_task,
        "_opencode_environment",
        lambda task: {"SAFE": "1", "XDG_DATA_HOME": str(private_home / "data")},
    )
    monkeypatch.setattr(
        byok_task,
        "_run_with_graceful_timeout",
        lambda *args, **kwargs: captured.update(args=args, kwargs=kwargs)
        or subprocess.CompletedProcess(args, 0, "", ""),
    )
    monkeypatch.setattr(
        byok_task,
        "_write_opencode_transcript",
        lambda stdout, path: captured.update(transcript=path),
    )

    byok_task._run_agent(_task(), transcript)

    assert captured["args"][:3] == ("opencode", "run", "--pure")
    assert "--auto" in captured["args"]
    assert "--model" in captured["args"]
    assert "azure/o4-mini" in captured["args"]
    assert "--agent" in captured["args"]
    assert "azure-issue" in captured["args"]
    assert "--format" in captured["args"]
    assert "json" in captured["args"]
    assert "--variant" not in captured["args"]
    assert captured["kwargs"]["env"] == {
        "SAFE": "1",
        "XDG_DATA_HOME": str(private_home / "data"),
    }
    assert captured["transcript"] == transcript
    assert not private_home.exists()


def test_report_only_agent_invocation_denies_file_mutation_tools(monkeypatch):
    captured = {}
    monkeypatch.setenv("BYOK_AGENT_HARNESS", "opencode")
    monkeypatch.setattr(byok_task, "_copilot_command", lambda: ["copilot"])
    monkeypatch.setattr(
        byok_task,
        "_agent_environment",
        lambda: {"COPILOT_PROVIDER_MODEL_ID": "gpt-5.4-mini"},
    )
    monkeypatch.setattr(
        byok_task,
        "_run_with_graceful_timeout",
        lambda *args, **kwargs: captured.update(args=args)
        or subprocess.CompletedProcess(args, 0, "", ""),
    )

    byok_task._run_agent(_task(), prompt="Analyze only.", report_only=True)

    assert "--excluded-tools=write" in captured["args"]
    assert "--excluded-tools=shell" in captured["args"]
    assert "--excluded-tools=edit" in captured["args"]
    assert "--excluded-tools=create" in captured["args"]
    assert "--excluded-tools=view" in captured["args"]
    assert "--excluded-tools=rg" in captured["args"]


def test_agent_invocation_has_graceful_session_timeout(monkeypatch):
    captured = {}
    monkeypatch.setenv("BYOK_AGENT_TIMEOUT_SECONDS", "123")
    monkeypatch.setenv("BYOK_AGENT_INTERRUPT_GRACE_SECONDS", "17")
    monkeypatch.setattr(byok_task, "_copilot_command", lambda: ["copilot"])
    monkeypatch.setattr(
        byok_task,
        "_agent_environment",
        lambda: {"COPILOT_PROVIDER_MODEL_ID": "gpt-5.4-mini"},
    )
    monkeypatch.setattr(
        byok_task,
        "_run_with_graceful_timeout",
        lambda *args, **kwargs: captured.update(kwargs=kwargs)
        or subprocess.CompletedProcess(args, 0, "", ""),
    )

    byok_task._run_agent(_task())

    assert captured["kwargs"]["timeout"] == 123
    assert captured["kwargs"]["grace_seconds"] == 17


def test_graceful_timeout_interrupts_before_raising(monkeypatch):
    import pytest

    calls = []
    interrupted = []

    class FakeProcess:
        returncode = 130

        def communicate(self, timeout=None):
            calls.append(timeout)
            if len(calls) == 1:
                raise subprocess.TimeoutExpired("copilot", timeout, output="partial")
            return "complete partial output", "interrupted"

    process = FakeProcess()
    monkeypatch.setattr(byok_task.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(
        byok_task,
        "_interrupt_process",
        lambda value: interrupted.append(value),
    )

    with pytest.raises(subprocess.TimeoutExpired) as captured:
        byok_task._run_with_graceful_timeout(
            "copilot",
            env={},
            timeout=123,
            grace_seconds=17,
        )

    assert calls == [123, 17]
    assert interrupted == [process]
    assert captured.value.output == "complete partial output"
    assert captured.value.stderr == "interrupted"


def test_timed_out_coding_session_fails_and_records_sanitized_metadata(
    monkeypatch, tmp_path, capsys
):
    transcript = tmp_path / "issue-42-chat.md"
    telemetry = tmp_path / "issue-42-telemetry.jsonl"
    metadata_path = tmp_path / "issue-42-metadata.json"
    recorded = {}
    monkeypatch.setattr(byok_task, "_existing_pr", lambda branch: "")
    monkeypatch.setattr(
        byok_task,
        "_run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, "", ""),
    )
    monkeypatch.setattr(byok_task, "_reset", lambda: None)
    monkeypatch.setattr(
        byok_task,
        "_audit_paths",
        lambda task: (transcript, telemetry, metadata_path),
    )
    monkeypatch.setattr(
        byok_task,
        "_run_agent",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(
                "copilot",
                1200,
                output=json.dumps(
                    {"type": "assistant.message", "data": {"outputTokens": 3}}
                ),
            )
        ),
    )
    monkeypatch.setattr(byok_task, "_sanitize_transcript", lambda path: recorded.update(sanitized=path))
    monkeypatch.setattr(byok_task, "_artifact_metadata", lambda path: {})
    monkeypatch.setattr(
        byok_task,
        "_write_metadata",
        lambda path, metadata: recorded.update(metadata=metadata),
    )

    result = byok_task.run_task(
        _task(tests=[]),
        base_branch="main",
        dry_run=False,
        force=False,
    )

    assert result == 0
    assert recorded["sanitized"] == transcript
    assert recorded["metadata"]["outcome"] == "timeout"
    assert "timed out after 1200 seconds" in capsys.readouterr().out


def test_timed_out_session_keeps_validated_in_scope_changes(monkeypatch, tmp_path):
    transcript = tmp_path / "issue-42-chat.md"
    telemetry = tmp_path / "issue-42-telemetry.jsonl"
    metadata_path = tmp_path / "issue-42-metadata.json"
    body_path = tmp_path / "pr-body.md"
    calls = []
    resets = []
    recorded = {}
    monkeypatch.setattr(byok_task, "_existing_pr", lambda branch: "")
    monkeypatch.setattr(
        byok_task,
        "_audit_paths",
        lambda task: (transcript, telemetry, metadata_path),
    )
    monkeypatch.setattr(
        byok_task,
        "_run_agent",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(
                "copilot",
                2400,
                output=json.dumps(
                    {
                        "type": "assistant.message",
                        "data": {"content": "Implemented the focused helper."},
                    }
                ),
            )
        ),
    )
    monkeypatch.setattr(byok_task, "_reset", lambda: resets.append(True))
    monkeypatch.setattr(byok_task, "_changed_paths", lambda: {"README.md"})
    monkeypatch.setattr(byok_task, "_sanitize_transcript", lambda path: None)
    monkeypatch.setattr(
        byok_task,
        "_agent_metadata",
        lambda stdout, telemetry_path, task: _metadata(),
    )
    monkeypatch.setattr(byok_task, "_artifact_metadata", lambda path: {})
    monkeypatch.setattr(
        byok_task,
        "_write_metadata",
        lambda path, metadata: recorded.update(metadata=dict(metadata)),
    )
    monkeypatch.setattr(
        byok_task,
        "_write_pr_body",
        lambda task, rationale, changed, metadata: (
            recorded.update(rationale=rationale),
            body_path.write_text("body", encoding="utf-8"),
            body_path,
        )[-1],
    )
    monkeypatch.setattr(
        byok_task,
        "_upsert_issue_note",
        lambda task, **kwargs: recorded.update(note=kwargs),
    )

    def run(*args, **kwargs):
        calls.append(args)
        if args[:3] == ("git", "diff", "--name-only"):
            return subprocess.CompletedProcess(args, 0, "README.md\n", "")
        if args[:3] == ("gh", "pr", "create"):
            return subprocess.CompletedProcess(args, 0, "https://example/pr/1", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(byok_task, "_run", run)

    result = byok_task.run_task(
        _task(tests=[]),
        base_branch="main",
        dry_run=False,
        force=False,
    )

    assert result == 0
    assert len(resets) == 1
    assert recorded["metadata"]["outcome"] == "timeout"
    assert recorded["metadata"]["validated_partial_changes"] is True
    assert "2400-second limit" in recorded["rationale"]
    assert recorded["note"]["outcome"] == "draft PR created"
    assert any(args[:3] == ("git", "commit", "-m") for args in calls)
    assert any(args[:2] == ("git", "push") for args in calls)
    assert any(args[:3] == ("gh", "pr", "create") for args in calls)


def test_issue_note_is_created_with_bounded_outcome(monkeypatch):
    calls = []
    captured = {}
    monkeypatch.setenv("GH_TOKEN", "token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/repo")
    monkeypatch.setenv("GITHUB_RUN_ID", "42")

    def run(*args, **kwargs):
        calls.append(args)
        if args[:2] == ("gh", "api") and "comments?per_page=100" in args[2]:
            return subprocess.CompletedProcess(args, 0, "[]", "")
        if "--input" in args:
            path = Path(args[args.index("--input") + 1])
            captured.update(json.loads(path.read_text(encoding="utf-8")))
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(byok_task, "_run", run)

    byok_task._upsert_issue_note(
        _task(),
        outcome="no PR needed",
        detail="One small slice was already satisfied.",
        metadata=_metadata(),
        rationale="### Decision\nSplit the remaining work.",
    )

    assert any("repos/example/repo/issues/42/comments" in args for args in calls)
    assert "azure-byok-agent-note:issue-42" in captured["body"]
    assert "Outcome: **no PR needed**" in captured["body"]
    assert "Queue state: **azure-paused**" in captured["body"]
    assert "Split the remaining work" in captured["body"]


def test_issue_note_replaces_existing_bot_comment(monkeypatch):
    calls = []
    monkeypatch.setenv("GH_TOKEN", "token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/repo")
    comments = json.dumps(
        [
            {
                "id": 700,
                "user": {"login": "github-actions[bot]"},
                "body": "<!-- azure-byok-agent-note:issue-42 -->",
            }
        ]
    )

    def run(*args, **kwargs):
        calls.append(args)
        stdout = comments if "comments?per_page=100" in args[2] else ""
        return subprocess.CompletedProcess(args, 0, stdout, "")

    monkeypatch.setattr(byok_task, "_run", run)

    byok_task._upsert_issue_note(
        _task(),
        outcome="timed out",
        detail="Stopped at the atomic time budget.",
    )

    assert any(
        args[:5]
        == ("gh", "api", "--method", "PATCH", "repos/example/repo/issues/comments/700")
        for args in calls
    )


def test_recurring_no_pr_note_does_not_pause_source_issue(monkeypatch):
    calls = []
    monkeypatch.setenv("GH_TOKEN", "token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/repo")

    def run(*args, **kwargs):
        calls.append(args)
        stdout = "[]" if args[:2] == ("gh", "api") else ""
        return subprocess.CompletedProcess(args, 0, stdout, "")

    monkeypatch.setattr(byok_task, "_run", run)

    byok_task._upsert_issue_note(
        _task(recurring=True),
        outcome="no PR needed",
        detail="No trustworthy corrective slice was justified.",
    )

    assert not any(args[:3] == ("gh", "issue", "edit") for args in calls)


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


def test_extract_final_agent_message_honors_report_limit():
    output = json.dumps(
        {
            "type": "assistant.message",
            "data": {"content": "1234567890"},
        }
    )

    assert byok_task._extract_final_agent_message(output, 5) == "12345"


def test_extract_agent_rationale_uses_latest_opencode_text_event():
    output = "\n".join(
        [
            json.dumps(
                {"type": "text", "part": {"text": "### Decision\nOld draft"}}
            ),
            json.dumps(
                {
                    "type": "text",
                    "part": {"text": "### Decision\nImplemented the focused change."},
                }
            ),
        ]
    )

    rationale = byok_task._extract_agent_rationale(output)

    assert "Implemented the focused change" in rationale
    assert "Old draft" not in rationale


def test_opencode_metadata_parses_exact_json_token_usage(monkeypatch):
    monkeypatch.setenv("AZURE_CODING_MODEL", "o4-mini")
    stdout = "\n".join(
        [
            json.dumps(
                {
                    "type": "step_finish",
                    "timestamp": 1000,
                    "sessionID": "session-open",
                    "part": {
                        "tokens": {
                            "input": 1423,
                            "output": 24,
                            "reasoning": 128,
                            "cache": {"read": 0, "write": 0},
                        },
                        "cost": 0.0022341,
                    },
                }
            ),
            json.dumps(
                {
                    "type": "step_finish",
                    "timestamp": 2000,
                    "sessionID": "session-open",
                    "part": {
                        "tokens": {
                            "input": 71,
                            "output": 73,
                            "reasoning": 0,
                            "cache": {"read": 1536, "write": 0},
                        },
                        "cost": 0.0008217,
                    },
                }
            ),
            json.dumps(
                {
                    "type": "text",
                    "timestamp": 3000,
                    "sessionID": "session-open",
                    "part": {"text": "Done."},
                }
            ),
        ]
    )

    metadata = byok_task._opencode_metadata(stdout, _task())

    assert metadata["harness"] == "opencode"
    assert metadata["model_id"] == "o4-mini"
    assert metadata["input_tokens"] == 3030
    assert metadata["cached_input_tokens"] == 1536
    assert metadata["output_tokens"] == 225
    assert metadata["reasoning_output_tokens"] == 128
    assert metadata["total_tokens"] == 3255
    assert metadata["api_calls"] == 2
    assert metadata["session_duration_ms"] == 2000
    assert metadata["session_id"] == "session-open"
    assert metadata["cost_usd"] == 0.003056


def test_opencode_transcript_keeps_visible_events_and_redacts(tmp_path):
    transcript = tmp_path / "chat.md"
    stdout = "\n".join(
        [
            json.dumps(
                {
                    "type": "tool_use",
                    "sessionID": "session-open",
                    "part": {
                        "tool": "edit",
                        "state": {
                            "status": "completed",
                            "input": {"filePath": "README.md"},
                            "output": "API_KEY=secret-value",
                        },
                    },
                }
            ),
            json.dumps(
                {
                    "type": "reasoning",
                    "sessionID": "session-open",
                    "part": {"text": "private reasoning"},
                }
            ),
            json.dumps(
                {
                    "type": "text",
                    "sessionID": "session-open",
                    "part": {"text": "### Decision\nDone."},
                }
            ),
        ]
    )

    byok_task._write_opencode_transcript(stdout, transcript)
    rendered = transcript.read_text(encoding="utf-8")

    assert "OpenCode CLI Session" in rendered
    assert "session-open" in rendered
    assert "Tool: `edit`" in rendered
    assert "README.md" in rendered
    assert "secret-value" not in rendered
    assert "[REDACTED]" in rendered
    assert "### Decision" in rendered
    assert "private reasoning" not in rendered


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


def test_transcript_diagnostics_count_compactions_and_provider_retries(tmp_path):
    transcript = tmp_path / "chat.md"
    transcript.write_text(
        "### ◌ Conversation Compacted\n"
        "Request failed due to a transient API error. Retrying...\n"
        "### ◌ Conversation Compacted\n",
        encoding="utf-8",
    )

    diagnostics = byok_task._transcript_diagnostics(transcript)

    assert diagnostics == {"context_compactions": 2, "transient_api_retries": 1}
    summary = byok_task._usage_summary(_metadata(**diagnostics))
    assert "Context compactions: 2; transient API retries: 1" in summary


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


def test_agent_failure_detail_includes_opencode_json_error():
    completed = subprocess.CompletedProcess(
        ["opencode", "run"],
        1,
        json.dumps(
            {
                "type": "error",
                "error": {"message": "Invalid model configuration api_key=secret-value"},
            }
        ),
        "",
    )

    detail = byok_task._agent_failure_detail(completed)

    assert "Invalid model configuration" in detail
    assert "secret-value" not in detail
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


def test_automated_rework_requires_the_reviewed_pr_to_remain_open(monkeypatch):
    monkeypatch.setattr(byok_task, "_existing_pr", lambda branch: "")

    result = byok_task.run_task(
        _task(tests=[]),
        base_branch="main",
        dry_run=False,
        force=True,
        required_pr="50",
    )

    assert result == 1
