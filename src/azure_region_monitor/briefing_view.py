"""One evidence-backed briefing shared by the dashboard and daily posts."""

from __future__ import annotations

import html
import json
from typing import Any
from urllib.parse import urlsplit

from azure_region_monitor.display import plain_feature_name, region_name

KIND_LABELS = {
    "delistings": "New delistings",
    "observation_gaps": "Evidence gaps",
    "continuing_absences": "Tracked absences",
    "restorations": "Known restorations",
    "new_listings": "New listings",
    "observation_recoveries": "Observations recovered",
    "scope_changes": "Monitoring scope changes",
    "other_changes": "Other status changes",
}
_FEATURE_UNITS = {
    "VM SKUs": ("VM size", "VM sizes"),
    "AKS extensions": ("AKS extension", "AKS extensions"),
    "AKS Kubernetes versions": ("AKS version", "AKS versions"),
    "Azure AI models": ("AI model/version", "AI models/versions"),
    "Azure Functions": ("Functions hosting/runtime option", "Functions hosting/runtime options"),
    "Container Apps": ("Container Apps resource type", "Container Apps resource types"),
}
_GUIDANCE = {
    "VM SKUs": "Planning compute here? Compare the listed sizes with your workload requirements.",
    "AKS extensions": "Using this extension? Check its own compatibility and regional requirements.",
    "AKS Kubernetes versions": "Planning an upgrade? Review the listed version against your cluster's supported upgrade path.",
    "Azure AI models": "Choosing a model location? Check this exact model/version against your residency and deployment requirements.",
    "Azure Functions": "Planning serverless hosting? Check the hosting plan and runtime together.",
    "Container Apps": "Planning container hosting? Check which resource type advertises the region.",
}


def has_briefing(day: dict[str, Any]) -> bool:
    return isinstance(day.get("briefing"), dict) and day["briefing"].get("version") == 1


def briefing_headline(briefing: dict[str, Any]) -> str:
    if not briefing.get("baseline_available"):
        return "Baseline missing: a daily change comparison is not available"
    counts = briefing["counts"]
    if counts.get("observation_gaps"):
        return "Evidence gaps need attention before interpreting regional changes"
    if counts.get("delistings"):
        return f"{counts['delistings']:,} regional listings disappeared; review affected targets"
    if counts.get("scope_changes"):
        return "Monitoring coverage changed; compare like-for-like evidence"
    gains = [group for group in briefing["groups"] if group["kind"] == "new_listings"]
    if gains:
        largest = max(gains, key=lambda group: group["listing_count"])
        subject = (
            f"{largest['feature_count']} VM sizes"
            if largest["modality"] == "VM SKUs" else largest["modality"]
        )
        count = len(largest["regions"])
        return f"{subject} gained listings across {count} {'region' if count == 1 else 'regions'}"
    if counts.get("restorations"):
        return "Previously missing regional listings returned"
    if counts.get("continuing_absences"):
        return "No new delistings; previously tracked listings remain absent"
    if counts.get("observation_recoveries") or counts.get("other_changes"):
        return "Observation status changed; review the evidence"
    return "No listing changes detected in the compared snapshots"


def briefing_excerpt(briefing: dict[str, Any]) -> str:
    if not briefing.get("baseline_available"):
        return "No trustworthy earlier snapshot is available. Current observations are not a daily rollout count."
    counts = briefing["counts"]
    return (
        f"{counts['new_listings']:,} new feature-region listings; "
        f"{counts['delistings']:,} new delistings; "
        f"{counts['restorations']:,} known restorations. "
        "Catalog evidence, not deployment results."
    )


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _coverage_count(value: object) -> int | None:
    if isinstance(value, dict):
        value = value.get("available")
    return value if isinstance(value, int) else None


def _feature_explanation(context: dict[str, Any]) -> str:
    facts = "".join(f"<li>{_escape(fact)}</li>" for fact in context["differentiators"][:2])
    links = []
    for source in context["sources"]:
        parsed = urlsplit(source["url"])
        if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password:
            links.append(
                f'<a href="{_escape(source["url"])}" target="_blank" rel="noopener noreferrer">'
                f'{_escape(source["label"])}</a>'
            )
        else:
            links.append("<span>Reference URL unavailable</span>")
    specificity = {
        "exact": "Documented feature",
        "family": "Documented family",
        "category": "Category context",
        "unverified": "Exact capability unverified",
    }.get(context["specificity"], "Context")
    return f"""<div class="briefing-feature-context">
      <p class="briefing-context-label">{_escape(specificity)}</p>
      <p><strong>{_escape(context['title'])}</strong></p>
      <p>{_escape(context['summary'])}</p>
      <ul>{facts}</ul>
      <p class="briefing-context-limit">{_escape(context['limitations'])}</p>
      <p class="briefing-context-sources">Read more: {' &middot; '.join(links)}</p>
    </div>"""


