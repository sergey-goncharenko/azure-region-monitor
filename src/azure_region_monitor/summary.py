from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any, Mapping, Protocol

from azure_region_monitor.display import plain_feature_name
from azure_region_monitor.feature_context import describe_feature
from azure_region_monitor.models import Change

ChangeKey = tuple[str, str, str]
MAX_FACTS = 40
MAX_EXAMPLES = 1
_PROMPT_PACKAGE = "azure_region_monitor.prompts"
_BLOG_SUMMARY_PROMPT = "blog_summary.md"
_FALLBACK_SYSTEM_PROMPT = """You are the editor of a daily change digest for an Azure regional availability monitor.
Write one evidence-grounded daily editorial package using only the structured facts provided.

Format:
- Return only a JSON object with exactly these string fields:
  {"narrative": "...", "excerpt": "...", "linkedin": "...", "short_post": "..."}
- narrative: first line is a plain headline, no markdown or '#', no more than 10 words,
  followed by at most 3 to 5 one-line bullets or short sentences.
- excerpt: one purpose-written, 1-2 sentence summary under 220 characters. Do not truncate
  the narrative or repeat its headline verbatim.
- When an AKS extension, VM size, or Azure AI model gains listings in multiple regions, make
  the excerpt a one-sentence hook naming that feature and its regional expansion; similar VM
  sizes may be grouped by shared family. Call these catalog listings, not deployment results.
- linkedin and short_post: review-only social variants that name the supplied date, state nonzero
  new/regression counts in compact wording, and may omit zero counts. Do not include URLs.

Treat the supplied changes as the dated scan's delta from the immediately preceding snapshot.
Lead with what changed in that comparison. Use historical classifications only to explain today's
signals; do not replace the daily story with an aggregate over the full retained history.

Write compact memo lines such as "<feature> now listed in N more regions (X -> Y); first listing
in <geography>" or "<feature> no longer listed in <regions> (X -> Y)." Group many similar VM sizes
into one line. Explain each identifier once in plain words, mention each feature only once, and
lead with regressions when they exist. If useful, end with one short sentence beginning
"What this means for Azure users:".

Rules: do not invent regions, models, features, dates, numbers, causes, quotas, capacity, customer
impact, outages, or SLAs. Unavailable means absent from the read-only catalog/list, not proof of
quota, capacity, deployment failure, or SLA impact. Do not repeat references, disclaimers, sign-offs,
or a call to action. Keep it around 150 to 200 words.
"""
_SOCIAL_EVIDENCE_NOTE = (
    "Evidence note: these are read-only Azure catalog/list signals; unavailable does not mean "
    "quota, capacity, deployment failure, or SLA impact."
)
_UNSUPPORTED_CLAIMS = (
    "quota",
    "sla",
    "deployment succeeded",
    "successful deployment",
    "deployment success",
    "eligible",
    "eligibility",
    "root cause",
    "caused by",
    "because of",
    "capacity is available",
    "available capacity",
    "has capacity",
)
_SOCIAL_COUNT_LABELS: dict[str, tuple[str, ...]] = {
    "new": (
        r"new\s+availabilit(?:y|ies)",
        r"new\s+availability\s+signals?",
        r"new\s+listings?",
        r"availability\s+gains?",
    ),
    "regression": (
        r"regressions?",
        r"delistings?",
        r"availability\s+loss(?:es)?",
        r"loss(?:es)?",
        r"dropped",
        r"removed",
        r"withdrawn",
        r"no\s+longer\s+listed",
    ),
    "parked": (
        r"parked\s+unknown",
        r"parked\s+unknown\s+transitions?",
        r"unknown\s+transitions?",
    ),
}
_SOCIAL_COUNT_LABEL_PATTERN = "|".join(
    f"(?:{label})" for labels in _SOCIAL_COUNT_LABELS.values() for label in labels
)
_SOCIAL_PREFIX_COUNT_RE = re.compile(
    rf"(?P<count>\d[\d,]*)\s+(?P<label>{_SOCIAL_COUNT_LABEL_PATTERN})\b",
    re.IGNORECASE,
)
_SOCIAL_LABEL_COLON_COUNT_RE = re.compile(
    rf"(?P<label>{_SOCIAL_COUNT_LABEL_PATTERN})\s*:\s*(?P<count>\d[\d,]*)\b",
    re.IGNORECASE,
)
_STANDALONE_SOCIAL_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])\d[\d,]*(?![A-Za-z0-9_.-])"
)


@lru_cache
def _load_system_prompt() -> str:
    try:
        prompt = (
            resources.files(_PROMPT_PACKAGE)
            .joinpath(_BLOG_SUMMARY_PROMPT)
            .read_text(encoding="utf-8")
            .strip()
        )
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        return _FALLBACK_SYSTEM_PROMPT
    return prompt or _FALLBACK_SYSTEM_PROMPT


