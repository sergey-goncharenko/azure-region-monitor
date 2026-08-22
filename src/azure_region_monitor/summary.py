from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any, Mapping, Protocol

from azure_region_monitor.models import Change

ChangeKey = tuple[str, str, str]
MAX_FACTS = 40
MAX_EXAMPLES = 4
_PROMPT_PACKAGE = "azure_region_monitor.prompts"
_BLOG_SUMMARY_PROMPT = "blog_summary.md"
_FALLBACK_SYSTEM_PROMPT = """You are the editor of a daily change digest for an Azure regional availability monitor.
Write a short, SRE-oriented mini blog post using only the structured facts provided.

Format:
- First line: a punchy headline, no markdown, no '#'.
- Then 4 to 6 short paragraphs, separated by blank lines.

Interpret the change classifications: net-new availability means a feature has never been
seen available in that region before; restored availability means it was available before,
then disappeared, and is now back; deprecation candidate means a stable availability signal
has disappeared for the first time; recurring disappearance means it has gone missing before.
Explain the practical impact for SREs in simple language, such as placement choice, capacity,
cost, scale, latency, upgrade paths, or feature enablement. Do not leave a raw SKU, model ID,
version, or feature code unexplained; translate it into a practical capability only when the
facts support that interpretation. End with a short final paragraph beginning "What this means
for Azure users:" that states the practical decision or planning impact. Keep every claim
grounded in the facts.

Rules: do not invent regions, models, features, dates, numbers, causes, quotas, or SLAs.
Do not add disclaimers, caveats, sign-offs, or a call to action. Keep it under ~350 words.
"""


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

_DETAILS_BY_MODALITY: dict[str, tuple[str, str, str]] = {
    "Azure AI models": (
        "Azure OpenAI model availability",
        "https://learn.microsoft.com/azure/ai-foundry/openai/concepts/models",
        "Use this to evaluate model capabilities, regional deployment options, latency, and data residency.",
    ),
    "AKS extensions": (
        "AKS cluster extensions",
        "https://learn.microsoft.com/azure/aks/cluster-extensions",
        "Cluster extensions provide Azure Resource Manager-driven installation and lifecycle management for AKS capabilities.",
    ),
    "AKS Kubernetes versions": (
        "AKS supported Kubernetes versions",
        "https://learn.microsoft.com/azure/aks/supported-kubernetes-versions",
        "Version availability affects upgrade targets, support windows, and regional rollout planning.",
    ),
    "Azure Functions": (
        "Azure Functions Flex Consumption plan",
        "https://learn.microsoft.com/azure/azure-functions/flex-consumption-plan",
        "Flex Consumption adds serverless scale with private networking, memory sizing, and fast scale-out options.",
    ),
    "Container Apps": (
        "Azure Container Apps overview",
        "https://learn.microsoft.com/azure/container-apps/overview",
        "Container Apps provides managed serverless containers with autoscale, ingress, revisions, jobs, and Dapr support.",
    ),
    "VM SKUs": (
        "Azure VM sizes",
        "https://learn.microsoft.com/azure/virtual-machines/sizes/overview",
        "VM size availability affects right-sizing, performance, cost, and capacity fallback choices.",
    ),
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
    ): "new managed cluster capabilities such as GitOps, policy, or observability",
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

