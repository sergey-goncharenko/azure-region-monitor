from __future__ import annotations

import importlib.util
import json
import re
import sys
import urllib.error
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_azure_issue_agent.py"
SPEC = importlib.util.spec_from_file_location("run_azure_issue_agent", SCRIPT_PATH)
assert SPEC is not None
issue_agent = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = issue_agent
SPEC.loader.exec_module(issue_agent)


def _issue(number: int, *, priority: str = "Normal", labels: list[str] | None = None) -> dict:
    return {
        "number": number,
        "title": "Improve blog social output",
        "body": f"""### Priority

{priority}

### Objective

Improve social blog draft quality.

### Context or acceptance evidence

The change should remain factual.
""",
        "labels": [{"name": label} for label in labels or ["azure-backlog"]],
        "url": f"https://github.com/example/repo/issues/{number}",
    }


def test_unlabelled_and_paused_issues_are_not_selected(tmp_path):
    path = tmp_path / "issues.json"
    path.write_text(
        json.dumps(
            [
                _issue(1, labels=["enhancement"]),
                _issue(2, labels=["azure-backlog", "azure-paused"]),
            ]
        ),
        encoding="utf-8",
    )

    context = issue_agent.build_issue_context(path)

    assert context["category"] == ""
    assert "No eligible open GitHub issues" in context["summary"]


def test_highest_priority_issue_is_selected_and_auto_scoped(tmp_path):
    path = tmp_path / "issues.json"
    path.write_text(
        json.dumps([_issue(22, priority="Low"), _issue(11, priority="High")]),
        encoding="utf-8",
    )

    context = issue_agent.build_issue_context(path)

    assert context["category"] == "issue-11"
    assert context["issue_number"] == 11
    assert "src/azure_region_monitor/blog.py" in context["allowed_paths"]
    assert "tests/test_blog.py" in context["tests"]
    assert "tests/test_blog.py" in context["allowed_paths"]
    assert context["evidence"]["issue_url"].endswith("/11")


def test_urgent_issue_precedes_high_and_recurring_label_is_preserved(tmp_path):
    path = tmp_path / "issues.json"
    urgent = _issue(
        30,
        priority="Urgent",
        labels=["azure-backlog", "azure-recurring", "azure-unknowns"],
    )
    high = _issue(20, priority="High")
    path.write_text(json.dumps([high, urgent]), encoding="utf-8")

    loaded = issue_agent._load_issues(path)
    context = issue_agent.build_issue_context(path)

    assert loaded[0]["number"] == 30
    assert loaded[0]["priority"] == 400
    assert "azure-unknowns" in loaded[0]["labels"]
    assert context["issue_number"] == 30
    assert context["recurring"] is True
    assert "azure-recurring" in context["evidence"]["issue_labels"]


def test_api_contract_issue_selects_api_source_and_tests(tmp_path):
    path = tmp_path / "issues.json"
    issue = _issue(45, priority="High")
    issue["title"] = "Extend public API contract test coverage"
    issue["body"] = """### Priority

High

### Objective

Extend public API contract coverage for `/api/diff`, `/api/services/{service}`, `/api/history/{date}`, and `/api/subscribe` without changing API implementation.
"""
    path.write_text(json.dumps([issue]), encoding="utf-8")

    context = issue_agent.build_issue_context(path)

    assert "src/azure_region_monitor/api.py" in context["allowed_paths"]
    assert "tests/test_api.py" in context["tests"]
    assert not any(path.startswith("docs/") for path in context["allowed_paths"])
    assert not any(path.startswith(".github/workflows/") for path in context["allowed_paths"])
    assert "src/azure_region_monitor/static_site.py" not in context["allowed_paths"]
    assert "src/azure_region_monitor/cli.py" not in context["allowed_paths"]


def test_dashboard_design_issue_selects_static_site_scope(tmp_path):
    path = tmp_path / "issues.json"
    issue = _issue(49, priority="Normal")
    issue["title"] = "Improve dashboard visual design and responsive usability"
    issue["body"] = """### Priority

Normal

### Objective

Improve dashboard visual design, responsive layout, navigation, and accessibility while preserving full data fidelity.
"""
    path.write_text(json.dumps([issue]), encoding="utf-8")

    context = issue_agent.build_issue_context(path)

    assert context["allowed_paths"] == [
        "src/azure_region_monitor/static_site.py",
        "tests/test_static_site.py",
    ]
    assert context["tests"] == ["tests/test_static_site.py"]


