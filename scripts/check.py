#!/usr/bin/env python3
"""Single repository validation entrypoint.

CI, the agentic publication gate, and agent sessions all call this so the three
cannot drift apart. ``--fix`` first repairs the mechanical findings (unused
imports, trailing whitespace) that have otherwise discarded whole agent runs.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def verify_commands(diff_range: str = "") -> list[list[str]]:
    """Return the checks in the order CI and the publication gate run them."""
    whitespace = ["git", "diff", "--check"]
    if diff_range:
        whitespace.append(diff_range)
    return [
        [sys.executable, "-m", "pytest"],
        [sys.executable, "-m", "ruff", "check", "."],
        [sys.executable, "-m", "ruff", "check", "--preview", "--select", "E117", "."],
        [sys.executable, "-m", "ruff", "check", "--select", "B018", "."],
        [sys.executable, "scripts/check_css.py"],
        whitespace,
    ]


def _run(command: Sequence[str]) -> int:
    print(f"\n$ {' '.join(command)}", flush=True)
    return subprocess.run(list(command), cwd=REPO_ROOT, check=False).returncode


def _git_lines(command: Sequence[str]) -> list[str]:
    result = subprocess.run(
        list(command),
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def changed_paths() -> list[str]:
    """Return working-tree changes, including files the agent has not staged yet."""
    tracked = _git_lines(["git", "diff", "--name-only", "HEAD"])
    untracked = _git_lines(["git", "ls-files", "--others", "--exclude-standard"])
    return sorted({*tracked, *untracked})


def strip_trailing_whitespace(paths: Iterable[str]) -> list[str]:
    """Remove the trailing whitespace `git diff --check` rejects but ruff cannot see."""
    repaired: list[str] = []
    for name in paths:
        path = REPO_ROOT / name
        if not path.is_file():
            continue
        try:
            original = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        cleaned = "\n".join(line.rstrip() for line in original.splitlines())
        if original.endswith("\n"):
            cleaned += "\n"
        if cleaned != original:
            path.write_text(cleaned, encoding="utf-8", newline="\n")
            repaired.append(name)
    return repaired


def apply_fixes(paths: Sequence[str]) -> None:
    python_paths = [
        name for name in paths if name.endswith(".py") and (REPO_ROOT / name).is_file()
    ]
    if python_paths:
        _run([sys.executable, "-m", "ruff", "check", "--fix", *python_paths])
    repaired = strip_trailing_whitespace(paths)
    if repaired:
        print(f"Stripped trailing whitespace from: {', '.join(repaired)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run repository validation.")
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Repair mechanical lint findings before verifying.",
    )
    parser.add_argument(
        "--path",
        action="append",
        default=[],
        dest="paths",
        help="Limit --fix to this path. Repeatable. Defaults to current working-tree changes.",
    )
    parser.add_argument(
        "--diff-range",
        default="",
        help="Commit range for the whitespace check, such as <base-sha>...HEAD.",
    )
    args = parser.parse_args()

    if args.fix:
        apply_fixes(args.paths or changed_paths())

    failed: list[str] = []
    for command in verify_commands(args.diff_range):
        if _run(command) != 0:
            failed.append(" ".join(command))

    if failed:
        print("\nFAILED:")
        for command in failed:
            print(f"  {command}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
