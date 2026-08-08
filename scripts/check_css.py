#!/usr/bin/env python3
"""Lint the dashboard stylesheet.

pytest and ruff cannot parse CSS, so two whole classes of defect reached `main`
unchallenged: custom properties declared but never referenced, and time values
written without a unit, which browsers silently drop.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STYLESHEET = REPO_ROOT / "src" / "azure_region_monitor" / "assets" / "dashboard.css"

# Most rules in this stylesheet are written on one line, so a declaration starts after
# `{` or `;` just as often as at the start of a line.
DECLARATION_START = r"(?:^|[{;])\s*"
DECLARATION_PATTERN = re.compile(DECLARATION_START + r"(--[A-Za-z0-9_-]+)\s*:", re.M)
REFERENCE_PATTERN = re.compile(r"var\(\s*(--[A-Za-z0-9_-]+)")
COMMENT_PATTERN = re.compile(r"/\*.*?\*/", re.S)
# `<time>` always needs a unit; unlike `<length>`, a bare 0 is invalid and dropped.
TIME_PROPERTIES = (
    "animation-duration",
    "animation-delay",
    "transition-duration",
    "transition-delay",
)
TIME_PATTERN = re.compile(
    DECLARATION_START + r"(" + "|".join(TIME_PROPERTIES) + r")\s*:\s*([^;}]+)",
    re.M,
)
TIME_VALUE_PATTERN = re.compile(r"^-?(?:\d+\.?\d*|\.\d+)$")


def unused_custom_properties(css: str) -> list[str]:
    """Return custom properties that no rule references, in declaration order."""
    body = COMMENT_PATTERN.sub("", css)
    referenced = set(REFERENCE_PATTERN.findall(body))
    seen: list[str] = []
    for name in DECLARATION_PATTERN.findall(body):
        if name not in referenced and name not in seen:
            seen.append(name)
    return seen


def unitless_time_values(css: str) -> list[str]:
    """Return `property: value` pairs where a time is missing its unit."""
    body = COMMENT_PATTERN.sub("", css)
    findings: list[str] = []
    for prop, raw in TIME_PATTERN.findall(body):
        value = raw.replace("!important", "").strip()
        if value.startswith("var(") or not value:
            continue
        for part in (piece.strip() for piece in value.split(",")):
            if TIME_VALUE_PATTERN.match(part):
                findings.append(f"{prop}: {part}")
    return findings


def lint(css: str) -> list[str]:
    problems = [
        f"Custom property {name} is declared but never referenced with var({name})."
        for name in unused_custom_properties(css)
    ]
    problems.extend(
        f"`{finding}` needs a time unit such as `0s`; browsers drop a unitless time."
        for finding in unitless_time_values(css)
    )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stylesheet", nargs="?", default=str(DEFAULT_STYLESHEET))
    args = parser.parse_args()

    path = Path(args.stylesheet)
    if not path.is_file():
        print(f"Stylesheet not found: {path}", file=sys.stderr)
        return 1

    problems = lint(path.read_text(encoding="utf-8"))
    if problems:
        print(f"{path}:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"{path}: no findings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
