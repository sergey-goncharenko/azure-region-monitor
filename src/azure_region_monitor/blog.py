"""Static daily changelog blog generated from the change-history narratives.

Pure and offline-testable: callers pass the history days (from
``api/history/index.json``) plus the site URL and a shared CSS block, and get
back HTML pages, an RSS feed, and sitemap entries. No I/O happens here.
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from typing import Any

BLOG_DIR = "blog"
FEED_PATH = "blog/feed.xml"
INDEX_PATH = "blog/index.html"
_EXCERPT_CHARS = 220
_SOCIAL_POST_LIMIT = 1
_SOCIAL_EVIDENCE_NOTE = (
    "Evidence note: these are read-only Azure catalog/list signals; unavailable does not mean "
    "quota, capacity, deployment failure, or SLA impact."
)
# A real blog-post headline is short. Anything longer is almost certainly a
# single-paragraph rule/older summary, so it is demoted to body text and the post
# gets a clean date-based title instead of a runaway one-line headline.
_MAX_HEADLINE_CHARS = 110
_TREND_DAYS = 7
_MODALITY_LABELS = (
    "AKS extensions",
    "AKS Kubernetes versions",
    "Azure Functions",
    "Azure AI models",
    "Model latency",
    "Azure model latency",
    "Container Apps",
    "VM SKUs",
)
_RULE_SECTION_LABELS = (
    *_MODALITY_LABELS,
    "Regressions to review",
    "New options to validate",
    "What this means for Azure users",
)
_LEGACY_REGRESSION_MARKERS = (
    "delisted",
    "withdrawn",
    "stopped listing",
    "stopped advertising",
    "stopped measuring",
    "dropped from",
    "deployment gone",
)


def split_narrative(narrative: str, source: str) -> tuple[str, list[str]]:
    """Split a stored narrative into (headline, paragraphs).

    AI blog-post narratives use a headline line followed by blank-line-separated
    paragraphs. The rule fallback is a single block with no separate headline. A
    candidate headline that is too long is treated as a body paragraph instead.
    """

    text = (narrative or "").strip()
    if not text:
        return "", []
    blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    if source == "rule" and len(blocks) == 1:
        labels = "|".join(re.escape(label) for label in _RULE_SECTION_LABELS)
        blocks = [
            block.strip()
            for block in re.split(rf"\s+(?=(?:{labels}):)", blocks[0])
            if block.strip()
        ]
    headline, rest = "", blocks
    if source == "ai" and blocks:
        headline, rest = blocks[0], blocks[1:]
        if not rest and "\n" in headline:
            first, remainder = headline.split("\n", 1)
            headline, rest = first.strip(), [remainder.strip()]
    elif source == "rule" and len(blocks) > 1 and not blocks[0].endswith(('.', '!', '?')):
        headline, rest = blocks[0], blocks[1:]
    # Demote an over-long "headline" to body text so the title stays clean.
    if headline and len(headline) > _MAX_HEADLINE_CHARS:
        rest = [headline, *rest]
        headline = ""
    return headline, [p for p in rest if p]


def select_blog_posts(history_index: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return blog posts (newest first) for every history day that has a narrative.

    Each post carries the parsed headline/paragraphs, the summary source, the
    change counts, and the highlights so a post page can be rendered without any
    further lookups.
    """

    if not isinstance(history_index, dict):
        return []
    days = [day for day in history_index.get("days", []) if isinstance(day, dict)]
    days_by_date = {
        str(day.get("date", "")).strip(): day
        for day in days
        if str(day.get("date", "")).strip()
    }
    posts: list[dict[str, Any]] = []
    for day in days:
        date = str(day.get("date", "")).strip()
        narrative = str(day.get("narrative", "")).strip()
        if not date or not narrative:
            continue
        source = str(day.get("narrative_source", "rule"))
        headline, paragraphs = split_narrative(narrative, source)
        counts = day.get("change_type_counts") if isinstance(day.get("change_type_counts"), dict) else {}
        posts.append(
            {
                "date": date,
                "slug": f"{BLOG_DIR}/{date}.html",
                "title": headline or f"Azure regional changes — {date}",
                "headline": headline,
                "paragraphs": paragraphs,
                "source": source,
                "new_availability": int(counts.get("new_availability", 0) or 0),
                "regressions": int(counts.get("regression", 0) or 0),
                "parked_unknown": int(day.get("parked_unknown_changes", 0) or 0),
                "highlights": day.get("highlights", []) if isinstance(day.get("highlights"), list) else [],
                "excerpt": str(day.get("editorial_excerpt", "")).strip(),
                "social_drafts": day.get("social_drafts")
                if isinstance(day.get("social_drafts"), dict)
                else None,
                "executive_summary": daily_executive_summary(
                    day,
                    days_by_date.get(str(day.get("previous_date", "")).strip()),
                ),
                "weekly_context": weekly_context(days, date),
            }
        )
    posts.sort(key=lambda post: post["date"], reverse=True)
    return posts


