from __future__ import annotations

import argparse
import copy
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
MAX_EVIDENCE_FILES = 5
MAX_AUTO_TESTS = 3
MAX_FILE_CHARS = 3_600
MAX_RELEVANT_EXCERPT_CHARS = 6_000
BACKLOG_LABEL = "azure-backlog"
PAUSED_LABEL = "azure-paused"
RECURRING_LABEL = "azure-recurring"
MAX_ISSUE_CONTEXT_CHARS = 60_000
MAX_TEXT_FIELD_CHARS = 8_000
MAX_GITHUB_REQUEST_ATTEMPTS = 3
MAX_TEXT_TOKEN_MATCHES = 5
_STOP_WORDS = {
    "about",
    "agent",
    "and",
    "availability",
    "azure",
    "bound",
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
_PRIORITIES = {"urgent": 400, "high": 300, "normal": 200, "low": 100}
_SCOPE_STEM_ALIASES = {
    "accessibility": {"static_site"},
    "dashboard": {"static_site"},
    "design": {"static_site"},
    "responsive": {"static_site"},
    "visual": {"static_site"},
}

class GitHubIssueContextClient:
    """Fetches bounded, relevant GitHub issue discussion and hierarchy context."""

    def __init__(
        self,
        *,
        repository: str,
        token: str,
        api_url: str = "https://api.github.com",
        opener: urllib.request.OpenerDirector | None = None,
    ) -> None:
        if not re.fullmatch(r"[^/\s]+/[^/\s]+", repository):
            raise ValueError("GitHub repository must use the owner/name format.")
        if not token:
            raise ValueError("A GitHub token is required to fetch issue context.")
        self._repository = repository
        self._token = token
        self._api_url = api_url.rstrip("/")
        self._opener = opener or urllib.request.build_opener()

    @classmethod
    def from_env(cls, repository: str) -> "GitHubIssueContextClient":
        return cls(repository=repository, token=os.environ.get("GH_TOKEN", ""))

    def fetch(self, issue_number: int) -> dict[str, Any]:
        issue = self._get_issue(issue_number)
        context = {
            "issue": self._issue_detail(issue),
            "parent_issue": self._parent_detail(issue),
            "sub_issues": self._sub_issue_details(issue_number),
        }
        return _limit_issue_context(context)

    def fetch_pull_request_feedback(self, issue_number: int) -> dict[str, Any] | None:
        owner = self._repository.split("/", 1)[0]
        query = urllib.parse.urlencode(
            {
                "state": "open",
                "head": f"{owner}:azure-issues/issue-{issue_number}",
                "per_page": 10,
            }
        )
        pulls = self._request(f"/repos/{self._repository}/pulls?{query}")
        if not isinstance(pulls, list) or not pulls:
            return None
        pull = pulls[0]
        number = pull.get("number")
        if not isinstance(number, int):
            return None
        return {
            "number": number,
            "title": pull.get("title", ""),
            "body": _limit_text(pull.get("body")),
            "url": pull.get("html_url", ""),
            "conversation_comments": [
                _comment_detail(comment)
                for comment in self._paginate(
                    f"/repos/{self._repository}/issues/{number}/comments"
                )
                if isinstance(comment, dict)
            ],
            "reviews": [
                _review_detail(review)
                for review in self._paginate(f"/repos/{self._repository}/pulls/{number}/reviews")
                if isinstance(review, dict)
            ],
            "inline_comments": [
                _review_comment_detail(comment)
                for comment in self._paginate(f"/repos/{self._repository}/pulls/{number}/comments")
                if isinstance(comment, dict)
            ],
        }

    def _get_issue(self, issue_number: int) -> dict[str, Any]:
        payload = self._request(f"/repos/{self._repository}/issues/{issue_number}")
        if not isinstance(payload, dict):
            raise RuntimeError(f"GitHub issue #{issue_number} returned an invalid response.")
        return payload

    def _parent_detail(self, issue: dict[str, Any]) -> dict[str, Any] | None:
        parent_url = issue.get("parent_issue_url")
        if not isinstance(parent_url, str):
            return None
        match = re.search(r"/issues/(\d+)$", parent_url)
        if not match:
            return None
        return self._issue_detail(self._get_issue(int(match.group(1))))

    def _sub_issue_details(self, issue_number: int) -> list[dict[str, Any]]:
        details = []
        for sub_issue in self._paginate(f"/repos/{self._repository}/issues/{issue_number}/sub_issues"):
            if not isinstance(sub_issue, dict) or not isinstance(sub_issue.get("number"), int):
                continue
            details.append(self._issue_detail(self._get_issue(sub_issue["number"])))
        return details

    def _issue_detail(self, issue: dict[str, Any]) -> dict[str, Any]:
        number = issue.get("number")
        comments = self._paginate(f"/repos/{self._repository}/issues/{number}/comments")
        return {
            "number": number,
            "title": issue.get("title", ""),
            "body": _limit_text(issue.get("body")),
            "url": issue.get("html_url", ""),
            "state": issue.get("state", ""),
            "state_reason": issue.get("state_reason"),
            "author": _login(issue.get("user")),
            "assignees": [_login(value) for value in issue.get("assignees", []) if _login(value)],
            "labels": sorted(_labels(issue)),
            "milestone": _milestone(issue.get("milestone")),
            "created_at": issue.get("created_at", ""),
            "updated_at": issue.get("updated_at", ""),
            "closed_at": issue.get("closed_at"),
            "issue_dependencies_summary": issue.get("issue_dependencies_summary", {}),
            "reactions": issue.get("reactions", {}),
            "comments": [_comment_detail(comment) for comment in comments if isinstance(comment, dict)],
        }

    def _paginate(self, path: str) -> list[Any]:
        values = []
        page = 1
        while True:
            separator = "&" if "?" in path else "?"
            payload = self._request(f"{path}{separator}{urllib.parse.urlencode({'per_page': 100, 'page': page})}")
            if not isinstance(payload, list):
                raise RuntimeError(f"GitHub endpoint {path} returned an invalid paginated response.")
            values.extend(payload)
            if len(payload) < 100:
                return values
            page += 1

    def _request(self, path: str) -> Any:
        request = urllib.request.Request(
            f"{self._api_url}{path}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        for attempt in range(MAX_GITHUB_REQUEST_ATTEMPTS):
            try:
                with self._opener.open(request, timeout=30) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as error:
                if error.code not in {429, 500, 502, 503, 504} or attempt + 1 == MAX_GITHUB_REQUEST_ATTEMPTS:
                    raise RuntimeError(
                        f"GitHub issue context request failed: HTTP {error.code}."
                    ) from error
            except (urllib.error.URLError, OSError) as error:
                if attempt + 1 == MAX_GITHUB_REQUEST_ATTEMPTS:
                    raise RuntimeError(f"GitHub issue context request failed: {error}") from error
            except json.JSONDecodeError as error:
                raise RuntimeError(f"GitHub issue context request failed: {error}") from error
            time.sleep(attempt + 1)
        raise RuntimeError("GitHub issue context request failed after retries.")


def _login(value: object) -> str:
    return value.get("login", "") if isinstance(value, dict) and isinstance(value.get("login"), str) else ""


def _milestone(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        "title": value.get("title", ""),
        "description": _limit_text(value.get("description")),
        "state": value.get("state", ""),
        "due_on": value.get("due_on"),
    }


def _comment_detail(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": value.get("id"),
        "url": value.get("html_url", ""),
        "author": _login(value.get("user")),
        "author_association": value.get("author_association", ""),
        "created_at": value.get("created_at", ""),
        "updated_at": value.get("updated_at", ""),
        "body": _limit_text(value.get("body")),
        "reactions": value.get("reactions", {}),
    }


def _review_detail(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": value.get("id"),
        "url": value.get("html_url", ""),
        "author": _login(value.get("user")),
        "author_association": value.get("author_association", ""),
        "state": value.get("state", ""),
        "submitted_at": value.get("submitted_at", ""),
        "body": _limit_text(value.get("body")),
    }


def _review_comment_detail(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": value.get("id"),
        "url": value.get("html_url", ""),
        "author": _login(value.get("user")),
        "author_association": value.get("author_association", ""),
        "created_at": value.get("created_at", ""),
        "updated_at": value.get("updated_at", ""),
        "path": value.get("path", ""),
        "line": value.get("line"),
        "side": value.get("side"),
        "body": _limit_text(value.get("body")),
    }


def _limit_text(value: object) -> str:
    text = value if isinstance(value, str) else ""
    if len(text) <= MAX_TEXT_FIELD_CHARS:
        return text
    half = MAX_TEXT_FIELD_CHARS // 2
    return text[:half] + "\n[...text truncated...]\n" + text[-half:]


def _limit_issue_context(context: dict[str, Any]) -> dict[str, Any]:
    serialized = json.dumps(context, ensure_ascii=False, sort_keys=True)
    if len(serialized) <= MAX_ISSUE_CONTEXT_CHARS:
        return context
    bounded = copy.deepcopy(context)
    bounded["context_truncated"] = True
    bounded["truncation_note"] = (
        "The selected issue, parent, and direct sub-issue context was fetched, but discussion "
        "text exceeded the "
        f"{MAX_ISSUE_CONTEXT_CHARS}-character Azure context budget."
    )
    for container, key, _ in _context_text_fields(bounded):
        container[key] = ""
    remaining = MAX_ISSUE_CONTEXT_CHARS - len(
        json.dumps(bounded, ensure_ascii=False, sort_keys=True)
    )
    for container, key, original in _context_text_fields(context):
        container_copy = _matching_context_container(bounded, container)
        if container_copy is None:
            continue
        if remaining <= 0:
            container_copy[key] = ""
            continue
        marker = "\n[...text truncated for context budget...]"
        if len(original) <= remaining:
            value = original
        elif remaining > len(marker):
            value = original[: remaining - len(marker)] + marker
        else:
            value = ""
        container_copy[key] = value
        remaining -= len(value)
    _enforce_serialized_context_budget(bounded)
    return bounded


def _context_text_fields(context: dict[str, Any]) -> list[tuple[dict[str, Any], str, str]]:
    fields = []
    details = [context.get("issue"), context.get("parent_issue"), *context.get("sub_issues", [])]
    for detail in details:
        if not isinstance(detail, dict):
            continue
        body = detail.get("body")
        if isinstance(body, str):
            fields.append((detail, "body", body))
        comments = detail.get("comments")
        if isinstance(comments, list):
            for comment in reversed(comments):
                if isinstance(comment, dict) and isinstance(comment.get("body"), str):
                    fields.append((comment, "body", comment["body"]))
    return fields


def _matching_context_container(
    bounded: dict[str, Any], original: dict[str, Any]
) -> dict[str, Any] | None:
    original_id = original.get("id")
    if original_id is not None:
        for detail in [bounded.get("issue"), bounded.get("parent_issue"), *bounded.get("sub_issues", [])]:
            if not isinstance(detail, dict):
                continue
            for comment in detail.get("comments", []):
                if isinstance(comment, dict) and comment.get("id") == original_id:
                    return comment
    original_number = original.get("number")
    if original_number is not None:
        for detail in [bounded.get("issue"), bounded.get("parent_issue"), *bounded.get("sub_issues", [])]:
            if isinstance(detail, dict) and detail.get("number") == original_number:
                return detail
    return None


def _enforce_serialized_context_budget(context: dict[str, Any]) -> None:
    for _ in range(len(_context_text_fields(context)) + 1):
        excess = len(json.dumps(context, ensure_ascii=False, sort_keys=True)) - MAX_ISSUE_CONTEXT_CHARS
        if excess <= 0:
            return
        text_fields = [
            (container, key, text)
            for container, key, text in _context_text_fields(context)
            if text
        ]
        if not text_fields:
            return
        container, key, text = max(text_fields, key=lambda field: len(field[2]))
        container[key] = text[: max(0, len(text) - excess - 16)]


def _read_excerpt(path: str) -> str:
    target = REPO_ROOT / path
    if not target.is_file():
        return f"[missing: {path}]"
    text = target.read_text(encoding="utf-8", errors="replace")
    if len(text) <= MAX_FILE_CHARS:
        return text
    half = MAX_FILE_CHARS // 2
    head = text[:half].rsplit("\n", 1)[0]
    tail = text[-half:].split("\n", 1)[-1]
    return head + "\n[...middle truncated...]\n" + tail


def _relevant_excerpt(path: str, tokens: set[str]) -> str:
    target = REPO_ROOT / path
    if not target.is_file():
        return f"[missing: {path}]"
    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    terms = set(tokens)
    if tokens & {"accessibility", "dashboard", "design", "responsive", "visual"}:
        terms.update(
            {
                "focus",
                "header",
                "media",
                "nav",
                "panel",
                "style",
                "timestamp",
                "toolbar",
            }
        )
    scored = []
    for index, line in enumerate(lines):
        lowered = line.lower()
        score = sum(1 for term in terms if term in lowered)
        if score:
            scored.append((score, index))
    selected: list[int] = []
    for _, index in sorted(scored, key=lambda item: (-item[0], item[1])):
        if any(abs(index - existing) < 24 for existing in selected):
            continue
        selected.append(index)
        if len(selected) >= 4:
            break
    if not selected:
        return _read_excerpt(path)

    excerpts = []
    for index in sorted(selected):
        start = max(0, index - 10)
        end = min(len(lines), index + 11)
        numbered = "\n".join(
            f"{line_number + 1:04d}: {lines[line_number]}"
            for line_number in range(start, end)
        )
        excerpts.append(f"# {path}:L{start + 1}-L{end}\n{numbered}")
    value = "\n\n".join(excerpts)
    if len(value) <= MAX_RELEVANT_EXCERPT_CHARS:
        return value
    return value[:MAX_RELEVANT_EXCERPT_CHARS] + "\n[...relevant excerpts truncated...]"


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
                "labels": sorted(labels),
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


def _candidate_source_paths(tokens: set[str]) -> list[str]:
    paths = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "src").rglob("*.py")
        if "__pycache__" not in path.parts
    ]
    if tokens & {"documentation", "docs", "guide", "instruction", "instructions", "readme"}:
        paths.extend(
            path.relative_to(REPO_ROOT).as_posix()
            for path in (REPO_ROOT / "docs").rglob("*.md")
        )
        paths.extend(["README.md", ".github/copilot-instructions.md"])
    if tokens & {"action", "actions", "ci", "schedule", "scheduled", "workflow", "workflows"}:
        paths.extend(
            path.relative_to(REPO_ROOT).as_posix()
            for path in (REPO_ROOT / ".github" / "workflows").glob("*.yml")
        )
    return sorted({path for path in paths if (REPO_ROOT / path).is_file()})


