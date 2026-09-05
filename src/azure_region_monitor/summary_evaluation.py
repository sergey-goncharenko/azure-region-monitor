"""Repeatable, offline scoring for daily-summary deployment comparisons."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Protocol

from azure_region_monitor.summary import _is_supported_narrative

PRODUCTION_DEPLOYMENT = "summary-gpt-5-6-terra"


class SummaryEvaluatorClient(Protocol):
    deployment: str

    def generate(self, *, system: str, user: str) -> str:
        """Generate a daily summary for one representative case."""


def load_cases(path: Path) -> list[dict[str, object]]:
    """Load a versioned representative evaluation dataset."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(cases, list) or not all(isinstance(case, dict) for case in cases):
        raise ValueError("Evaluation dataset must contain a cases array of objects.")
    return cases


def evaluate_responses(
    cases: list[Mapping[str, object]],
    responses: Mapping[str, Mapping[str, Mapping[str, object]]],
    *,
    input_cost_per_million: float = 0.0,
    output_cost_per_million: float = 0.0,
) -> dict[str, object]:
    """Score recorded deployment responses without requiring Azure credentials."""
    deployments: dict[str, dict[str, object]] = {}
    for deployment, by_case in responses.items():
        results: list[dict[str, object]] = []
        for case in cases:
            case_id = case.get("id")
            response = by_case.get(case_id) if isinstance(case_id, str) else None
            if not isinstance(response, Mapping):
                continue
            text = response.get("text")
            expected_terms = case.get("expected_terms", [])
            terms = expected_terms if isinstance(expected_terms, list) else []
            grounded = isinstance(text, str) and all(
                isinstance(term, str) and term.lower() in text.lower() for term in terms
            )
            input_tokens = _number(response.get("input_tokens"))
            output_tokens = _number(response.get("output_tokens"))
            results.append(
                {
                    "id": case_id,
                    "contract_passed": isinstance(text, str) and _is_supported_narrative(text),
                    "groundedness_passed": grounded,
                    "latency_ms": _number(response.get("latency_ms")),
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "estimated_cost": (
                        input_tokens * input_cost_per_million + output_tokens * output_cost_per_million
                    )
                    / 1_000_000,
                }
            )
        deployments[deployment] = _deployment_report(results)
    return {"production_deployment": PRODUCTION_DEPLOYMENT, "deployments": deployments}


def main(argv: list[str] | None = None) -> int:
    """Score recorded live runs; generation remains explicit and credential-gated."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("responses", type=Path)
    parser.add_argument("--candidate-deployment", required=True)
    parser.add_argument("--input-cost-per-million", type=float, default=0.0)
    parser.add_argument("--output-cost-per-million", type=float, default=0.0)
    args = parser.parse_args(argv)
    cases = load_cases(args.dataset)
    response_payload = json.loads(args.responses.read_text(encoding="utf-8"))
    if not isinstance(response_payload, dict):
        raise ValueError("Responses must be an object keyed by deployment.")
    report = evaluate_responses(
        cases,
        response_payload,
        input_cost_per_million=args.input_cost_per_million,
        output_cost_per_million=args.output_cost_per_million,
    )
    if args.candidate_deployment not in report["deployments"]:
        raise ValueError("Responses do not include the requested candidate deployment.")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _deployment_report(results: list[dict[str, object]]) -> dict[str, object]:
    count = len(results)
    return {
        "cases": results,
        "contract_pass_rate": _rate(results, "contract_passed"),
        "groundedness_pass_rate": _rate(results, "groundedness_passed"),
        "mean_latency_ms": _mean(results, "latency_ms"),
        "total_input_tokens": sum(_number(result.get("input_tokens")) for result in results),
        "total_output_tokens": sum(_number(result.get("output_tokens")) for result in results),
        "estimated_cost": sum(float(result["estimated_cost"]) for result in results),
        "evaluated_cases": count,
    }


def _rate(results: list[dict[str, object]], field: str) -> float:
    return sum(result[field] is True for result in results) / len(results) if results else 0.0


def _mean(results: list[dict[str, object]], field: str) -> float:
    return sum(_number(result.get(field)) for result in results) / len(results) if results else 0.0


def _number(value: object) -> float:
    return float(value) if isinstance(value, int | float) else 0.0