def daily_executive_summary(
    day: dict[str, Any], previous_day: dict[str, Any] | None = None
) -> str:
    """Explain one day's changes, optionally comparing its recorded predecessor."""

    date = str(day.get("date", "")).strip()
    counts = day.get("change_type_counts")
    if not date or not isinstance(counts, dict):
        return ""

    new_availability = _as_int(counts.get("new_availability"))
    regressions = _as_int(counts.get("regression"))
    parked_unknown = _as_int(
        day.get("parked_unknown_changes", counts.get("status_change"))
    )
    previous_date = str(day.get("previous_date", "")).strip()
    if previous_date:
        opening = (
            f"Compared with the {previous_date} snapshot, the {date} scan recorded "
            f"{new_availability:,} new {_plural(new_availability, 'listing')}, "
            f"{regressions:,} {_plural(regressions, 'regression')}, and "
            f"{parked_unknown:,} parked unknown {_plural(parked_unknown, 'transition')}."
        )
    else:
        opening = (
            f"The {date} scan recorded {new_availability:,} new "
            f"{_plural(new_availability, 'listing')}, {regressions:,} "
            f"{_plural(regressions, 'regression')}, and {parked_unknown:,} parked unknown "
            f"{_plural(parked_unknown, 'transition')}."
        )

    comparison = ""
    if previous_day and isinstance(previous_day.get("change_type_counts"), dict):
        previous_counts = previous_day["change_type_counts"]
        comparison = " ".join(
            (
                _count_comparison(
                    "New listings",
                    new_availability,
                    _as_int(previous_counts.get("new_availability")),
                ),
                _count_comparison(
                    "Regressions",
                    regressions,
                    _as_int(previous_counts.get("regression")),
                ),
            )
        )

    classifications = _classification_summary(day.get("change_context_counts"))
    if regressions and new_availability:
        meaning = (
            f"Review the {regressions:,} {_plural(regressions, 'regression')} against existing "
            f"regional targets and fallbacks first; treat the {new_availability:,} new "
            f"{_plural(new_availability, 'listing')} as options to validate."
        )
    elif regressions:
        meaning = (
            f"Review the {regressions:,} {_plural(regressions, 'regression')} against existing "
            "regional targets and fallbacks."
        )
    elif new_availability:
        meaning = (
            f"The {new_availability:,} new {_plural(new_availability, 'listing')} expand the "
            "set of regional options to validate."
        )
    else:
        meaning = "No clear rollout or regression signal was recorded for this scan."

    comparison_block = " ".join(part for part in (opening, comparison) if part)
    modality_counts = day.get("change_modality_counts")
    if not isinstance(modality_counts, dict):
        modality_counts = _legacy_modality_counts(str(day.get("narrative", "")))
    modalities = _modality_summary(modality_counts)
    representatives = _representative_changes(
        day.get("highlights"), str(day.get("narrative", ""))
    )
    meaning_block = (
        f"What this means: {meaning} These are read-only catalog/list signals, not quota, "
        "capacity, or deployment results."
    )
    return "\n\n".join(
        part
        for part in (
            comparison_block,
            modalities,
            representatives,
            classifications,
            meaning_block,
        )
        if part
    )


def weekly_context(days: list[dict[str, Any]], target_date: str) -> str:
    """Summarize at most the seven calendar days ending on target_date."""

    try:
        end = datetime.fromisoformat(target_date).date()
    except ValueError:
        return ""
    start = end - timedelta(days=_TREND_DAYS - 1)
    window: list[dict[str, Any]] = []
    for day in days:
        try:
            day_date = datetime.fromisoformat(str(day.get("date", ""))).date()
        except ValueError:
            continue
        if start <= day_date <= end and isinstance(day.get("change_type_counts"), dict):
            window.append(day)
    if len(window) < 2:
        return ""

    new_availability = sum(
        _as_int(day["change_type_counts"].get("new_availability")) for day in window
    )
    regressions = sum(
        _as_int(day["change_type_counts"].get("regression")) for day in window
    )
    expansion_led = sum(
        _as_int(day["change_type_counts"].get("new_availability"))
        > _as_int(day["change_type_counts"].get("regression"))
        for day in window
    )
    regression_led = sum(
        _as_int(day["change_type_counts"].get("regression"))
        > _as_int(day["change_type_counts"].get("new_availability"))
        for day in window
    )
    if expansion_led and regression_led:
        pattern = (
            f"New listings led on {expansion_led} {_plural(expansion_led, 'scan')}; "
            f"regressions led on {regression_led}."
        )
    elif expansion_led:
        pattern = f"New listings led on all {expansion_led} recorded {_plural(expansion_led, 'scan')}."
    elif regression_led:
        pattern = f"Regressions led on all {regression_led} recorded {_plural(regression_led, 'scan')}."
    else:
        pattern = "New listings and regressions were balanced on the recorded scans."
    return (
        f"7-day context ({start.isoformat()} to {end.isoformat()}): across "
        f"{len(window)} recorded {_plural(len(window), 'scan')}, there were "
        f"{new_availability:,} new {_plural(new_availability, 'listing')} and "
        f"{regressions:,} {_plural(regressions, 'regression')}. {pattern}"
    )


