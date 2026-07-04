"""Static daily changelog blog generated from the change-history narratives.

Pure and offline-testable: callers pass the history days (from
``api/history/index.json``) plus the site URL and a shared CSS block, and get
back HTML pages, an RSS feed, and sitemap entries. No I/O happens here.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from email.utils import format_datetime
from typing import Any

BLOG_DIR = "blog"
FEED_PATH = "blog/feed.xml"
INDEX_PATH = "blog/index.html"
_EXCERPT_CHARS = 220
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


def _source_label(source: str) -> str:
    return "AI summary" if source == "ai" else "Auto summary"


def _counts_line(post: dict[str, Any]) -> str:
    return (
        f'<span class="blog-count blog-count-new">{post["new_availability"]:,} new</span>'
        f'<span class="blog-count blog-count-regression">{post["regressions"]:,} regressions</span>'
        f'<span class="blog-count blog-count-parked">{post["parked_unknown"]:,} parked</span>'
    )


def _page(title: str, description: str, canonical: str, site_url: str, style_block: str, body: str) -> str:
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
  {style_block}
</head>
<body>
  <main class="content-page">
{body}
  </main>
</body>
</html>
"""


def _nav() -> str:
    return """      <nav class="links" aria-label="Dashboard links">
        <a href="/index.html">Summary</a>
        <a href="/heatmap.html">Detailed heatmap</a>
        <a href="/latency.html">Model latency</a>
        <a href="/methodology.html">Status meanings</a>
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
        post["title"],
        _excerpt(post) or f"Azure regional changes for {post['date']}.",
        canonical,
        site_url,
        style_block,
        body,
    )


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
        items.append(
            f'<li class="{css}"><code>{html.escape(region)}</code> {html.escape(feature)} '
            f"<span class=\"blog-change-arrow\">{html.escape(previous)} → "
            f"{html.escape(current)}</span>{classification_badge}</li>"
        )
    if not items:
        return ""
    rendered = "\n".join(items)
    return f"""<div class="blog-highlights">
        <h3>Notable changes</h3>
        <ul>{rendered}</ul>
      </div>"""


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
