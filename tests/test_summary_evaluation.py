from pathlib import Path

from azure_region_monitor.summary_evaluation import evaluate_responses, load_cases


def test_evaluation_compares_production_and_candidate_with_cost_latency_and_quality():
    cases = load_cases(Path("tests/fixtures/summary_evaluation_cases.json"))
    text = "Azure AI model listed.\n\nWhat this means for Azure users: review regional planning."
    responses = {
        "gpt-5.4-mini": {
            "ai-model": {"text": text, "latency_ms": 125, "input_tokens": 100, "output_tokens": 20}
        },
        "gpt-5.4": {
            "ai-model": {"text": text, "latency_ms": 150, "input_tokens": 110, "output_tokens": 25}
        },
    }

    report = evaluate_responses(
        cases,
        responses,
        input_cost_per_million=2.0,
        output_cost_per_million=8.0,
    )

    production = report["deployments"]["gpt-5.4-mini"]
    candidate = report["deployments"]["gpt-5.4"]
    assert report["production_deployment"] == "gpt-5.4-mini"
    assert production["contract_pass_rate"] == 1.0
    assert production["groundedness_pass_rate"] == 1.0
    assert production["mean_latency_ms"] == 125.0
    assert production["total_input_tokens"] == 100.0
    assert production["estimated_cost"] == 0.00036
    assert candidate["total_output_tokens"] == 25.0