def _count_comparison(label: str, current: int, previous: int) -> str:
    if current == previous:
        return f"{label} held at {current:,}."
    direction = "rose" if current > previous else "fell"
    return f"{label} {direction} from {previous:,} to {current:,}."


def _classification_summary(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    labels = (
        ("deprecation_candidate", "deprecation candidate"),
        ("recurring_regression", "recurring disappearance"),
        ("net_new_availability", "net-new regional listing"),
        ("restored_availability", "restored regional listing"),
    )
    parts = [
        f"{_as_int(value.get(key)):,} {_plural(_as_int(value.get(key)), label)}"
        for key, label in labels
        if _as_int(value.get(key))
    ]
    return f"What changed: {', '.join(parts)}." if parts else ""


def _modality_summary(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    groups: list[tuple[int, str]] = []
    for modality, raw_counts in value.items():
        if not isinstance(raw_counts, dict):
            continue
        additions = _as_int(raw_counts.get("new_availability"))
        regressions = _as_int(raw_counts.get("regression"))
        if not additions and not regressions:
            continue
        text = (
            f"{modality}: {additions:,} new {_plural(additions, 'listing')}, "
            f"{regressions:,} {_plural(regressions, 'regression')}"
        )
        groups.append((additions + regressions, text))
    groups.sort(key=lambda item: (-item[0], item[1]))
    if not groups:
        return ""
    shown = [text for _, text in groups[:3]]
    remaining = len(groups) - len(shown)
    suffix = f"; and {remaining} other {_plural(remaining, 'area')}" if remaining else ""
    return f"Where it changed: {'; '.join(shown)}{suffix}."


def _legacy_rule_sections(narrative: str) -> list[tuple[str, str, str]]:
    _, paragraphs = split_narrative(narrative, "rule")
    sections: list[tuple[str, str, str]] = []
    for paragraph in paragraphs:
        modality = next(
            (label for label in _MODALITY_LABELS if paragraph.startswith(f"{label}:")),
            "",
        )
        if not modality:
            continue
        lowered = paragraph.lower()
        change_type = (
            "regression"
            if any(marker in lowered for marker in _LEGACY_REGRESSION_MARKERS)
            else "new_availability"
        )
        sections.append((modality, change_type, paragraph))
    return sections


def _legacy_modality_counts(narrative: str) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for modality, change_type, paragraph in _legacy_rule_sections(narrative):
        match = re.search(r"\(([\d,]+) signals?;", paragraph)
        if not match:
            continue
        modality_counts = counts.setdefault(
            modality,
            {"new_availability": 0, "regression": 0},
        )
        modality_counts[change_type] += _as_int(match.group(1).replace(",", ""))
    return counts


def _representative_changes(value: object, narrative: str = "") -> str:
    examples: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    items = value if isinstance(value, list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        change_type = str(item.get("change_type", ""))
        modality = str(item.get("modality", ""))
        feature = str(item.get("feature", ""))
        key = (change_type, modality, _normalized_feature_key(feature))
        if not feature or key in seen:
            continue
        seen.add(key)
        action = "was newly listed" if change_type == "new_availability" else "was no longer listed"
        coverage_delta = abs(_as_int(item.get("feature_coverage_delta")))
        region = str(item.get("region", "")).strip()
        if coverage_delta > 1:
            location = f"in {coverage_delta:,} regions"
        elif region:
            location = f"in {region}"
        else:
            location = "in the monitored catalog"
        examples.append(f"{_plain_feature_name(feature)} {action} {location}")
        if len(examples) == 3:
            break
    for modality, change_type, paragraph in _legacy_rule_sections(narrative):
        if len(examples) == 3:
            break
        example_match = re.search(r"Examples?:\s*([^;]+)", paragraph)
        if not example_match:
            continue
        identifiers = re.findall(r"\(([^()]*)\)", example_match.group(1))
        if not identifiers:
            continue
        feature = _legacy_feature_key(modality, identifiers[-1])
        key = (change_type, modality, _normalized_feature_key(feature))
        if key in seen:
            continue
        seen.add(key)
        action = (
            "was among the new regional listings"
            if change_type == "new_availability"
            else "was among the listings no longer present"
        )
        examples.append(f"{_plain_feature_name(feature)} {action}")
    return f"Representative changes: {'; '.join(examples)}." if examples else ""


def _legacy_feature_key(modality: str, identifier: str) -> str:
    prefixes = {
        "AKS extensions": "extensionTypes.",
        "AKS Kubernetes versions": "kubernetesVersions.",
        "Azure Functions": "runtimes.",
        "Azure AI models": "aiModels.",
        "Container Apps": "containerApps.",
        "VM SKUs": "vmSkus.",
    }
    return f"{prefixes.get(modality, '')}{identifier}"


def _normalized_feature_key(feature: str) -> str:
    return feature.lower().replace("vmskus.standard.", "vmskus.")


def _plain_feature_name(feature: str) -> str:
    if feature.startswith("aiModels."):
        parts = feature.removeprefix("aiModels.").split(".")
        publisher = parts[0] if parts else "unknown"
        model_parts = parts[1:-1] if len(parts) > 2 else parts[1:]
        model = ".".join(model_parts) or "unknown"
        version = parts[-1] if len(parts) > 2 else ""
        publisher_name = {
            "anthropic": "Anthropic",
            "meta": "Meta",
            "microsoft": "Microsoft",
            "moonshotai": "Moonshot AI",
            "openai": "OpenAI",
            "xai": "xAI",
        }.get(publisher.lower(), publisher)
        version_text = f" (version {version})" if version else ""
        return f"{_display_model_name(model)} model from {publisher_name}{version_text}"
    if feature.startswith("vmSkus."):
        sku = " ".join(
            part.capitalize()
            for part in feature.removeprefix("vmSkus.").split(".")
        )
        return f"{sku} VM size"
    if feature.startswith("kubernetesVersions."):
        return f"AKS {feature.removeprefix('kubernetesVersions.')}"
    if feature.startswith("extensionTypes."):
        return f"{feature.removeprefix('extensionTypes.')} AKS extension"
    if feature.startswith("runtimes."):
        return f"{feature.removeprefix('runtimes.').replace('.', ' ')} Functions runtime"
    if feature.startswith("containerApps."):
        return f"{feature.removeprefix('containerApps.')} Container Apps capability"
    return feature


def _display_model_name(model: str) -> str:
    parts = model.split("-")
    display_parts = []
    for part in parts:
        lowered = part.lower()
        if lowered == "gpt":
            display_parts.append("GPT")
        elif re.fullmatch(r"k\d+", lowered):
            display_parts.append(lowered.upper())
        elif lowered in {
            "astra",
            "claude",
            "fable",
            "haiku",
            "kimi",
            "mythos",
            "opus",
            "sonnet",
        }:
            display_parts.append(lowered.title())
        else:
            display_parts.append(part)
    if len(display_parts) >= 2 and display_parts[0] == "GPT":
        return "-".join(display_parts[:2]) + (
            f" {' '.join(display_parts[2:])}" if len(display_parts) > 2 else ""
        )
    return " ".join(display_parts)


def _excerpt(post: dict[str, Any]) -> str:
    authored = str(post.get("excerpt", "")).strip()
    if authored:
        return authored
    body = " ".join(post.get("paragraphs", []))
    if not body:
        return ""
    if len(body) <= _EXCERPT_CHARS:
        return body
    return body[:_EXCERPT_CHARS].rsplit(" ", 1)[0].rstrip(",.;:") + "…"


def render_daily_summary_paragraphs(summary: str) -> str:
    labels = (
        "Where it changed:",
        "Representative changes:",
        "What changed:",
        "What this means:",
    )
    paragraphs = []
    for paragraph in summary.split("\n\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        label = next((candidate for candidate in labels if paragraph.startswith(candidate)), "")
        if label:
            remainder = paragraph.removeprefix(label).strip()
            paragraphs.append(
                f'<p class="daily-summary-text"><strong>{html.escape(label)}</strong> '
                f"{html.escape(remainder)}</p>"
            )
        else:
            paragraphs.append(f'<p class="daily-summary-text">{html.escape(paragraph)}</p>')
    return "".join(paragraphs)


def render_social_drafts(
    posts: list[dict[str, Any]],
    site_url: str,
    limit: int = _SOCIAL_POST_LIMIT,
) -> str:
    """Return review-only social post drafts for the latest narrated days."""

    sections = [
        "## Social post drafts",
        (
            "Review-only drafts generated from the daily blog narrative and structured change "
            "evidence. Availability claims are read-only catalog/list signals from this monitor; "
            "`unavailable` means absent from the monitored evidence, not proof of quota, capacity, "
            "deployment failure, or SLA impact. Drafts are rendered from the daily editorial "
            "package, with a structured fallback for older history entries."
        ),
    ]
    selected = posts[: max(limit, 0)]
    if not selected:
        sections.append("No narrated blog posts were available for social drafts.")
        return "\n\n".join(sections) + "\n"

    for post in selected:
        url = f"{site_url.rstrip('/')}/{post['slug']}"
        package = post.get("social_drafts")
        if isinstance(package, dict) and all(
            isinstance(package.get(name), str) and package[name].strip()
            for name in ("linkedin", "short_post")
        ):
            linkedin = _social_with_digest(package["linkedin"], url)
            short_post = _social_with_digest(package["short_post"], url)
            source = "Editorial package"
        else:
            linkedin = _linkedin_draft(post, url)
            short_post = _short_post_draft(post, url)
            source = "Structured legacy fallback"
        sections.extend(
            [
                f"### {post['date']} - {post['title']}",
                f"Source: {source}",
                "#### LinkedIn draft",
                f"```text\n{linkedin}\n```",
                "#### Short-post draft",
                f"```text\n{short_post}\n```",
            ]
        )
    return "\n\n".join(sections) + "\n"


def _social_with_digest(text: str, url: str) -> str:
    result = text.strip()
    if _SOCIAL_EVIDENCE_NOTE not in result:
        result = f"{result}\n\n{_SOCIAL_EVIDENCE_NOTE}"
    if url not in result:
        result = f"{result}\n\nFull digest: {url}"
    return result


def _linkedin_draft(post: dict[str, Any], url: str) -> str:
    lines = [
        f"Azure regional availability changed on {post['date']}: {post['title']}.",
    ]
    excerpt = _excerpt(post)
    if excerpt:
        lines.extend(["", excerpt])

    lines.extend(
        [
            "",
            "Signal counts:",
            f"- {post['new_availability']:,} new availability signals",
            f"- {post['regressions']:,} regressions",
            f"- {post['parked_unknown']:,} parked unknown transitions",
        ]
    )
    bullets = _social_highlight_bullets(post)
    if bullets:
        lines.extend(["", "Engineering context:"])
        lines.extend(f"- {bullet}" for bullet in bullets)
    lines.extend(
        [
            "",
            _SOCIAL_EVIDENCE_NOTE,
            "",
            f"Full digest: {url}",
        ]
    )
    return "\n".join(lines)


def _short_post_draft(post: dict[str, Any], url: str) -> str:
    counts = (
        f"{post['new_availability']:,} new availability, "
        f"{post['regressions']:,} regressions, "
        f"{post['parked_unknown']:,} parked unknown."
    )
    highlight = _top_social_highlight(post)
    context = f" {highlight}" if highlight else ""
    return (
        f"Azure regional availability watch ({post['date']}): {counts}{context}\n\n"
        f"Read-only catalog/list evidence, not quota or SLA proof.\n{url}"
    )


def _social_highlight_bullets(post: dict[str, Any], limit: int = 4) -> list[str]:
    bullets: list[str] = []
    highlights = post.get("highlights", [])
    if not isinstance(highlights, list):
        return bullets
    for item in highlights:
        if not isinstance(item, dict):
            continue
        bullets.extend(_social_bullets_for_highlight(item))
        if len(bullets) >= limit:
            return bullets[:limit]
    return bullets


def _top_social_highlight(post: dict[str, Any]) -> str:
    bullets = _social_highlight_bullets(post, limit=1)
    return bullets[0] if bullets else ""


def _social_bullets_for_highlight(item: dict[str, Any]) -> list[str]:
    region = str(item.get("region") or "").strip()
    feature = str(item.get("feature") or "").strip()
    previous = str(item.get("previous") or "absent")
    current = str(item.get("current") or "absent")
    classification = str(item.get("classification_label") or "").strip()
    expansion = str(item.get("expansion_label") or "").strip()
    bullets: list[str] = []
    if region and feature:
        suffix = f" ({classification})" if classification else ""
        bullets.append(f"{region}: {feature} moved {previous} -> {current}{suffix}.")
    if expansion:
        bullets.append(f"Rollout pattern: {expansion}.")

    coverage = _social_coverage(item)
    if coverage:
        bullets.append(coverage)
    stability = _social_stability(item)
    if stability:
        bullets.append(stability)

    still_available = _as_str_list(item.get("still_available_regions"))
    if str(item.get("change_type") or "") == "regression" and still_available:
        bullets.append(f"Fallback signal remains in {_sample_regions(still_available)}.")
    return bullets


def _social_coverage(item: dict[str, Any]) -> str:
    current_regions = _as_int(item.get("feature_current_available_regions"))
    total_regions = _as_int(item.get("feature_total_regions"))
    coverage_pct = _as_float(item.get("feature_current_coverage_pct"))
    coverage_delta = _as_int(item.get("feature_coverage_delta"))
    if total_regions <= 0:
        return ""
    delta = f", {coverage_delta:+d} {_plural(abs(coverage_delta), 'region')}" if coverage_delta else ""
    return f"Coverage: {current_regions}/{total_regions} monitored regions ({_format_pct(coverage_pct)}{delta})."


def _social_stability(item: dict[str, Any]) -> str:
    history_days = _as_int(item.get("history_days"))
    missing_days = _as_int(item.get("missing_days"))
    unavailable_pct = _as_float(item.get("unavailable_pct"))
    prior_disappearances = _as_int(item.get("prior_disappearances"))
    if history_days <= 0 and prior_disappearances <= 0:
        return ""
    parts = []
    if history_days > 0:
        parts.append(
            f"unavailable {missing_days}/{history_days} prior days ({_format_pct(unavailable_pct)})"
        )
    if prior_disappearances > 0:
        parts.append(
            f"{prior_disappearances} prior {_plural(prior_disappearances, 'disappearance')}"
        )
    return "Stability: " + "; ".join(parts) + "."


def _source_label(source: str) -> str:
    return "AI summary" if source == "ai" else "Auto summary"


def _counts_line(post: dict[str, Any]) -> str:
    return (
        f'<span class="blog-count blog-count-new">{post["new_availability"]:,} new</span>'
        f'<span class="blog-count blog-count-regression">{post["regressions"]:,} regressions</span>'
        f'<span class="blog-count blog-count-parked">{post["parked_unknown"]:,} parked</span>'
    )


def _page(
    title: str,
    description: str,
    canonical: str,
    site_url: str,
    style_block: str,
    body: str,
    *,
    page_type: str = "website",
    structured_data: dict[str, Any] | None = None,
) -> str:
    metadata = _social_metadata(title, description, canonical, page_type)
    json_ld = _json_ld_script(structured_data)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="{html.escape(description)}">
  <title>{html.escape(title)}</title>
  <link rel="canonical" href="{html.escape(canonical)}">
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <link rel="alternate" type="application/rss+xml" title="Azure regional changes feed" href="{html.escape(site_url)}/{FEED_PATH}">
    {metadata}
    {json_ld}
  {style_block}
</head>
<body>
  <main id="main-content" class="content-page">
{body}
  </main>
</body>
</html>
"""


def _social_metadata(title: str, description: str, canonical: str, page_type: str) -> str:
    return "\n  ".join(
        [
            '<meta property="og:site_name" content="Azure Regional Feature Availability Monitor">',
            f'<meta property="og:type" content="{html.escape(page_type)}">',
            f'<meta property="og:title" content="{html.escape(title)}">',
            f'<meta property="og:description" content="{html.escape(description)}">',
            f'<meta property="og:url" content="{html.escape(canonical)}">',
            '<meta name="twitter:card" content="summary">',
            f'<meta name="twitter:title" content="{html.escape(title)}">',
            f'<meta name="twitter:description" content="{html.escape(description)}">',
        ]
    )


def _json_ld_script(data: dict[str, Any] | None) -> str:
    if not data:
        return ""
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True).replace("</", "<\\/")
    return f'<script type="application/ld+json">{payload}</script>'


def _nav() -> str:
    return """      <nav class="links" aria-label="Dashboard links">
        <a href="/index.html">Summary</a>
        <a href="/heatmap.html">Detailed heatmap</a>
        <a href="/latency.html">Model latency</a>
        <a href="/methodology.html">Status meanings</a>
                <a href="/insights/">Insights</a>
        <a href="/blog/feed.xml">RSS feed</a>
      </nav>"""


def render_blog_index(posts: list[dict[str, Any]], site_url: str, style_block: str) -> str:
    canonical = f"{site_url}/{BLOG_DIR}/"
    summary = str(posts[0].get("executive_summary", "")) if posts else ""
    context = str(posts[0].get("weekly_context", "")) if posts else ""
    trend_section = _render_executive_summary(summary, context)
    if posts:
        cards = "\n".join(_render_index_card(post) for post in posts)
        body_inner = f'<div class="blog-list">{cards}</div>'
    else:
        body_inner = (
            '<div class="note" role="note">No change summaries have been published yet. '
            "The blog fills in automatically as the daily scan detects region changes.</div>"
        )
    body = f"""    <header>
      <div>
        <h1>Azure Regional Changes — Daily Blog</h1>
        <div class="timestamp">A short daily post on what changed across Azure regions</div>
      </div>
{_nav()}
    </header>
    <div class="note" role="note">
      Each post summarizes the day's region availability changes — new rollouts, likely
      deprecations, and latency shifts — written from the monitor's structured evidence.
      Subscribe via the <a href="/blog/feed.xml">RSS feed</a>.
    </div>
    {trend_section}
    <section class="panel" aria-label="Daily change posts">
      {body_inner}
    </section>"""
    return _page(
        "Azure Regional Changes — Daily Blog",
        "Daily summaries of Azure regional availability changes: rollouts, deprecations, and latency shifts.",
        canonical,
        site_url,
        style_block,
        body,
        structured_data={
            "@context": "https://schema.org",
            "@type": "Blog",
            "name": "Azure Regional Changes Daily Blog",
            "description": "Daily summaries of Azure regional availability changes from read-only catalog and listing evidence.",
            "url": canonical,
        },
    )


def _render_index_card(post: dict[str, Any]) -> str:
    excerpt = _excerpt(post)
    excerpt_html = f'<p class="blog-card-excerpt">{html.escape(excerpt)}</p>' if excerpt else ""
    return f"""<article class="blog-card">
        <div class="blog-card-meta">
          <time datetime="{html.escape(post['date'])}">{html.escape(post['date'])}</time>
          <span class="narrative-badge">{html.escape(_source_label(post['source']))}</span>
        </div>
        <h2 class="blog-card-title"><a href="/{html.escape(post['slug'])}">{html.escape(post['title'])}</a></h2>
        {excerpt_html}
        <div class="blog-card-counts">{_counts_line(post)}</div>
        <a class="blog-readmore" href="/{html.escape(post['slug'])}">Read the full post →</a>
      </article>"""


def render_blog_post(
    post: dict[str, Any],
    newer: dict[str, Any] | None,
    older: dict[str, Any] | None,
    site_url: str,
    style_block: str,
) -> str:
    canonical = f"{site_url}/{post['slug']}"
    headline = post["headline"] or post["title"]
    paragraphs = "".join(f"<p>{html.escape(p)}</p>" for p in post["paragraphs"])
    if not paragraphs:
        paragraphs = f"<p>{html.escape(post['title'])}</p>"
    highlights = _render_highlights(post.get("highlights", []))
    prev_next = _render_prev_next(newer, older)
    trend_section = _render_executive_summary(
        str(post.get("executive_summary", "")),
        str(post.get("weekly_context", "")),
    )
    body = f"""    <header>
      <div>
        <h1 class="blog-post-title">{html.escape(headline)}</h1>
        <div class="timestamp">
          <time datetime="{html.escape(post['date'])}">{html.escape(post['date'])}</time>
          &middot; <span class="narrative-badge">{html.escape(_source_label(post['source']))}</span>
        </div>
      </div>
{_nav()}
    </header>
    <article class="panel blog-post">
      <div class="blog-post-counts">{_counts_line(post)}</div>
      {trend_section}
            <div class="blog-post-body">{paragraphs}</div>
      {highlights}
    </article>
    {prev_next}
    <section class="panel" aria-label="About this blog">
      <p class="panel-subtitle" style="padding: 0 2px;">Generated from the monitor's structured change evidence.
      See the <a href="/methodology.html">status meanings</a> for what each signal proves, or browse
      <a href="/blog/">all posts</a>.</p>
    </section>"""
    return _page(
        f"{post['title']} | Azure regional availability {post['date']}",
        _excerpt(post) or f"Azure regional availability changes for {post['date']}.",
        canonical,
        site_url,
        style_block,
        body,
        page_type="article",
        structured_data=_blog_post_json_ld(post, canonical),
    )


def _render_executive_summary(summary: str, context: str = "") -> str:
    if not summary:
        return ""
    context_html = (
        f'<p class="weekly-context"><strong>7-day context</strong> '
        f'{html.escape(context.removeprefix("7-day context "))}</p>'
        if context
        else ""
    )
    summary_html = render_daily_summary_paragraphs(summary)
    return (
        '<section class="daily-summary blog-daily-summary" aria-label="Daily executive summary">'
        '<span class="daily-summary-kicker">Daily executive summary</span>'
        f"{summary_html}{context_html}"
        "</section>"
    )


def _blog_post_json_ld(post: dict[str, Any], canonical: str) -> dict[str, Any]:
    description = _excerpt(post) or f"Azure regional availability changes for {post['date']}."
    return {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": post["title"],
        "description": description,
        "datePublished": post["date"],
        "dateModified": post["date"],
        "mainEntityOfPage": canonical,
        "url": canonical,
        "author": {
            "@type": "Organization",
            "name": "Azure Regional Feature Availability Monitor",
        },
        "publisher": {
            "@type": "Organization",
            "name": "Azure Regional Feature Availability Monitor",
        },
        "keywords": _post_keywords(post),
    }


def _post_keywords(post: dict[str, Any]) -> list[str]:
    keywords = {
        "Azure regional availability",
        "Azure region rollout",
        "Azure availability monitor",
    }
    for item in post.get("highlights", [])[:8]:
        if not isinstance(item, dict):
            continue
        for key in ("modality", "group", "feature", "region"):
            value = str(item.get(key, "")).strip()
            if value:
                keywords.add(value)
    return sorted(keywords)


def _render_highlights(highlights: list[Any]) -> str:
    items = []
    for item in highlights[:12]:
        if not isinstance(item, dict):
            continue
        region = str(item.get("region", ""))
        feature = str(item.get("feature", ""))
        previous = str(item.get("previous", ""))
        current = str(item.get("current", ""))
        change_type = str(item.get("change_type", ""))
        classification = str(item.get("classification_label", "")).strip()
        classification_badge = (
            f' <span class="blog-change-context">{html.escape(classification)}</span>'
            if classification
            else ""
        )
        css = "blog-change"
        if change_type == "new_availability":
            css += " blog-change-new"
        elif change_type == "regression":
            css += " blog-change-regression"
        metrics = _render_change_metrics(item)
        details = _render_change_details(item)
        items.append(
            f'<li class="{css}"><div class="blog-change-main"><code>{html.escape(region)}</code> '
            f"{html.escape(feature)} <span class=\"blog-change-arrow\">{html.escape(previous)} → "
            f"{html.escape(current)}</span>{classification_badge}</div>{metrics}{details}</li>"
        )
    if not items:
        return ""
    rendered = "\n".join(items)
    return f"""<div class="blog-highlights">
        <h3>Engineering context</h3>
        <ul>{rendered}</ul>
      </div>"""


def _render_change_metrics(item: dict[str, Any]) -> str:
    metrics: list[str] = []
    history_days = _as_int(item.get("history_days"))
    missing_days = _as_int(item.get("missing_days"))
    unavailable_pct = _as_float(item.get("unavailable_pct"))
    prior_disappearances = _as_int(item.get("prior_disappearances"))
    if history_days > 0:
        metrics.append(
            f"unavailable {missing_days}/{history_days} prior days ({_format_pct(unavailable_pct)})"
        )
    if prior_disappearances > 0:
        metrics.append(
            f"{prior_disappearances} prior {_plural(prior_disappearances, 'disappearance')}"
        )

    current_regions = _as_int(item.get("feature_current_available_regions"))
    total_regions = _as_int(item.get("feature_total_regions"))
    coverage_pct = _as_float(item.get("feature_current_coverage_pct"))
    coverage_delta = _as_int(item.get("feature_coverage_delta"))
    if total_regions > 0:
        delta = f", {coverage_delta:+d} {_plural(abs(coverage_delta), 'region')}" if coverage_delta else ""
        metrics.append(
            f"coverage {current_regions}/{total_regions} monitored regions ({_format_pct(coverage_pct)}{delta})"
        )

    deprecated_pct = _as_float(item.get("feature_deprecated_coverage_pct"))
    if deprecated_pct > 0:
        metrics.append(f"coverage removed from {_format_pct(deprecated_pct)} of prior regions")

    region_group = str(item.get("region_group") or "").strip()
    group_current = _as_int(item.get("region_group_current_available_regions"))
    group_previous = _as_int(item.get("region_group_previous_available_regions"))
    if region_group and group_current:
        metrics.append(f"{region_group}: {group_current} current, {group_previous} prior")

    expansion = str(item.get("expansion_label") or "").strip()
    if expansion:
        metrics.append(expansion)

    if not metrics:
        return ""
    spans = "".join(f"<span>{html.escape(metric)}</span>" for metric in metrics)
    return f'<div class="blog-change-metrics">{spans}</div>'


def _render_change_details(item: dict[str, Any]) -> str:
    details: list[str] = []
    same_day_regions = _as_str_list(item.get("same_day_new_regions"))
    if same_day_regions:
        details.append(f"Also newly available in {_sample_regions(same_day_regions)}.")
    still_available = _as_str_list(item.get("still_available_regions"))
    change_type = str(item.get("change_type") or "")
    if change_type == "regression" and still_available:
        details.append(f"Still available in {_sample_regions(still_available)}.")
    note = str(item.get("feature_note") or "").strip()
    if note:
        details.append(note)

    details_url = str(item.get("details_url") or "").strip()
    details_label = str(item.get("details_label") or "Learn more").strip()
    if details_url:
        details.append(
            f'<a class="blog-change-link" href="{html.escape(details_url)}">{html.escape(details_label)}</a>'
        )

    if not details:
        return ""
    return '<div class="blog-change-details">' + " ".join(_render_detail(detail) for detail in details) + "</div>"


def _render_detail(detail: str) -> str:
    if detail.startswith('<a class="blog-change-link"'):
        return detail
    return html.escape(detail)


def _sample_regions(regions: list[str], limit: int = 6) -> str:
    shown = regions[:limit]
    rendered = ", ".join(shown)
    remaining = len(regions) - len(shown)
    if remaining > 0:
        rendered += f", and {remaining} more"
    return rendered


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _format_pct(value: float) -> str:
    return f"{value:.1f}%"


def _plural(count: int, word: str) -> str:
    return word if count == 1 else f"{word}s"


def _render_prev_next(newer: dict[str, Any] | None, older: dict[str, Any] | None) -> str:
    # "newer" is the more recent post; "older" is the previous day.
    left = (
        f'<a class="blog-nav-prev" href="/{html.escape(older["slug"])}">← {html.escape(older["date"])}</a>'
        if older
        else "<span></span>"
    )
    right = (
        f'<a class="blog-nav-next" href="/{html.escape(newer["slug"])}">{html.escape(newer["date"])} →</a>'
        if newer
        else "<span></span>"
    )
    return f"""<nav class="blog-post-nav" aria-label="Post navigation">
      {left}
      <a class="blog-nav-index" href="/blog/">All posts</a>
      {right}
    </nav>"""


def render_blog_feed(posts: list[dict[str, Any]], site_url: str, limit: int = 50) -> str:
    now = format_datetime(datetime.now(timezone.utc))
    items = "\n".join(_render_feed_item(post, site_url) for post in posts[:limit])
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Azure Regional Changes — Daily Blog</title>
    <link>{html.escape(site_url)}/{BLOG_DIR}/</link>
    <atom:link xmlns:atom="http://www.w3.org/2005/Atom" href="{html.escape(site_url)}/{FEED_PATH}" rel="self" type="application/rss+xml"/>
    <description>Daily summaries of Azure regional availability changes: rollouts, deprecations, and latency shifts.</description>
    <language>en</language>
    <lastBuildDate>{now}</lastBuildDate>
{items}
  </channel>
</rss>
"""


def _render_feed_item(post: dict[str, Any], site_url: str) -> str:
    url = f"{site_url}/{post['slug']}"
    description = _excerpt(post) or post["title"]
    return f"""    <item>
      <title>{html.escape(post['title'])}</title>
      <link>{html.escape(url)}</link>
      <guid isPermaLink="true">{html.escape(url)}</guid>
      <pubDate>{_pub_date(post['date'])}</pubDate>
      <description>{html.escape(description)}</description>
    </item>"""


def _pub_date(date: str) -> str:
    try:
        parsed = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        parsed = datetime.now(timezone.utc)
    return format_datetime(parsed)


def blog_sitemap_entries(posts: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    """Return (path, priority, lastmod) sitemap rows for the blog index and posts."""

    if not posts:
        return []
    newest = posts[0]["date"]
    entries: list[tuple[str, str, str]] = [(f"/{BLOG_DIR}/", "0.8", newest)]
    for post in posts:
        entries.append((f"/{post['slug']}", "0.6", post["date"]))
    return entries
