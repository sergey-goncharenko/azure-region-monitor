from __future__ import annotations

import json
import re
import subprocess
import argparse
from pathlib import Path
from typing import Any

from azure_region_monitor.social_client import AzureOpenAiTextClient

REPO_ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_CHARS = 2_400

_SYSTEM_PROMPT = """You are a precise documentation reviewer for an Azure regional availability monitor.

Review only the bounded repository evidence supplied. Identify confirmed documentation or instruction drift, not hypothetical improvements. Preserve the project's status semantics: unavailable is a successful read-only listing/catalog absence, not quota, capacity, deployment failure, customer eligibility, or SLA evidence.

Return only this JSON object:
{
  "summary": "one concise paragraph",
  "confirmed_drift": [
    {"file": "relative path", "finding": "factually grounded drift", "recommendation": "small concrete update"}
  ],
  "follow_up_needed": true
}

Use an empty confirmed_drift list and follow_up_needed=false when the supplied evidence does not prove a documentation change is needed. Do not propose code changes, do not access the network, and do not invent implementation facts."""


def _read_excerpt(path: str) -> str:
    target = REPO_ROOT / path
    if not target.exists():
        return f"[missing: {path}]"
    text = target.read_text(encoding="utf-8", errors="replace")
    if len(text) <= MAX_FILE_CHARS:
        return text
    return text[:MAX_FILE_CHARS].rsplit("\n", 1)[0] + "\n[truncated]"


def _git_history() -> str:
    completed = subprocess.run(
        ["git", "log", "-8", "--oneline"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() or "[git history unavailable]"


def build_review_facts() -> str:
    files = (
        "README.md",
        ".github/copilot-instructions.md",
        "docs/agentic-sessions.md",
        ".github/workflows/daily-scan.yml",
        ".github/workflows/scheduled-azure-backlog.yml",
        ".github/workflows/scheduled-copilot-agents.yml",
    )
    payload = {
        "recent_git_history": _git_history(),
        "files": {path: _read_excerpt(path) for path in files},
    }
    return "Bounded local repository evidence:\n" + json.dumps(
        payload, ensure_ascii=False, sort_keys=True
    )


def _parse_review(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {
            "summary": "Azure reviewer returned non-JSON output; no automatic follow-up was created.",
            "confirmed_drift": [],
            "follow_up_needed": False,
        }
    if not isinstance(payload, dict):
        return {
            "summary": "Azure reviewer returned an invalid response shape; no automatic follow-up was created.",
            "confirmed_drift": [],
            "follow_up_needed": False,
        }
    drift = payload.get("confirmed_drift")
    if not isinstance(drift, list):
        drift = []
    validated = [
        item
        for item in drift
        if isinstance(item, dict)
        and isinstance(item.get("file"), str)
        and isinstance(item.get("finding"), str)
        and isinstance(item.get("recommendation"), str)
    ]
    return {
        "summary": str(payload.get("summary", "No review summary was returned.")).strip(),
        "confirmed_drift": validated,
        "follow_up_needed": bool(payload.get("follow_up_needed")) and bool(validated),
    }


def render_review_markdown(review: dict[str, Any]) -> str:
    lines = ["## Azure documentation review", "", review["summary"], ""]
    drift = review["confirmed_drift"]
    if not drift:
        lines.append("No confirmed documentation drift was found in the bounded review.")
        return "\n".join(lines) + "\n"

    lines.extend(["### Confirmed drift", ""])
    for item in drift:
        lines.extend(
            [
                f"- **{item['file']}** — {item['finding']}",
                f"  - Recommended follow-up: {item['recommendation']}",
            ]
        )
    lines.extend(
        [
            "",
            "Review output is advisory. It does not edit files, create PRs, or change live data.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a bounded Azure documentation review.")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    client = AzureOpenAiTextClient.from_env(max_output_tokens=900)
    review = _parse_review(client.generate(system=_SYSTEM_PROMPT, user=build_review_facts()))
    if args.output is not None:
        args.output.write_text(json.dumps(review, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(render_review_markdown(review))


if __name__ == "__main__":
    main()
