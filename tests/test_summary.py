import json

from azure_region_monitor.models import Change
from azure_region_monitor.summary import ChangeContext, build_change_narrative, change_key


def _change(region, feature, previous, current, change_type, service="ai"):
    return Change(
        region=region,
        service=service,
        feature=feature,
        previous=previous,
        current=current,
        change_type=change_type,
    )


class _FakeClient:
    def __init__(self, reply="eastus newly lists gpt-5.", error=None, deployment=None):
        self.reply = reply
        self.error = error
        self.deployment = deployment
        self.calls = []

    def generate(self, *, system, user):
        self.calls.append((system, user))
        if self.error is not None:
            raise self.error
        return self.reply


def _editorial_package(
    date="2026-07-03",
    new=1,
    regressions=0,
    parked=0,
):
    counts = f"{new:,} new availability, {regressions:,} regressions, and {parked:,} parked unknown"
    return json.dumps(
        {
            "narrative": (
                "Regional catalog update\n\n"
                "A monitored catalog signal changed.\n\n"
                "What this means for Azure users: review regional placement options."
            ),
            "excerpt": "A purpose-written summary of the monitored regional catalog change.",
            "linkedin": f"{date} recorded {counts} transitions.",
            "short_post": f"{date} recorded {counts} transitions.",
        }
    )


def test_rule_summary_when_no_client():
    changes = [
        _change("eastus", "aiModels.openai.gpt-5.2025", "unavailable", "available", "new_availability"),
        _change("westus3", "vmSkus.standard.d2as.v5", "available", "unavailable", "regression", service="compute"),
    ]

    result = build_change_narrative(changes, client=None)

    assert result["narrative_source"] == "rule"
    assert result["narrative_fallback_reason"] == "no_narrative_client"
    assert "1 new availability signal" in result["narrative"]
    assert "1 regression" in result["narrative"]
    assert "eastus" in result["narrative"]
    assert "westus3" in result["narrative"]


def test_no_signals_returns_rule_no_change_message():
    changes = [
        _change("eastus", "aiModels.x.y.1", "available", "unknown", "status_change"),
    ]
    result = build_change_narrative(changes, client=_FakeClient())
    assert result["narrative_source"] == "rule"
    assert "No new availability or regression" in result["narrative"]


def test_ai_path_used_when_client_and_signals_present():
    changes = [
        _change("eastus", "aiModels.openai.gpt-5.2025", "unavailable", "available", "new_availability"),
    ]
    client = _FakeClient(
        reply=_editorial_package(date="2026-07-03")
    )

    result = build_change_narrative(changes, client=client, date="2026-07-03")

    assert result["narrative_source"] == "ai"
    assert result["narrative"].startswith("Regional catalog update")
    assert result["editorial_excerpt"].startswith("A purpose-written")
    assert result["social_drafts"]["linkedin"].startswith("2026-07-03")
    assert result["narrative_fallback_reason"] is None
    assert len(client.calls) == 1
    # Facts must be passed to the model.
    _system, user = client.calls[0]
    assert "new_availability" in user and "eastus" in user


def test_ai_prompt_requires_plain_language_and_azure_user_impact_section():
    changes = [
        _change(
            "eastus",
            "vmSkus.standard.ncads.h100.v5",
            "unavailable",
            "available",
            "new_availability",
        ),
    ]
    client = _FakeClient(reply="Headline\n\nBody.")

    build_change_narrative(changes, client=client)

    system, _user = client.calls[0]
    assert "simple language" in system
    assert "raw SKU, model ID, version, or feature code unexplained" in system
    assert "broader movement in the monitored Azure" in system
    assert 'beginning "What this means for Azure users:"' in system


