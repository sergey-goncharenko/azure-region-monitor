from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "agent_inspect.py"
SPEC = importlib.util.spec_from_file_location("agent_inspect", SCRIPT_PATH)
assert SPEC is not None
agent_inspect = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = agent_inspect
SPEC.loader.exec_module(agent_inspect)


def test_inspect_file_returns_bounded_numbered_range(monkeypatch, tmp_path):
    source = tmp_path / "src" / "example.py"
    source.parent.mkdir()
    source.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")
    monkeypatch.setattr(agent_inspect, "REPO_ROOT", tmp_path)
    monkeypatch.delenv("COPILOT_HOME", raising=False)

    rendered = agent_inspect.inspect_file("src/example.py", 2, 3)

    assert rendered == "0002: two\n0003: three"


def test_inspect_file_rejects_unsafe_or_large_ranges(monkeypatch, tmp_path):
    source = tmp_path / "example.py"
    source.write_text("line\n" * 200, encoding="utf-8")
    monkeypatch.setattr(agent_inspect, "REPO_ROOT", tmp_path)

    with pytest.raises(agent_inspect.InspectionError, match="repository-relative"):
        agent_inspect.inspect_file(str(source.resolve()), 1, 2)
    with pytest.raises(agent_inspect.InspectionError, match="cannot exceed 120 lines"):
        agent_inspect.inspect_file("example.py", 1, 121)
    with pytest.raises(agent_inspect.InspectionError, match="exceeds the file"):
        agent_inspect.inspect_file("example.py", 201, 201)


def test_inspect_file_caps_character_output(monkeypatch, tmp_path):
    source = tmp_path / "example.py"
    source.write_text("x" * (agent_inspect.MAX_CHARS + 100), encoding="utf-8")
    monkeypatch.setattr(agent_inspect, "REPO_ROOT", tmp_path)
    monkeypatch.delenv("COPILOT_HOME", raising=False)

    rendered = agent_inspect.inspect_file("example.py", 1, 1)

    assert "inspection truncated" in rendered
    assert len(rendered) < 200


def test_inspect_file_enforces_per_session_budget(monkeypatch, tmp_path):
    source = tmp_path / "example.py"
    source.write_text("line\n", encoding="utf-8")
    home = tmp_path / "copilot-home"
    monkeypatch.setattr(agent_inspect, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("COPILOT_HOME", str(home))
    monkeypatch.setenv("BYOK_AGENT_INSPECTION_BUDGET", "4")

    for _ in range(4):
        assert agent_inspect.inspect_file("example.py", 1, 1) == "0001: line"

    with pytest.raises(agent_inspect.InspectionError, match="budget exhausted"):
        agent_inspect.inspect_file("example.py", 1, 1)
