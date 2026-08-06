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


def test_css_only_change_is_reported_but_never_blocks():
    # Issue #53 shape: all dashboard CSS lives in a Python string literal.
    changed = ["src/azure_region_monitor/static_site.py"]
    assert summarize.missing_regression_test(changed) is True

    problems = summarize.findings(changed, check_status=0)
    assert len(problems) == 1
    assert "tests/test_static_site.py" in problems[0]


def test_source_change_with_a_test_reports_nothing():
    changed = ["src/azure_region_monitor/static_site.py", "tests/test_static_site.py"]
    assert summarize.missing_regression_test(changed) is False
    assert summarize.findings(changed, check_status=0) == []


def test_docs_only_change_needs_no_test():
    assert summarize.missing_regression_test(["README.md"]) is False


def test_failed_check_is_reported_alongside_the_missing_test():
    problems = summarize.findings(["src/azure_region_monitor/api.py"], check_status=1)
    assert len(problems) == 2
    assert "scripts/check.py --fix" in problems[0]


def test_report_markdown_is_idempotently_updatable_and_lists_changed_files():
    report = summarize.report_markdown(
        ["src/azure_region_monitor/static_site.py"],
        check_status=0,
        check_log="",
        run_url="https://example.invalid/run/1",
    )
    assert report.startswith(summarize.MARKER)
    assert "advisory" in report
    assert "- `src/azure_region_monitor/static_site.py`" in report
    assert "https://example.invalid/run/1" in report


def test_clean_report_states_success_without_a_findings_list():
    report = summarize.report_markdown([], check_status=0, check_log="", run_url="")
    assert "Deterministic validation passed" in report
    assert "advisory" not in report


def test_long_check_output_is_truncated_from_the_front():
    tail = summarize._log_tail("x" * (summarize.MAX_LOG_CHARS + 500))
    assert tail.startswith("...truncated...")
    assert len(tail) == summarize.MAX_LOG_CHARS + len("...truncated...\n")


def test_main_writes_the_report_and_machine_readable_state(tmp_path):
    changed = tmp_path / "changed.txt"
    changed.write_text("src/azure_region_monitor/static_site.py\n", encoding="utf-8")
    check_log = tmp_path / "check.log"
    check_log.write_text("boom\n", encoding="utf-8")
    out = tmp_path / "out"

    argv = [
        "summarize_agentic_validation.py",
        "--changed-files",
        str(changed),
        "--check-status",
        "1",
        "--check-log",
        str(check_log),
        "--output-dir",
        str(out),
    ]
    original = sys.argv
    sys.argv = argv
    try:
        assert summarize.main() == 0
    finally:
        sys.argv = original

    state = json.loads((out / "validation.json").read_text(encoding="utf-8"))
    assert state["state"] == "failure"
    assert state["check_status"] == 1
    assert state["changed_files"] == ["src/azure_region_monitor/static_site.py"]
    assert "boom" in (out / "validation.md").read_text(encoding="utf-8")
