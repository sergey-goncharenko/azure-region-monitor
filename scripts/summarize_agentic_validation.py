#!/usr/bin/env python3
"""Summarize the advisory validation of one agentic candidate patch.

Publication used to require a perfect patch, so a run whose only flaw was a missing
test or a lint finding produced nothing at all and the same issue was re-selected the
next day. Security and patch-integrity checks still block; quality findings are
reported on the resulting pull request instead of discarding the agent's work.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

SOURCE_PATTERN = re.compile(r"^src/.*\.py$")
TEST_PATTERN = re.compile(r"^tests/test_.*\.py$")
MARKER = "<!-- azure-agentic-validation -->"
MAX_LOG_CHARS = 8_000


def suggested_test_path(source_path: str) -> str:
    """Return the test module this repository would conventionally put the assertion in."""
    return f"tests/test_{Path(source_path).stem}.py"


def sources_without_tests(changed_files: list[str]) -> list[str]:
    if any(TEST_PATTERN.match(name) for name in changed_files):
        return []
    return [name for name in changed_files if SOURCE_PATTERN.match(name)]


def checks(changed_files: list[str], check_status: int) -> list[tuple[str, bool, str]]:
    """Return (name, passed, detail) for every advisory check, passing ones included.

    Reporting only the failures made a green suite indistinguishable from a broken one.
    """
    untested = sources_without_tests(changed_files)
    if untested:
        targets = ", ".join(f"`{suggested_test_path(name)}`" for name in untested)
        test_detail = f"none of the changed source files has a matching test; add {targets}"
    else:
        test_detail = "present"
    return [
        (
            "Tests, lint and stylesheet (`scripts/check.py`)",
            check_status == 0,
            "all green" if check_status == 0 else "failed - see the output below",
        ),
        ("Regression test accompanies the source change", not untested, test_detail),
    ]


def findings(changed_files: list[str], check_status: int) -> list[str]:
    return [
        f"{name}: {detail}" for name, passed, detail in checks(changed_files, check_status) if not passed
    ]


def _log_tail(check_log: str) -> str:
    if len(check_log) <= MAX_LOG_CHARS:
        return check_log
    return "...truncated...\n" + check_log[-MAX_LOG_CHARS:]


def report_markdown(
    changed_files: list[str],
    check_status: int,
    check_log: str,
    run_url: str,
) -> str:
    rows = checks(changed_files, check_status)
    failed = [row for row in rows if not row[1]]
    lines = [
        MARKER,
        "## Agentic publication validation",
        "",
        "This draft is published even when checks report findings. Review or repair every "
        "finding before marking the pull request ready.",
        "",
        "| Check | Result |",
        "| --- | --- |",
    ]
    lines.extend(
        f"| {name} | {'pass' if passed else 'action needed'} - {detail} |" for name, passed, detail in rows
    )
    lines.extend(["", "### Changed files", ""])
    lines.extend(f"- `{name}`" for name in changed_files)
    if failed:
        lines.extend(
            [
                "",
                "### Review before ready",
                "",
                "Push a fix or leave an ordinary review or source-issue comment with the "
                "decision and evidence. This report does not start another agent run.",
            ]
        )
    if run_url:
        lines.extend(["", f"[Publication run]({run_url})"])
    if check_status != 0:
        lines.extend(
            [
                "",
                "<details><summary>Validation output</summary>",
                "",
                "```",
                _log_tail(check_log).rstrip(),
                "```",
                "",
                "</details>",
            ]
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--changed-files", required=True, help="File listing changed paths.")
    parser.add_argument("--check-status", type=int, required=True)
    parser.add_argument("--check-log", required=True)
    parser.add_argument("--run-url", default="")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    changed_files = [
        line.strip()
        for line in Path(args.changed_files).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    check_log_path = Path(args.check_log)
    check_log = check_log_path.read_text(encoding="utf-8", errors="replace")

    problems = findings(changed_files, args.check_status)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "validation.md").write_text(
        report_markdown(changed_files, args.check_status, check_log, args.run_url),
        encoding="utf-8",
        newline="\n",
    )
    (output_dir / "validation.json").write_text(
        json.dumps(
            {
                # `neutral`, not `failure`: a red cross reads as "this is broken" and these
                # findings never block the pull request.
                "conclusion": "success" if not problems else "neutral",
                "title": (
                    "Advisory validation passed"
                    if not problems
                    else f"{len(problems)} advisory finding(s), nothing blocking"
                ),
                "summary": (
                    "Tests, lint and stylesheet checks all passed on the published patch."
                    if not problems
                    else "\n".join(f"- {problem}" for problem in problems)
                ),
                "changed_files": changed_files,
                "check_status": args.check_status,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"Advisory validation findings: {len(problems)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
