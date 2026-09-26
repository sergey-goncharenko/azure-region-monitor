"""Source and generated-runtime contracts; no Azure calls or model inference."""

import json
import re
from decimal import Decimal
from pathlib import Path

import pytest


WORKFLOWS = Path(__file__).resolve().parents[1] / ".github/workflows"
LANES = ("scheduled-agentic-backlog", "agentic-pr-rework", "codex-canary")
REPOSITORY_MODEL = "${{ vars.AZWATCH_AGENTIC_MODEL }}"
CANARY_MODEL = (
    "${{ inputs.model == 'gpt-6-astra' && 'gpt-6-astra' || vars.AZWATCH_AGENTIC_MODEL }}"
)
# Verified Azure Retail Prices API, East US 2 / Global Standard, 2026-09-26.
# Use long-context rates, plus the cache-write ceiling for ordinary input because
# pinned AWF misses Responses input_tokens_details.cache_write_tokens.
ASTRA_USD_PER_MILLION = {
    "input": Decimal("25"),
    "output": Decimal("75"),
    "cache_read": Decimal("2"),
    "cache_write": Decimal("25"),
}


def read_workflow(lane, suffix):
    return (WORKFLOWS / f"{lane}.{suffix}").read_text(encoding="utf-8")


def job(lock, name):
    body = lock.split(f"\n  {name}:\n", 1)[1]
    return re.split(r"\n  [\w-]+:\n", body, maxsplit=1)[0]


def awf_configs(lock):
    # Read the actual serialized config used by AWF, not comments or source YAML.
    decoder = json.JSONDecoder()
    configs = []
    for line in lock.splitlines():
        if "printf" in line and "'{\"$schema\":" in line:
            configs.append(decoder.raw_decode(line[line.index("{"):])[0])
    assert len(configs) == 2, "Expected separate agent and detector AWF configurations"
    return configs


def env_values(text, name):
    return re.findall(rf"^[ \t]+{re.escape(name)}: (.+)$", text, re.MULTILINE)


def test_astra_is_an_explicit_manual_canary_choice_not_a_new_production_default():
    source = read_workflow("codex-canary", "md")
    inputs = source.split("    inputs:\n", 1)[1].split("\npermissions:", 1)[0]
    choice = inputs.split("      model:\n", 1)[1]
    assert "required: false" in choice
    assert "type: choice" in choice
    assert "default: repository-default" in choice
    assert re.findall(r"^\s+- (.+)$", choice, re.MULTILINE) == [
        "repository-default",
        "gpt-6-astra",
    ]
    assert "  schedule:" not in source
    assert "  repository_dispatch:" not in source
    # Only explicit Astra selects it; empty/default/other input retains the repo var.
    assert env_values(source, "model") == [CANARY_MODEL, REPOSITORY_MODEL]
    assert f"\nmodel: {REPOSITORY_MODEL}\n" in source
    agent = job(read_workflow("codex-canary", "lock.yml"), "agent")
    for name in ("COPILOT_MODEL", "COPILOT_PROVIDER_MODEL_ID", "COPILOT_PROVIDER_WIRE_MODEL"):
        assert env_values(agent, name) == [CANARY_MODEL]
    assert env_values(agent, "COPILOT_PROVIDER_WIRE_API") == ["responses"]


@pytest.mark.parametrize("lane", LANES[:2])
def test_production_lanes_keep_their_existing_runtime_model_configuration(lane):
    source = read_workflow(lane, "md")
    lock = read_workflow(lane, "lock.yml")
    assert f"\nmodel: {REPOSITORY_MODEL}\n" in source
    assert "inputs.model" not in source
    assert "inputs.model" not in lock
    agent = job(lock, "agent")
    assert env_values(agent, "COPILOT_MODEL") == [REPOSITORY_MODEL]
    assert env_values(agent, "COPILOT_PROVIDER_MODEL_ID") == [REPOSITORY_MODEL]
    assert env_values(agent, "COPILOT_PROVIDER_WIRE_API") == ["responses"]
    # Do not change production session retry policy while isolating the canary.
    assert env_values(agent, "GH_AW_HARNESS_MAX_RETRIES") == []


