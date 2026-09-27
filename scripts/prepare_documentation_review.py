"""Source-triggered and weekly documentation reviews with bounded context."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
STATE_VERSION = 2
DOCS_BRANCH = "azure-docs/documentation-alignment"
MAX_DIFF_CHARS = 12_000
MAX_DIFF_PATHS = 12
REVIEW_INTERVAL = timedelta(days=7)


def _command(root: Path, *args: str) -> str:
    result = subprocess.run(
        args, cwd=root, capture_output=True, text=True, encoding="utf-8", check=False
    )
    if result.returncode != 0:
        raise RuntimeError(f"{args[0]} {args[1]} failed: {result.stderr.strip()}")
    return result.stdout


def relevant_source(path: str) -> bool:
    if path.endswith(".lock.yml"):
        return False
    if path.startswith(".github/workflows/"):
        return path.endswith((".yml", ".yaml", ".md"))
    if path.startswith(("src/", "scripts/", "infra/")):
        return not path.endswith((".md", ".png", ".svg"))
    return path in {"pyproject.toml", "Dockerfile", "azure.yaml"}


def _fingerprint(files: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode("utf-8")).hexdigest()


def source_state(root: Path) -> dict[str, Any]:
    head = _command(root, "git", "rev-parse", "HEAD").strip()
    files = {}
    for entry in _command(root, "git", "ls-tree", "-rz", "--full-tree", head).split("\0"):
        if not entry:
            continue
        metadata, path = entry.split("\t", 1)
        _, kind, blob = metadata.split()
        if kind != "blob" or not relevant_source(path):
            continue
        if path.startswith(".github/workflows/"):
            content = _command(root, "git", "show", f"{head}:{path}")
            if path.endswith(".md"):
                frontmatter = re.match(r"\A---\n(.*?)\n---(?:\n|\Z)", content, re.S)
                if frontmatter is None:
                    raise RuntimeError(f"Workflow frontmatter is invalid: {path}")
                content = frontmatter[1]
            content = re.sub(r"(?m)^[ \t]*#.*\n?", "", content)
            # Ignore a fixed clock shift, but retain cadence changes such as daily to weekly.
            content = re.sub(
                r"""(?m)^([ \t]*- cron:[ \t]*["']?)[0-5]?\d[ \t]+(?:[01]?\d|2[0-3])(?=[ \t])""",
                r"\1MINUTE HOUR",
                content,
            )
            blob = hashlib.sha256(content.strip().encode("utf-8")).hexdigest()
        files[path] = blob
    return {
        "version": STATE_VERSION, "head_sha": head,
        "fingerprint": _fingerprint(files), "files": files,
    }


def read_state(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    state = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(state, dict)
        or state.get("version") != STATE_VERSION
        or re.fullmatch(r"[0-9a-f]{40}", str(state.get("head_sha", ""))) is None
        or re.fullmatch(r"[0-9a-f]{64}", str(state.get("fingerprint", ""))) is None
        or not isinstance(state.get("files"), dict)
        or not all(
            isinstance(path, str)
            and relevant_source(path)
            and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", str(blob))
            for path, blob in state["files"].items()
        )
        or state["fingerprint"] != _fingerprint(state["files"])
        or not isinstance(state.get("last_augmentation_at"), str)
    ):
        raise ValueError("Invalid documentation review checkpoint; no model may run.")
    _review_time(state["last_augmentation_at"])
    return state


def _review_time(value: str) -> datetime:
    timestamp = datetime.fromisoformat(value)
    if timestamp.tzinfo is None:
        raise ValueError("Documentation review timestamp must include a timezone.")
    return timestamp.astimezone(timezone.utc)


def _reader_context(root: Path, repository: str) -> list[dict[str, Any]]:
    issues = json.loads(_command(
        root, "gh", "issue", "list", "--repo", repository, "--state", "all",
        "--limit", "5", "--search", "sort:updated-desc", "--json", "number,title,body,url,state",
    ))
    if not isinstance(issues, list):
        raise ValueError("Invalid reader-context response.")
    context = []
    for issue in issues[:5]:
        if (
            not isinstance(issue, dict)
            or type(issue.get("number")) is not int
            or not all(isinstance(issue.get(key), str) for key in ("title", "url", "state"))
            or not isinstance(issue.get("body"), (str, type(None)))
        ):
            raise ValueError("Invalid reader-context issue.")
        context.append({
            "number": issue["number"], "title": issue["title"][:200],
            "url": issue["url"], "state": issue["state"],
            "body_excerpt": (issue["body"] or "")[:1_000],
        })
    return context


def prepare_review(
    root: Path, state_path: Path, repository: str, default_branch: str,
    *, now: datetime | None = None,
) -> dict[str, Any]:
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    current = source_state(root)
    previous = read_state(state_path)
    current["last_augmentation_at"] = (
        previous["last_augmentation_at"] if previous else current_time.isoformat()
    )
    plan = {"run_agent": False, "checkpoint": False, "source_state": current}
    if previous is None:
        return {
            **plan,
            "checkpoint": True,
            "outcome": "baseline",
            "reason": "Initialized baseline; first general augmentation is due in seven days.",
        }
    last_augmentation = _review_time(previous["last_augmentation_at"])
    if last_augmentation > current_time:
        raise ValueError("Documentation checkpoint timestamp is in the future.")
    weekly_due = current_time - last_augmentation >= REVIEW_INTERVAL
    source_changed = previous["fingerprint"] != current["fingerprint"]
    if not source_changed and not weekly_due:
        return {
            **plan,
            "reason": (
                "No new relevant source changes and weekly augmentation is not due; no model call. "
                f"Previous outcome: {previous.get('outcome', 'unknown')}."
            ),
        }
    pulls = json.loads(
        _command(
            root, "gh", "pr", "list", "--repo", repository, "--head", DOCS_BRANCH,
            "--base", default_branch, "--state", "open", "--json", "number",
        )
    )
    if not isinstance(pulls, list):
        raise ValueError("Invalid documentation PR response; no model may run.")
    if pulls:
        return {
            **plan,
            "reason": f"Documentation PR #{pulls[0]['number']} is open; no model call.",
        }
    changed = sorted(
        path for path in previous["files"].keys() | current["files"].keys()
        if previous["files"].get(path) != current["files"].get(path)
    )
    diff = ""
    if changed:
        _command(root, "git", "merge-base", "--is-ancestor", previous["head_sha"], current["head_sha"])
        diff = _command(
            root, "git", "diff", "--no-ext-diff", "--unified=3",
            previous["head_sha"], current["head_sha"], "--", *changed[:MAX_DIFF_PATHS],
        )
    if weekly_due:
        current["last_augmentation_at"] = current_time.isoformat()
    return {
        **plan,
        "run_agent": True,
        "review_kind": "weekly-augmentation" if weekly_due else "source-change",
        "reason": (
            "Weekly general augmentation: research external changes and evolving reader needs."
            if weekly_due else
            f"Source-triggered documentation review with {len(changed)} changed files."
        ),
        "base_sha": previous["head_sha"],
        "head_sha": current["head_sha"],
        "changed_paths": changed[:MAX_DIFF_PATHS],
        "changed_path_count": len(changed),
        "diff": diff[:MAX_DIFF_CHARS],
        "diff_truncated": len(changed) > MAX_DIFF_PATHS or len(diff) > MAX_DIFF_CHARS,
        "reader_context": _reader_context(root, repository),
    }


def complete_review(plan: dict[str, Any], result_path: Path, state_path: Path) -> bool:
    if not plan["run_agent"] and not plan["checkpoint"]:
        return False
    outcome = plan.get("outcome", "failed")
    if plan["run_agent"] and result_path.exists():
        result = json.loads(result_path.read_text(encoding="utf-8"))
        outcome = result["outcome"]
        if outcome in {"skipped-open-pr", "stale-source"}:
            return False
        if outcome not in {"published", "no-change", "needs-evidence", "failed"}:
            raise ValueError("Invalid documentation review outcome.")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps({**plan["source_state"], "outcome": outcome}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "complete"))
    parser.add_argument("--repository", required=True)
    parser.add_argument("--default-branch", default="main")
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--github-output", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "prepare":
        plan = prepare_review(REPO_ROOT, args.state, args.repository, args.default_branch)
        args.plan.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        print(f"## Documentation review gate\n\n{plan['reason']}\n")
        outputs = {"run_agent": plan["run_agent"], "checkpoint": plan["checkpoint"]}
    else:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        saved = complete_review(plan, args.result, args.state)
        outputs = {"save_state": saved}
        if saved:
            outcome = read_state(args.state)["outcome"]
            print(f"Documentation source checkpoint recorded: {outcome}.")
    with args.github_output.open("a", encoding="utf-8") as stream:
        for key, value in outputs.items():
            stream.write(f"{key}={str(value).lower()}\n")
    if args.mode == "complete" and saved and outcome == "failed":
        raise SystemExit("Documentation attempt failed; checkpointed to prevent automatic retries.")


if __name__ == "__main__":
    main()
