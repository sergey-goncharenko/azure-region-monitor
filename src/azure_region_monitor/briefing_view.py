"""One evidence-backed briefing shared by the dashboard and daily posts."""

from __future__ import annotations

import html
import json
import re
from typing import Any
from urllib.parse import urlsplit

from azure_region_monitor.briefing import coalesce_briefing_groups
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
    "Azure AI models": ("AI model", "AI models"),
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
    if isinstance(briefing.get("digest"), dict):
        return _digest_headline(briefing)
    counts = briefing["counts"]
    if counts.get("observation_gaps"):
        return "Evidence gaps need attention before interpreting regional changes"
    if counts.get("delistings"):
        return f"{counts['delistings']:,} regional listings disappeared; review affected targets"
    if counts.get("scope_changes"):
        return "Monitoring coverage changed; compare like-for-like evidence"
    gains = [
        (group, status)
        for group in coalesce_briefing_groups(briefing["groups"])
        for status in group["statuses"]
        if status["kind"] == "new_listings"
    ]
    if gains:
        group, largest = max(gains, key=lambda item: item[1]["listing_count"])
        subject = (
            f"{largest['feature_count']} VM sizes"
            if group["modality"] == "VM SKUs" else group["modality"]
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
    if isinstance(briefing.get("digest"), dict):
        return _digest_excerpt(briefing["digest"])
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


def _digest_totals(digest: dict[str, Any]) -> dict[str, Any]:
    totals = digest.get("totals")
    return totals if isinstance(totals, dict) else {}


def _digest_count(digest: dict[str, Any], key: str) -> int:
    value = _digest_totals(digest).get(key)
    return value if isinstance(value, int) else 0


def _digest_modalities(digest: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in digest.get("modalities", []) if isinstance(item, dict)]


def _digest_gaps(digest: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in digest.get("gaps", []) if isinstance(item, dict)]


def _digest_retirements(digest: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in digest.get("retirements", []) if isinstance(item, dict)]


def _previous_date(briefing: dict[str, Any]) -> str:
    previous = str(briefing.get("previous_timestamp") or "")
    return previous[:10] if previous else "the previous scan"


def _digest_unit(modality: str, count: int) -> str:
    singular, plural = _FEATURE_UNITS.get(modality, ("feature", "features"))
    return singular if count == 1 else plural


def _join_phrases(parts: list[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    if len(parts) == 2:
        return " and ".join(parts)
    return ", ".join(parts[:-1]) + f", and {parts[-1]}"


def _strings(values: object) -> list[str]:
    return [value for value in values if isinstance(value, str)] if isinstance(values, list) else []


def _new_regions(feature: dict[str, Any]) -> list[str]:
    restored = set(_strings(feature.get("restored_regions")))
    return [region for region in _strings(feature.get("gained_regions")) if region not in restored]


def _returned_regions(feature: dict[str, Any]) -> list[str]:
    gained = set(_strings(feature.get("gained_regions")))
    return [region for region in _strings(feature.get("restored_regions")) if region in gained]


def _is_returned_only(feature: dict[str, Any]) -> bool:
    # Listings that came back after a gap are not new regional rollouts; keep them apart.
    return (
        bool(_returned_regions(feature))
        and not _new_regions(feature)
        and not _strings(feature.get("lost_regions"))
    )


def _modality_features(modality: dict[str, Any]) -> list[dict[str, Any]]:
    return [feature for feature in modality.get("features", []) if isinstance(feature, dict)]


def _modality_change_counts(modality: dict[str, Any]) -> dict[str, int]:
    def count(key: str) -> int:
        value = modality.get(key)
        return value if isinstance(value, int) else 0

    features = _modality_features(modality)
    if not features:
        return {"new": count("gained_features"), "returned": 0, "lost": count("lost_features")}
    return {
        "new": sum(1 for feature in features if _new_regions(feature)),
        "returned": sum(1 for feature in features if _is_returned_only(feature)),
        "lost": count("lost_features"),
    }


def _digest_subject(digest: dict[str, Any], kind: str) -> str:
    subjects = []
    for modality in _digest_modalities(digest):
        count = _modality_change_counts(modality)[kind]
        if count:
            subjects.append(f"{count:,} {_digest_unit(str(modality.get('modality') or ''), count)}")
    return _join_phrases(subjects)


def _digest_regions(digest: dict[str, Any], select) -> list[str]:
    return sorted({
        region
        for modality in _digest_modalities(digest)
        for feature in _modality_features(modality)
        for region in select(feature)
    }, key=region_name)


def _digest_headline(briefing: dict[str, Any]) -> str:
    digest = briefing["digest"]
    lost = _digest_subject(digest, "lost")
    new = _digest_subject(digest, "new")
    returned = _digest_subject(digest, "returned")
    if not (lost or new or returned):
        retirements = _digest_retirements(digest)
        if retirements:
            label = str(retirements[0].get("label") or "A retired modality")
            suffix = f"{label} retired"
            if len(retirements) > 1:
                suffix += f" and {len(retirements) - 1:,} more retired"
            return f"No regional listing changes · {suffix}"
        return f"No regional listing changes since {_previous_date(briefing)}"
    parts = []
    if lost:
        parts.append(f"{lost} dropped regions")
    if new:
        parts.append(f"{new} gained new regions")
    if returned:
        parts.append(f"{returned} returned")
    if not lost:
        parts.append("nothing dropped")
    elif not (new or returned):
        parts.append("nothing gained")
    return " · ".join(parts)


def _digest_excerpt(digest: dict[str, Any]) -> str:
    lost = _digest_subject(digest, "lost")
    new = _digest_subject(digest, "new")
    returned = _digest_subject(digest, "returned")
    catalog_gaps = _digest_count(digest, "catalog_gap_listings")
    measurement_gaps = _digest_count(digest, "measurement_gap_listings")

    def with_regions(phrase: str, regions: list[str]) -> str:
        return f"{phrase} ({', '.join(region_name(region) for region in regions)})" if regions else phrase

    changes = []
    if new:
        changes.append(with_regions(f"{new} gained new regions", _digest_regions(digest, _new_regions)))
    if returned:
        changes.append(with_regions(f"{returned} returned", _digest_regions(digest, _returned_regions)))
    if not changes:
        changes.append("no gains")
    changes.append(f"{lost} dropped regions" if lost else "nothing dropped")
    parts = ["; ".join(changes)]
    if catalog_gaps:
        parts.append(f"{catalog_gaps:,} catalog gaps need follow-up")
    if measurement_gaps:
        parts.append(f"{measurement_gaps:,} measurement gaps were not catalog evidence")
    return "; ".join(parts) + ". Catalog evidence, not deployment results."


def _safe_learn_url(value: object) -> str:
    if not isinstance(value, str):
        return ""
    parsed = urlsplit(value)
    if (
        parsed.scheme == "https"
        and parsed.hostname in {"learn.microsoft.com", "azure.microsoft.com"}
        and not parsed.username
        and not parsed.password
    ):
        return value
    return ""


def _safe_registry_url(value: object) -> str:
    if not isinstance(value, str):
        return ""
    parsed = urlsplit(value)
    if (
        parsed.scheme == "https"
        and parsed.hostname
        and not parsed.username
        and not parsed.password
    ):
        return value
    return ""


def _feature_learn_link(feature: dict[str, Any]) -> str:
    reference = feature.get("learn_reference")
    if isinstance(reference, dict):
        url = _safe_learn_url(reference.get("url"))
        title = reference.get("title") if isinstance(reference.get("title"), str) else "Learn"
    else:
        url = ""
        title = "Learn"
    if not url:
        url = _safe_learn_url(feature.get("details_url"))
        title = "Learn"
        if urlsplit(url).path.rstrip("/").endswith("/search"):
            # A search for the raw identifier is not a reference; show no link instead.
            url = ""
    if not url:
        return ""
    return (
        f'<a class="briefing-learn-link" href="{_escape(url)}" '
        f'target="_blank" rel="noopener noreferrer">{_escape(title)}</a>'
    )


def _region_display_list(regions: list[str], restored_regions: set[str] | None = None) -> list[str]:
    restored_regions = restored_regions or set()
    return [
        f"{region_name(region)} (returned)" if region in restored_regions else region_name(region)
        for region in regions
    ]


def _region_delta_html(regions: list[str], *, label: str, restored_regions: set[str] | None = None) -> str:
    restored_regions = restored_regions or set()
    if label == "returned":
        # Every region here came back after a gap, so the chip style says it once.
        names = [region_name(region) for region in regions]
        tone, sign = "returned", "↩"
    else:
        names = _region_display_list(regions, restored_regions)
        tone = "loss" if label == "lost" else "gain"
        sign = "−" if label == "lost" else "+"
    if not names:
        return ""
    full = ", ".join(names)
    if len(names) <= 3:
        chips = []
        for region, name in zip(regions, names, strict=True):
            returned = label != "returned" and region in restored_regions
            returned_class = " is-returned" if returned else ""
            chips.append(
                f'<span class="briefing-region-chip briefing-region-chip-{tone}{returned_class}">'
                f'{_escape(sign)} {_escape(name)}</span>'
            )
        return "".join(chips)
    text = f"{sign}{len(names):,} regions"
    return (
        f'<span class="briefing-region-chip briefing-region-chip-{tone} briefing-region-tooltip" '
        f'tabindex="0" title="{_escape(full)}" '
        f'aria-label="{_escape(text + ": " + full)}">'
        f'{_escape(text)}<span role="tooltip">{_escape(full)}</span></span>'
    )


def _coverage_html(feature: dict[str, Any]) -> str:
    before = feature.get("coverage_before")
    after = feature.get("coverage_after")
    if isinstance(before, int) and isinstance(after, int):
        return f'<span class="briefing-coverage">{before:,} &rarr; {after:,} regions</span>'
    return ""


def _feature_badges_html(feature: dict[str, Any]) -> str:
    geographies = [
        geography.strip()
        for geography in feature.get("new_geographies") or []
        if isinstance(geography, str) and geography.strip()
    ]
    badges = []
    if feature.get("first_seen"):
        # A first listing is new in every geography it appears in; one badge says that.
        badges.append(
            f"first listing · {len(geographies)} geographies" if len(geographies) > 1 else "first listing"
        )
    else:
        badges.extend(f"first in {geography}" for geography in geographies)
    return "".join(f'<span class="briefing-badge">{_escape(badge)}</span>' for badge in badges)


def _feature_member_name(feature: dict[str, Any]) -> str:
    label = str(feature.get("label") or feature.get("feature") or "Feature")
    if feature.get("modality") == "VM SKUs":
        member = label.replace("_", " ")
        member = re.sub(r"\bVM size\b", "", member, flags=re.IGNORECASE).strip()
        member = re.sub(r"^Standard\s+", "", member, flags=re.IGNORECASE)
        member = re.sub(r"\s+V[0-9]+$", "", member, flags=re.IGNORECASE)
        return member or label
    if feature.get("modality") == "Azure AI models":
        version = re.search(r"\(version ([^)]+)\)$", label)
        if version:
            return f"version {version.group(1)}"
    return label


def _compact_member_names(features: list[dict[str, Any]]) -> str:
    names = [_feature_member_name(feature) for feature in features]
    visible = names[:5]
    suffix = f" … +{len(names) - len(visible):,}" if len(names) > len(visible) else ""
    return ", ".join(visible) + suffix


def _range_text(values: list[int]) -> str:
    low = min(values)
    high = max(values)
    return f"{low:,}" if low == high else f"{low:,}–{high:,}"


def _cluster_coverage_html(features: list[dict[str, Any]]) -> str:
    before = [feature.get("coverage_before") for feature in features]
    after = [feature.get("coverage_after") for feature in features]
    if not all(isinstance(value, int) for value in before + after):
        return ""
    return (
        f'<span class="briefing-coverage">{_range_text(before)} &rarr; '
        f'{_range_text(after)} regions</span>'
    )


def _cluster_badges_html(features: list[dict[str, Any]]) -> str:
    return _feature_badges_html({
        "first_seen": any(feature.get("first_seen") for feature in features),
        "new_geographies": sorted({
            geography
            for feature in features
            for geography in feature.get("new_geographies", [])
            if isinstance(geography, str) and geography.strip()
        }),
    })


def _cluster_region_delta_html(features: list[dict[str, Any]], key: str, label: str) -> str:
    members = [feature for feature in features if feature.get(key)]
    if not members:
        return ""
    region_sets = [
        frozenset(region for region in feature.get(key, []) if isinstance(region, str))
        for feature in members
    ]
    regions = sorted(set().union(*region_sets), key=region_name)
    restored = {
        region
        for feature in members
        for region in feature.get("restored_regions", [])
        if isinstance(region, str)
    } if label == "gained" else set()
    varies = len(set(region_sets)) > 1
    note = '<span class="briefing-varies">varies by size</span>' if varies else ""
    return f'{_region_delta_html(regions, label=label, restored_regions=restored)}{note}'


def _cluster_restored_badge(features: list[dict[str, Any]]) -> str:
    count = sum(
        len([region for region in feature.get("restored_regions", []) if isinstance(region, str)])
        for feature in features
    )
    if not count:
        return ""
    return f'<span class="briefing-badge briefing-badge-returned">({count:,} returned)</span>'


def _cluster_label(feature: dict[str, Any]) -> str:
    cluster = feature.get("cluster")
    if isinstance(cluster, dict) and isinstance(cluster.get("label"), str) and cluster["label"]:
        return cluster["label"]
    return str(feature.get("label") or feature.get("feature") or "Feature")


def _cluster_key(feature: dict[str, Any]) -> str:
    cluster = feature.get("cluster")
    if isinstance(cluster, dict) and isinstance(cluster.get("key"), str) and cluster["key"]:
        return cluster["key"]
    return str(feature.get("feature") or _cluster_label(feature))


def _cluster_changed_region_count(features: list[dict[str, Any]]) -> int:
    return len({
        region
        for feature in features
        for key in ("gained_regions", "lost_regions")
        for region in feature.get(key, [])
        if isinstance(region, str)
    })


def _digest_cluster_line(features: list[dict[str, Any]]) -> str:
    if len(features) == 1:
        return _digest_feature_line(features[0])
    label = _cluster_label(features[0])
    modality = str(features[0].get("modality") or "")
    is_loss = any(feature.get("lost_regions") for feature in features)
    returned_only = all(_is_returned_only(feature) for feature in features)
    icon = "▼" if is_loss else "↩" if returned_only else "▲"
    tone = "loss" if is_loss else "returned" if returned_only else "gain"
    count = len(features)
    members = _compact_member_names(features)
    region_bits = []
    lost_html = _cluster_region_delta_html(features, "lost_regions", "lost")
    if lost_html:
        region_bits.append(f'<span><strong>Dropped:</strong> {lost_html}</span>')
    gained_html = _cluster_region_delta_html(
        features, "gained_regions", "returned" if returned_only else "gained"
    )
    if gained_html:
        gained_label = "Returned" if returned_only else "Gained"
        region_bits.append(f'<span><strong>{gained_label}:</strong> {gained_html}</span>')
    summary_meta = "".join((
        _cluster_coverage_html(features),
        "" if returned_only else _cluster_restored_badge(features),
        _cluster_badges_html(features),
    ))
    details = "".join(_digest_feature_line(feature) for feature in features)
    return f"""<li class="briefing-digest-cluster is-{tone}">
      <details>
        <summary>
          <span class="briefing-change-icon" aria-hidden="true">{icon}</span>
          <div>
            <strong>{_escape(label)}</strong>
            <span class="briefing-cluster-members">{count:,} {_escape(_digest_unit(modality, count))}: {_escape(members)}</span>
            <span class="briefing-feature-meta">{''.join(region_bits)}{summary_meta}</span>
          </div>
        </summary>
        <ul class="briefing-digest-features briefing-digest-cluster-details">{details}</ul>
      </details>
    </li>"""


def _digest_clusters(features: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: dict[tuple[str, bool], list[dict[str, Any]]] = {}
    for feature in features:
        groups.setdefault((_cluster_key(feature), _is_returned_only(feature)), []).append(feature)
    clusters = list(groups.values())
    clusters.sort(key=lambda items: (
        0 if any(feature.get("lost_regions") for feature in items)
        else 2 if all(_is_returned_only(feature) for feature in items) else 1,
        -len(items),
        -_cluster_changed_region_count(items),
        _cluster_label(items[0]).casefold(),
    ))
    return clusters


def _digest_feature_line(feature: dict[str, Any]) -> str:
    label = str(feature.get("label") or feature.get("feature") or "Feature")
    short = str(feature.get("short") or "")
    reference = feature.get("learn_reference")
    if not short and isinstance(reference, dict) and isinstance(reference.get("title"), str):
        short = reference["title"]
    gained = [region for region in feature.get("gained_regions", []) if isinstance(region, str)]
    lost = [region for region in feature.get("lost_regions", []) if isinstance(region, str)]
    restored = {
        region for region in feature.get("restored_regions", [])
        if isinstance(region, str)
    }
    is_loss = bool(lost)
    returned_only = _is_returned_only(feature)
    icon = "▼" if is_loss else "↩" if returned_only else "▲"
    tone = "loss" if is_loss else "returned" if returned_only else "gain"
    lost_html = _region_delta_html(lost, label="lost")
    gained_html = _region_delta_html(
        gained, label="returned" if returned_only else "gained", restored_regions=restored
    )
    if lost_html and gained_html:
        regions = (
            f'<span><strong>Dropped:</strong> {lost_html}</span>'
            f'<span><strong>Gained:</strong> {gained_html}</span>'
        )
    else:
        regions = lost_html or gained_html
    meaning = f'<span class="briefing-feature-meaning">{_escape(short)}</span>' if short else ""
    return f"""<li class="briefing-digest-feature is-{tone}">
      <span class="briefing-change-icon" aria-hidden="true">{icon}</span>
      <div>
        <strong>{_escape(label)}</strong>
        {meaning}
        <span class="briefing-feature-meta">{regions}{_coverage_html(feature)}{_feature_badges_html(feature)}{_feature_learn_link(feature)}</span>
      </div>
    </li>"""


def _cluster_list_html(clusters: list[list[dict[str, Any]]], *, show_all_label: str) -> str:
    visible = clusters[:6]
    hidden = clusters[6:]
    visible_html = "".join(_digest_cluster_line(cluster) for cluster in visible)
    if not hidden:
        return f'<ul class="briefing-digest-features">{visible_html}</ul>'
    if len(hidden) > 200:
        overflow = (
            f'<p class="briefing-overflow">{len(hidden):,} more changed groups are available '
            "in the full evidence explorer.</p>"
        )
    else:
        overflow = (
            '<ul class="briefing-digest-features">'
            f'{"".join(_digest_cluster_line(cluster) for cluster in hidden)}</ul>'
        )
    return (
        f'<ul class="briefing-digest-features">{visible_html}</ul>'
        f'<details class="briefing-more-features"><summary>{_escape(show_all_label)}</summary>{overflow}</details>'
    )


def _digest_feature_list(features: list[dict[str, Any]]) -> str:
    clusters = _digest_clusters(features)
    active = [cluster for cluster in clusters if not all(_is_returned_only(feature) for feature in cluster)]
    returned = [cluster for cluster in clusters if all(_is_returned_only(feature) for feature in cluster)]
    html = (
        _cluster_list_html(active, show_all_label=f"Show all {len(active):,} groups")
        if active else ""
    )
    if returned:
        modality = str(returned[0][0].get("modality") or "")
        count = sum(len(cluster) for cluster in returned)
        html += (
            '<details class="briefing-returned-features"><summary>'
            f"↩ {count:,} {_escape(_digest_unit(modality, count))} returned after a gap "
            f"in {len(returned):,} {'group' if len(returned) == 1 else 'groups'}"
            " — listings that were missing in the previous scan</summary>"
            f'{_cluster_list_html(returned, show_all_label=f"Show all {len(returned):,} returned groups")}'
            "</details>"
        )
    return html


def _digest_modality_row(modality: dict[str, Any]) -> str:
    name = str(modality.get("modality") or "Service")
    gained_listings = modality.get("gained_listings") if isinstance(modality.get("gained_listings"), int) else 0
    lost_features = modality.get("lost_features") if isinstance(modality.get("lost_features"), int) else 0
    lost_listings = modality.get("lost_listings") if isinstance(modality.get("lost_listings"), int) else 0
    gained_regions = [region for region in modality.get("gained_regions", []) if isinstance(region, str)]
    lost_regions = [region for region in modality.get("lost_regions", []) if isinstance(region, str)]
    features = _modality_features(modality)
    counts = _modality_change_counts(modality)
    pills = []
    if features:
        new_listings = sum(len(_new_regions(feature)) for feature in features)
        returned_listings = sum(len(_returned_regions(feature)) for feature in features)
        new_regions = sorted({region for feature in features for region in _new_regions(feature)}, key=region_name)
        returned_regions = sorted(
            {region for feature in features for region in _returned_regions(feature)}, key=region_name
        )
    else:
        new_listings, returned_listings = gained_listings, 0
        new_regions, returned_regions = gained_regions, []
    if counts["new"]:
        pills.append(
            f'<span class="briefing-pill briefing-pill-gain">▲ {counts["new"]:,} '
            f'{_escape(_digest_unit(name, counts["new"]))} +{new_listings:,} new '
            f'{"listing" if new_listings == 1 else "listings"}</span>'
        )
    if counts["returned"]:
        pills.append(
            f'<span class="briefing-pill briefing-pill-returned">↩ {counts["returned"]:,} '
            f'{_escape(_digest_unit(name, counts["returned"]))} returned · {returned_listings:,} '
            f'{"listing" if returned_listings == 1 else "listings"}</span>'
        )
    if lost_features or lost_listings:
        pills.append(
            f'<span class="briefing-pill briefing-pill-loss">▼ {lost_features:,} '
            f'{_escape(_digest_unit(name, lost_features))} −{lost_listings:,} listings</span>'
        )
    region_bits = []
    new_html = _region_delta_html(new_regions, label="gained")
    if new_html:
        region_bits.append(f'<span><strong>New regions:</strong> {new_html}</span>')
    returned_html = _region_delta_html(returned_regions, label="returned")
    if returned_html:
        region_bits.append(f'<span><strong>Returned in:</strong> {returned_html}</span>')
    lost_html = _region_delta_html(lost_regions, label="lost")
    if lost_html:
        region_bits.append(f'<span><strong>Dropped:</strong> {lost_html}</span>')
    return f"""<article class="briefing-digest-modality">
      <div class="briefing-digest-modality-top">
        <h3>{_escape(name)}</h3>
        <div class="briefing-pills">{''.join(pills)}</div>
      </div>
      <p class="briefing-region-deltas">{' '.join(region_bits)}</p>
      {_digest_feature_list(features)}
    </article>"""


def _digest_gap_line(gap: dict[str, Any]) -> str:
    modality = str(gap.get("modality") or "Unknown modality")
    count = gap.get("listing_count") if isinstance(gap.get("listing_count"), int) else gap.get("feature_count", 0)
    count = count if isinstance(count, int) else 0
    regions = [region for region in gap.get("regions", []) if isinstance(region, str)]
    if gap.get("measurement"):
        source = {
            "Model latency": "GitHub Models",
            "Azure model latency": "Azure OpenAI",
        }.get(modality, modality)
        region_note = ""
        if regions and regions != ["github-global"]:
            region_note = " in " + ", ".join(region_name(region) for region in regions)
        return (
            f'<li class="briefing-gap-line is-measurement">{count:,} {_escape(source)} latency '
            f'{"check" if count == 1 else "checks"} returned no result{_escape(region_note)} '
            "— measurement gap, not catalog evidence</li>"
        )
    region_text = ", ".join(region_name(region) for region in regions)
    region_suffix = f" in {_escape(region_text)}" if region_text else ""
    return (
        f'<li class="briefing-gap-line is-catalog">{count:,} catalog '
        f'{"listing" if count == 1 else "listings"} returned no result '
        f'({_escape(modality)}){region_suffix}</li>'
    )


def _digest_retirement_line(retirement: dict[str, Any]) -> str:
    label = str(retirement.get("label") or "A retired modality")
    retired_on = str(retirement.get("retired_on") or "the recorded retirement date")
    checks = retirement.get("historical_checks")
    checks = checks if isinstance(checks, int) else 0
    source_url = _safe_registry_url(retirement.get("source_url"))
    source = (
        f' <a href="{_escape(source_url)}" target="_blank" rel="noopener noreferrer">Announcement</a>'
        if source_url else ""
    )
    return (
        f'<li class="briefing-gap-line is-retirement">{_escape(label)} retired: '
        f"the service shut down on {_escape(retired_on)}, so its {checks:,} "
        f"{'check is' if checks == 1 else 'checks are'} no longer measured.{source}</li>"
    )


def _render_digest_glance(briefing: dict[str, Any]) -> str:
    digest = briefing["digest"]
    gains = _digest_count(digest, "gained_features")
    losses = _digest_count(digest, "lost_features")
    has_new = bool(_digest_subject(digest, "new"))
    tone = "loss" if losses else "gain" if has_new else "returned" if gains else "neutral"
    changed = [
        modality for modality in _digest_modalities(digest)
        if modality.get("gained_features") or modality.get("lost_features")
    ]
    rows = "".join(_digest_modality_row(modality) for modality in changed)
    if not rows:
        rows = f'<p class="briefing-no-change">No regional listing changes since {_escape(_previous_date(briefing))}.</p>'
    gaps = "".join(_digest_gap_line(gap) for gap in _digest_gaps(digest))
    retirements = "".join(
        _digest_retirement_line(retirement) for retirement in _digest_retirements(digest)
    )
    notices = gaps + retirements
    gap_html = f'<ul class="briefing-gap-list">{notices}</ul>' if notices else ""
    return f"""<div class="briefing-opening briefing-glance">
      <p class="briefing-eyebrow">At a glance — since {_escape(_previous_date(briefing))}<span>Daily regional evidence</span></p>
      <h2 class="briefing-headline--{tone}">{_escape(_digest_headline(briefing))}</h2>
      <p class="briefing-evidence"><strong>What this proves:</strong> read-only catalog/list or measurement evidence; not quota, capacity, successful deployment, outage, or confirmed retirement. <a href="/methodology.html">Methodology</a></p>
      <div class="briefing-digest-list">{rows}</div>
      {gap_html}
    </div>"""


def _status_summary(status: dict[str, Any], modality: str, status_index: int) -> str:
    kind = status["kind"]
    regions = ", ".join(region_name(region) for region in status["regions"])
    examples = []
    for example in status.get("examples", [])[:1]:
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
        guidance = "Catalog/list evidence only; verify exact requirements before changing regional plans."
    return f"""<section class="briefing-status" data-status="{status_index}">
      <div class="briefing-card-top"><span class="briefing-kind">{_escape(KIND_LABELS.get(kind, kind))}</span></div>
      <p class="briefing-card-count"><strong data-status-listing-count>{status['listing_count']:,}</strong> feature-region <span data-status-record-unit>{'record' if status['listing_count'] == 1 else 'records'}</span></p>
      <p class="briefing-regions" data-status-regions>{_escape(regions)}</p>
      {''.join(examples)}
      <p class="briefing-guidance">{_escape(guidance)}</p>
    </section>"""


def _group_card(group: dict[str, Any], index: int) -> str:
    modality = group["modality"]
    count = group["feature_count"]
    singular, plural = _FEATURE_UNITS.get(modality, ("feature", "features"))
    statuses = "".join(
        _status_summary(status, modality, status_index)
        for status_index, status in enumerate(group["statuses"])
    )
    return f"""<article class="briefing-card" data-group="{index}">
      <div class="briefing-card-top"><span class="briefing-modality">{_escape(modality)}</span></div>
      <h3><span data-feature-count>{count:,}</span> <span data-feature-unit>{_escape(singular if count == 1 else plural)}</span></h3>
      <p class="briefing-card-count"><strong data-listing-count>{group['listing_count']:,}</strong> feature-region <span data-record-unit>{'record' if group['listing_count'] == 1 else 'records'}</span></p>
      {statuses}
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
    groups = sorted(coalesce_briefing_groups(briefing["groups"]), key=lambda group: (
        min(priority.get(status["kind"], 5) for status in group["statuses"]),
        -group["listing_count"],
        group["modality"],
    ))
    changed_regions = sorted({
        region for group in groups
        if any(
            status["kind"] in {"new_listings", "restorations", "delistings", "observation_gaps"}
            for status in group["statuses"]
        )
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
    has_digest = briefing.get("baseline_available") and isinstance(briefing.get("digest"), dict)
    legacy_opening = f"""<div class="briefing-opening">
        <p class="briefing-eyebrow">Since the previous scan <span>Scan-wide briefing</span></p>
        <h2>{_escape(briefing_headline(briefing))}</h2>
        <p class="briefing-window">{_escape(compared)}{_escape(gap_note)}</p>
        {affected_html}
        {baseline_note}{metrics_html}
        <p class="briefing-tracking">{_escape(tracking_note)}</p>
        <p class="briefing-evidence"><strong>What this proves:</strong> read-only catalog/list or measurement evidence.
          Not quota, capacity, successful deployment, an outage, or confirmed retirement.
          <a href="/methodology.html">Methodology</a></p>
      </div>"""
    opening_html = _render_digest_glance(briefing) if has_digest else legacy_opening
    collapsed_intro = (
        f"{affected_html}{baseline_note}{metrics_html}"
        f'<p class="briefing-tracking">{_escape(tracking_note)}</p>'
        if has_digest else ""
    )
    content_open = (
        '<details class="briefing-content briefing-full-evidence">'
        '<summary>Full evidence, filters and history</summary>'
        if has_digest else '<div class="briefing-content">'
    )
    content_close = "</details>" if has_digest else "</div>"
    return f"""<section class="panel reader-briefing" aria-label="Daily change briefing">
      {opening_html}
      {content_open}
        {collapsed_intro}
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
      {content_close}
      <script type="application/json" class="briefing-data">{encoded}</script>
      <script src="/assets/briefing.js" defer></script>
    </section>"""