def _group_card(group: dict[str, Any], index: int) -> str:
    modality, kind = group["modality"], group["kind"]
    count = group["feature_count"]
    singular, plural = _FEATURE_UNITS.get(modality, ("feature", "features"))
    regions = ", ".join(region_name(region) for region in group["regions"])
    examples = []
    for example in group.get("examples", [])[:1]:
        before = _coverage_count(example.get("coverage_before"))
        after = _coverage_count(example.get("coverage_after"))
        coverage = (
            f" Listing coverage: {before} &rarr; {after} regions."
            if isinstance(before, int) and isinstance(after, int)
            else ""
        )
        examples.append(
            f'<p class="briefing-example">Example: {_escape(plain_feature_name(example["feature"]))}.'
            f"{coverage}</p>"
        )
        if example.get("novelty"):
            examples.append(f'<p class="briefing-novelty">{_escape(example["novelty"])}</p>')
        if isinstance(example.get("feature_context"), dict):
            examples.append(_feature_explanation(example["feature_context"]))
    if kind == "delistings":
        guidance = "If this matches a planned regional target, verify it with the provider. This is not an outage or retirement notice."
    elif kind == "observation_gaps":
        guidance = "No trustworthy current result. Do not treat this as an unavailable service."
    elif kind == "continuing_absences":
        guidance = "Previously tracked delistings remain absent. No new delistings does not mean recovery."
    elif kind == "scope_changes":
        guidance = "The observation set changed; these records are not counted as confirmed rollouts or delistings."
    elif kind == "observation_recoveries":
        guidance = "A trustworthy observation returned after a gap; this does not establish a new rollout."
    elif modality in {"Model latency", "Azure model latency"}:
        guidance = "Measurement coverage changed. This is not a catalog rollout or evidence that a deployment was removed."
    else:
        guidance = _GUIDANCE.get(modality, "Review the exact evidence before changing regional plans.")
    return f"""<article class="briefing-card" data-group="{index}">
      <div class="briefing-card-top"><span class="briefing-kind">{_escape(KIND_LABELS.get(kind, kind))}</span>
        <span class="briefing-modality">{_escape(modality)}</span></div>
      <h3><span data-feature-count>{count:,}</span> <span data-feature-unit>{_escape(singular if count == 1 else plural)}</span></h3>
      <p class="briefing-card-count"><strong data-listing-count>{group['listing_count']:,}</strong> feature-region <span data-record-unit>{'record' if group['listing_count'] == 1 else 'records'}</span></p>
      <p class="briefing-regions" data-regions>{_escape(regions)}</p>
      {''.join(examples)}
      <p class="briefing-guidance">{_escape(guidance)}</p>
      <button type="button" data-explore-group="{index}">Explore exact changes</button>
    </article>"""