def test_ai_facts_include_history_classification_and_sre_impact():
    change = _change(
        "eastus",
        "aiModels.openai.gpt-5.2025",
        "unavailable",
        "available",
        "new_availability",
    )
    client = _FakeClient(reply="Headline\n\nBody.")

    build_change_narrative(
        [change],
        client=client,
        contexts={
            change_key(change): ChangeContext(
                classification="restored_availability",
                history_days=7,
                available_days=5,
                missing_days=2,
                unavailable_pct=28.6,
                prior_disappearances=2,
                last_available_date="2026-07-01",
                last_missing_date="2026-07-03",
                region_group="North America",
                expansion_kind="restored_region",
                feature_total_regions=10,
                feature_previous_available_regions=4,
                feature_current_available_regions=5,
                feature_current_coverage_pct=50.0,
                feature_coverage_delta=1,
                still_available_regions=("eastus", "westus3"),
                details_url="https://learn.microsoft.com/azure/ai-foundry/openai/concepts/models",
                feature_note="Use this to evaluate model capabilities.",
            )
        },
    )

    _system, user = client.calls[0]
    assert "classification=restored_availability" in user
    assert "prior_disappearances=2" in user
    assert "unavailable_pct=28.6%" in user
    assert "feature_coverage=5/10" in user
    assert "still_available_regions=eastus, westus3" in user
    assert "details_url=https://learn.microsoft.com/azure/ai-foundry/openai/concepts/models" in user
    assert "sre_impact=" in user


def test_ai_failure_falls_back_to_rule():
    changes = [
        _change("eastus", "aiModels.openai.gpt-5.2025", "unavailable", "available", "new_availability"),
    ]
    client = _FakeClient(error=RuntimeError("boom"), deployment="gpt-5-mini")

    result = build_change_narrative(changes, client=client)

    assert result["narrative_source"] == "rule"
    assert result["narrative_fallback_reason"] == "generation_failed"
    assert result["narrative_model_deployment"] == "gpt-5-mini"
    assert "eastus" in result["narrative"]
    assert "Azure AI model/version catalog entry for model selection (openai.gpt-5.2025)" in result["narrative"]
    assert "What this means for Azure users:" in result["narrative"]


def test_ai_empty_reply_falls_back_to_rule():
    changes = [
        _change("eastus", "aiModels.openai.gpt-5.2025", "unavailable", "available", "new_availability"),
    ]
    client = _FakeClient(reply="   ")

    result = build_change_narrative(changes, client=client)

    assert result["narrative_source"] == "rule"


def test_invalid_editorial_package_falls_back_to_rule():
    changes = [
        _change("eastus", "aiModels.openai.gpt-5.2025", "unavailable", "available", "new_availability"),
    ]

    result = build_change_narrative(
        changes,
        client=_FakeClient(reply='{"narrative": "missing required fields"}'),
        date="2026-07-03",
    )

    assert result["narrative_source"] == "rule"
    assert result["narrative_fallback_reason"] == "unsupported_generation"
    assert result["social_drafts"]["linkedin"].startswith("2026-07-03")


def test_ai_unsupported_claim_falls_back_with_observable_reason():
    changes = [
        _change("eastus", "aiModels.openai.gpt-5.2025", "unavailable", "available", "new_availability"),
    ]

    result = build_change_narrative(
        changes,
        client=_FakeClient(reply="East US has available capacity and a new quota."),
    )

    assert result["narrative_source"] == "rule"
    assert result["narrative_fallback_reason"] == "unsupported_generation"


def test_ai_requires_user_impact_section_and_rejects_unsupported_claims():
    changes = [
        _change("eastus", "vmSkus.standard.d2as.v5", "unavailable", "available", "new_availability"),
    ]

    for reply in (
        "A VM SKU is listed.",
        "What this means for Azure users: this SKU is eligible because of a root cause.",
        "What this means for Azure users: deployment success is guaranteed.",
    ):
        result = build_change_narrative(changes, client=_FakeClient(reply=reply))
        assert result["narrative_source"] == "rule"
        assert result["narrative_fallback_reason"] == "unsupported_generation"


