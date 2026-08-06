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


def missing_regression_test(changed_files: list[str]) -> bool:
    has_source = any(SOURCE_PATTERN.match(name) for name in changed_files)
    has_test = any(TEST_PATTERN.match(name) for name in changed_files)
    return has_source and not has_test


def findings(changed_files: list[str], check_status: int) -> list[str]:
    results: list[str] = []
    if check_status != 0:
        results.append(
            "`python scripts/check.py` failed on the candidate patch. "
            "Run `python scripts/check.py --fix` on this branch to reproduce and repair it."
        )
    if missing_regression_test(changed_files):
        results.append(
            "A `src/**/*.py` change landed without a `tests/test_*.py` change. "
            "Presentation-only edits still need one focused assertion, and for generated "
            "CSS or HTML that assertion belongs in `tests/test_static_site.py`."
        )
    return results


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
    problems = findings(changed_files, check_status)
    lines = [MARKER, "## Agentic publication validation", ""]
    if not problems:
        lines.append("Deterministic validation passed on the published patch.")
    else:
        lines.append(
            "This draft was published so the work is reviewable, but deterministic "
            "validation reported findings. They are advisory: only security and "
            "patch-integrity checks block publication."
        )
        lines.append("")
        lines.extend(f"{index}. {problem}" for index, problem in enumerate(problems, start=1))
    lines.extend(["", "### Changed files", ""])
    lines.extend(f"- `{name}`" for name in changed_files)
    if run_url:
        lines.extend(["", f"[Publication run]({run_url})"])
    if problems and check_status != 0:
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
                "state": "success" if not problems else "failure",
                "description": (
                    "Deterministic validation passed."
                    if not problems
                    else f"{len(problems)} advisory validation finding(s)."
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