def test_generated_page_shell_issue_includes_static_site_and_blog_scope(tmp_path):
    path = tmp_path / "issues.json"
    issue = _issue(56, priority="Low")
    issue["title"] = "Unify dashboard navigation and generated page shell"
    issue["body"] = """### Priority

Low

### Objective

Unify the dashboard page shell and navigation across all generated public HTML pages.
"""
    path.write_text(json.dumps([issue]), encoding="utf-8")

    context = issue_agent.build_issue_context(path)

    assert context["allowed_paths"] == [
        "src/azure_region_monitor/static_site.py",
        "src/azure_region_monitor/blog.py",
        "tests/test_static_site.py",
        "tests/test_blog.py",
    ]
    assert context["tests"] == ["tests/test_static_site.py", "tests/test_blog.py"]


def test_missing_priority_defaults_to_normal(tmp_path):
    path = tmp_path / "issues.json"
    issue = _issue(11)
    issue["body"] = "### Objective\n\nImprove social blog draft quality.\n"
    path.write_text(json.dumps([issue]), encoding="utf-8")

    assert issue_agent._load_issues(path)[0]["priority"] == 200


def test_issue_task_renderer_labels_unselected_output():
    rendered = issue_agent.render_issue_task_markdown(
        {
            "summary": "No eligible issues.",
            "category": "",
            "allowed_paths": [],
            "tests": [],
        }
    )

    assert "## Azure GitHub issue backlog task" in rendered
    assert "No eligible issue task" in rendered


def test_selected_issue_includes_comments_and_subissue_context(tmp_path):
    path = tmp_path / "issues.json"
    path.write_text(json.dumps([_issue(11, priority="High")]), encoding="utf-8")

    class ContextClient:
        def fetch(self, issue_number):
            assert issue_number == 11
            return {
                "issue": {"number": 11, "comments": [{"body": "Use concise highlights."}]},
                "parent_issue": None,
                "sub_issues": [{"number": 12, "title": "Validate summary", "comments": []}],
            }

        def fetch_pull_request_feedback(self, issue_number):
            return None

    context = issue_agent.build_issue_context(path, github_context_client=ContextClient())

    rich_context = context["evidence"]["github_issue_context"]
    assert rich_context["issue"]["comments"][0]["body"] == "Use concise highlights."
    assert rich_context["sub_issues"][0]["number"] == 12


def test_selected_issue_reports_context_fetch_warning_without_broadening_scope(tmp_path):
    path = tmp_path / "issues.json"
    path.write_text(json.dumps([_issue(11, priority="High")]), encoding="utf-8")

    class ContextClient:
        def fetch(self, issue_number):
            raise RuntimeError("GitHub issue context request failed: HTTP 503.")

        def fetch_pull_request_feedback(self, issue_number):
            return None

    context = issue_agent.build_issue_context(path, github_context_client=ContextClient())

    assert "github_issue_context" not in context["evidence"]
    assert "HTTP 503" in context["evidence"]["github_issue_context_warning"]
    assert "src/azure_region_monitor/blog.py" in context["allowed_paths"]


def test_github_context_client_fetches_comments_and_direct_subissues():
    class Response:
        def __init__(self, payload):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def read(self):
            return json.dumps(self._payload).encode("utf-8")

    class Opener:
        def __init__(self, responses):
            self.responses = responses

        def open(self, request, timeout):
            return Response(self.responses[request.full_url])

    root = {
        "number": 11,
        "title": "Parent work",
        "body": "Root body",
        "html_url": "https://github.com/example/repo/issues/11",
        "state": "open",
        "user": {"login": "owner"},
        "assignees": [],
        "labels": [],
        "parent_issue_url": None,
    }
    child = {
        "number": 12,
        "title": "Child work",
        "body": "Child body",
        "html_url": "https://github.com/example/repo/issues/12",
        "state": "open",
        "user": {"login": "owner"},
        "assignees": [],
        "labels": [],
        "parent_issue_url": None,
    }
    base = "https://api.github.com/repos/example/repo/issues"
    opener = Opener(
        {
            f"{base}/11": root,
            f"{base}/11/comments?per_page=100&page=1": [
                {"id": 1, "body": "Root comment", "user": {"login": "reviewer"}}
            ],
            f"{base}/11/sub_issues?per_page=100&page=1": [{"number": 12}],
            f"{base}/12": child,
            f"{base}/12/comments?per_page=100&page=1": [
                {"id": 2, "body": "Child comment", "user": {"login": "reviewer"}}
            ],
        }
    )

    client = issue_agent.GitHubIssueContextClient(
        repository="example/repo", token="test-token", opener=opener
    )
    context = client.fetch(11)

    assert context["issue"]["comments"][0]["body"] == "Root comment"
    assert context["sub_issues"][0]["title"] == "Child work"
    assert context["sub_issues"][0]["comments"][0]["body"] == "Child comment"


