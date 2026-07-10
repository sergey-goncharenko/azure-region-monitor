from __future__ import annotations

from datetime import date, datetime, timezone


def build_prompt(run_date: date | None = None) -> str:
    run_date = run_date or datetime.now(timezone.utc).date()
    return f"""# Scheduled Azure Codex task: documentation and instructions maintenance

Run date: {run_date.isoformat()}

## Goal

Check one small documentation/instruction surface for confirmed drift against the current implementation and recent local history.

## Scope

- Start with `git log -8 --oneline`, README.md, `.github/copilot-instructions.md`, and docs/agentic-sessions.md.
- Choose at most one additional documentation file only when recent local history points to it.
- Inspect local git history and the checked-out repository only. Do not use web search, external network tools, GitHub APIs, or browser automation.
- Keep status semantics precise: do not describe unavailable as quota, capacity, deployment failure, or SLA impact unless a dedicated probe produced that evidence.
- Keep changes small and directly tied to implementation drift.

## Budget and guardrails

- Target 10 minutes of focused work; stop after one bounded review pass.
- Read at most six files total and use at most six shell commands before deciding whether drift is confirmed.
- Never use `cat`, unbounded `git show`, recursive file scans, or commands that print whole files. Use `sed -n` in windows of at most 160 lines and pipe search output through `head -50`.
- Do not copy full file contents into the response; summarize findings in your own words.
- Do not use web search or external network tools; the task is intentionally offline after checkout.
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