from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
_SAFE_BRANCH_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,63}")


def _run(*args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=check,
    )


def _summary(message: str) -> None:
    print(message)


def _proposal(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _is_safe_repo_path(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        return False
    try:
        (REPO_ROOT / candidate).resolve().relative_to(REPO_ROOT.resolve())
    except ValueError:
        return False
    return (REPO_ROOT / candidate).is_file()


def _write_pr_body(proposal: dict[str, Any]) -> Path:
    handle = tempfile.NamedTemporaryFile("w", suffix=".md", encoding="utf-8", delete=False)
    tests = proposal["tests"] or [""]
    handle.write(
        "Azure-funded backlog proposal.\n\n"
        + proposal["summary"]
        + "\n\n"
        + proposal["pr_body"]
        + "\n\nValidation:\n"
        + "\n".join(f"- python -m pytest {path}".rstrip() for path in tests)
        + "\n- python -m ruff check .\n"
    )
    handle.close()
    return Path(handle.name)


def _existing_pr(branch: str) -> str:
    completed = _run("gh", "pr", "list", "--head", branch, "--state", "open", "--json", "number", "--jq", ".[0].number // empty")
    return completed.stdout.strip() if completed.returncode == 0 else ""


def apply_proposal(
    proposal: dict[str, Any], *, branch_prefix: str, base_branch: str, dry_run: bool, force: bool
) -> int:
    if proposal.get("decision") != "patch":
        _summary("No patch proposal to apply.")
        return 0
    required = ("category", "patch", "pr_title", "pr_body", "allowed_paths")
    if not all(proposal.get(key) for key in required):
        _summary("Incomplete patch proposal; no branch or PR was created.")
        return 0
    if not isinstance(proposal.get("tests"), list) or not all(
        isinstance(path, str) and path for path in proposal["tests"]
    ):
        _summary("Invalid patch test scope; no branch or PR was created.")
        return 0
    if not isinstance(proposal.get("allowed_paths"), list) or not all(
        _is_safe_repo_path(path) for path in proposal["allowed_paths"]
    ):
        _summary("Invalid patch file scope; no branch or PR was created.")
        return 0
    if dry_run:
        _summary("Dry run requested; patch proposal was not applied.")
        return 0

    category = str(proposal["category"])
    if not _SAFE_BRANCH_COMPONENT.fullmatch(category) or not _SAFE_BRANCH_COMPONENT.fullmatch(
        branch_prefix
    ):
        _summary("Invalid patch category or branch prefix; no branch or PR was created.")
        return 0
    branch = f"{branch_prefix}/{category}"
    existing = _existing_pr(branch)
    if existing and not force:
        _summary(f"Skipped patch proposal: PR #{existing} is already open for {branch}.")
        return 0

    _run("git", "fetch", "origin", base_branch, "--depth", "1")
    checkout = _run("git", "checkout", "-B", branch, f"origin/{base_branch}")
    if checkout.returncode != 0:
        _summary("Could not create a clean proposal branch; no PR was created.")
        return 0

    with tempfile.NamedTemporaryFile("w", suffix=".patch", encoding="utf-8", delete=False) as handle:
        handle.write(str(proposal["patch"]))
        patch_path = Path(handle.name)
    try:
        if _run("git", "apply", "--check", str(patch_path)).returncode != 0:
            _summary("Patch did not apply cleanly; no PR was created.")
            return 0
        _run("git", "apply", str(patch_path), check=True)
        changed = set(_run("git", "diff", "--name-only", check=True).stdout.splitlines())
        allowed = set(proposal["allowed_paths"])
        if not changed or not changed.issubset(allowed):
            _run("git", "reset", "--hard")
            _summary("Patch changed paths outside the derived safe scope; no PR was created.")
            return 0
        if _run("python", "-m", "pytest", *proposal["tests"]).returncode != 0:
            _run("git", "reset", "--hard")
            _summary("Focused patch tests failed; no PR was created.")
            return 0
        if _run("python", "-m", "ruff", "check", ".").returncode != 0 or _run("git", "diff", "--check").returncode != 0:
            _run("git", "reset", "--hard")
            _summary("Patch lint or whitespace validation failed; no PR was created.")
            return 0
        _run("git", "config", "user.name", "github-actions[bot]", check=True)
        _run("git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com", check=True)
        _run("git", "add", "-A", check=True)
        commit_prefix = {
            "azure-docs": "docs",
            "azure-unknowns": "fix",
        }.get(branch_prefix, "feat")
        _run("git", "commit", "-m", f"{commit_prefix}: advance {category}", check=True)
        if _run("git", "push", "--force-with-lease", "origin", branch).returncode != 0:
            _summary("Patch committed locally but could not be pushed; no PR was created.")
            return 0
        if existing:
            _summary(f"Updated existing draft PR #{existing}: {branch}.")
            return 0
        body = _write_pr_body(proposal)
        try:
            created = _run(
                "gh",
                "pr",
                "create",
                "--draft",
                "--base",
                base_branch,
                "--head",
                branch,
                "--title",
                str(proposal["pr_title"]),
                "--body-file",
                str(body),
            )
        finally:
            body.unlink(missing_ok=True)
        if created.returncode != 0:
            _summary("Patch branch was pushed but draft PR creation failed.")
            return 1
        _summary(f"Created draft PR: {created.stdout.strip()}")
        return 0
    finally:
        patch_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and apply a bounded Azure proposal.")
    parser.add_argument("--proposal", type=Path, required=True)
    parser.add_argument("--branch-prefix", required=True)
    parser.add_argument("--base-branch", default=os.environ.get("BASE_BRANCH", "main"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    raise SystemExit(
        apply_proposal(
            _proposal(args.proposal),
            branch_prefix=args.branch_prefix,
            base_branch=args.base_branch,
            dry_run=args.dry_run,
            force=args.force,
        )
    )


if __name__ == "__main__":
    main()