def test_github_context_client_fetches_pull_request_review_feedback():
    class Response:
        def __init__(self, payload):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def read(self):
            return json.dumps(self._payload).encode("utf-8")

    class Opener:
        def __init__(self, responses):
            self.responses = responses

        def open(self, request, timeout):
            return Response(self.responses[request.full_url])

    base = "https://api.github.com/repos/example/repo"
    opener = Opener(
        {
            f"{base}/pulls?state=open&head=example%3Aazure-issues%2Fissue-11&per_page=10": [
                {
                    "number": 50,
                    "title": "Improve API",
                    "body": "Initial PR body",
                    "html_url": "https://github.com/example/repo/pull/50",
                }
            ],
            f"{base}/issues/50/comments?per_page=100&page=1": [
                {"id": 1, "body": "Please explain the fallback.", "user": {"login": "owner"}}
            ],
            f"{base}/pulls/50/reviews?per_page=100&page=1": [
                {
                    "id": 2,
                    "state": "CHANGES_REQUESTED",
                    "body": "Avoid process-global state.",
                    "user": {"login": "owner"},
                }
            ],
            f"{base}/pulls/50/comments?per_page=100&page=1": [
                {
                    "id": 3,
                    "path": "src/api.py",
                    "line": 42,
                    "side": "RIGHT",
                    "body": "Add a regression test here.",
                    "user": {"login": "owner"},
                }
            ],
        }
    )
    client = issue_agent.GitHubIssueContextClient(
        repository="example/repo", token="test-token", opener=opener
    )

    feedback = client.fetch_pull_request_feedback(11)

    assert feedback is not None
    assert feedback["number"] == 50
    assert feedback["conversation_comments"][0]["body"] == "Please explain the fallback."
    assert feedback["reviews"][0]["state"] == "CHANGES_REQUESTED"
    assert feedback["inline_comments"][0]["path"] == "src/api.py"


def test_issue_context_budget_marks_truncation(monkeypatch):
    monkeypatch.setattr(issue_agent, "MAX_ISSUE_CONTEXT_CHARS", 800)
    context = {
        "issue": {
            "number": 11,
            "body": "root " * 300,
            "comments": [{"id": 1, "body": "latest " * 300}],
        },
        "parent_issue": None,
        "sub_issues": [],
    }

    bounded = issue_agent._limit_issue_context(context)

    assert bounded["context_truncated"] is True
    assert "context budget" in bounded["truncation_note"]
    assert len(json.dumps(bounded)) <= issue_agent.MAX_ISSUE_CONTEXT_CHARS


def test_github_context_client_retries_transient_failure(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def read(self):
            return b'{"ok": true}'

    class Opener:
        calls = 0

        def open(self, request, timeout):
            self.calls += 1
            if self.calls == 1:
                raise urllib.error.URLError("temporary network failure")
            return Response()

    sleeps = []
    monkeypatch.setattr(issue_agent.time, "sleep", sleeps.append)
    opener = Opener()
    client = issue_agent.GitHubIssueContextClient(
        repository="example/repo", token="test-token", opener=opener
    )

    assert client._request("/test") == {"ok": True}
    assert opener.calls == 2
    assert sleeps == [1]


def test_relevant_excerpt_selects_line_numbered_matching_windows(monkeypatch, tmp_path):
    source = tmp_path / "src" / "ui.py"
    source.parent.mkdir()
    source.write_text(
        "\n".join(
            [
                "def unrelated():",
                "    return None",
                *(f"padding_{index} = {index}" for index in range(30)),
                "def dashboard_toolbar():",
                "    focus_visible = True",
                "    return focus_visible",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(issue_agent, "REPO_ROOT", tmp_path)

    excerpt = issue_agent._relevant_excerpt(
        "src/ui.py", {"dashboard", "design", "focus"}
    )

    assert "# src/ui.py:L" in excerpt
    assert "def dashboard_toolbar" in excerpt
    assert "focus_visible" in excerpt
    assert re.search(r"\d{4}: def dashboard_toolbar", excerpt)