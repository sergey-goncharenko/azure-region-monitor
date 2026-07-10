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
MAX_EVIDENCE_FILES = 5
MAX_AUTO_TESTS = 3
BACKLOG_LABEL = "azure-backlog"
PAUSED_LABEL = "azure-paused"
_STOP_WORDS = {
    "about",
    "agent",
    "and",
    "availability",
    "azure",
    "bound",
    "dashboard",
    "evidence",
    "for",
    "from",
    "improve",
    "into",
    "more",
    "our",
    "repository",
    "solution",
    "the",
    "this",
    "to",
    "without",
}
_PRIORITIES = {"high": 300, "normal": 200, "low": 100}

_SYSTEM_PROMPT = """You are a cautious senior engineer proposing one small, evidence-backed repository improvement for an approved GitHub backlog issue.

Use only the supplied issue and bounded local evidence. Never edit generated snapshot data, add create/delete lifecycle probes, weaken tests, claim quota/capacity/SLA conclusions, or change files outside the approved allowlist.

Return only this JSON object:
{
  "decision": "patch" or "no_change",
  "summary": "concise factual conclusion",
  "pr_title": "feat: ... or fix: ...",
  "pr_body": "why the patch is justified and tests to run",
  "patch": "unified diff or empty string"
}

Choose no_change unless the approved issue and supplied excerpts prove a small fix is ready. Before proposing a patch, verify that the work is not already implemented in the supplied excerpts. For a patch, include only standard unified diff text for the supplied allowlist paths, with exact unchanged context from the excerpts. Do not include prose outside the JSON object."""


def _load_unknowns_module():
    path = REPO_ROOT / "scripts" / "run_azure_unknowns_agent.py"
    spec = importlib.util.spec_from_file_location("azure_issue_unknowns", path)
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


def _labels(issue: dict[str, Any]) -> set[str]:
    labels = issue.get("labels")
    if not isinstance(labels, list):
        return set()
    names = set()
    for label in labels:
        if isinstance(label, str) and label:
            names.add(label.lower())
        elif isinstance(label, dict) and isinstance(label.get("name"), str):
            names.add(label["name"].lower())
    return names


def _issue_field(body: str, label: str) -> str:
    pattern = re.compile(
        rf"^###\s+{re.escape(label)}\s*$\n+(.*?)(?=^###\s+|\Z)", re.IGNORECASE | re.MULTILINE | re.DOTALL
    )
    match = pattern.search(body)
    if not match:
        return ""
    value = re.sub(r"<!--.*?-->", "", match.group(1), flags=re.DOTALL).strip()
    return "\n".join(line.rstrip() for line in value.splitlines()).strip()


def _priority(body: str) -> int:
    value = _issue_field(body, "Priority").lower()
    for name, priority in _PRIORITIES.items():
        if value.startswith(name):
            return priority
    return _PRIORITIES["normal"]


def _load_issues(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []

    issues = []
    for issue in payload:
        if not isinstance(issue, dict):
            continue
        labels = _labels(issue)
        if BACKLOG_LABEL not in labels or PAUSED_LABEL in labels:
            continue
        number = issue.get("number")
        title = issue.get("title")
        body = issue.get("body", "")
        if not isinstance(number, int) or number <= 0 or not isinstance(title, str) or not isinstance(body, str):
            continue
        objective = _issue_field(body, "Objective")
        if not title.strip() or not objective:
            continue
        url = issue.get("url")
        issues.append(
            {
                "number": number,
                "title": title.strip(),
                "objective": objective,
                "priority": _priority(body),
                "url": url.strip() if isinstance(url, str) else "",
            }
        )
    return sorted(issues, key=lambda item: (-item["priority"], item["number"]))


def _issue_tokens(issue: dict[str, Any]) -> set[str]:
    raw = f"{issue['title']} {issue['objective']}"
    return {
        token
        for token in re.findall(r"[a-z0-9]{3,}", raw.lower())
        if token not in _STOP_WORDS
    }


def _candidate_source_paths() -> list[str]:
    paths = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "src").rglob("*.py")
        if "__pycache__" not in path.parts
    ]
    paths.extend(
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "docs").rglob("*.md")
    )
    paths.extend(
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / ".github" / "workflows").glob("*.yml")
    )
    paths.extend(["README.md", ".github/copilot-instructions.md"])
    return sorted({path for path in paths if (REPO_ROOT / path).is_file()})


def _score_path(path: str, tokens: set[str]) -> int:
    text = (REPO_ROOT / path).read_text(encoding="utf-8", errors="replace").lower()
    path_text = path.lower()
    return sum((10 if token in path_text else 0) + text.count(token) for token in tokens)


