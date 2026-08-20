"""Static daily changelog blog generated from the change-history narratives.

Pure and offline-testable: callers pass the history days (from
``api/history/index.json``) plus the site URL and a shared CSS block, and get
back HTML pages, an RSS feed, and sitemap entries. No I/O happens here.
"""

from __future__ import annotations

import html
from importlib import resources
import json
import re
from datetime import datetime, timezone
from email.utils import format_datetime
from typing import Any, Protocol

BLOG_DIR = "blog"
FEED_PATH = "blog/feed.xml"
INDEX_PATH = "blog/index.html"
_EXCERPT_CHARS = 220
_SOCIAL_POST_LIMIT = 1
_SOCIAL_LINKEDIN_MIN_CHARS = 700
_SOCIAL_LINKEDIN_MAX_CHARS = 2_800
_SOCIAL_SHORT_POST_MIN_CHARS = 180
_SOCIAL_SHORT_POST_MAX_CHARS = 600
_SOCIAL_MAX_HIGHLIGHTS = 4
_SOCIAL_NARRATIVE_MAX_CHARS = 1_600
_SOCIAL_MAX_REGION_SAMPLES = 5
_SOCIAL_EVIDENCE_NOTE = (
    "Evidence note: these are read-only Azure catalog/list signals; unavailable does not mean "
    "quota, capacity, deployment failure, or SLA impact."
)
_FALLBACK_SOCIAL_PROMPT = """You are an expert technical communications editor writing review-only social copy for Azure SREs, platform engineers, and cloud architects.

Write a useful, evidence-bound LinkedIn post and a concise short post from the structured daily Azure regional availability facts. Lead with the most operationally meaningful story, not a dump of raw counts. Explain the decision impact: placement, fallback, rollout timing, IaC assumptions, latency, scale, cost, or upgrade planning.

Strict truth rules:
- Treat available/unavailable as read-only catalog, listing, provider-metadata, or measurement evidence only.
- Never claim quota, live capacity, successful deployment, customer eligibility, root cause, or SLA impact.
- Call disappearance a deprecation candidate or recurring catalog instability only when the facts use that classification.
- Do not invent regions, numbers, model capabilities, causes, or customer impact.

Return only a JSON object with exactly these string fields:
{"linkedin": "...", "short_post": "..."}

LinkedIn: 700-1,500 characters, 3-5 short paragraphs or bullets, no hashtags, must include the supplied full digest URL and the supplied evidence note verbatim.
Short post: 180-500 characters, concise, must include the full digest URL and a compact evidence note.
Both posts must name the supplied date and state all three supplied counts: new availability, regressions, and parked unknown transitions.
"""
# A real blog-post headline is short. Anything longer is almost certainly a
# single-paragraph rule/older summary, so it is demoted to body text and the post
# gets a clean date-based title instead of a runaway one-line headline.
_MAX_HEADLINE_CHARS = 110


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
    headline, rest = "", blocks
    if source == "ai" and blocks:
        headline, rest = blocks[0], blocks[1:]
        if not rest and "\n" in headline:
            first, remainder = headline.split("\n", 1)
            headline, rest = first.strip(), [remainder.strip()]
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
            }
        )
    posts.sort(key=lambda post: post["date"], reverse=True)
    return posts


def _excerpt(post: dict[str, Any]) -> str:
    body = " ".join(post.get("paragraphs", []))
    if not body:
        return ""
    if len(body) <= _EXCERPT_CHARS:
        return body
    return body[:_EXCERPT_CHARS].rsplit(" ", 1)[0].rstrip(",.;:") + "…"


class SocialDraftClient(Protocol):
    def generate(self, *, system: str, user: str) -> str:
        """Return a social-copy JSON object or raise on failure."""


def render_social_drafts(
    posts: list[dict[str, Any]],
    site_url: str,
    limit: int = _SOCIAL_POST_LIMIT,
    client: SocialDraftClient | None = None,
) -> str:
    """Return review-only social post drafts for the latest narrated days."""

    sections = [
        "## Social post drafts",
        (
            "Review-only drafts generated from the daily blog narrative and structured change "
            "evidence. Availability claims are read-only catalog/list signals from this monitor; "
            "`unavailable` means absent from the monitored evidence, not proof of quota, capacity, "
            "deployment failure, or SLA impact. AI social copy falls back to a structured template "
            "if the configured model is unavailable."
        ),
    ]
    selected = posts[: max(limit, 0)]
    if not selected:
        sections.append("No narrated blog posts were available for social drafts.")
        return "\n\n".join(sections) + "\n"

    for post in selected:
        url = f"{site_url.rstrip('/')}/{post['slug']}"
        ai_drafts = _generate_ai_social_drafts(post, url, client)
        linkedin = ai_drafts["linkedin"] if ai_drafts else _linkedin_draft(post, url)
        short_post = ai_drafts["short_post"] if ai_drafts else _short_post_draft(post, url)
        source = "AI social copy" if ai_drafts else "Structured fallback"
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


