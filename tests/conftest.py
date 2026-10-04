import pytest


@pytest.fixture(autouse=True)
def _disable_live_learn_lookup(monkeypatch):
    monkeypatch.setenv("LEARN_LOOKUP_ENABLED", "0")
