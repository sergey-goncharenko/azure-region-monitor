#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MAX_LINES = 120
MAX_CHARS = 12_000
DEFAULT_BUDGET = 4


class InspectionError(ValueError):
    pass


def _inspection_budget() -> int:
    raw = os.environ.get("BYOK_AGENT_INSPECTION_BUDGET", str(DEFAULT_BUDGET))
    try:
        return max(0, min(DEFAULT_BUDGET, int(raw)))
    except ValueError:
        return DEFAULT_BUDGET


def _consume_inspection() -> None:
    home = os.environ.get("COPILOT_HOME", "").strip()
    if not home:
        return
    state_path = Path(home) / "bounded-inspection-count"
    try:
        used = int(state_path.read_text(encoding="utf-8")) if state_path.is_file() else 0
    except (OSError, ValueError):
        used = 0
    budget = _inspection_budget()
    if used >= budget:
        raise InspectionError(
            f"Inspection budget exhausted ({budget} calls); edit now or return a decomposition."
        )
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(str(used + 1), encoding="utf-8")


def inspect_file(path: str, start: int, end: int) -> str:
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise InspectionError("Path must be repository-relative and cannot contain '..'.")
    if start < 1 or end < start:
        raise InspectionError("Line range must be positive and ordered.")
    if end - start + 1 > MAX_LINES:
        raise InspectionError(f"A single inspection cannot exceed {MAX_LINES} lines.")

    target = (REPO_ROOT / candidate).resolve()
    try:
        target.relative_to(REPO_ROOT.resolve())
    except ValueError as error:
        raise InspectionError("Path resolves outside the repository.") from error
    if not target.is_file():
        raise InspectionError(f"Repository file not found: {path}")

    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    if start > len(lines):
        raise InspectionError(f"Start line {start} exceeds the file's {len(lines)} lines.")

    _consume_inspection()
    rendered: list[str] = []
    character_count = 0
    for line_number in range(start, min(end, len(lines)) + 1):
        line = f"{line_number:04d}: {lines[line_number - 1]}"
        if character_count + len(line) + 1 > MAX_CHARS:
            rendered.append(
                f"[inspection truncated at {MAX_CHARS} characters; request a narrower range]"
            )
            break
        rendered.append(line)
        character_count += len(line) + 1
    return "\n".join(rendered)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print one bounded, line-numbered repository file range for Copilot."
    )
    parser.add_argument("path")
    parser.add_argument("start", type=int)
    parser.add_argument("end", type=int)
    args = parser.parse_args()
    try:
        print(inspect_file(args.path, args.start, args.end))
    except InspectionError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