def test_rule_fallback_expands_known_identifier_modalities():
    changes = [
        _change("eastus", "aiModels.openai.gpt-5.2025", "unavailable", "available", "new_availability"),
        _change("westus3", "vmSkus.standard.d2as.v5", "unavailable", "available", "new_availability"),
        _change("centralus", "extensions.flux", "unavailable", "available", "new_availability"),
        _change("eastus2", "runtimes.python.3.12", "unavailable", "available", "new_availability"),
        _change("westeurope", "containerApps.managedEnvironments", "unavailable", "available", "new_availability"),
    ]

    narrative = build_change_narrative(changes)["narrative"]

    assert "model/version catalog entry" in narrative
    assert "right-sizing compute" in narrative
    assert "managed cluster capabilities" in narrative
    assert "Flex Consumption runtime" in narrative
    assert "serverless container planning" in narrative


def test_ai_failure_surfaces_the_generation_error():
    changes = [
        _change("eastus", "aiModels.openai.gpt-5.2025", "unavailable", "available", "new_availability"),
    ]

    result = build_change_narrative(changes, client=_FakeClient(error=RuntimeError("MCP timed out")))

    assert result["narrative_source"] == "rule"
    assert result["narrative_generation_error"] == "RuntimeError: MCP timed out"


def test_rule_summary_is_opinionated_about_rollout_and_deprecation():
    changes = [
        _change("eastus", "aiModels.openai.gpt-5.2025", "unavailable", "available", "new_availability"),
        _change("westeurope", "aiModels.openai.gpt-4-32k.2023", "available", "unavailable", "regression"),
    ]

    narrative = build_change_narrative(changes, client=None)["narrative"]

    # New AI model listing is framed as a rollout; a delisting as likely deprecation.
    assert "rolling out" in narrative
    assert "likely deprecation" in narrative
    # Modality is the sentence prefix and regions are named.
    assert "Azure AI models:" in narrative
    assert "eastus" in narrative and "westeurope" in narrative


def test_rule_summary_starts_with_a_plain_language_azure_movement():
    changes = [
        _change("eastus", "aiModels.openai.gpt-5.2025", "unavailable", "available", "new_availability"),
        _change("westeurope", "vmSkus.standard.d2as.v5", "available", "unavailable", "regression"),
    ]

    narrative = build_change_narrative(changes, client=None)["narrative"]

    assert (
        "In everyday terms, the monitor now has 1 newly listed option and no longer has 1 "
        "previously listed option"
        in narrative
    )
    assert "These catalog changes can affect where teams plan workloads or select services." in narrative
    assert narrative.index("In everyday terms") < narrative.index("Azure AI models:")


def test_rule_summary_frames_latency_additions_and_removals():
    changes = [
        _change("eastus", "aiLatency.openai.gpt-5.1", "unavailable", "available", "new_availability"),
        _change("westus3", "aiLatency.openai.gpt-4o", "available", "unavailable", "regression"),
    ]

    narrative = build_change_narrative(changes, client=None)["narrative"]

    assert "started measuring" in narrative
    assert "stopped measuring" in narrative
    assert "Azure model latency:" in narrative


def test_rule_summary_uses_history_classification_breakdown():
    restored = _change(
        "eastus",
        "aiModels.openai.gpt-5.2025",
        "unavailable",
        "available",
        "new_availability",
    )
    net_new = _change(
        "westus3",
        "aiModels.openai.gpt-5.2025",
        "unavailable",
        "available",
        "new_availability",
    )

    narrative = build_change_narrative(
        [restored, net_new],
        client=None,
        contexts={
            change_key(restored): ChangeContext(
                classification="restored_availability",
                history_days=5,
                available_days=3,
                missing_days=2,
                unavailable_pct=40.0,
                prior_disappearances=1,
                feature_total_regions=4,
                feature_current_available_regions=2,
            ),
            change_key(net_new): ChangeContext(
                classification="net_new_availability",
                history_days=5,
                missing_days=5,
                unavailable_pct=100.0,
                expansion_kind="new_feature",
                feature_total_regions=4,
                feature_current_available_regions=2,
            ),
        },
    )["narrative"]

    assert "1 net-new regional availability" in narrative
    assert "1 restored availability" in narrative
    assert "up to 1 prior disappearance" in narrative
    assert "Coverage now ranges from 2 to 2 of 4 monitored regions" in narrative
    assert "unavailable 100.0% of prior observations" in narrative
    assert "first observed anywhere" in narrative
    assert "SRE impact:" in narrative