SYSTEM_PROMPT = _load_system_prompt()


@dataclass(frozen=True)
class ChangeContext:
    classification: str
    history_days: int = 0
    available_days: int = 0
    missing_days: int = 0
    unknown_days: int = 0
    unavailable_pct: float = 0.0
    prior_disappearances: int = 0
    last_available_date: str | None = None
    last_missing_date: str | None = None
    region_group: str | None = None
    expansion_kind: str | None = None
    feature_total_regions: int = 0
    feature_previous_available_regions: int = 0
    feature_current_available_regions: int = 0
    feature_previous_coverage_pct: float = 0.0
    feature_current_coverage_pct: float = 0.0
    feature_coverage_delta: int = 0
    feature_deprecated_coverage_pct: float = 0.0
    region_group_previous_available_regions: int = 0
    region_group_current_available_regions: int = 0
    same_day_new_regions: tuple[str, ...] = ()
    still_available_regions: tuple[str, ...] = ()
    details_url: str | None = None
    details_label: str | None = None
    feature_note: str | None = None

    @property
    def label(self) -> str:
        return classification_label(self.classification)


_CLASSIFICATION_LABELS = {
    "net_new_availability": "net-new regional availability",
    "restored_availability": "restored availability",
    "deprecation_candidate": "deprecation candidate",
    "recurring_regression": "recurring disappearance",
    "uncertain_regression": "availability loss with limited history",
    "new_availability_signal": "availability gain without history",
    "regression_signal": "availability loss without history",
}

_CLASSIFICATION_PLURALS = {
    "net_new_availability": "net-new regional availabilities",
    "restored_availability": "restored availabilities",
    "deprecation_candidate": "deprecation candidates",
    "recurring_regression": "recurring disappearances",
    "uncertain_regression": "availability losses with limited history",
    "new_availability_signal": "availability gains without history",
    "regression_signal": "availability losses without history",
}

_CLASSIFICATION_ORDER = (
    "deprecation_candidate",
    "recurring_regression",
    "net_new_availability",
    "restored_availability",
    "uncertain_regression",
    "regression_signal",
    "new_availability_signal",
)

_EXPANSION_LABELS = {
    "new_feature": "first observed anywhere in the monitored regions",
    "regional_expansion": "regional expansion of an existing signal",
    "region_group_first": "first observed in this geography",
    "restored_region": "restored regional signal",
}

_SRE_IMPACT: dict[tuple[str, str], str] = {
    (
        "Azure AI models",
        "new_availability",
    ): "new regional model/version options for latency, residency, and model selection",
    (
        "Azure AI models",
        "regression",
    ): "review model deployment targets and fallback model/version choices",
    (
        "Azure model latency",
        "new_availability",
    ): "new measured deployment paths for latency-aware routing decisions",
    (
        "Azure model latency",
        "regression",
    ): "latency evidence disappeared, so routing assumptions need a fresh check",
    (
        "Model latency",
        "new_availability",
    ): "new benchmark coverage for comparing model speed",
    (
        "Model latency",
        "regression",
    ): "benchmark coverage disappeared, reducing confidence in speed comparisons",
    (
        "AKS extensions",
        "new_availability",
    ): "check the named extension's requirements before adding it to regional cluster plans",
    (
        "AKS extensions",
        "regression",
    ): "extension install plans and regional cluster templates may need adjustment",
    (
        "AKS Kubernetes versions",
        "new_availability",
    ): "new upgrade or patch targets for regional cluster maintenance windows",
    (
        "AKS Kubernetes versions",
        "regression",
    ): "cluster upgrade plans may lose a target version in affected regions",
    (
        "Azure Functions",
        "new_availability",
    ): "more Flex Consumption placement choices for burst scale and lower ops overhead",
    (
        "Azure Functions",
        "regression",
    ): "serverless placement and runtime assumptions need a regional fallback",
    (
        "Container Apps",
        "new_availability",
    ): "new serverless container placement for event-driven scale and microservices",
    (
        "Container Apps",
        "regression",
    ): "regional container app deployment targets may need rerouting",
    (
        "VM SKUs",
        "new_availability",
    ): "more compute shapes for right-sizing, performance, and cost tuning",
    (
        "VM SKUs",
        "regression",
    ): "capacity planning and SKU fallback lists should be rechecked",
}

