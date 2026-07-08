from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


DEFAULT_SNAPSHOT_URL = "https://azwatch.operator.lat/api/latest.json"
DEFAULT_LABELS = ("copilot-agent", "scheduled-agent")
REPO_ROOT = Path(__file__).resolve().parents[1]

CATEGORY_TEST_HINTS = {
    "aksExtensions": ("tests/test_aks_extension_catalog_probe.py", "tests/test_aks_extension_probe.py"),
    "aksKubernetesVersions": ("tests/test_aks_versions_probe.py",),
    "functions": ("tests/test_functions_probe.py",),
    "aiModels": ("tests/test_ai_models_probe.py",),
    "modelLatency": ("tests/test_model_latency.py", "tests/test_latency_client_resilience.py"),
    "aiLatency": ("tests/test_ai_model_latency.py",),
    "containerApps": ("tests/test_container_apps_probe.py",),
    "vmSkus": ("tests/test_vm_skus_probe.py",),
}

CATEGORY_WORKFLOW_HINTS = {
    "aksExtensions": (".github/workflows/aks-extension-tests.yml",),
    "aksKubernetesVersions": (".github/workflows/aks-version-tests.yml",),
    "functions": (".github/workflows/function-flex-tests.yml",),
    "aiModels": (".github/workflows/ai-model-tests.yml",),
    "modelLatency": (".github/workflows/model-latency-tests.yml",),
    "aiLatency": (".github/workflows/azure-latency-tests.yml",),
    "containerApps": (".github/workflows/container-apps-tests.yml",),
    "vmSkus": (".github/workflows/vm-sku-tests.yml",),
}


@dataclass(frozen=True)
class UnknownGroup:
    category: str
    unknown_count: int
    regions: tuple[str, ...]
    services: tuple[str, ...]
    features: tuple[str, ...]
    error_codes: tuple[tuple[str, int], ...]
    messages: tuple[tuple[str, int], ...]

    @property
    def test_hints(self) -> tuple[str, ...]:
        return CATEGORY_TEST_HINTS.get(self.category, ())

    @property
    def workflow_hints(self) -> tuple[str, ...]:
        return CATEGORY_WORKFLOW_HINTS.get(self.category, ())


@dataclass(frozen=True)
class SnapshotLoadResult:
    snapshot: dict[str, Any] | None
    source: str
    warning: str | None = None


@dataclass(frozen=True)
class AgentSession:
    key: str
    title: str
    labels: tuple[str, ...]
    body: str
    custom_instructions: str


class GitHubClient:
    def __init__(self, *, token: str, api_url: str = "https://api.github.com") -> None:
        self.token = token
        self.api_url = api_url.rstrip("/")

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self.api_url}{path}",
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GitHub API {method} {path} failed: {exc.code} {detail}") from exc
        if not body:
            return None
        return json.loads(body)


def feature_category(feature: str) -> str:
    if feature == "extensionCatalog":
        return "aksExtensions"
    if feature.startswith("extensions.") or feature.startswith("extensionTypes."):
        return "aksExtensions"
    if feature.startswith("kubernetesVersions."):
        return "aksKubernetesVersions"
    if feature.startswith("hostingPlans.") or feature.startswith("runtimes."):
        return "functions"
    if feature.startswith("aiModels."):
        return "aiModels"
    if feature.startswith("modelLatency."):
        return "modelLatency"
    if feature.startswith("aiLatency."):
        return "aiLatency"
    if feature.startswith("containerApps."):
        return "containerApps"
    if feature == "vmSkuCatalog" or feature.startswith("vmSkus."):
        return "vmSkus"
    return feature.split(".", 1)[0]