@pytest.mark.parametrize("lane", LANES)
def test_only_astra_gets_a_provider_price_overlay_with_all_four_token_classes(lane):
    source = read_workflow(lane, "md")
    lock = read_workflow(lane, "lock.yml")
    assert "imports:\n  - shared/agentic-policy.md\n  - shared/agentic-models.md" in source
    assert "\nmodels:" not in source  # Rates have one shared source of truth.
    for config in awf_configs(lock):
        assert config["$schema"].endswith("/v0.28.10/awf-config.schema.json")
        proxy = config["apiProxy"]
        assert "defaultAiCreditsPricing" not in proxy
        assert "AWF_DEFAULT_AI_CREDITS_PRICING" not in lock
        assert set(proxy["providers"]) == {"github-copilot"}
        models = proxy["providers"]["github-copilot"]["models"]
        assert set(models) == {"gpt-6-astra"}  # No catch-all or Terra repricing.
        cost = models["gpt-6-astra"]["cost"]
        assert set(cost) == set(ASTRA_USD_PER_MILLION)
        actual = {key: Decimal(str(value)) * 1_000_000 for key, value in cost.items()}
        assert actual == ASTRA_USD_PER_MILLION
        # Do not confuse cached reads ($2/M) with cache creation ($25/M).
        assert actual["cache_write"] == actual["input"] > actual["cache_read"]
    recorded = json.loads(env_values(lock, "GH_AW_INFO_MODEL_COSTS")[0].strip("'"))
    assert recorded["providers"] == awf_configs(lock)[0]["apiProxy"]["providers"]


def test_model_catalog_is_separate_from_canonical_policy_and_records_accounting_limits():
    catalog = (WORKFLOWS / "shared/agentic-models.md").read_text(encoding="utf-8")
    frontmatter = catalog.split("---", 2)[1]
    policy = (WORKFLOWS / "shared/agentic-policy.md").read_text(encoding="utf-8")
    assert "gpt-6-astra" not in policy
    assert "default-ai-credits-pricing:" not in frontmatter
    assert "models:\n  providers:\n    github-copilot:" in frontmatter
    assert "https://prices.azure.com/api/retail/prices" in catalog
    assert "USD PER TOKEN" in catalog
    assert "cache-write rate does not manufacture missing Azure Responses usage data" in catalog
    assert "usage.input_tokens_details.cache_write_tokens is ignored" in catalog
    assert "$25/M cache-write ceiling (not the $20/M ordinary-input tariff)" in catalog
    assert "not a hard pre-request reservation or invoice" in catalog


@pytest.mark.parametrize(
    "total_input,cache_read,cache_write",
    [(0, 0, 0), (2000, 0, 0), (2000, 0, 2000), (2000, 500, 700), (2000, 2000, 0)],
)
@pytest.mark.parametrize(
    "input_rate,output_rate,read_rate,write_rate",
    [("10", "50", "1", "12.5"), ("20", "75", "2", "25")],
)
def test_astra_rate_bound_covers_responses_cache_writes_even_when_parser_misses_them(
    total_input, cache_read, cache_write, input_rate, output_rate, read_rate, write_rate
):
    # Pin the arithmetic contract, not a replacement usage parser. AWF v0.28.10
    # passes total input and cached_tokens through response.completed, but drops
    # cache_write_tokens. Read/write counts are disjoint subsets of total input.
    event = {
        "type": "response.completed",
        "response": {
            "model": "gpt-6-astra",
            "usage": {
                "input_tokens": total_input,
                "input_tokens_details": {
                    "cached_tokens": cache_read,
                    "cache_write_tokens": cache_write,
                },
                "output_tokens": 40,
            },
        },
    }
    usage = event["response"]["usage"]
    total = usage["input_tokens"]
    reads = usage["input_tokens_details"]["cached_tokens"]
    writes = usage["input_tokens_details"]["cache_write_tokens"]
    fresh = total - reads - writes
    assert fresh >= 0
    output = usage["output_tokens"]
    tariff = (
        fresh * Decimal(input_rate)
        + reads * Decimal(read_rate)
        + writes * Decimal(write_rate)
        + output * Decimal(output_rate)
    ) / 1_000_000
    proxy = awf_configs(read_workflow("codex-canary", "lock.yml"))[0]["apiProxy"]
    cost = proxy["providers"]["github-copilot"]["models"]["gpt-6-astra"]["cost"]
    cost = {key: Decimal(str(value)) for key, value in cost.items()}
    # What pinned AWF charges after ignoring the new write detail.
    flattened_bound = (
        (total - reads) * cost["input"]
        + reads * cost["cache_read"]
        + output * cost["output"]
    )
    # The same catalog remains conservative if a parser supplies separate writes.
    separated_bound = (
        fresh * cost["input"]
        + reads * cost["cache_read"]
        + writes * cost["cache_write"]
        + output * cost["output"]
    )
    assert flattened_bound == separated_bound
    assert flattened_bound >= tariff
    if input_rate == "20":
        assert flattened_bound - tariff == fresh * Decimal("0.000005")