# Describe observations, not provider intent or workload health.
_INTERPRETATION: dict[tuple[str, str], str] = {
    ("Azure AI models", "new_availability"): "models/versions newly listed",
    ("Azure AI models", "regression"): "models/versions no longer listed (not confirmed retirement)",
    ("Azure model latency", "new_availability"): "started measuring new model/region deployments",
    ("Azure model latency", "regression"): "measurement coverage no longer present",
    ("Model latency", "new_availability"): "new models added to the speed board",
    ("Model latency", "regression"): "models dropped from the speed board",
    ("AKS extensions", "new_availability"): "extension types now listed",
    ("AKS extensions", "regression"): "extension types stopped listing",
    ("AKS Kubernetes versions", "new_availability"): "Kubernetes versions now offered",
    ("AKS Kubernetes versions", "regression"): "Kubernetes versions withdrawn",
    ("Azure Functions", "new_availability"): "Functions hosting/runtimes now listed",
    ("Azure Functions", "regression"): "Functions hosting/runtimes stopped listing",
    ("Container Apps", "new_availability"): "Container Apps now advertised",
    ("Container Apps", "regression"): "Container Apps stopped advertising",
    ("VM SKUs", "new_availability"): "VM sizes now offered",
    ("VM SKUs", "regression"): "VM sizes withdrawn",
}


def _interpretation(modality: str, change_type: str) -> str:
    default = "newly available" if change_type == "new_availability" else "stopped listing"
    return _INTERPRETATION.get((modality, change_type), default)


def classification_label(classification: str) -> str:
    return _CLASSIFICATION_LABELS.get(classification, classification.replace("_", " "))


def expansion_label(expansion_kind: str | None, region_group: str | None = None) -> str:
    if expansion_kind == "region_group_first" and region_group:
        return f"first observed in {region_group}"
    if expansion_kind is None:
        return ""
    return _EXPANSION_LABELS.get(expansion_kind, expansion_kind.replace("_", " "))


def feature_details(feature: str) -> tuple[str | None, str | None, str | None]:
    context = describe_feature(feature)
    source = context["sources"][0] if context["sources"] else {}
    note = " ".join([context["summary"], *context["differentiators"], context["limitations"]])
    return context["title"], source.get("url"), note


def change_key(change: Change) -> ChangeKey:
    return (change.region, change.service, change.feature)


class NarrativeClient(Protocol):
    def generate(self, *, system: str, user: str) -> str:
        """Return a short natural-language summary or raise on failure."""


def build_change_narrative(
    changes: list[Change], *, client: NarrativeClient | None = None,
    contexts: Mapping[ChangeKey, ChangeContext] | None = None,
    date: str | None = None,
) -> dict[str, Any]:
    """Build a human-readable change narrative with a deterministic fallback.

    Returns a dict with the editorial package, source, fallback reason, and model deployment.
    The AI path is only attempted when a client is provided and there are clear
    signals; any failure falls back to the rule-based summary. This function
    never raises.
    """

    signals = _clear_signal_changes(changes)
    context_map = contexts or {}
    rule = _rule_summary(changes, signals, context_map)
    fallback_package = _rule_editorial_package(rule, changes, date)

    deployment = _client_deployment(client)
    if client is None:
        return _rule_result(fallback_package, "no_narrative_client", deployment)
    if not signals:
        return _rule_result(fallback_package, "no_clear_signals", deployment)

    try:
        user = _facts_block(changes, signals, context_map, date)
        text = client.generate(system=SYSTEM_PROMPT, user=user).strip()
    except Exception as error:
        return _rule_result(
            fallback_package,
            "generation_failed",
            deployment,
            metadata=_client_generation_metadata(client),
            generation_error=_generation_error(error),
        )

    package, rejection_reason = _parse_editorial_package(text, changes, date)
    if package is None:
        return _rule_result(
            fallback_package,
            f"unsupported_generation:{rejection_reason or 'unknown'}",
            deployment,
            _client_generation_metadata(client),
        )
    result: dict[str, Any] = {
        **package,
        "narrative_source": "ai",
        "narrative_fallback_reason": None,
        "narrative_model_deployment": deployment,
    }
    result.update(_client_generation_metadata(client))
    return result


def _rule_result(
    package: Mapping[str, Any],
    reason: str,
    deployment: str | None,
    metadata: Mapping[str, object] | None = None,
    generation_error: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        **package,
        "narrative_source": "rule",
        "narrative_fallback_reason": reason,
        "narrative_model_deployment": deployment,
        "narrative_generation_error": generation_error,
    }
    if metadata:
        result.update(metadata)
    return result


def _client_deployment(client: NarrativeClient | None) -> str | None:
    deployment = getattr(client, "deployment", None)
    return deployment if isinstance(deployment, str) and deployment else None


def _client_generation_metadata(client: NarrativeClient) -> dict[str, object]:
    metadata = getattr(client, "generation_metadata", {})
    if not isinstance(metadata, Mapping):
        return {}
    return {
        key: value
        for key, value in metadata.items()
        if key
        in {
            "narrative_mcp_status",
            "narrative_mcp_error",
            "narrative_grounding_status",
            "narrative_microsoft_learn_urls",
        }
    }


def _generation_error(error: Exception) -> str:
    detail = str(error).replace("\n", " ").strip()
    return f"{type(error).__name__}: {detail}"[:300]