def rank_unknown_groups(snapshot: dict[str, Any]) -> list[UnknownGroup]:
    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "count": 0,
            "regions": set(),
            "services": set(),
            "features": set(),
            "error_codes": Counter(),
            "messages": Counter(),
        }
    )

    for region, services in snapshot.get("regions", {}).items():
        for service, features in services.items():
            for feature, result in features.items():
                if result.get("status") != "unknown":
                    continue
                category = feature_category(feature)
                group = grouped[category]
                group["count"] += 1
                group["regions"].add(region)
                group["services"].add(service)
                group["features"].add(feature)
                if result.get("error_code"):
                    group["error_codes"][str(result["error_code"])] += 1
                if result.get("message"):
                    group["messages"][_compact_message(str(result["message"]))] += 1

    groups = [
        UnknownGroup(
            category=category,
            unknown_count=values["count"],
            regions=tuple(sorted(values["regions"])),
            services=tuple(sorted(values["services"])),
            features=tuple(sorted(values["features"])[:12]),
            error_codes=tuple(values["error_codes"].most_common(5)),
            messages=tuple(values["messages"].most_common(5)),
        )
        for category, values in grouped.items()
    ]
    return sorted(groups, key=lambda group: (-group.unknown_count, group.category))


def load_snapshot(snapshot_url: str, snapshot_path: Path | None) -> SnapshotLoadResult:
    if snapshot_url:
        try:
            with urlopen(snapshot_url, timeout=30) as response:
                return SnapshotLoadResult(json.loads(response.read().decode("utf-8")), snapshot_url)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            warning = f"Could not load snapshot URL {snapshot_url}: {exc}"
        except OSError as exc:
            warning = f"Could not load snapshot URL {snapshot_url}: {exc}"
    else:
        warning = None

    candidate_paths = []
    if snapshot_path is not None:
        candidate_paths.append(snapshot_path)
    candidate_paths.extend((REPO_ROOT / "public/api/latest.json", REPO_ROOT / "data/snapshots/latest.json"))

    for candidate_path in candidate_paths:
        if not candidate_path.exists():
            continue
        try:
            return SnapshotLoadResult(
                json.loads(candidate_path.read_text(encoding="utf-8")), str(candidate_path), warning
            )
        except json.JSONDecodeError as exc:
            warning = f"Could not parse snapshot file {candidate_path}: {exc}"

    return SnapshotLoadResult(None, "none", warning or "No snapshot source was available.")


def build_docs_session(now: datetime) -> AgentSession:
    body = f"""# Scheduled Copilot task: documentation and instructions maintenance

Run date: {now.date().isoformat()}

## Goal

Check whether this repository's documentation, runbooks, workflows, and Copilot instructions still match the current implementation and recent project history.

## Scope

- Compare current code and tests with [README.md](README.md), [docs/poc-deployment.md](docs/poc-deployment.md), [docs/spec](docs/spec), [docs/roadmap](docs/roadmap), and [.github/copilot-instructions.md](.github/copilot-instructions.md).
- Inspect recent commits, open PRs/issues, and recent failed GitHub Actions runs when that context is available.
- Keep status semantics precise: do not describe `unavailable` as quota or deployment failure unless a dedicated probe produced that evidence.
- Keep changes small and directly tied to implementation drift.

## Budget and guardrails

- Target 30 minutes of focused work; stop before 45 minutes if the task is not converging.
- Prefer targeted reads over broad repository scans.
- Do not run Azure create/delete probes or change live dashboard data.
- Create exactly one pull request when changes are needed. If no change is needed, comment on this issue with the checked areas and close it without opening a PR.

## Validation

- For docs-only changes, run `python -m pytest tests/test_static_site.py tests/test_summary.py` when practical.
- If code or generated dashboard behavior changes, run the focused tests for the touched slice, then `python -m pytest` and `ruff check .` when practical.

## Pull request

- Use a title like `docs: refresh monitor docs and Copilot instructions`.
- Summarize what drift was found and which checks were run.
"""
    return AgentSession(
        key="docs",
        title="[agent/docs] Documentation and instruction maintenance",
        labels=(*DEFAULT_LABELS, "agent-docs"),
        body=body,
        custom_instructions=(
            "Follow the issue body exactly. Keep the work bounded, update docs/instructions only "
            "when they are demonstrably out of sync, and open one PR only if changes are needed."
        ),
    )


