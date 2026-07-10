from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

from azure_region_monitor.social_client import AzureOpenAiTextClient

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GOALS_PATH = REPO_ROOT / "config" / "azure_agent_goals.json"
MAX_EVIDENCE_FILES = 5

_SYSTEM_PROMPT = """You are a cautious senior engineer proposing one small, evidence-backed repository improvement from an approved goal queue.

Use only the supplied goal and bounded local evidence. Never edit generated snapshot data, add create/delete lifecycle probes, weaken tests, claim quota/capacity/SLA conclusions, or change files outside the approved allowlist.

Return only this JSON object:
{
  "decision": "patch" or "no_change",
  "summary": "concise factual conclusion",
  "pr_title": "feat: ... or fix: ...",
  "pr_body": "why the patch is justified and tests to run",
  "patch": "unified diff or empty string"
}

Choose no_change unless the approved goal and supplied excerpts prove a small fix is ready. Before proposing a patch, verify that the work is not already implemented in the supplied excerpts. For a patch, include only standard unified diff text for the supplied allowlist paths, with exact unchanged context from the excerpts. Do not include prose outside the JSON object."""


def _load_unknowns_module():
    path = REPO_ROOT / "scripts" / "run_azure_unknowns_agent.py"
    spec = importlib.util.spec_from_file_location("azure_goal_unknowns", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load shared Azure patch proposal helper.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git_history() -> str:
    import subprocess

    completed = subprocess.run(
        ["git", "log", "-8", "--oneline"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() or "[git history unavailable]"


def _load_goals(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    goals = payload.get("goals") if isinstance(payload, dict) else None
    if not isinstance(goals, list):
        return []
    valid = []
    for goal in goals:
        if not isinstance(goal, dict) or not goal.get("enabled"):
            continue
        goal_id = str(goal.get("id", "")).strip()
        title = str(goal.get("title", "")).strip()
        description = str(goal.get("goal", "")).strip()
        paths = goal.get("allowed_paths")
        tests = goal.get("tests")
        if (
            not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", goal_id)
            or not title
            or not description
            or not isinstance(paths, list)
            or not isinstance(tests, list)
        ):
            continue
        allowed_paths = [str(item) for item in paths if isinstance(item, str) and item]
        test_paths = [str(item) for item in tests if isinstance(item, str) and item]
        if not allowed_paths or not test_paths:
            continue
        if any(not (REPO_ROOT / item).exists() for item in allowed_paths + test_paths):
            continue
        valid.append(
            {
                "id": goal_id,
                "title": title,
                "goal": description,
                "priority": int(goal.get("priority", 0)),
                "allowed_paths": allowed_paths,
                "tests": test_paths,
            }
        )
    return sorted(valid, key=lambda item: (-item["priority"], item["id"]))


def build_goal_context(goals_path: Path = DEFAULT_GOALS_PATH) -> dict[str, Any]:
    goals = _load_goals(goals_path)
    if not goals:
        return {
            "category": "",
            "summary": "No enabled Azure coding goals were found in config/azure_agent_goals.json.",
            "allowed_paths": [],
            "tests": [],
            "evidence": {},
        }
    goal = goals[0]
    unknowns = _load_unknowns_module()
    evidence_paths = goal["allowed_paths"][:MAX_EVIDENCE_FILES]
    evidence = {
        "goal_id": goal["id"],
        "goal_title": goal["title"],
        "goal": goal["goal"],
        "recent_git_history": _git_history(),
        "allowed_paths": goal["allowed_paths"],
        "tests": goal["tests"],
        "file_excerpts": {path: unknowns._read_excerpt(path) for path in evidence_paths},
    }
    return {
        "category": goal["id"],
        "summary": "Highest-priority enabled Azure coding goal selected from the approved queue.",
        "allowed_paths": goal["allowed_paths"],
        "tests": goal["tests"],
        "evidence": evidence,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a bounded Azure goal patch proposal.")
    parser.add_argument("--goals", type=Path, default=DEFAULT_GOALS_PATH)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    unknowns = _load_unknowns_module()
    context = build_goal_context(args.goals)
    if not context["category"]:
        proposal = unknowns._no_change(context, context["summary"])
    else:
        client = AzureOpenAiTextClient.from_env(max_output_tokens=1_600)
        raw = client.generate(
            system=_SYSTEM_PROMPT,
            user="Approved goal and bounded local evidence:\n" + json.dumps(
                context["evidence"], ensure_ascii=False, sort_keys=True
            ),
        )
        proposal = unknowns._parse_proposal(raw, context)

    args.output.write_text(json.dumps(proposal, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(render_goal_markdown(proposal))


def render_goal_markdown(proposal: dict[str, Any]) -> str:
    lines = ["## Azure higher-level goal review", "", proposal["summary"], ""]
    if proposal["decision"] != "patch":
        lines.append("No safe goal patch proposal was produced; no branch or PR will be created.")
        return "\n".join(lines) + "\n"
    lines.extend(
        [
            f"- Goal: `{proposal['category']}`",
            f"- Proposed PR: `{proposal['pr_title']}`",
            f"- Allowed paths: {', '.join(f'`{path}`' for path in proposal['allowed_paths'])}",
            f"- Focused tests: {', '.join(f'`{path}`' for path in proposal['tests']) or 'none'}",
            "",
            "Patch output is validated locally before any branch or draft PR is created.",
        ]
    )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