def _is_supported_narrative(text: str) -> bool:
    return _narrative_rejection_reason(text) is None


def _narrative_rejection_reason(text: str) -> str | None:
    lowered = text.lower()
    if len(text.split()) > 350:
        return "narrative_too_long"
    if any(claim in lowered for claim in _UNSUPPORTED_CLAIMS):
        return "narrative_unsupported_claim"
    return None


def _parse_editorial_package(
    text: str, changes: list[Change], date: str | None
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None, "invalid_json"
    if not isinstance(payload, dict) or set(payload) != {"narrative", "excerpt", "linkedin", "short_post"}:
        return None, "invalid_schema"
    if not all(isinstance(value, str) and value.strip() for value in payload.values()):
        return None, "empty_field"
    narrative = payload["narrative"].strip()
    excerpt = payload["excerpt"].strip()
    rejection_reason = _narrative_rejection_reason(narrative)
    if rejection_reason is not None:
        return None, rejection_reason
    if len(excerpt) > 220:
        return None, "excerpt_too_long"
    if _has_unsupported_claim(excerpt):
        return None, "excerpt_unsupported_claim"
    social_rejection = _social_package_rejection_reason(payload, changes, date)
    if social_rejection is not None:
        return None, social_rejection
    return {
        "narrative": narrative,
        "editorial_excerpt": excerpt,
        "social_drafts": {
            "linkedin": payload["linkedin"].strip(),
            "short_post": payload["short_post"].strip(),
        },
    }, None


def _has_unsupported_claim(text: str) -> bool:
    return any(claim in text.lower() for claim in _UNSUPPORTED_CLAIMS)


def _is_supported_social_package(payload: Mapping[str, Any], changes: list[Change], date: str) -> bool:
    return _social_package_rejection_reason(payload, changes, date) is None


def _social_package_rejection_reason(
    payload: Mapping[str, Any], changes: list[Change], date: str | None
) -> str | None:
    for field in ("linkedin", "short_post"):
        text = payload[field]
        if not isinstance(text, str):
            return f"social_{field}_invalid"
        lowered = text.lower()
        if date is not None and date.lower() not in lowered:
            return f"social_{field}_missing_date"
        if "http://" in lowered or "https://" in lowered:
            return f"social_{field}_url"
        if _has_unsupported_claim(text):
            return f"social_{field}_unsupported_claim"
        count_rejection = _unsupported_social_count_reason(text, changes, date, field)
        if count_rejection is not None:
            return count_rejection
    return None


def _unsupported_social_count_reason(
    text: str, changes: list[Change], date: str | None, field: str
) -> str | None:
    expected = {
        "new": sum(change.change_type == "new_availability" for change in changes),
        "regression": sum(change.change_type == "regression" for change in changes),
        "parked": _parked_unknown_count(changes),
    }
    observed: set[str] = set()
    for match in _social_count_matches(text):
        key = _social_count_key(match["label"])
        count = _social_count(match["count"])
        observed.add(key)
        if count != expected[key]:
            return f"social_{field}_unsupported_{key}_count"
    for key in ("new", "regression"):
        if expected[key] > 0 and key not in observed:
            return f"social_{field}_missing_{key}_count"
    allowed_numbers = _supported_social_numbers(changes, expected, date)
    for match in _STANDALONE_SOCIAL_NUMBER_RE.finditer(text):
        if _social_count(match.group()) not in allowed_numbers:
            return f"social_{field}_unsupported_number"
    return None


def _social_count_matches(text: str) -> list[dict[str, str]]:
    matches = [
        {"label": match.group("label"), "count": match.group("count"), "start": str(match.start())}
        for match in _SOCIAL_PREFIX_COUNT_RE.finditer(text)
    ]
    matches.extend(
        {"label": match.group("label"), "count": match.group("count"), "start": str(match.start())}
        for match in _SOCIAL_LABEL_COLON_COUNT_RE.finditer(text)
    )
    return sorted(matches, key=lambda item: int(item["start"]))


def _social_count_key(label: str) -> str:
    normalized = " ".join(label.lower().split())
    for key, patterns in _SOCIAL_COUNT_LABELS.items():
        for pattern in patterns:
            if re.fullmatch(pattern, normalized, re.IGNORECASE):
                return key
    raise ValueError(f"unsupported social count label: {label}")


def _social_count(text: str) -> int:
    return int(text.replace(",", ""))


def _supported_social_numbers(
    changes: list[Change], expected: Mapping[str, int], date: str | None
) -> set[int]:
    allowed = set(expected.values())
    allowed.update(_date_numbers(date))
    allowed.update(
        {
            len(changes),
            len(_clear_signal_changes(changes)),
            len({change.region for change in changes}),
            len({change.feature for change in changes}),
            len({(change.service, change.feature) for change in changes}),
            len({change.service for change in changes}),
        }
    )
    grouped_counters: list[Counter[object]] = [
        Counter(change.change_type for change in changes),
        Counter(_modality(change.feature) for change in changes),
        Counter((change.change_type, _modality(change.feature)) for change in changes),
        Counter(change.region for change in changes),
        Counter(change.feature for change in changes),
        Counter(_vm_social_family_key(change.feature) for change in changes if _modality(change.feature) == "VM SKUs"),
    ]
    for counter in grouped_counters:
        allowed.update(counter.values())
    return allowed


def _date_numbers(date: str | None) -> set[int]:
    if not date:
        return set()
    numbers = {int(part) for part in re.findall(r"\d+", date)}
    compact = "".join(re.findall(r"\d+", date))
    if compact:
        numbers.add(int(compact))
    return numbers


def _vm_social_family_key(feature: str) -> str:
    context = describe_feature(feature)
    family_key = context.get("family_key")
    return family_key if isinstance(family_key, str) and family_key else feature


def _rule_editorial_package(
    narrative: str, changes: list[Change], date: str | None
) -> dict[str, Any]:
    new_availability = sum(change.change_type == "new_availability" for change in changes)
    regressions = sum(change.change_type == "regression" for change in changes)
    parked_unknown = _parked_unknown_count(changes)
    daily_counts = (
        f"{new_availability:,} new availability signals, {regressions:,} regressions, and "
        f"{parked_unknown:,} parked unknown transitions"
    )
    label = date or "Latest scan"
    lines = [line.strip() for line in narrative.splitlines() if line.strip()]
    excerpt = (lines[1] if len(lines) > 1 else lines[0]).strip()
    expansion = _rule_expansion_teaser(changes)
    if expansion:
        excerpt = expansion
    if len(excerpt) > 219:
        excerpt = excerpt[:216].rstrip() + "..."
    social = f"{label}: {daily_counts}. {excerpt} {_SOCIAL_EVIDENCE_NOTE}"
    return {
        "narrative": narrative,
        "editorial_excerpt": excerpt,
        "social_drafts": {"linkedin": social, "short_post": f"{label}: {daily_counts}. {_SOCIAL_EVIDENCE_NOTE}"},
    }


def _rule_expansion_teaser(changes: list[Change]) -> str:
    regions_by_feature: dict[str, set[str]] = {}
    for change in changes:
        if (
            change.change_type == "new_availability"
            and _modality(change.feature) in {"AKS extensions", "VM SKUs", "Azure AI models"}
        ):
            regions_by_feature.setdefault(change.feature, set()).add(change.region)
    candidates = [
        (len(regions), feature)
        for feature, regions in regions_by_feature.items()
        if len(regions) > 1
    ]
    if not candidates:
        return ""
    count, feature = max(candidates, key=lambda candidate: (candidate[0], candidate[1]))
    return (
        f"Worth a closer look: {plain_feature_name(feature)} was newly listed in "
        f"{count} more regions (catalog evidence, not deployment results)."
    )


def _parked_unknown_count(changes: list[Change]) -> int:
    return sum(1 for change in changes if "unknown" in {change.previous, change.current})


def _clear_signal_changes(changes: list[Change]) -> list[Change]:
    priority = {"regression": 0, "new_availability": 1}
    signals = [c for c in changes if c.change_type in priority]
    return sorted(
        signals,
        key=lambda c: (priority[c.change_type], c.region, _modality(c.feature), c.feature),
    )


def _rule_summary(
    changes: list[Change],
    signals: list[Change],
    context_map: Mapping[ChangeKey, ChangeContext],
) -> str:
    if not signals:
        return "No new availability or regression signals in the latest scan."

    new_avail = [c for c in signals if c.change_type == "new_availability"]
    regressions = [c for c in signals if c.change_type == "regression"]

    headline = f"{len(new_avail)} new {_plural(len(new_avail), 'listing')}, {len(regressions)} no longer listed"
    bullets: list[str] = []
    if regressions:
        bullets.extend(_compact_change_lines(regressions, "regression", context_map))
    if new_avail:
        bullets.extend(_compact_change_lines(new_avail, "new_availability", context_map))

    conclusion = (
        "What this means for Azure users: recheck existing targets first, then treat new listings "
        "as placement options to validate; catalog evidence is not quota or capacity proof."
        if regressions
        else "What this means for Azure users: treat new listings as placement options to validate; "
        "catalog evidence is not quota or capacity proof."
    )
    return "\n".join([headline, *bullets[:5], conclusion])


def _plain_language_overview(new_avail: list[Change], regressions: list[Change]) -> str:
    """Describe the overall movement before the modality-specific technical detail."""

    if new_avail and regressions:
        movement = (
            f"the monitor now has {len(new_avail)} newly listed "
            f"{_plural(len(new_avail), 'option')} and no longer has {len(regressions)} "
            f"previously listed {_plural(len(regressions), 'option')}"
        )
    elif new_avail:
        movement = (
            f"the monitor now has {len(new_avail)} newly listed "
            f"{_plural(len(new_avail), 'option')}"
        )
    else:
        movement = (
            f"the monitor no longer has {len(regressions)} previously listed "
            f"{_plural(len(regressions), 'option')}"
        )
    return (
        "In everyday terms, "
        + movement
        + " across the regions it observed. These catalog changes can affect where "
        "teams plan workloads or select services."
    )


def _opinionated_sentences(
    changes: list[Change],
    change_type: str,
    context_map: Mapping[ChangeKey, ChangeContext],
) -> list[str]:
    """One interpretive sentence per modality, grouping that modality's changes."""

    by_modality: dict[str, list[Change]] = {}
    for change in changes:
        by_modality.setdefault(_modality(change.feature), []).append(change)

    sentences: list[str] = []
    for modality in sorted(by_modality):
        group = by_modality[modality]
        breakdown = _classification_breakdown(group, context_map)
        impact = _impact(modality, change_type)
        context = _context_datapoints(group, context_map) if len(group) <= 5 else ""
        context_text = f" {context}" if context else ""
        sentences.append(
            f"{modality}: {_interpretation(modality, change_type)} "
            f"({len(group)} {_plural(len(group), 'signal')}; {breakdown}). "
            f"Example: {_examples(group)}.{context_text} Why it matters: {impact}."
        )
    return sentences


def _compact_change_lines(
    changes: list[Change],
    change_type: str,
    context_map: Mapping[ChangeKey, ChangeContext],
) -> list[str]:
    vm_changes = [change for change in changes if _modality(change.feature) == "VM SKUs"]
    vm_features = {change.feature for change in vm_changes}
    group_vm_sizes = len(vm_features) > 3
    other_changes = [
        change
        for change in changes
        if _modality(change.feature) != "VM SKUs" or not group_vm_sizes
    ]

    lines: list[str] = []
    if vm_changes and group_vm_sizes:
        lines.append(_compact_vm_line(vm_changes, change_type))

    by_feature: dict[tuple[str, str], list[Change]] = {}
    for change in other_changes:
        by_feature.setdefault((_modality(change.feature), change.feature), []).append(change)

    for (_modality_name, _feature), group in sorted(by_feature.items()):
        lines.append(_compact_feature_line(group, change_type, context_map))
    return lines


def _compact_vm_line(changes: list[Change], change_type: str) -> str:
    features = sorted({change.feature for change in changes})
    regions = tuple(sorted({change.region for change in changes}))
    families = _vm_family_summary(features)
    direction = "gained" if change_type == "new_availability" else "are no longer listed in"
    return (
        f"{len(features)} VM {_plural(len(features), 'size')}, mostly {families}, "
        f"{direction} {_region_phrase(regions)}."
    )


def _compact_feature_line(
    changes: list[Change],
    change_type: str,
    context_map: Mapping[ChangeKey, ChangeContext],
) -> str:
    feature = changes[0].feature
    regions = tuple(sorted({change.region for change in changes}))
    contexts = [_context_for(change, context_map) for change in changes]
    coverage = _coverage_shift(contexts)
    expansion = _expansion_summary(contexts)
    description = _feature_description(feature)

    if change_type == "new_availability":
        sentence = (
            f"{description} now listed in {len(regions)} more "
            f"{_plural(len(regions), 'region')} ({_region_phrase(regions)})"
        )
    else:
        sentence = (
            f"{description} no longer listed in {len(regions)} "
            f"{_plural(len(regions), 'region')} ({_region_phrase(regions)})"
        )
    if coverage:
        sentence += f" ({coverage})"
    if expansion:
        sentence += f"; {expansion}"
    return sentence + "."


def _coverage_shift(contexts: list[ChangeContext]) -> str:
    pairs = {
        (context.feature_previous_available_regions, context.feature_current_available_regions)
        for context in contexts
        if context.feature_total_regions > 0
    }
    if len(pairs) != 1:
        return ""
    previous, current = next(iter(pairs))
    return f"{previous} -> {current} monitored regions"


def _expansion_summary(contexts: list[ChangeContext]) -> str:
    labels = sorted(
        {
            expansion_label(context.expansion_kind, context.region_group)
            for context in contexts
            if expansion_label(context.expansion_kind, context.region_group)
        }
    )
    return "; ".join(labels[:2])


def _region_phrase(regions: tuple[str, ...], limit: int = 4) -> str:
    shown = regions[:limit]
    phrase = ", ".join(shown)
    remaining = len(regions) - len(shown)
    if remaining > 0:
        phrase += f", and {remaining} more"
    return phrase


def _vm_family_summary(features: list[str]) -> str:
    family_counts: Counter[str] = Counter()
    family_labels: dict[str, str] = {}
    for feature in features:
        family_key, family_label = _vm_family(feature)
        family_counts[family_key] += 1
        family_labels.setdefault(family_key, family_label)
    parts = [
        f"{family_labels[key]} ({family_counts[key]} {_plural(family_counts[key], 'size')})"
        for key in family_counts
    ]
    if len(parts) <= 1:
        return parts[0] if parts else "VM sizes"
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:2]) + f", and {len(parts) - 2} more families"