def build_unknowns_session(
    now: datetime,
    snapshot_result: SnapshotLoadResult,
    groups: list[UnknownGroup],
    *,
    force_without_candidates: bool,
) -> AgentSession | None:
    if not groups and not force_without_candidates:
        return None

    top_group = groups[0] if groups else None
    title_suffix = top_group.category if top_group else "no-current-candidate"
    context = _format_unknown_context(snapshot_result, groups)
    hints = _format_validation_hints(top_group)
    body = f"""# Scheduled Copilot task: investigate parked unknowns

Run date: {now.date().isoformat()}

## Goal

Investigate the top parked `unknown` modality by number of unknown checks, and decide whether the probe/tests/workflow should be fixed so the corresponding checks can correctly report `available` or `unavailable`.

## Precomputed candidate

{context}

## Scope

- Focus on the top candidate only. Do not broaden into unrelated modalities.
- First determine whether the current `unknown` results are caused by probe code, CLI parsing, timeout handling, workflow configuration, test fixtures, or missing trustworthy Azure evidence.
- Only change logic from `unknown` toward `available` or `unavailable` when the read-only evidence genuinely supports that status.
- Preserve this project's status semantics: `unknown` means the probe lacked trustworthy evidence; `unavailable` means the read-only listing/catalog succeeded and the feature was absent.
- Prefer tests that reproduce the classification issue before changing probe behavior.

## Budget and guardrails

- Target 30 minutes of focused work; stop before 45 minutes if the task is not converging.
- Do not run Azure create/delete lifecycle probes.
- Do not update generated live snapshot data by hand.
- Create exactly one pull request when there is a code, test, workflow, or docs fix. If the unknowns are legitimate and no repo change is justified, comment on this issue with the evidence and close it without opening a PR.

## Validation hints

{hints}

## Pull request

- Use a title like `fix: improve {title_suffix} unknown classification` when code changes are made.
- Include the selected modality, evidence reviewed, and checks run.
"""
    return AgentSession(
        key="unknowns",
        title=f"[agent/unknowns] Investigate parked unknowns: {title_suffix}",
        labels=(*DEFAULT_LABELS, "agent-unknowns"),
        body=body,
        custom_instructions=(
            "Follow the issue body exactly. Investigate only the selected unknown modality, "
            "protect the documented status semantics, and open one PR only if a repo change is justified."
        ),
    )


def ensure_label(client: GitHubClient, repo: str, label: str) -> None:
    label_path = f"/repos/{repo}/labels/{quote(label, safe='')}"
    try:
        client.request("GET", label_path)
        return
    except RuntimeError as exc:
        if "failed: 404" not in str(exc):
            raise
    client.request(
        "POST",
        f"/repos/{repo}/labels",
        {"name": label, "color": "8250df", "description": "Scheduled Copilot agent work"},
    )


def open_issue_exists(client: GitHubClient, repo: str, session: AgentSession) -> bool:
    query = urlencode({"state": "open", "labels": ",".join(session.labels), "per_page": "100"})
    issues = client.request("GET", f"/repos/{repo}/issues?{query}")
    return bool(issues)


def create_copilot_issue(
    client: GitHubClient,
    repo: str,
    session: AgentSession,
    *,
    base_branch: str,
    model: str,
) -> str:
    for label in session.labels:
        ensure_label(client, repo, label)

    agent_assignment: dict[str, Any] = {
        "target_repo": repo,
        "base_branch": base_branch,
        "custom_instructions": session.custom_instructions,
    }
    if model:
        agent_assignment["model"] = model

    issue = client.request(
        "POST",
        f"/repos/{repo}/issues",
        {
            "title": session.title,
            "body": session.body,
            "labels": list(session.labels),
            "assignees": ["copilot-swe-agent[bot]"],
            "agent_assignment": agent_assignment,
        },
    )
    return str(issue.get("html_url", issue.get("url", "")))