# Opinionated phrasing per (modality, change direction). Grounded in what the change
# type actually proves: absent->available is a rollout; available->unavailable is a delisting.
_INTERPRETATION: dict[tuple[str, str], str] = {
    ("Azure AI models", "new_availability"): "newer models/versions rolling out",
    ("Azure AI models", "regression"): "models/versions delisted (likely deprecation)",
    ("Azure model latency", "new_availability"): "started measuring new model/region deployments",
    ("Azure model latency", "regression"): "stopped measuring (deployment gone)",
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
    # Imported here because history imports this module; a module-level import cycles.
    from azure_region_monitor.history import _feature_category

    return _DETAILS_BY_MODALITY.get(_feature_category(feature), (None, None, None))


def change_key(change: Change) -> ChangeKey:
    return (change.region, change.service, change.feature)


class NarrativeClient(Protocol):
    def generate(self, *, system: str, user: str) -> str:
        """Return a short natural-language summary or raise on failure."""


def build_change_narrative(
    changes: list[Change], *, client: NarrativeClient | None = None,
    contexts: Mapping[ChangeKey, ChangeContext] | None = None,
) -> dict[str, str | None]:
    """Build a human-readable change narrative with a deterministic fallback.

    Returns a dict with the narrative, source, fallback reason, and model deployment.
    The AI path is only attempted when a client is provided and there are clear
    signals; any failure falls back to the rule-based summary. This function
    never raises.
    """

    signals = _clear_signal_changes(changes)
    context_map = contexts or {}
    rule = _rule_summary(changes, signals, context_map)

    deployment = _client_deployment(client)
    if client is None:
        return _rule_result(rule, "no_narrative_client", deployment)
    if not signals:
        return _rule_result(rule, "no_clear_signals", deployment)

    try:
        user = _facts_block(signals, context_map)
        text = client.generate(system=SYSTEM_PROMPT, user=user).strip()
    except Exception as error:
        return _rule_result(
            rule,
            "generation_failed",
            deployment,
            metadata=_client_generation_metadata(client),
            generation_error=_generation_error(error),
        )

    if not text:
        return _rule_result(rule, "empty_generation", deployment, _client_generation_metadata(client))
    if not _is_supported_narrative(text):
        return _rule_result(
            rule, "unsupported_generation", deployment, _client_generation_metadata(client)
        )
    result: dict[str, Any] = {
        "narrative": text,
        "narrative_source": "ai",
        "narrative_fallback_reason": None,
        "narrative_model_deployment": deployment,
    }
    result.update(_client_generation_metadata(client))
    return result


def _rule_result(
    narrative: str,
    reason: str,
    deployment: str | None,
    metadata: Mapping[str, object] | None = None,
    generation_error: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "narrative": narrative,
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
    lowered = text.lower()
    unsupported_claims = (
        "quota",
        "sla",
        "deployment succeeded",
        "successful deployment",
        "capacity is available",
        "available capacity",
    )
    return len(text.split()) <= 350 and not any(claim in lowered for claim in unsupported_claims)


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
    regions = {c.region for c in signals}

    parts = [
        f"Latest scan: {len(new_avail)} new availability "
        f"{_plural(len(new_avail), 'signal')} and {len(regressions)} "
        f"{_plural(len(regressions), 'regression')} across {len(regions)} "
        f"{_plural(len(regions), 'region')}."
    ]
    # Regressions first: a delisting/deprecation is the more consequential signal.
    parts.extend(_opinionated_sentences(regressions, "regression", context_map))
    parts.extend(_opinionated_sentences(new_avail, "new_availability", context_map))
    parts.append(
        "What this means for Azure users: review placement and fallback plans using these "
        "catalog/list signals before changing production deployments."
    )
    return " ".join(parts)


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
        datapoints = _context_datapoints(group, context_map)
        sentences.append(
            f"{modality}: {_interpretation(modality, change_type)} "
            f"({len(group)} {_plural(len(group), 'signal')}; {breakdown}). "
            f"SRE impact: {impact}. {datapoints} Examples: {_examples(group)}."
        )
    return sentences


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
        parts.append(
            f"Coverage now ranges from {min(coverage_counts)} to {max(coverage_counts)} "
            f"of {coverage_total} monitored regions."
        )
    if max_unavailable > 0:
        parts.append(f"The noisiest affected signal was unavailable {_format_pct(max_unavailable)} of prior observations.")
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
    signals: list[Change],
    context_map: Mapping[ChangeKey, ChangeContext],
) -> str:
    lines = ["Change facts (do not invent anything beyond these):"]
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
        lines.append(f"- (and {remaining} more similar changes)")
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
        "VM SKUs": "Azure virtual-machine size",
        "Azure AI models": "Azure AI model",
        "AKS Kubernetes versions": "AKS Kubernetes upgrade version",
        "AKS extensions": "AKS cluster extension",
        "Azure Functions": "Azure Functions runtime or hosting option",
        "Container Apps": "Azure Container Apps capability",
    }
    return f"{descriptions.get(modality, modality)} ({label})"