def _vm_family(feature: str) -> tuple[str, str]:
    context = describe_feature(feature)
    family_key = context.get("family_key")
    family_label = context.get("family_label")
    if isinstance(family_key, str) and family_key and isinstance(family_label, str) and family_label:
        return family_key, family_label.split(" · ", 1)[0]
    fallback = _feature_label(feature).split(".", 1)[0].upper()
    return feature, fallback


def _context_datapoints(
    changes: list[Change],
    context_map: Mapping[ChangeKey, ChangeContext],
) -> str:
    contexts = [_context_for(change, context_map) for change in changes]
    max_unavailable = max((context.unavailable_pct for context in contexts), default=0.0)
    coverage_counts = [
        context.feature_current_available_regions
        for context in contexts
        if context.feature_total_regions > 0
    ]
    coverage_total = next((context.feature_total_regions for context in contexts if context.feature_total_regions), 0)
    expansion_labels = sorted(
        {
            expansion_label(context.expansion_kind, context.region_group)
            for context in contexts
            if expansion_label(context.expansion_kind, context.region_group)
        }
    )

    parts: list[str] = []
    if coverage_counts and coverage_total:
        low, high = min(coverage_counts), max(coverage_counts)
        coverage = str(low) if low == high else f"{low} to {high}"
        parts.append(f"Current listing coverage: {coverage} of {coverage_total} monitored regions.")
    if max_unavailable > 0:
        parts.append(
            f"Historical listing absence reached {_format_pct(max_unavailable)} of prior observations; "
            "absence before a first listing is not service instability."
        )
    if expansion_labels:
        parts.append(f"Expansion pattern: {'; '.join(expansion_labels)}.")
    return " ".join(parts)


