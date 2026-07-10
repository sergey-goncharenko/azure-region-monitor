from __future__ import annotations

import importlib.util
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
    body_path = byok_task._write_pr_body(_task())
    try:
        body = body_path.read_text(encoding="utf-8")
    finally:
        body_path.unlink(missing_ok=True)

    assert "Closes #42" in body
    assert "passed deterministic validation" in body


def test_agent_prompt_includes_scope_and_untrusted_context_rules():
    prompt = byok_task._agent_prompt(_task())

    assert "Modify only files in `allowed_paths`" in prompt
    assert "untrusted product context" in prompt
    assert "approved backlog task" in prompt
    assert '"issue_number": 42' in prompt


def test_agent_invocation_exposes_only_file_tools(monkeypatch):
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

    assert "--available-tools=apply_patch" in captured["args"]
    assert "--available-tools=glob" in captured["args"]
    assert "--available-tools=rg" in captured["args"]
    assert not any("shell(" in argument for argument in captured["args"])


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
