from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_azure_docs_review.py"
SPEC = importlib.util.spec_from_file_location("run_azure_docs_review", SCRIPT_PATH)
assert SPEC is not None
docs_review = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = docs_review
SPEC.loader.exec_module(docs_review)


def test_parse_review_accepts_confirmed_drift():
    review = docs_review._parse_review(
        '{"summary":"One confirmed drift.","confirmed_drift":[{"file":"README.md",'
        '"finding":"A stale claim.","recommendation":"Update the claim."}],'
        '"follow_up_needed":true}'
    )

    assert review["follow_up_needed"] is True
    assert review["confirmed_drift"][0]["file"] == "README.md"
    assert "Recommended follow-up" in docs_review.render_review_markdown(review)


def test_parse_review_fails_closed_for_non_json_output():
    review = docs_review._parse_review("not valid JSON")

    assert review["confirmed_drift"] == []
    assert review["follow_up_needed"] is False
    assert "non-JSON" in review["summary"]