def planned_sessions(
    selected: str,
    *,
    now: datetime,
    snapshot_result: SnapshotLoadResult,
    unknown_groups: list[UnknownGroup],
    force_unknowns_without_candidates: bool,
) -> list[AgentSession]:
    sessions = []
    if selected in {"both", "unknowns"}:
        unknowns_session = build_unknowns_session(
            now,
            snapshot_result,
            unknown_groups,
            force_without_candidates=force_unknowns_without_candidates,
        )
        if unknowns_session is not None:
            sessions.append(unknowns_session)
    return sessions


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start scheduled Copilot cloud-agent sessions.")
    parser.add_argument("--session", choices=("both", "docs", "unknowns"), default="both")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--base-branch", default="main")
    parser.add_argument("--snapshot-url", default=DEFAULT_SNAPSHOT_URL)
    parser.add_argument("--snapshot-path", type=Path)
    parser.add_argument("--token-env", default="COPILOT_AGENT_TOKEN")
    parser.add_argument("--api-url", default=os.environ.get("GITHUB_API_URL", "https://api.github.com"))
    parser.add_argument("--model", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="Create a session even if a matching open issue exists.")
    parser.add_argument(
        "--force-unknowns-without-candidates",
        action="store_true",
        help="Create the unknowns session even when no unknown statuses are present in the snapshot.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if not args.repo:
        print("A target repository is required via --repo or GITHUB_REPOSITORY.", file=sys.stderr)
        return 2

    snapshot_result = load_snapshot(args.snapshot_url, args.snapshot_path)
    unknown_groups = rank_unknown_groups(snapshot_result.snapshot) if snapshot_result.snapshot else []
    sessions = planned_sessions(
        args.session,
        now=datetime.now(timezone.utc),
        snapshot_result=snapshot_result,
        unknown_groups=unknown_groups,
        force_unknowns_without_candidates=args.force_unknowns_without_candidates,
    )

    if not sessions:
        print("No Copilot agent sessions to start.")
        if snapshot_result.warning:
            print(snapshot_result.warning)
        return 0

    if args.dry_run:
        print(json.dumps([session.__dict__ for session in sessions], indent=2))
        return 0

    token = os.environ.get(args.token_env, "")
    if not token:
        print(f"Missing required token in ${args.token_env}.", file=sys.stderr)
        return 2

    client = GitHubClient(token=token, api_url=args.api_url)
    for session in sessions:
        if not args.force and open_issue_exists(client, args.repo, session):
            print(f"Skipped {session.key}: matching open issue already exists.")
            continue
        url = create_copilot_issue(
            client,
            args.repo,
            session,
            base_branch=args.base_branch,
            model=args.model,
        )
        print(f"Started {session.key}: {url}")
    return 0


def _compact_message(message: str) -> str:
    return " ".join(message.split())[:180]


def _format_unknown_context(
    snapshot_result: SnapshotLoadResult, groups: list[UnknownGroup]
) -> str:
    lines = [f"Snapshot source: `{snapshot_result.source}`."]
    if snapshot_result.warning:
        lines.append(f"Snapshot warning: {snapshot_result.warning}")
    if not groups:
        lines.append("No current `unknown` statuses were found in the loaded snapshot.")
        lines.append("Use recent workflow runs only to confirm whether this remains true.")
        return "\n".join(lines)

    top = groups[0]
    lines.extend(
        (
            f"Top candidate: `{top.category}` with {top.unknown_count} unknown checks.",
            f"Regions: {_format_sample(top.regions, 12)}",
            f"Services: {_format_sample(top.services, 8)}",
            f"Features: {_format_sample(top.features, 12)}",
        )
    )
    if top.error_codes:
        lines.append(f"Top error codes: {_format_counter(top.error_codes)}")
    if top.messages:
        lines.append(f"Top messages: {_format_counter(top.messages)}")
    if len(groups) > 1:
        lines.append("Other unknown groups:")
        for group in groups[1:5]:
            lines.append(f"- `{group.category}`: {group.unknown_count} unknown checks")
    return "\n".join(lines)


def _format_validation_hints(group: UnknownGroup | None) -> str:
    if group is None:
        return "- Run the narrow tests for any probe or docs touched by the investigation."

    lines = []
    if group.test_hints:
        lines.append(f"- Start with: `python -m pytest {' '.join(group.test_hints)}`")
    else:
        lines.append("- Start with the narrow tests for the selected modality.")
    if group.workflow_hints:
        lines.append(f"- Review workflow configuration: `{', '.join(group.workflow_hints)}`")
    lines.append("- If shared probe behavior changes, also run `python -m pytest` and `ruff check .`.")
    return "\n".join(lines)


def _format_sample(values: tuple[str, ...], limit: int) -> str:
    visible = values[:limit]
    suffix = "" if len(values) <= limit else f" and {len(values) - limit} more"
    return ", ".join(f"`{value}`" for value in visible) + suffix


def _format_counter(values: tuple[tuple[str, int], ...]) -> str:
    return ", ".join(f"`{value}` ({count})" for value, count in values)


if __name__ == "__main__":
    raise SystemExit(main())