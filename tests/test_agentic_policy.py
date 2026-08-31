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
    assert "Policy revision: `2`" in policy
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