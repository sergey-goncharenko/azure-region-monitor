from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

from azure_region_monitor.social_client import AzureOpenAiTextClient

REPO_ROOT = Path(__file__).resolve().parents[1]

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


def _max_issue_items(value: object) -> int:
    try:
        return max(0, min(2, int(value)))
    except (TypeError, ValueError):
        return 2


def _propose_issues(
    client: AzureOpenAiTextClient, issues_path: Path, limit: int, repository: str
) -> list[dict[str, Any]]:
    issues = _load_module("azure_backlog_issues", "run_azure_issue_agent.py")
    unknowns = _load_module("azure_backlog_issue_unknowns", "run_azure_unknowns_agent.py")
    if repository and not os.environ.get("GH_TOKEN"):
        raise RuntimeError("GH_TOKEN is required to fetch GitHub issue comments and sub-issues.")
    github_context_client = (
        issues.GitHubIssueContextClient.from_env(repository) if repository else None
    )
    proposals = []
    for index in range(limit):
        context = issues.build_issue_context(issues_path, index, github_context_client)
        if not context["category"]:
            proposal = unknowns._no_change(context, context["summary"])
        else:
            raw = client.generate(
                system=issues._SYSTEM_PROMPT,
                user="Approved GitHub issue and bounded local evidence:\n" + json.dumps(
                    context["evidence"], ensure_ascii=False, sort_keys=True
                ),
            )
            proposal = unknowns._parse_proposal(raw, context)
            proposal["issue_number"] = context["issue_number"]
        proposals.append({"kind": "issue", "proposal": proposal})
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
            "issue": "GitHub backlog issue",
            "docs": "Documentation alignment",
        }[item["kind"]]
        lines.extend([f"### {prefix}: `{proposal['category'] or 'none'}`", "", proposal["summary"], ""])
        if proposal["decision"] == "patch":
            lines.append(f"Draft PR candidate: `{proposal['pr_title']}`")
        else:
            lines.append("No safe patch proposal was produced.")
        lines.append("")
    return "\n".join(lines)


def build_cycle(
    client: AzureOpenAiTextClient,
    issues_path: Path,
    max_issues: object,
    repository: str = "",
) -> dict[str, list[dict[str, Any]]]:
    proposals = _propose_issues(client, issues_path, _max_issue_items(max_issues), repository)
    proposals.append(_propose_docs(client))
    return {"proposals": proposals}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate bounded Azure GitHub issue patch proposals.")
    parser.add_argument("--issues", type=Path, required=True)
    parser.add_argument("--max-issues", type=int, default=2)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    client = AzureOpenAiTextClient.from_env(max_output_tokens=1_600)
    cycle = build_cycle(client, args.issues, args.max_issues, args.repository)
    args.output.write_text(json.dumps(cycle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(render_cycle_markdown(cycle))


if __name__ == "__main__":
    main()
