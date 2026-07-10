from __future__ import annotations

import importlib.util
import json
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
    assert context["evidence"]["issue_url"].endswith("/11")


def test_missing_priority_defaults_to_normal(tmp_path):
    path = tmp_path / "issues.json"
    issue = _issue(11)
    issue["body"] = "### Objective\n\nImprove social blog draft quality.\n"
    path.write_text(json.dumps([issue]), encoding="utf-8")

    assert issue_agent._load_issues(path)[0]["priority"] == 200


def test_issue_renderer_labels_no_change_output():
    rendered = issue_agent.render_issue_markdown(
        {
            "decision": "no_change",
            "summary": "No eligible issues.",
            "category": "",
            "allowed_paths": [],
            "tests": [],
        }
    )

    assert "## Azure GitHub issue backlog review" in rendered
    assert "No safe issue patch proposal" in rendered


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