def _classification_breakdown(
    changes: list[Change],
    context_map: Mapping[ChangeKey, ChangeContext],
) -> str:
    counts: dict[str, int] = {}
    max_prior_disappearances = 0
    for change in changes:
        context = _context_for(change, context_map)
        counts[context.classification] = counts.get(context.classification, 0) + 1
        max_prior_disappearances = max(max_prior_disappearances, context.prior_disappearances)

    ordered = [classification for classification in _CLASSIFICATION_ORDER if classification in counts]
    ordered.extend(sorted(set(counts) - set(ordered)))
    parts = [_counted_classification(counts[classification], classification) for classification in ordered]
    if max_prior_disappearances > 0:
        parts.append(
            f"up to {max_prior_disappearances} prior "
            f"{_plural(max_prior_disappearances, 'disappearance')}"
        )
    return ", ".join(parts)


def _counted_classification(count: int, classification: str) -> str:
    if count == 1:
        return f"1 {classification_label(classification)}"
    label = _CLASSIFICATION_PLURALS.get(classification, f"{classification_label(classification)} signals")
    return f"{count} {label}"


def _examples(changes: list[Change]) -> str:
    shown = changes[:MAX_EXAMPLES]
    rendered = "; ".join(f"{c.region} · {_feature_description(c.feature)}" for c in shown)
    remaining = len(changes) - len(shown)
    if remaining > 0:
        rendered += f"; and {remaining} more"
    return rendered


