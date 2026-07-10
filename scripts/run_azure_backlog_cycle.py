from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from azure_region_monitor.social_client import AzureOpenAiTextClient

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT_URL = "https://azwatch.operator.lat/api/latest.json"

_DOCS_PATCH_SYSTEM = """You are a cautious technical writer for an Azure regional availability monitor.

The supplied review has confirmed specific documentation or instruction drift. Propose one small, factual patch that addresses only that confirmed drift. Use only the supplied excerpts. Preserve the repository's status semantics: unavailable is catalog/listing absence evidence, not quota, capacity, deployment, eligibility, or SLA evidence. Do not modify generated data, source code, tests, or workflows unless the confirmed drift explicitly names one of those files.

Return only this JSON object:
{
    "decision": "patch" or "no_change",
    "summary": "concise factual conclusion",
    "pr_title": "docs: ...",
    "pr_body": "why the patch is justified and validation to run",
    "patch": "unified diff or empty string"
}

Choose no_change unless the review and supplied excerpts prove an exact, small textual correction. For a patch, include only standard unified diff text for the allowed paths, with exact unchanged context from the excerpts. Do not include prose outside the JSON object."""


def _load_module(name: str, script_name: str):
    path = REPO_ROOT / "scripts" / script_name
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {script_name}.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _max_goal_items(goals_path: Path) -> int:
    try:
        payload = json.loads(goals_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 2
    value = payload.get("max_items_per_run", 2) if isinstance(payload, dict) else 2
    try:
        return max(0, min(2, int(value)))
    except (TypeError, ValueError):
        return 2


def _propose_unknowns(client: AzureOpenAiTextClient, snapshot_url: str) -> dict[str, Any]:
    unknowns = _load_module("azure_backlog_unknowns", "run_azure_unknowns_agent.py")
    context = unknowns.build_proposal_context(snapshot_url)
    if not context["category"]:
        proposal = unknowns._no_change(context, context["summary"])
    else:
        raw = client.generate(
            system=unknowns._SYSTEM_PROMPT,
            user="Bounded unknown-status evidence:\n" + json.dumps(
                context["evidence"], ensure_ascii=False, sort_keys=True
            ),
        )
        proposal = unknowns._parse_proposal(raw, context)
    return {"kind": "unknowns", "proposal": proposal}


def _propose_goals(
    client: AzureOpenAiTextClient, goals_path: Path, limit: int
) -> list[dict[str, Any]]:
    goals = _load_module("azure_backlog_goals", "run_azure_goal_agent.py")
    unknowns = _load_module("azure_backlog_goal_unknowns", "run_azure_unknowns_agent.py")
    proposals = []
    for index in range(min(limit, _max_goal_items(goals_path))):
        context = goals.build_goal_context(goals_path, index)
        if not context["category"]:
            proposal = unknowns._no_change(context, context["summary"])
        else:
            raw = client.generate(
                system=goals._SYSTEM_PROMPT,
                user="Approved goal and bounded local evidence:\n" + json.dumps(
                    context["evidence"], ensure_ascii=False, sort_keys=True
                ),
            )
            proposal = unknowns._parse_proposal(raw, context)
        proposals.append({"kind": "goal", "proposal": proposal})
    return proposals


def _propose_docs(client: AzureOpenAiTextClient) -> dict[str, Any]:
    docs = _load_module("azure_backlog_docs", "run_azure_docs_review.py")
    unknowns = _load_module("azure_backlog_docs_unknowns", "run_azure_unknowns_agent.py")
    review = docs._parse_review(
        client.generate(system=docs._SYSTEM_PROMPT, user=docs.build_review_facts())
    )
    allowed_paths = [
        item["file"]
        for item in review["confirmed_drift"]
        if (REPO_ROOT / item["file"]).is_file()
    ]
    context = {
        "category": "documentation-alignment" if allowed_paths else "",
        "summary": review["summary"],
        "allowed_paths": list(dict.fromkeys(allowed_paths)),
        "tests": ["tests/test_static_site.py"]
        if any(path in {"README.md", "public/index.html"} for path in allowed_paths)
        else [],
        "evidence": {
            "review": review,
            "allowed_paths": allowed_paths,
            "file_excerpts": {path: docs._read_excerpt(path) for path in allowed_paths},
        },
    }
    if not context["category"]:
        proposal = unknowns._no_change(
            context, "No confirmed documentation drift was found in the bounded review."
        )
    else:
        raw = client.generate(
            system=_DOCS_PATCH_SYSTEM,
            user="Confirmed documentation drift and bounded excerpts:\n"
            + json.dumps(context["evidence"], ensure_ascii=False, sort_keys=True),
        )
        proposal = unknowns._parse_proposal(raw, context)
    return {"kind": "docs", "proposal": proposal}


def render_cycle_markdown(cycle: dict[str, Any]) -> str:
    lines = ["## Azure coding backlog", ""]
    for item in cycle["proposals"]:
        proposal = item["proposal"]
        prefix = {
            "unknowns": "Unknowns",
            "goal": "Backlog",
            "docs": "Documentation alignment",
        }[item["kind"]]
        lines.extend([f"### {prefix}: `{proposal['category'] or 'none'}`", "", proposal["summary"], ""])
        if proposal["decision"] == "patch":
            lines.append(f"Draft PR candidate: `{proposal['pr_title']}`")
        else:
            lines.append("No safe patch proposal was produced.")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate bounded Azure backlog patch proposals.")
    parser.add_argument("--snapshot-url", default=DEFAULT_SNAPSHOT_URL)
    parser.add_argument("--goals", type=Path, default=REPO_ROOT / "config" / "azure_agent_backlog.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    client = AzureOpenAiTextClient.from_env(max_output_tokens=1_600)
    max_items = _max_goal_items(args.goals)
    unknown = _propose_unknowns(client, args.snapshot_url)
    proposals = []
    if unknown["proposal"]["category"]:
        proposals.append(unknown)
    remaining = max(0, max_items - len(proposals))
    proposals.extend(_propose_goals(client, args.goals, remaining))
    proposals.append(_propose_docs(client))
    cycle = {"proposals": proposals}
    args.output.write_text(json.dumps(cycle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(render_cycle_markdown(cycle))


if __name__ == "__main__":
    main()
