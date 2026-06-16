from azure_region_monitor.models import Change
from azure_region_monitor.summary import build_change_narrative


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
    def __init__(self, reply="eastus newly lists gpt-5.", error=None):
        self.reply = reply
        self.error = error
        self.calls = []

    def generate(self, *, system, user):
        self.calls.append((system, user))
        if self.error is not None:
            raise self.error
        return self.reply


def test_rule_summary_when_no_client():
    changes = [
        _change("eastus", "aiModels.openai.gpt-5.2025", "unavailable", "available", "new_availability"),
        _change("westus3", "vmSkus.standard.d2as.v5", "available", "unavailable", "regression", service="compute"),
    ]

    result = build_change_narrative(changes, client=None)

    assert result["narrative_source"] == "rule"
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
    client = _FakeClient(reply="eastus newly lists openai/gpt-5.")

    result = build_change_narrative(changes, client=client)

    assert result["narrative_source"] == "ai"
    assert result["narrative"] == "eastus newly lists openai/gpt-5."
    assert len(client.calls) == 1
    # Facts must be passed to the model.
    _system, user = client.calls[0]
    assert "new_availability" in user and "eastus" in user


def test_ai_failure_falls_back_to_rule():
    changes = [
        _change("eastus", "aiModels.openai.gpt-5.2025", "unavailable", "available", "new_availability"),
    ]
    client = _FakeClient(error=RuntimeError("boom"))

    result = build_change_narrative(changes, client=client)

    assert result["narrative_source"] == "rule"
    assert "eastus" in result["narrative"]


def test_ai_empty_reply_falls_back_to_rule():
    changes = [
        _change("eastus", "aiModels.openai.gpt-5.2025", "unavailable", "available", "new_availability"),
    ]
    client = _FakeClient(reply="   ")

    result = build_change_narrative(changes, client=client)

    assert result["narrative_source"] == "rule"