def _facts_block(
    changes: list[Change],
    signals: list[Change],
    context_map: Mapping[ChangeKey, ChangeContext],
    date: str | None,
) -> str:
    lines = [
        "Daily editorial facts (do not invent anything beyond these):",
        f"date={date or 'not supplied'} | "
        f"new_availability={sum(change.change_type == 'new_availability' for change in changes)} | "
        f"regressions={sum(change.change_type == 'regression' for change in changes)} | "
        f"parked_unknown={_parked_unknown_count(changes)}",
    ]
    groups: dict[tuple[str, str], list[Change]] = {}
    for change in signals:
        groups.setdefault((change.change_type, _modality(change.feature)), []).append(change)
    lines.append("Complete grouped totals (a listing is one feature in one region, not a unique product):")
    for (direction, modality), group in sorted(groups.items()):
        lines.append(
            f"- {direction} | modality={modality} | listings={len(group)} | "
            f"distinct_features={len({(item.service, item.feature) for item in group})} | "
            f"regions={_csv(tuple(sorted({item.region for item in group})))}"
        )
    lines.append("Individual examples follow; their ordering is not a measure of significance:")
    for change in signals[:MAX_FACTS]:
        context = _context_for(change, context_map)
        modality = _modality(change.feature)
        lines.append(
            f"- {change.change_type} | region={change.region} | "
            f"modality={modality} | feature={change.feature} | "
            f"transition={change.previous or 'absent'}->{change.current or 'absent'} | "
            f"classification={context.classification} ({context.label}) | "
            f"prior_disappearances={context.prior_disappearances} | "
            f"history_days={context.history_days} | available_days={context.available_days} | "
            f"missing_days={context.missing_days} | unknown_days={context.unknown_days} | "
            f"unavailable_pct={_format_pct(context.unavailable_pct)} | "
            f"last_available={context.last_available_date or 'never'} | "
            f"last_missing={context.last_missing_date or 'never'} | "
            f"region_group={context.region_group or 'unknown'} | "
            f"expansion={expansion_label(context.expansion_kind, context.region_group) or 'none'} | "
            f"feature_coverage={context.feature_current_available_regions}/{context.feature_total_regions} "
            f"({_format_pct(context.feature_current_coverage_pct)}) | "
            f"previous_feature_coverage={context.feature_previous_available_regions}/{context.feature_total_regions} "
            f"({_format_pct(context.feature_previous_coverage_pct)}) | "
            f"coverage_delta={context.feature_coverage_delta:+d} regions | "
            f"deprecated_coverage={_format_pct(context.feature_deprecated_coverage_pct)} | "
            f"region_group_coverage={context.region_group_current_available_regions} current, "
            f"{context.region_group_previous_available_regions} previous | "
            f"same_day_new_regions={_csv(context.same_day_new_regions) or 'none'} | "
            f"still_available_regions={_csv(context.still_available_regions) or 'none'} | "
            f"details_url={context.details_url or 'none'} | "
            f"feature_note={context.feature_note or 'none'} | "
            f"sre_impact={_impact(modality, change.change_type)}"
        )
    remaining = len(signals) - MAX_FACTS
    if remaining > 0:
        lines.append(f"- ({remaining} additional records not shown; use the complete grouped totals above)")
    return "\n".join(lines)