def test_canary_disables_catalog_substitution_and_session_reruns_not_guardrails():
    source = read_workflow("codex-canary", "md")
    lock = read_workflow("codex-canary", "lock.yml")
    assert "harness:\n    max-retries: 0" in source
    assert "model-fallback: false" in source
    agent = job(lock, "agent")
    assert env_values(agent, "GH_AW_HARNESS_MAX_RETRIES") == ["0"]
    proxy = awf_configs(lock)[0]["apiProxy"]
    assert proxy["modelFallback"] == {"enabled": False}
    assert proxy["enableTokenSteering"] is True
    assert proxy["maxAiCredits"] == 700
    assert "GH_AW_MODEL_FALLBACK: gpt-5.6-terra" not in lock


@pytest.mark.parametrize("lane", LANES)
def test_detector_and_existing_security_boundaries_remain_intact(lane):
    source = read_workflow(lane, "md")
    lock = read_workflow(lane, "lock.yml")
    metadata = json.loads(lock.splitlines()[0].split(": ", 1)[1])
    assert metadata["compiler_version"] == "v0.87.10"
    assert metadata["strict"] is True
    assert metadata["engine_versions"] == {
        "copilot": "${{ vars.AZWATCH_AGENTIC_COPILOT_VERSION }}"
    }
    assert "max-continuations: 3" in source
    assert "max-turns: ${{ vars.AZWATCH_AGENTIC_MAX_TURNS }}" in source
    assert "max-daily-ai-credits: 1400" in source
    assert [c["apiProxy"]["maxAiCredits"] for c in awf_configs(lock)] == [700, 200]
    detector = job(lock, "detection")
    assert env_values(detector, "COPILOT_MODEL") == [REPOSITORY_MODEL]
    assert env_values(detector, "COPILOT_PROVIDER_MODEL_ID") == [REPOSITORY_MODEL]
    assert env_values(detector, "GH_AW_HARNESS_MAX_RETRIES") == ["0"]
    assert "inputs.model" not in detector
    if lane == "codex-canary":
        assert env_values(detector, "COPILOT_PROVIDER_WIRE_MODEL") == [REPOSITORY_MODEL]
    for runtime in (job(lock, "agent"), detector):
        assert env_values(runtime, "ENGINE_VERSION") == [
            "${{ vars.AZWATCH_AGENTIC_COPILOT_VERSION }}"
        ]
        assert 'install_copilot_cli.sh" "${ENGINE_VERSION}"' in runtime
        assert "--exclude-env COPILOT_PROVIDER_API_KEY" in runtime
        assert env_values(runtime, "COPILOT_PROVIDER_API_KEY") == [
            "${{ secrets.AZURE_CODING_OPENAI_KEY }}"
        ]
        assert env_values(runtime, "COPILOT_PROVIDER_BASE_URL") == [
            "${{ secrets.AZWATCH_AGENTIC_AZURE_BASE_URL }}"
        ]
    agent = job(lock, "agent")
    permissions = agent.split("\n    env:", 1)[0]
    assert "contents: read" in permissions
    assert "issues: read" in permissions
    assert "pull-requests: read" in permissions
    assert ": write" not in permissions
    grants = re.findall(r"^\s+# --allow-tool (.+)$", agent, re.MULTILINE)
    for command in ("git checkout", "git add", "git commit"):
        assert f"shell({command}:*)" in grants
    for command in ("git", "git push", "git show-ref", "bash", "sh"):
        assert f"shell({command}:*)" not in grants
        assert f"shell({command})" not in grants
    assert "shell" not in grants
    assert "shell(*)" not in grants
