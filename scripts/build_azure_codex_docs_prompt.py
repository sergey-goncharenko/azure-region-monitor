from __future__ import annotations

from datetime import date, datetime, timezone


def build_prompt(run_date: date | None = None) -> str:
    run_date = run_date or datetime.now(timezone.utc).date()
    return f"""# Scheduled Azure Codex task: documentation and instructions maintenance

Run date: {run_date.isoformat()}

## Goal

Check whether this repository's documentation, runbooks, workflows, and Copilot instructions still match the current implementation and recent project history.

## Scope

- Compare current code and tests with README.md, docs/poc-deployment.md, docs/spec, docs/roadmap, docs/agentic-sessions.md, and .github/copilot-instructions.md.
- Inspect recent commits, open PRs/issues, and recent failed GitHub Actions runs when that context is available locally or through the checked-out repository.
- Keep status semantics precise: do not describe unavailable as quota, capacity, deployment failure, or SLA impact unless a dedicated probe produced that evidence.
- Keep changes small and directly tied to implementation drift.

## Budget and guardrails

- Target 30 minutes of focused work; stop before 45 minutes if the task is not converging.
- Prefer targeted reads over broad repository scans.
- Do not run Azure create/delete probes or change live dashboard data.
- Do not edit generated public/api or data snapshot files by hand.
- Create a pull request only when changes are needed. If no change is needed, leave the working tree clean.

## Validation

- For docs-only changes, run python -m pytest tests/test_static_site.py tests/test_summary.py when practical.
- If code or generated dashboard behavior changes, run the focused tests for the touched slice, then python -m pytest and python -m ruff check . when practical.

## Pull request

- Use a title like docs: refresh monitor docs and agent instructions.
- Summarize what drift was found and which checks were run.
"""


def main() -> None:
    print(build_prompt())


if __name__ == "__main__":
    main()