def _derive_scope(issue: dict[str, Any]) -> tuple[list[str], list[str]]:
    tokens = _issue_tokens(issue)
    ranked_sources = sorted(
        ((_score_path(path, tokens), path) for path in _candidate_source_paths()),
        key=lambda item: (-item[0], item[1]),
    )
    sources = [path for score, path in ranked_sources if score > 0][:MAX_EVIDENCE_FILES]
    if not sources:
        return [], []

    tests: list[str] = []
    for source in sources:
        if source.startswith("src/azure_region_monitor/"):
            candidate = f"tests/test_{Path(source).stem}.py"
            if (REPO_ROOT / candidate).is_file() and candidate not in tests:
                tests.append(candidate)
        if source.startswith("docs/") or source == "README.md":
            static_site_test = "tests/test_static_site.py"
            if (REPO_ROOT / static_site_test).is_file() and static_site_test not in tests:
                tests.append(static_site_test)

    test_paths = [
        path.relative_to(REPO_ROOT).as_posix() for path in (REPO_ROOT / "tests").glob("test_*.py")
    ]
    ranked_tests = sorted(
        ((_score_path(path, tokens), path) for path in test_paths),
        key=lambda item: (-item[0], item[1]),
    )
    for score, path in ranked_tests:
        if score <= 0 or path in tests:
            continue
        tests.append(path)
        if len(tests) >= MAX_AUTO_TESTS:
            break
    return sources, tests[:MAX_AUTO_TESTS]


def build_issue_context(issues_path: Path, index: int = 0) -> dict[str, Any]:
    issues = _load_issues(issues_path)
    if not issues:
        return {
            "category": "",
            "summary": "No eligible open GitHub issues were found with the azure-backlog label.",
            "allowed_paths": [],
            "tests": [],
            "evidence": {},
        }
    if index < 0 or index >= len(issues):
        return {
            "category": "",
            "summary": "No additional eligible GitHub backlog issue was found for this run slot.",
            "allowed_paths": [],
            "tests": [],
            "evidence": {},
        }

    issue = issues[index]
    unknowns = _load_unknowns_module()
    allowed_paths, tests = _derive_scope(issue)
    if not allowed_paths:
        return {
            "category": "",
            "summary": f"No bounded source scope could be derived for GitHub issue #{issue['number']}.",
            "allowed_paths": [],
            "tests": [],
            "evidence": {},
        }
    evidence_paths = allowed_paths[:MAX_EVIDENCE_FILES]
    evidence = {
        "issue_number": issue["number"],
        "issue_url": issue["url"],
        "issue_title": issue["title"],
        "objective": issue["objective"],
        "priority": issue["priority"],
        "recent_git_history": _git_history(),
        "allowed_paths": allowed_paths,
        "tests": tests,
        "file_excerpts": {path: unknowns._read_excerpt(path) for path in evidence_paths},
    }
    return {
        "category": f"issue-{issue['number']}",
        "summary": "Highest-priority eligible GitHub backlog issue selected with auto-derived scope.",
        "allowed_paths": allowed_paths,
        "tests": tests,
        "issue_number": issue["number"],
        "evidence": evidence,
    }


def render_issue_markdown(proposal: dict[str, Any]) -> str:
    lines = ["## Azure GitHub issue backlog review", "", proposal["summary"], ""]
    if proposal["decision"] != "patch":
        lines.append("No safe issue patch proposal was produced; no branch or PR will be created.")
        return "\n".join(lines) + "\n"
    lines.extend(
        [
            f"- Issue: `{proposal['category']}`",
            f"- Proposed PR: `{proposal['pr_title']}`",
            f"- Allowed paths: {', '.join(f'`{path}`' for path in proposal['allowed_paths'])}",
            f"- Focused tests: {', '.join(f'`{path}`' for path in proposal['tests']) or 'none'}",
            "",
            "Patch output is validated locally before any branch or draft PR is created.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a bounded GitHub issue patch proposal.")
    parser.add_argument("--issues", type=Path, required=True)
    parser.add_argument("--index", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    unknowns = _load_unknowns_module()
    context = build_issue_context(args.issues, args.index)
    if not context["category"]:
        proposal = unknowns._no_change(context, context["summary"])
    else:
        client = AzureOpenAiTextClient.from_env(max_output_tokens=1_600)
        raw = client.generate(
            system=_SYSTEM_PROMPT,
            user="Approved GitHub issue and bounded local evidence:\n"
            + json.dumps(context["evidence"], ensure_ascii=False, sort_keys=True),
        )
        proposal = unknowns._parse_proposal(raw, context)
        proposal["issue_number"] = context["issue_number"]

    args.output.write_text(json.dumps(proposal, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(render_issue_markdown(proposal))


if __name__ == "__main__":
    main()