def render_briefing(day: dict[str, Any], *, include_feedback: bool = True) -> str:
    if not has_briefing(day):
        return ""
    briefing = day["briefing"]
    counts = briefing["counts"]
    date = str(day.get("date", ""))
    previous = str(briefing.get("previous_timestamp") or "")
    current = str(briefing["current_timestamp"])
    compared = f"{previous[:10]} to {current[:10]}" if previous else "No earlier snapshot"
    comparison_days = briefing.get("comparison_days")
    gap_note = (
        f" This comparison spans {comparison_days} days, not just yesterday."
        if isinstance(comparison_days, (int, float)) and comparison_days > 1
        else ""
    )
    priority = {"observation_gaps": 0, "delistings": 1, "scope_changes": 2, "restorations": 3, "new_listings": 4}
    groups = sorted(briefing["groups"], key=lambda group: (
        priority.get(group["kind"], 5), -group["listing_count"], group["modality"],
    ))
    changed_regions = sorted({
        region for group in groups
        if group["kind"] in {"new_listings", "restorations", "delistings", "observation_gaps"}
        for region in group["regions"]
    }, key=region_name)
    affected = ", ".join(region_name(region) for region in changed_regions)
    affected_html = (
        f'<p class="briefing-affected"><strong>New changes across services:</strong> {_escape(affected)}</p>'
        if len(changed_regions) <= 6 else
        f'<details class="briefing-affected"><summary>{len(changed_regions)} regions with new changes or gaps</summary><p>{_escape(affected)}</p></details>'
    ) if changed_regions else ""
    regions = briefing.get("regions", sorted({region for group in groups for region in group["regions"]}))
    modalities = briefing.get("modalities", sorted({group["modality"] for group in groups}))
    region_options = "".join(
        f'<option value="{_escape(region)}">{_escape(region_name(region))}</option>'
        for region in sorted(regions, key=region_name)
    )
    modality_options = "".join(
        f'<option value="{_escape(modality)}">{_escape(modality)}</option>'
        for modality in modalities
    )
    cards = "".join(_group_card(group, index) for index, group in enumerate(groups))
    metrics = "".join(
        f'<div><strong>{counts.get(kind, 0):,}</strong><span>{KIND_LABELS[kind]}</span></div>'
        for kind in ("new_listings", "delistings", "restorations", "continuing_absences", "observation_gaps")
    )
    scope = briefing.get("scope", {})
    scope_note = ""
    if scope.get("added_regions") or scope.get("removed_regions") or counts.get("scope_changes"):
        scope_note = (
            '<p class="briefing-warning">Monitoring scope changed. '
            "Scope-only records are separated from listing changes; check the comparison coverage.</p>"
        )
    tracking = briefing.get("tracking", {})
    since = str(tracking.get("since") or "the available comparisons")
    tracking_note = (
        f"Absence tracking starts at {since}; older disappearances may not be included."
        if not tracking.get("complete")
        else f"Absence tracking starts at {since}."
    )
    continuing = counts.get("continuing_absences", 0)
    absence_note = (
        f"{continuing:,} tracked listings remain absent. "
        "Zero new delistings does not mean previous absences recovered."
    )
    evidence_url = f"/api/history/{day['change_path']}" if day.get("change_path") else ""
    # Embed compact aggregates only. Exact records are fetched when the explorer opens.
    payload = {
        "date": date, "groups": groups, "regions": {region: region_name(region) for region in regions},
        "kindLabels": KIND_LABELS, "featureUnits": _FEATURE_UNITS,
        "evidenceUrl": evidence_url,
    }
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).replace("<", "\\u003c")
    baseline_note = "" if briefing.get("baseline_available") else (
        '<p class="briefing-warning">Change counts are not available without a baseline. '
        "The current scan is not evidence of a new rollout.</p>"
    )
    metrics_html = f'<div class="briefing-metrics" aria-label="Scan-wide counts">{metrics}</div>' if briefing.get("baseline_available") else ""
    evidence_link = f'<a href="{_escape(evidence_url)}">Download complete daily evidence</a>' if evidence_url else ""
    feedback_link = (
        f'<p class="briefing-feedback"><a href="/reading-check/{_escape(date)}.html">'
        "Optional: take a 15-second reading check</a>"
        " <span>For deliberate reader testing. For everyday feedback, use the floating feedback buttons.</span></p>"
        if include_feedback else ""
    )
    return f"""<section class="panel reader-briefing" aria-label="Daily change briefing">
      <div class="briefing-opening">
        <p class="briefing-eyebrow">Since the previous scan <span>Scan-wide briefing</span></p>
        <h2>{_escape(briefing_headline(briefing))}</h2>
        <p class="briefing-window">{_escape(compared)}{_escape(gap_note)}</p>
        {affected_html}
        {baseline_note}{metrics_html}
        <p class="briefing-tracking">{_escape(tracking_note)}</p>
        <p class="briefing-evidence"><strong>What this proves:</strong> read-only catalog/list or measurement evidence.
          Not quota, capacity, successful deployment, an outage, or confirmed retirement.
          <a href="/methodology.html">Methodology</a></p>
      </div>
      <div class="briefing-content">
        {scope_note}
        <div class="briefing-filter-heading"><h3>Changes relevant to you</h3>
          <span>One listing = one feature in one region</span></div>
        <div class="briefing-filters">
          <label for="briefing-region">Region<select id="briefing-region" disabled><option value="">All monitored regions</option>{region_options}</select></label>
          <label for="briefing-modality">Service / modality<select id="briefing-modality" disabled><option value="">All services</option>{modality_options}</select></label>
          <button type="button" data-reset-briefing disabled>Reset filters</button>
        </div>
        <p class="briefing-selection" role="status" data-selection>All regions and services. Groups below separate new changes from continuing observations.</p>
        <div class="briefing-cards">{cards}</div>
        <p class="briefing-empty" data-empty {'hidden' if groups else ''}>No matching change or evidence-gap records. This is not a deployment-health assessment.</p>
        <details class="briefing-context">
          <summary>Observation history and comparison coverage</summary>
          <p>{_escape(absence_note)} {_escape(tracking_note)}</p>
          <p>Previous snapshot: {_escape(previous or 'not available')}<br>Current snapshot: {_escape(current)}</p>
          <p>Snapshot timestamps do not establish freshness of every carried-forward modality. The monitor does not assess your running workloads.</p>
          <p>Added check records: {scope.get('added_checks', 0):,}; removed check records: {scope.get('removed_checks', 0):,}.
            Changes to the observation set do not establish provider intent.</p>
        </details>
        <details class="briefing-explorer">
          <summary>Exact changes and supporting evidence</summary>
          <p>Grouped by feature. Coverage counts are scan-wide; region and service filters limit the listed records.</p>
          <label for="briefing-search">Find a feature or identifier<input id="briefing-search" type="search" placeholder="For example: D128, vmware, Python" disabled></label>
          <p role="status" data-evidence-status>Open to load the complete records, without rerunning probes.</p>
          <button type="button" data-evidence-retry hidden>Retry loading evidence</button>
          <div data-evidence-rows></div>
          <div class="briefing-pager" hidden>
            <button type="button" data-evidence-prev>Previous</button>
            <span data-evidence-page></span><button type="button" data-evidence-next>Next</button>
          </div>
          {evidence_link}
        </details>
        <noscript><p>Enable JavaScript for filters and paged evidence. The scan-wide brief and {evidence_link or 'published JSON evidence'} remain available.</p></noscript>
        {feedback_link}
      </div>
      <script type="application/json" class="briefing-data">{encoded}</script>
      <script src="/assets/briefing.js" defer></script>
    </section>"""
