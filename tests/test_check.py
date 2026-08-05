from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
SPEC = importlib.util.spec_from_file_location("check", SCRIPT_PATH)
assert SPEC is not None
check = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = check
SPEC.loader.exec_module(check)


def test_verify_commands_run_tests_first_and_whitespace_last():
    commands = check.verify_commands()
    assert commands[0][1:] == ["-m", "pytest"]
    assert commands[1][1:] == ["-m", "ruff", "check", "."]
    assert commands[-1] == ["git", "diff", "--check"]


def test_verify_commands_accept_a_commit_range_for_pull_request_ci():
    assert check.verify_commands("abc123...HEAD")[-1] == [
        "git",
        "diff",
        "--check",
        "abc123...HEAD",
    ]


def test_strip_trailing_whitespace_repairs_lines_ruff_reports_and_git_rejects(tmp_path, monkeypatch):
    monkeypatch.setattr(check, "REPO_ROOT", tmp_path)
    target = tmp_path / "sample.py"
    target.write_text("value = 1   \n\t\nlast = 2\n", encoding="utf-8")

    assert check.strip_trailing_whitespace(["sample.py"]) == ["sample.py"]
    assert target.read_text(encoding="utf-8") == "value = 1\n\nlast = 2\n"


def test_strip_trailing_whitespace_preserves_a_missing_final_newline(tmp_path, monkeypatch):
    monkeypatch.setattr(check, "REPO_ROOT", tmp_path)
    target = tmp_path / "sample.md"
    target.write_text("# Title  ", encoding="utf-8")

    assert check.strip_trailing_whitespace(["sample.md"]) == ["sample.md"]
    assert target.read_text(encoding="utf-8") == "# Title"


def test_strip_trailing_whitespace_skips_clean_and_missing_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(check, "REPO_ROOT", tmp_path)
    clean = tmp_path / "clean.md"
    clean.write_text("# Title\n", encoding="utf-8")

    assert check.strip_trailing_whitespace(["clean.md", "absent.md"]) == []
    assert clean.read_text(encoding="utf-8") == "# Title\n"


def test_changed_paths_merges_tracked_edits_with_new_untracked_tests(monkeypatch):
    outputs = {
        ("git", "diff", "--name-only", "HEAD"): "src/a.py\n",
        ("git", "ls-files", "--others", "--exclude-standard"): "tests/test_a.py\nsrc/a.py\n",
    }

    def fake_run(command, **_kwargs):
        return subprocess.CompletedProcess(command, 0, outputs[tuple(command)], "")

    monkeypatch.setattr(check.subprocess, "run", fake_run)

    assert check.changed_paths() == ["src/a.py", "tests/test_a.py"]
