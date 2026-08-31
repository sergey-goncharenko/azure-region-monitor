from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "summarize_agentic_validation.py"
SPEC = importlib.util.spec_from_file_location("summarize_agentic_validation", SCRIPT_PATH)
assert SPEC is not None
summarize = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = summarize
SPEC.loader.exec_module(summarize)


PROBE = "src/azure_region_monitor/probes/model_latency.py"


def test_suggested_test_path_points_at_the_matching_module():
    # PR #71 changed the latency probe and was told the assertion belonged in the
    # static-site tests, which was boilerplate for a completely unrelated surface.
    assert summarize.suggested_test_path(PROBE) == "tests/test_model_latency.py"
    assert (
        summarize.suggested_test_path("src/azure_region_monitor/static_site.py")
        == "tests/test_static_site.py"
    )


def test_sources_without_tests_lists_the_actual_files():
    assert summarize.sources_without_tests([PROBE]) == [PROBE]
    assert summarize.sources_without_tests([PROBE, "tests/test_model_latency.py"]) == []
    assert summarize.sources_without_tests(["README.md"]) == []


def test_checks_report_passing_rows_too():
    rows = summarize.checks([PROBE], check_status=0)
    assert any("scripts/check.py" in name for name, _passed, _detail in rows)
    assert rows[0][1] is True and rows[0][2] == "all green"
    assert rows[1][1] is False


def test_report_names_the_right_test_file_and_says_nothing_is_blocked():
    report = summarize.report_markdown([PROBE], 0, "", "https://example.invalid/run/1")
    assert report.startswith(summarize.MARKER)
    assert "draft is published even when checks report findings" in report
    assert "tests/test_model_latency.py" in report
    assert "static_site" not in report
    # The green row must stay visible, otherwise a reader cannot tell a passing suite
    # from a broken one.
    assert "pass - all green" in report
    assert "before marking the pull request ready" in report
    assert "https://example.invalid/run/1" in report


def test_clean_report_has_no_resolution_section():
    report = summarize.report_markdown([PROBE, "tests/test_model_latency.py"], 0, "", "")
    assert "action needed" not in report
    assert "To resolve" not in report


def test_failed_check_marks_the_row_and_attaches_the_output():
    report = summarize.report_markdown([PROBE], 1, "boom happened", "")
    assert "action needed - failed" in report
    assert "boom happened" in report
    assert "Review before ready" in report
    assert "does not start another agent run" in report


def test_long_check_output_is_truncated_from_the_front():
    tail = summarize._log_tail("x" * (summarize.MAX_LOG_CHARS + 500))
    assert tail.startswith("...truncated...")
    assert len(tail) == summarize.MAX_LOG_CHARS + len("...truncated...\n")


def _run_main(tmp_path, changed_lines: str, check_status: str):
    changed = tmp_path / "changed.txt"
    changed.write_text(changed_lines, encoding="utf-8")
    check_log = tmp_path / "check.log"
    check_log.write_text("boom\n", encoding="utf-8")
    out = tmp_path / "out"

    original = sys.argv
    sys.argv = [
        "summarize_agentic_validation.py",
        "--changed-files",
        str(changed),
        "--check-status",
        check_status,
        "--check-log",
        str(check_log),
        "--output-dir",
        str(out),
    ]
    try:
        assert summarize.main() == 0
    finally:
        sys.argv = original
    return json.loads((out / "validation.json").read_text(encoding="utf-8")), out


def test_advisory_result_is_neutral_never_failure(tmp_path):
    # A red cross reads as "the build is broken"; these findings never block the PR.
    state, out = _run_main(tmp_path, f"{PROBE}\n", "1")
    assert state["conclusion"] == "neutral"
    assert "nothing blocking" in state["title"]
    assert state["check_status"] == 1
    assert state["changed_files"] == [PROBE]
    assert "boom" in (out / "validation.md").read_text(encoding="utf-8")


def test_clean_run_concludes_success(tmp_path):
    state, _ = _run_main(tmp_path, f"{PROBE}\ntests/test_model_latency.py\n", "0")
    assert state["conclusion"] == "success"