def _score_path(path: str, tokens: set[str]) -> int:
    text = (REPO_ROOT / path).read_text(encoding="utf-8", errors="replace").lower()
    path_text = path.lower()
    stem = Path(path).stem.lower()
    path_score = sum(100 if token in path_text else 0 for token in tokens)
    exact_stem_score = sum(1_000 if token == stem else 0 for token in tokens)
    text_score = sum(min(text.count(token), MAX_TEXT_TOKEN_MATCHES) for token in tokens)
    return path_score + exact_stem_score + text_score


def _derive_scope(issue: dict[str, Any]) -> tuple[list[str], list[str]]:
    tokens = _issue_tokens(issue)
    ranked_sources = sorted(
        ((_score_path(path, tokens), path) for path in _candidate_source_paths(tokens)),
        key=lambda item: (-item[0], item[1]),
    )
    preferred_stems = set(tokens)
    for token in tokens:
        preferred_stems.update(_SCOPE_STEM_ALIASES.get(token, set()))
    exact_sources = [
        (score, path)
        for score, path in ranked_sources
        if Path(path).stem.lower() in preferred_stems
    ]
    selected_sources = exact_sources or ranked_sources
    sources = [path for score, path in selected_sources if score > 0][:MAX_EVIDENCE_FILES]
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

    if not tests:
        test_paths = [
            path.relative_to(REPO_ROOT).as_posix()
            for path in (REPO_ROOT / "tests").glob("test_*.py")
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


def build_issue_context(
    issues_path: Path,
    index: int = 0,
    github_context_client: GitHubIssueContextClient | None = None,
    scope_override: tuple[list[str], list[str]] | None = None,
    additional_evidence: dict[str, Any] | None = None,
    selected_issue: dict[str, Any] | None = None,
) -> dict[str, Any]:
    issues = [selected_issue] if selected_issue is not None else _load_issues(issues_path)
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
    source_paths, tests = scope_override or _derive_scope(issue)
    if not source_paths:
        return {
            "category": "",
            "summary": f"No bounded source scope could be derived for GitHub issue #{issue['number']}.",
            "allowed_paths": [],
            "tests": [],
            "evidence": {},
        }
    allowed_paths = list(dict.fromkeys([*source_paths, *tests]))
    evidence_paths = allowed_paths[:MAX_EVIDENCE_FILES]
    issue_tokens = _issue_tokens(issue)
    github_issue_context: dict[str, Any] | None = None
    github_pull_request_feedback: dict[str, Any] | None = None
    github_context_warning = ""
    if github_context_client is not None:
        try:
            github_issue_context = github_context_client.fetch(issue["number"])
        except RuntimeError as error:
            github_context_warning = str(error)
        try:
            github_pull_request_feedback = github_context_client.fetch_pull_request_feedback(
                issue["number"]
            )
        except RuntimeError as error:
            github_context_warning = " ".join(
                value for value in (github_context_warning, str(error)) if value
            )
    evidence = {
        "issue_number": issue["number"],
        "issue_url": issue["url"],
        "issue_title": issue["title"],
        "objective": issue["objective"],
        "priority": issue["priority"],
        "issue_labels": issue["labels"],
        "recent_git_history": _git_history(),
        "allowed_paths": allowed_paths,
        "tests": tests,
        "file_excerpts": {
            path: _relevant_excerpt(path, issue_tokens) for path in evidence_paths
        },
    }
    if github_issue_context is not None:
        evidence["github_issue_context"] = github_issue_context
    if github_pull_request_feedback is not None:
        evidence["github_pull_request_feedback"] = github_pull_request_feedback
    if github_context_warning:
        evidence["github_issue_context_warning"] = github_context_warning
    if additional_evidence:
        evidence.update(additional_evidence)
    return {
        "category": f"issue-{issue['number']}",
        "summary": "Highest-priority eligible GitHub backlog issue selected with auto-derived scope.",
        "allowed_paths": allowed_paths,
        "tests": tests,
        "issue_number": issue["number"],
        "recurring": RECURRING_LABEL in issue["labels"],
        "evidence": evidence,
    }


def render_issue_task_markdown(task: dict[str, Any]) -> str:
    lines = ["## Azure GitHub issue backlog task", "", task["summary"], ""]
    if not task["category"]:
        lines.append("No eligible issue task was selected.")
        return "\n".join(lines) + "\n"
    lines.extend(
        [
            f"- Issue: `{task['category']}`",
            f"- Allowed paths: {', '.join(f'`{path}`' for path in task['allowed_paths'])}",
            f"- Focused tests: {', '.join(f'`{path}`' for path in task['tests']) or 'full suite'}",
            "",
            "Copilot CLI edits are validated locally before any branch or draft PR is created.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a bounded GitHub issue coding task.")
    parser.add_argument("--issues", type=Path, required=True)
    parser.add_argument("--index", type=int, default=0)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    github_context_client = (
        GitHubIssueContextClient.from_env(args.repository)
        if args.repository and os.environ.get("GH_TOKEN")
        else None
    )
    context = build_issue_context(args.issues, args.index, github_context_client)
    args.output.write_text(json.dumps(context, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(render_issue_task_markdown(context))


if __name__ == "__main__":
    main()