def _generate_ai_social_drafts(
    post: dict[str, Any],
    url: str,
    client: SocialDraftClient | None,
) -> dict[str, str] | None:
    if client is None:
        return None
    try:
        response = client.generate(system=_load_social_prompt(), user=_social_facts(post, url)).strip()
    except Exception:
        return None
    return _parse_social_drafts(response, post, url)


def _load_social_prompt() -> str:
    try:
        prompt = (
            resources.files("azure_region_monitor.prompts")
            .joinpath("social_drafts.md")
            .read_text(encoding="utf-8")
            .strip()
        )
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        return _FALLBACK_SOCIAL_PROMPT
    return prompt or _FALLBACK_SOCIAL_PROMPT


def _social_facts(post: dict[str, Any], url: str) -> str:
    facts = {
        "date": post["date"],
        "title": post["title"],
        "narrative": _social_narrative(post),
        "counts": {
            "new_availability": post["new_availability"],
            "regressions": post["regressions"],
            "parked_unknown": post["parked_unknown"],
        },
        "highlights": _compact_social_highlights(post.get("highlights", [])),
        "full_digest_url": url,
        "evidence_note": _SOCIAL_EVIDENCE_NOTE,
    }
    return "Structured facts (use only these facts):\n" + json.dumps(
        facts, ensure_ascii=False, sort_keys=True
    )


def _social_narrative(post: dict[str, Any]) -> str:
    narrative = "\n\n".join(post.get("paragraphs", []))
    if len(narrative) <= _SOCIAL_NARRATIVE_MAX_CHARS:
        return narrative
    return narrative[:_SOCIAL_NARRATIVE_MAX_CHARS].rsplit(" ", 1)[0].rstrip(".,;:") + "…"


def _compact_social_highlights(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    keys = (
        "region",
        "feature",
        "previous",
        "current",
        "change_type",
        "classification_label",
        "expansion_label",
        "history_days",
        "missing_days",
        "unavailable_pct",
        "prior_disappearances",
        "feature_total_regions",
        "feature_previous_available_regions",
        "feature_current_available_regions",
        "feature_current_coverage_pct",
        "feature_coverage_delta",
        "feature_deprecated_coverage_pct",
        "region_group",
        "region_group_current_available_regions",
        "region_group_previous_available_regions",
    )
    highlights: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        compact = {key: item[key] for key in keys if key in item}
        for list_key in ("same_day_new_regions", "still_available_regions"):
            regions = _as_str_list(item.get(list_key))
            if regions:
                compact[list_key] = regions[:_SOCIAL_MAX_REGION_SAMPLES]
        highlights.append(compact)
        if len(highlights) >= _SOCIAL_MAX_HIGHLIGHTS:
            break
    return highlights


def _parse_social_drafts(
    response: str, post: dict[str, Any], url: str
) -> dict[str, str] | None:
    text = response.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    linkedin = _validated_social_copy(
        payload.get("linkedin"),
        post,
        url,
        _SOCIAL_LINKEDIN_MIN_CHARS,
        _SOCIAL_LINKEDIN_MAX_CHARS,
    )
    short_post = _validated_social_copy(
        payload.get("short_post"),
        post,
        url,
        _SOCIAL_SHORT_POST_MIN_CHARS,
        _SOCIAL_SHORT_POST_MAX_CHARS,
    )
    if not linkedin or not short_post:
        return None
    return {"linkedin": linkedin, "short_post": short_post}


def _validated_social_copy(
    value: object,
    post: dict[str, Any],
    url: str,
    minimum_length: int,
    maximum_length: int,
) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) < minimum_length or len(text) > maximum_length:
        return None
    if url not in text:
        text = f"{text}\n\n{url}"
    if not _has_social_evidence_note(text):
        text = f"{text}\n\n{_SOCIAL_EVIDENCE_NOTE}"
    if len(text) > maximum_length or not _has_daily_social_evidence(text, post):
        return None
    return text


def _has_social_evidence_note(text: str) -> bool:
    normalized = " ".join(text.lower().split())
    return (
        "read-only" in normalized
        and "catalog/list" in normalized
        and "unavailable does not mean quota" in normalized
        and "capacity" in normalized
        and "deployment failure" in normalized
        and "sla impact" in normalized
    )


def _has_daily_social_evidence(text: str, post: dict[str, Any]) -> bool:
    normalized = " ".join(text.lower().split())
    required = (
        str(post["date"]).lower(),
        f"{post['new_availability']:,} new availability",
        f"{post['regressions']:,} regressions",
        f"{post['parked_unknown']:,} parked unknown",
    )
    return all(fact in normalized for fact in required)


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
    description = " ".join(post["paragraphs"]) or post["title"]
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
