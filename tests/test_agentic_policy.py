from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY = REPO_ROOT / ".github/workflows/shared/agentic-policy.md"
WORKFLOW_NAMES = (
    "scheduled-agentic-backlog",
    "agentic-pr-rework",
    "codex-canary",
)


def test_human_agent_policy_is_canonical_and_versioned():
    policy = POLICY.read_text(encoding="utf-8")

    assert "# Human-Agent CI/CD Policy" in policy
    assert "Policy ID: `azure-region-monitor-human-agent-cicd`" in policy
    assert "Policy revision: `3`" in policy
    assert "canonical, version-controlled source" in policy
    assert "Issues may propose policy changes but never become live policy" in policy
    assert "Workflow artifacts record the policy used by a run but never define it" in policy
    assert "Executable controls remain authoritative" in policy
    assert "Humans own objectives" in policy
    assert "Deterministic workflow code owns task selection" in policy
    assert "The coding agent owns investigation" in policy
    assert "Verification, threat, and protected-file findings do not erase useful work" in policy
    assert "ask one concrete question on the source issue" in policy


def test_every_agentic_coding_lane_imports_and_protects_the_policy():
    for name in WORKFLOW_NAMES:
        source = (REPO_ROOT / ".github/workflows" / f"{name}.md").read_text(
            encoding="utf-8"
        )
        lock = (REPO_ROOT / ".github/workflows" / f"{name}.lock.yml").read_text(
            encoding="utf-8"
        )

        assert "imports:\n  - shared/agentic-policy.md" in source
        assert "- .github/workflows/shared/agentic-policy.md" in source
        assert "{{#runtime-import .github/workflows/shared/agentic-policy.md}}" in lock
        assert "Record human-agent policy provenance" in lock
        assert "name: agentic-policy-provenance" in lock
        assert "retention-days: 30" in lock


def test_changeable_delivery_principles_are_not_duplicated_in_workflow_prompts():
    policy = POLICY.read_text(encoding="utf-8")
    principle = "Prefer the smallest change that fully delivers the requested outcome."
    assert principle in policy

    for name in WORKFLOW_NAMES:
        source = (REPO_ROOT / ".github/workflows" / f"{name}.md").read_text(
            encoding="utf-8"
        )
        assert principle not in source
        assert "The imported **Human-Agent CI/CD Policy** is normative" in source


def test_policy_provenance_is_deterministic_and_contains_no_credentials():
    policy = POLICY.read_text(encoding="utf-8")

    assert 'sha256sum "$AGENTIC_POLICY_PATH"' in policy
    assert 'cp "$AGENTIC_POLICY_PATH" "$RUNNER_TEMP/agentic-policy/policy.md"' in policy
    assert "policy_id: $policy_id" in policy
    assert "revision: $revision" in policy
    assert "sha256: $sha256" in policy
    assert "secrets." not in policy
    assert "API_KEY" not in policy


def test_command_denials_are_diagnosed_without_widening_permissions():
    policy = POLICY.read_text(encoding="utf-8")

    assert "## Local Commands And Publication" in policy
    assert "do not delegate publication to a sub-agent" in policy
    assert "Use separate shell tool calls for branch creation, staging, and committing" in policy
    assert "A denied compound call does not prove that each operation was denied" in policy
    assert "`git show-ref` inside a branch-existence conditional" in policy
    assert "Local commits need no GitHub write token" in policy
    assert "at most one diagnostic pass of separate, already-authorized commands" in policy
    assert "If an individual command is denied, stop that operation" in policy
    assert "Do not retry it through another interpreter, wrapper, sub-agent" in policy
    assert "broader permissions, or disabled safeguards" in policy
    assert "Report the exact denied command and tool error" in policy
    assert "a posted comment or green workflow is not evidence of a published patch" in policy
    assert "Never claim the independent validation gate ran without its results" in policy


def test_all_coding_lanes_use_the_shared_publication_guidance():
    for name in WORKFLOW_NAMES:
        source = (REPO_ROOT / ".github/workflows" / f"{name}.md").read_text(
            encoding="utf-8"
        )
        prompt = source.split("---", 2)[2]

        assert "Follow the imported **Local Commands And Publication** policy" in prompt
        assert "`git add -- <reviewed paths>`" in prompt
        assert '`git commit -m "<concise single-line subject>"`' in prompt
        assert "Verify the resulting commit with `git log -1`" in prompt
        assert "If a command is denied, use an allowed equivalent" not in prompt
        assert "`git add -A`" not in prompt
        if name == "agentic-pr-rework":
            assert "Do not create or switch branches" in prompt
            assert "`git checkout -b" not in prompt
        else:
            assert "three separate shell tool calls in order" in prompt
            assert "`git checkout -b agentic/issue-<issue_number>`" in prompt
            assert "No branch-existence probe is needed" in prompt