def _plural(count: int, word: str) -> str:
    return word if count == 1 else f"{word}s"


def _format_pct(value: float) -> str:
    return f"{value:.1f}%"


def _csv(values: tuple[str, ...]) -> str:
    return ", ".join(values)


def _context_for(
    change: Change,
    context_map: Mapping[ChangeKey, ChangeContext],
) -> ChangeContext:
    return context_map.get(change_key(change)) or _default_context(change)


def _default_context(change: Change) -> ChangeContext:
    if change.change_type == "new_availability":
        return ChangeContext(classification="new_availability_signal")
    if change.change_type == "regression":
        return ChangeContext(classification="regression_signal")
    return ChangeContext(classification="status_change")


def _impact(modality: str, change_type: str) -> str:
    if (modality, change_type) in _SRE_IMPACT:
        return _SRE_IMPACT[(modality, change_type)]
    if change_type == "new_availability":
        return "new regional placement or feature options to evaluate"
    return "regional placement and fallback assumptions should be rechecked"


def _modality(feature: str) -> str:
    if feature == "extensionCatalog" or feature.startswith(("extensions.", "extensionTypes.")):
        return "AKS extensions"
    if feature.startswith("kubernetesVersions."):
        return "AKS Kubernetes versions"
    if feature.startswith(("hostingPlans.", "runtimes.")):
        return "Azure Functions"
    if feature.startswith("aiModels."):
        return "Azure AI models"
    if feature.startswith("modelLatency."):
        return "Model latency"
    if feature.startswith("aiLatency."):
        return "Azure model latency"
    if feature.startswith("containerApps."):
        return "Container Apps"
    if feature == "vmSkuCatalog" or feature.startswith("vmSkus."):
        return "VM SKUs"
    return feature.split(".", 1)[0]


def _feature_label(feature: str) -> str:
    for prefix in (
        "aiModels.",
        "aiLatency.",
        "modelLatency.",
        "extensionTypes.",
        "runtimes.",
        "vmSkus.",
    ):
        if feature.startswith(prefix):
            feature = feature.removeprefix(prefix)
            break
    feature = feature.removeprefix("standard.")
    return feature


def _feature_description(feature: str) -> str:
    label = _feature_label(feature)
    modality = _modality(feature)
    descriptions = {
        "VM SKUs": "Azure virtual-machine size for right-sizing compute",
        "Azure AI models": "Azure AI model/version catalog entry for model selection",
        "AKS Kubernetes versions": "AKS Kubernetes version for upgrade planning",
        "AKS extensions": "AKS cluster extension type for managed cluster capabilities",
        "Azure Functions": "Azure Functions Flex Consumption runtime or hosting option",
        "Container Apps": "Azure Container Apps provider capability for serverless container planning",
    }
    return f"{descriptions.get(modality, modality)} ({label})"
