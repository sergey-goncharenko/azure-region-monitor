from __future__ import annotations

from typing import Protocol

from azure_region_monitor.models import Change

MAX_FACTS = 40
MAX_EXAMPLES = 4
SYSTEM_PROMPT = (
    "You are the editor of a daily change digest for an Azure regional availability "
    "monitor. Write a short, opinionated mini blog-post about ONLY the structured "
    "change facts provided.\n\n"
    "Format:\n"
    "- First line: a punchy headline (no more than ~10 words, no markdown, no '#').\n"
    "- Then 2 to 3 short paragraphs, separated by a blank line.\n\n"
    "Voice: confident and interpretive, like a sharp infrastructure newsletter — but "
    "every claim must be grounded in the facts. Read the signals and say what they "
    "mean: absent/unavailable -> available is a rollout or new deployment (for AI "
    "models, a newer model or version rolling out); available -> unavailable is a "
    "delisting (for AI models, a likely deprecation or retirement); for the latency "
    "modalities, additions mean the monitor started measuring and removals mean it "
    "stopped. Call out the region(s) and modality that saw the most movement, and note "
    "any regressions explicitly because they matter most.\n\n"
    "Rules: Do not invent regions, models, features, or numbers that are not in the "
    "facts. Do not add disclaimers, caveats, sign-offs, or a call to action. Keep the "
    "whole thing under ~130 words."
)

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


class NarrativeClient(Protocol):
    def generate(self, *, system: str, user: str) -> str:
        """Return a short natural-language summary or raise on failure."""


def build_change_narrative(
    changes: list[Change], *, client: NarrativeClient | None = None
) -> dict[str, str]:
    """Build a human-readable change narrative with a deterministic fallback.

    Returns a dict with 'narrative' and 'narrative_source' ('ai' or 'rule').
    The AI path is only attempted when a client is provided and there are clear
    signals; any failure falls back to the rule-based summary. This function
    never raises.
    """

    signals = _clear_signal_changes(changes)
    rule = _rule_summary(changes, signals)

    if client is None or not signals:
        return {"narrative": rule, "narrative_source": "rule"}

    try:
        user = _facts_block(signals)
        text = client.generate(system=SYSTEM_PROMPT, user=user).strip()
    except Exception:
        return {"narrative": rule, "narrative_source": "rule"}

    if not text:
        return {"narrative": rule, "narrative_source": "rule"}
    return {"narrative": text, "narrative_source": "ai"}


def _clear_signal_changes(changes: list[Change]) -> list[Change]:
    priority = {"regression": 0, "new_availability": 1}
    signals = [c for c in changes if c.change_type in priority]
    return sorted(
        signals,
        key=lambda c: (priority[c.change_type], c.region, _modality(c.feature), c.feature),
    )


def _rule_summary(changes: list[Change], signals: list[Change]) -> str:
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
    parts.extend(_opinionated_sentences(regressions, "regression"))
    parts.extend(_opinionated_sentences(new_avail, "new_availability"))
    return " ".join(parts)


def _opinionated_sentences(changes: list[Change], change_type: str) -> list[str]:
    """One interpretive sentence per modality, grouping that modality's changes."""

    by_modality: dict[str, list[Change]] = {}
    for change in changes:
        by_modality.setdefault(_modality(change.feature), []).append(change)

    sentences: list[str] = []
    for modality in sorted(by_modality):
        group = by_modality[modality]
        sentences.append(
            f"{modality}: {_interpretation(modality, change_type)} "
            f"({len(group)} {_plural(len(group), 'signal')}) — {_examples(group)}."
        )
    return sentences


def _examples(changes: list[Change]) -> str:
    shown = changes[:MAX_EXAMPLES]
    rendered = "; ".join(f"{c.region} · {_feature_label(c.feature)}" for c in shown)
    remaining = len(changes) - len(shown)
    if remaining > 0:
        rendered += f"; and {remaining} more"
    return rendered


def _facts_block(signals: list[Change]) -> str:
    lines = ["Change facts (do not invent anything beyond these):"]
    for change in signals[:MAX_FACTS]:
        lines.append(
            f"- {change.change_type} | region={change.region} | "
            f"modality={_modality(change.feature)} | feature={change.feature} | "
            f"{change.previous or 'absent'}->{change.current or 'absent'}"
        )
    remaining = len(signals) - MAX_FACTS
    if remaining > 0:
        lines.append(f"- (and {remaining} more similar changes)")
    return "\n".join(lines)


def _plural(count: int, word: str) -> str:
    return word if count == 1 else f"{word}s"


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
