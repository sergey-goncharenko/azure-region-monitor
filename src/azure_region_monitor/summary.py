from __future__ import annotations

from typing import Protocol

from azure_region_monitor.models import Change

MAX_FACTS = 40
MAX_EXAMPLES = 4
SYSTEM_PROMPT = (
    "You write a short daily change digest for an Azure regional availability monitor. "
    "Summarize ONLY the structured change facts provided into 1 to 3 short, factual sentences. "
    "Do not invent regions, models, features, or numbers that are not in the facts. "
    "Prefer plain language such as 'newly lists', 'stopped listing', or 'region added'. "
    "Do not add caveats, disclaimers, or a preamble."
)


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
    if new_avail:
        parts.append("New availability — " + _examples(new_avail) + ".")
    if regressions:
        parts.append("Regressions — " + _examples(regressions) + ".")
    return " ".join(parts)


def _examples(changes: list[Change]) -> str:
    shown = changes[:MAX_EXAMPLES]
    rendered = "; ".join(
        f"{c.region} · {_feature_label(c.feature)} ({_modality(c.feature)})" for c in shown
    )
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
    for prefix in ("aiModels.", "modelLatency.", "extensionTypes.", "runtimes.", "vmSkus."):
        if feature.startswith(prefix):
            feature = feature.removeprefix(prefix)
            break
    feature = feature.removeprefix("standard.")
    return feature
