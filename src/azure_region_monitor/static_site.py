from __future__ import annotations

import html
import json
import re
import shutil
from pathlib import Path
from typing import Any

from azure_region_monitor.blog import (
    blog_sitemap_entries,
    render_blog_feed,
    render_blog_index,
    render_blog_post,
    select_blog_posts,
)
from azure_region_monitor.history import copy_history_to_api
from azure_region_monitor.latency_view import (
    annotate_rank_changes,
    build_latency_rows,
    build_latency_series,
    build_regional_latency_rows,
    previous_leaderboard_ranks,
    previous_regional_ranks,
)
from azure_region_monitor.models import Snapshot
from azure_region_monitor.snapshot_shards import build_modality_shards, build_summary
from azure_region_monitor.storage import load_snapshot

# Dashboard styles live in a real stylesheet so design work is a reviewable CSS diff
# rather than an edit to a Python string literal.
DASHBOARD_CSS_PATH = Path(__file__).resolve().parent / "assets" / "dashboard.css"

_COUNTRY_NAMES = {
  "AE": "United Arab Emirates",
  "AT": "Austria",
  "AU": "Australia",
  "BE": "Belgium",
  "BR": "Brazil",
  "CA": "Canada",
  "CH": "Switzerland",
  "CL": "Chile",
  "CN": "China",
  "DE": "Germany",
  "DK": "Denmark",
  "ES": "Spain",
  "FI": "Finland",
  "FR": "France",
  "GB": "United Kingdom",
  "GR": "Greece",
  "HK": "Hong Kong",
  "ID": "Indonesia",
  "IE": "Ireland",
  "IL": "Israel",
  "IN": "India",
  "IT": "Italy",
  "JP": "Japan",
  "KR": "Korea",
  "MX": "Mexico",
  "MY": "Malaysia",
  "NL": "Netherlands",
  "NO": "Norway",
  "NZ": "New Zealand",
  "PL": "Poland",
  "PT": "Portugal",
  "QA": "Qatar",
  "SE": "Sweden",
  "SG": "Singapore",
  "TW": "Taiwan",
  "US": "United States",
  "ZA": "South Africa",
}

# Azure multi-country geographies. These region IDs cover a whole geography rather
# than a single country, so Azure itself names them "East Asia", "North Europe",
# etc. Showing them by their geography name (instead of the physical datacenter
# country such as Hong Kong or Ireland) matches Azure's naming and makes them
# recognizable and searchable as Asia/Europe regions across the dashboard.
_GEOGRAPHY_REGIONS = {
  "eastasia": {"name": "East Asia", "badge": "AS", "label": "E Asia"},
  "southeastasia": {"name": "Southeast Asia", "badge": "AS", "label": "SE Asia"},
  "northeurope": {"name": "North Europe", "badge": "EU", "label": "N Europe"},
  "westeurope": {"name": "West Europe", "badge": "EU", "label": "W Europe"},
}

_LARGE_EXTENSION_GROUP_THRESHOLD = 10
_PRIMARY_EXTENSION_GROUPS = {"microsoft"}
_SITE_URL = "https://azwatch.operator.lat"
_SITE_DESCRIPTION = (
  "Read-only Azure regional availability evidence for AKS, Azure Functions, "
  "Azure AI models, Container Apps, and VM SKUs."
)
_REPOSITORY_URL = "https://github.com/sergey-goncharenko/azure-region-monitor"
_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "base-uri 'self'; "
    "object-src 'none'; "
    "frame-ancestors 'none'; "
    "form-action 'none'; "
    "img-src 'self' data:; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "connect-src 'self'; "
    "upgrade-insecure-requests"
)
_SECURITY_HEADERS = {
    "Content-Security-Policy": _CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
    "magnetometer=(), microphone=(), payment=(), usb=()",
}
_API_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
    "Access-Control-Allow-Headers": "*",
    "Cache-Control": "public, must-revalidate, max-age=60",
}
_LATEST_SNAPSHOT_HEADERS = {
  **_API_HEADERS,
  "Content-Disposition": 'attachment; filename="azure-region-monitor-latest.json"',
}
_INSIGHT_PAGES = (
  {
    "slug": "azure-openai-regional-availability",
    "title": "Azure OpenAI Regional Availability Tracker",
    "description": "Evidence-based tracking of Azure OpenAI model availability by Azure region, including model rollout and delisting signals.",
    "categories": ("Azure AI models", "Azure model latency"),
    "keywords": "Azure OpenAI regional availability, Azure AI Foundry model regions, GPT model rollout",
  },
  {
    "slug": "azure-vm-sku-regional-availability",
    "title": "Azure VM SKU Regional Availability Tracker",
    "description": "Read-only VM SKU listing evidence by Azure region for capacity planning, right-sizing, and regional fallback analysis.",
    "categories": ("VM SKUs",),
    "keywords": "Azure VM SKU regional availability, Azure VM sizes by region, GPU VM availability",
  },
  {
    "slug": "aks-version-regional-rollout",
    "title": "AKS Version And Extension Regional Rollout Tracker",
    "description": "Regional rollout evidence for AKS Kubernetes versions and AKS extension catalog signals.",
    "categories": ("AKS Kubernetes versions", "AKS extensions"),
    "keywords": "AKS Kubernetes version availability, AKS regional rollout, AKS extensions by region",
  },
)


def build_static_site(
    output_dir: Path,
    snapshot_path: Path = Path("data/snapshots/latest.json"),
    diff_path: Path = Path("data/diffs/latest.json"),
    history_path: Path = Path("data/history"),
) -> None:
    snapshot = load_snapshot(snapshot_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    api_dir = output_dir / "api"
    api_dir.mkdir(parents=True, exist_ok=True)

    shutil.copyfile(snapshot_path, api_dir / "latest.json")
    if diff_path.exists():
        shutil.copyfile(diff_path, api_dir / "diff.json")
    copy_history_to_api(history_path, api_dir / "history")
    _write_snapshot_shards(api_dir, snapshot)

    recent_changes = _load_recent_changes(history_path)
    latency_history = _load_latency_history(history_path)
    latency_series = build_latency_series(latency_history)
    leaderboard_prev_ranks = previous_leaderboard_ranks(latency_history)
    regional_prev_ranks = previous_regional_ranks(latency_history)
    (output_dir / "index.html").write_text(
        _render_index(snapshot, recent_changes=recent_changes), encoding="utf-8"
    )
    (output_dir / "heatmap.html").write_text(_render_heatmap_page(snapshot), encoding="utf-8")
    (output_dir / "latency.html").write_text(
        _render_latency_page(
            snapshot,
            latency_series,
            leaderboard_prev_ranks=leaderboard_prev_ranks,
            regional_prev_ranks=regional_prev_ranks,
        ),
        encoding="utf-8",
    )
    (output_dir / "methodology.html").write_text(_render_methodology_page(snapshot), encoding="utf-8")
    blog_posts = select_blog_posts(_load_history_index(history_path))
    _write_blog(output_dir, blog_posts)
    _write_insights(output_dir, snapshot, blog_posts)
    _write_latency_api(api_dir, snapshot)
    _write_discovery_assets(
        output_dir, snapshot, recent_changes=recent_changes, blog_posts=blog_posts
    )
    _write_static_web_app_config(output_dir)


def _write_blog(output_dir: Path, posts: list[dict[str, Any]]) -> None:
    blog_dir = output_dir / "blog"
    blog_dir.mkdir(parents=True, exist_ok=True)
    style = _style_block()
    (blog_dir / "index.html").write_text(
        render_blog_index(posts, _SITE_URL, style), encoding="utf-8"
    )
    (blog_dir / "feed.xml").write_text(render_blog_feed(posts, _SITE_URL), encoding="utf-8")
    # posts are newest-first; "newer" is the previous item, "older" is the next item.
    for index, post in enumerate(posts):
        newer = posts[index - 1] if index > 0 else None
        older = posts[index + 1] if index + 1 < len(posts) else None
        (blog_dir / f"{post['date']}.html").write_text(
            render_blog_post(post, newer, older, _SITE_URL, style), encoding="utf-8"
        )


def _write_insights(output_dir: Path, snapshot: Snapshot, posts: list[dict[str, Any]]) -> None:
    insights_dir = output_dir / "insights"
    insights_dir.mkdir(parents=True, exist_ok=True)
    style = _style_block()
    (insights_dir / "index.html").write_text(
        _render_insights_index(snapshot, posts, style), encoding="utf-8"
    )
    for page in _INSIGHT_PAGES:
        (insights_dir / f"{page['slug']}.html").write_text(
            _render_insight_page(snapshot, posts, page, style), encoding="utf-8"
        )


def _load_history_index(history_path: Path) -> dict[str, Any] | None:
    index_path = history_path / "index.json"
    if not index_path.exists():
        return None
    try:
        return json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _write_discovery_assets(
    output_dir: Path,
    snapshot: Snapshot,
    recent_changes: dict[str, Any] | None = None,
    blog_posts: list[dict[str, Any]] | None = None,
) -> None:
    (output_dir / "favicon.svg").write_text(_render_favicon(), encoding="utf-8")
    (output_dir / "robots.txt").write_text(_render_robots_txt(), encoding="utf-8")
    (output_dir / "sitemap.xml").write_text(
        _render_sitemap(snapshot, blog_posts=blog_posts), encoding="utf-8"
    )
    (output_dir / "llms.txt").write_text(_render_llms_txt(snapshot), encoding="utf-8")
    (output_dir / "llms-full.txt").write_text(
        _render_llms_full_txt(snapshot, recent_changes=recent_changes), encoding="utf-8"
    )


def _write_static_web_app_config(output_dir: Path) -> None:
    config = {
        "globalHeaders": _SECURITY_HEADERS,
        "routes": [
          {
            "route": "/api/latest.json",
            "headers": _LATEST_SNAPSHOT_HEADERS,
          },
            {
                "route": "/api/*",
                "headers": _API_HEADERS,
            }
        ],
        "mimeTypes": {
            ".json": "application/json",
            ".gz": "application/gzip",
          ".svg": "image/svg+xml",
          ".txt": "text/plain; charset=utf-8",
          ".xml": "application/xml",
        },
    }
    (output_dir / "staticwebapp.config.json").write_text(
        json.dumps(config, indent=2) + "\n", encoding="utf-8"
    )


def _render_favicon() -> str:
    return """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="AZ">
  <rect width="64" height="64" rx="12" fill="#0f4c81"/>
  <path d="M13 46 25 18h7l12 28h-7l-2.2-5.7H22.1L20 46h-7Zm11.2-11.5h8.5L28.4 23l-4.2 11.5Z" fill="#f7fbff"/>
  <path d="M37 46v-5.1l12.7-17.1H38.2V18h20.1v5.1L45.7 40.2h12.9V46H37Z" fill="#9ee6c8"/>
</svg>
"""


def _render_robots_txt() -> str:
    return f"""User-agent: *
Allow: /

Sitemap: {_SITE_URL}/sitemap.xml
"""


def _render_sitemap(
    snapshot: Snapshot, blog_posts: list[dict[str, Any]] | None = None
) -> str:
    lastmod = _snapshot_lastmod(snapshot)
    urls = [
        ("/", "1.0", lastmod),
        ("/heatmap.html", "0.9", lastmod),
        ("/latency.html", "0.8", lastmod),
        ("/methodology.html", "0.8", lastmod),
        ("/llms.txt", "0.7", lastmod),
        ("/llms-full.txt", "0.7", lastmod),
        ("/api/latest.json", "0.6", lastmod),
        ("/api/summary.json", "0.6", lastmod),
        ("/api/latency.json", "0.6", lastmod),
        ("/api/modalities/manifest.json", "0.6", lastmod),
        ("/api/history/index.json", "0.5", lastmod),
    ]
    urls.append(("/insights/", "0.8", lastmod))
    for page in _INSIGHT_PAGES:
        urls.append((f"/insights/{page['slug']}.html", "0.7", lastmod))
    # Blog index + every dated post, so the changelog is discoverable via the sitemap.
    for path, priority, post_lastmod in blog_sitemap_entries(blog_posts or []):
        urls.append((path, priority, post_lastmod))
    entries = "\n".join(
        "  <url>\n"
        f"    <loc>{html.escape(_SITE_URL + path)}</loc>\n"
        f"    <lastmod>{html.escape(entry_lastmod)}</lastmod>\n"
        f"    <priority>{priority}</priority>\n"
        "  </url>"
        for path, priority, entry_lastmod in urls
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{entries}
</urlset>
"""


def _render_insights_index(snapshot: Snapshot, posts: list[dict[str, Any]], style: str) -> str:
    lastmod = _snapshot_lastmod(snapshot)
    cards = "\n".join(_render_insight_card(snapshot, page) for page in _INSIGHT_PAGES)
    latest_posts = _render_insight_recent_posts(posts[:5])
    description = (
        "Evergreen Azure regional availability guides for Azure OpenAI, VM SKUs, and AKS rollout evidence."
    )
    canonical = f"{_SITE_URL}/insights/"
    body = f"""    <header>
      <div>
        <h1>Azure Regional Availability Insights</h1>
        <div class="timestamp">Latest snapshot: {html.escape(snapshot.timestamp.isoformat())}</div>
      </div>
      {_insights_nav()}
    </header>
    {_render_alpha_notice(len(snapshot.regions))}
    <section class="panel prose" aria-label="About these insights">
      <div class="panel-header">
        <h2>Evergreen Search Guides</h2>
        <div class="panel-subtitle">Stable topic pages backed by the latest read-only monitor snapshot</div>
      </div>
      <div class="prose-body">
        <p>These pages turn the daily evidence stream into durable references for engineers searching for Azure regional availability, rollout, delisting, and fallback-planning signals.</p>
      </div>
    </section>
    <section class="insight-grid" aria-label="Insight topics">
      {cards}
    </section>
    {latest_posts}"""
    return _content_page(
        title="Azure Regional Availability Insights",
        description=description,
        canonical=canonical,
        style=style,
        body=body,
        structured_data={
            "@context": "https://schema.org",
            "@type": "CollectionPage",
            "name": "Azure Regional Availability Insights",
            "description": description,
            "url": canonical,
            "dateModified": lastmod,
        },
    )


def _render_insight_card(snapshot: Snapshot, page: dict[str, Any]) -> str:
    rows = _insight_rows(snapshot, page)
    statuses = _status_counts(rows)
    features = {str(row["feature"]) for row in rows}
    available = statuses.get("available", 0)
    checks = len(rows)
    available_pct = round(available / checks * 100) if checks else 0
    href = f"{html.escape(str(page['slug']))}.html"
    return f"""<article class="insight-card">
        <h2><a href="{href}">{html.escape(str(page['title']))}</a></h2>
        <p>{html.escape(str(page['description']))}</p>
        <div class="blog-card-counts">
          <span class="blog-count">{len(features):,} features</span>
          <span class="blog-count blog-count-new">{available_pct}% listed available</span>
          <span class="blog-count">{checks:,} checks</span>
        </div>
      </article>"""


def _render_insight_page(
    snapshot: Snapshot,
    posts: list[dict[str, Any]],
    page: dict[str, Any],
    style: str,
) -> str:
    rows = _insight_rows(snapshot, page)
    statuses = _status_counts(rows)
    groups = _feature_group_summaries(rows)[:12]
    features = {str(row["feature"]) for row in rows}
    regions = {str(row["region"]) for row in rows}
    checks = len(rows)
    available = statuses.get("available", 0)
    available_pct = round(available / checks * 100) if checks else 0
    canonical = f"{_SITE_URL}/insights/{page['slug']}.html"
    group_rows = "\n".join(_render_group_row(row) for row in groups) or _empty_table_row(5)
    related_posts = _render_insight_recent_posts(_related_insight_posts(posts, page))
    keywords = str(page["keywords"])
    body = f"""    <header>
      <div>
        <h1>{html.escape(str(page['title']))}</h1>
        <div class="timestamp">Latest snapshot: {html.escape(snapshot.timestamp.isoformat())}</div>
      </div>
      {_insights_nav()}
    </header>
    {_render_alpha_notice(len(snapshot.regions))}
    <section class="metrics" aria-label="Insight summary">
      {_render_metric("Features", len(features))}
      {_render_metric("Regions", len(regions))}
      {_render_metric("Checks", checks)}
      {_render_metric("Listed available", f"{available_pct}%")}
    </section>
    <section class="panel prose" aria-label="What this insight tracks">
      <div class="panel-header">
        <h2>What This Tracks</h2>
        <div class="panel-subtitle">{html.escape(keywords)}</div>
      </div>
      <div class="prose-body">
        <p>{html.escape(str(page['description']))}</p>
        <p>Read the data as catalog, listing, provider metadata, or latency-measurement evidence. It does not prove quota, live capacity, successful deployment, customer eligibility, or SLA.</p>
        <p>Use this page to decide which regions deserve closer deployment testing, IaC fallback review, or follow-up investigation.</p>
      </div>
    </section>
    <section class="panel" aria-label="Current feature groups">
      <div class="panel-header">
        <h2>Current Feature Groups</h2>
        <div class="panel-subtitle">Latest snapshot grouped for quick scanability</div>
      </div>
      <div class="table-wrap compact-table">
        <table>
          <thead>
            <tr>
              <th>Modality</th>
              <th>Group</th>
              <th class="number">Features</th>
              <th class="number">Available</th>
              <th class="number">Checks</th>
            </tr>
          </thead>
          <tbody>{group_rows}</tbody>
        </table>
      </div>
    </section>
    {related_posts}"""
    return _content_page(
        title=str(page["title"]),
        description=str(page["description"]),
        canonical=canonical,
        style=style,
        body=body,
        structured_data={
            "@context": "https://schema.org",
            "@type": "WebPage",
            "name": str(page["title"]),
            "description": str(page["description"]),
            "url": canonical,
            "keywords": keywords,
            "dateModified": _snapshot_lastmod(snapshot),
        },
    )


def _content_page(
    *,
    title: str,
    description: str,
    canonical: str,
    style: str,
    body: str,
    structured_data: dict[str, Any] | None = None,
) -> str:
    social = _page_social_metadata(title, description, canonical)
    json_ld = _structured_data_script(structured_data)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="{html.escape(description)}">
  <title>{html.escape(title)}</title>
  <link rel="canonical" href="{html.escape(canonical)}">
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <link rel="alternate" href="/llms.txt" type="text/plain" title="LLM guide">
  <link rel="alternate" type="application/rss+xml" title="Azure regional changes feed" href="/blog/feed.xml">
  {social}
  {json_ld}
  {style}
</head>
<body>
  <main id="main-content" class="content-page">
{body}
  </main>
</body>
</html>
"""


def _page_social_metadata(title: str, description: str, canonical: str) -> str:
    return "\n  ".join(
        [
            '<meta property="og:site_name" content="Azure Regional Feature Availability Monitor">',
            '<meta property="og:type" content="website">',
            f'<meta property="og:title" content="{html.escape(title)}">',
            f'<meta property="og:description" content="{html.escape(description)}">',
            f'<meta property="og:url" content="{html.escape(canonical)}">',
            '<meta name="twitter:card" content="summary">',
            f'<meta name="twitter:title" content="{html.escape(title)}">',
            f'<meta name="twitter:description" content="{html.escape(description)}">',
        ]
    )


def _structured_data_script(data: dict[str, Any] | None) -> str:
    if not data:
        return ""
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True).replace("</", "<\\/")
    return f'<script type="application/ld+json">{payload}</script>'


def _insights_nav() -> str:
    return """      <nav class="links" aria-label="Dashboard links">
        <a href="/index.html">Summary</a>
        <a href="/heatmap.html">Detailed heatmap</a>
        <a href="/methodology.html">Status meanings</a>
        <a href="/blog/">Blog</a>
        <a href="/api/latest.json" download="azure-region-monitor-latest.json">Download latest JSON</a>
      </nav>"""


def _insight_rows(snapshot: Snapshot, page: dict[str, Any]) -> list[dict[str, object]]:
    categories = set(page["categories"])
    return [row for row in _flatten_snapshot(snapshot) if str(row["category"]) in categories]


def _related_insight_posts(posts: list[dict[str, Any]], page: dict[str, Any]) -> list[dict[str, Any]]:
    categories = set(page["categories"])
    matches = []
    for post in posts:
        highlights = post.get("highlights", [])
        if not isinstance(highlights, list):
            continue
        for item in highlights:
            if not isinstance(item, dict):
                continue
            feature = str(item.get("feature", ""))
            modality = str(item.get("modality") or _feature_category(feature))
            if modality in categories:
                matches.append(post)
                break
    return matches[:5]


def _render_insight_recent_posts(posts: list[dict[str, Any]]) -> str:
    if not posts:
        return """<section class="panel prose" aria-label="Recent related posts">
      <div class="panel-header"><h2>Recent Related Posts</h2></div>
      <div class="prose-body"><p>No related daily posts are available yet.</p></div>
    </section>"""
    items = "\n".join(
        f'<li><a href="/{html.escape(post["slug"])}">{html.escape(post["title"])}</a> '
        f'<span class="timestamp">{html.escape(post["date"])}</span></li>'
        for post in posts
    )
    return f"""<section class="panel prose" aria-label="Recent related posts">
      <div class="panel-header"><h2>Recent Related Posts</h2></div>
      <div class="prose-body"><ul class="insight-post-list">{items}</ul></div>
    </section>"""


def _empty_table_row(columns: int) -> str:
    return f'<tr><td colspan="{columns}" class="empty">No matching checks in the latest snapshot.</td></tr>'


def _render_llms_txt(snapshot: Snapshot) -> str:
    rows = _flatten_snapshot(snapshot)
    regions = _sort_regions(snapshot.regions)
    features = {str(row["feature"]) for row in rows}
    return f"""# Azure Regional Feature Availability Monitor

> {_SITE_DESCRIPTION}

Canonical site: {_SITE_URL}/
Repository: {_REPOSITORY_URL}
Latest snapshot: {snapshot.timestamp.isoformat()}

## Useful Resources

- [{_SITE_URL}/]({_SITE_URL}/): summary dashboard with modality and regional group availability.
- [{_SITE_URL}/heatmap.html]({_SITE_URL}/heatmap.html): paged, filterable heatmap backed by the latest JSON snapshot.
- [{_SITE_URL}/latency.html]({_SITE_URL}/latency.html): LLM model response-latency leaderboard measured from the GitHub Models global vantage.
- [{_SITE_URL}/methodology.html]({_SITE_URL}/methodology.html): status semantics and probe evidence notes.
- [{_SITE_URL}/blog/]({_SITE_URL}/blog/): daily changelog blog — a short post per day summarizing region availability changes (RSS at {_SITE_URL}/blog/feed.xml).
- [{_SITE_URL}/insights/]({_SITE_URL}/insights/): evergreen topic pages for Azure OpenAI, VM SKU, and AKS regional availability search/discovery.
- [{_SITE_URL}/api/latest.json]({_SITE_URL}/api/latest.json): complete current machine-readable snapshot.
- [{_SITE_URL}/api/summary.json]({_SITE_URL}/api/summary.json): tiny headline counts (status and per-modality totals).
- [{_SITE_URL}/api/modalities/manifest.json]({_SITE_URL}/api/modalities/manifest.json): per-modality shard index; each modality is a smaller JSON under api/modalities/.
- [{_SITE_URL}/api/history/index.json]({_SITE_URL}/api/history/index.json): compact history index with daily snapshot and change links.
- [{_SITE_URL}/llms-full.txt]({_SITE_URL}/llms-full.txt): fuller guide for LLM and crawler consumers.

## Current Scope

- Regions: {len(regions):,}
- Unique features: {len(features):,}
- Checks: {len(rows):,}

## Status Semantics

- available: positive read-only catalog or listing evidence was found.
- unavailable: the probe completed, but the feature was absent from that catalog or listing.
- unknown: the probe did not get trustworthy evidence because a command, API call, or provider response failed.
- partial: reserved for multi-condition checks.
"""


def _render_llms_full_txt(snapshot: Snapshot, recent_changes: dict[str, Any] | None = None) -> str:
    rows = _flatten_snapshot(snapshot)
    status_counts = _status_counts(rows)
    modality_lines = "\n".join(
        f"- {item['category']}: {len(item['features']):,} features, {item['checks']:,} checks"
        for item in _modality_summaries(rows)
    )
    history_note = "No recent change summary is currently published."
    if recent_changes and isinstance(recent_changes.get("days"), list):
        history_note = f"Recent change days in published summary: {len(recent_changes['days']):,}."
        days = [day for day in recent_changes["days"] if isinstance(day, dict)]
        latest_narrative = str(days[0].get("narrative", "")).strip() if days else ""
        if latest_narrative:
            history_note += f"\nLatest change digest: {latest_narrative}"
    return f"""# Azure Regional Feature Availability Monitor - LLM Reference

This project publishes public, read-only evidence about Azure regional feature rollout. It does not perform create/delete deployment probes, quota checks, inference tests, or private subscription capacity validation.

## Canonical URLs

- Site: {_SITE_URL}/
- Repository: {_REPOSITORY_URL}
- Latest JSON snapshot: {_SITE_URL}/api/latest.json
- History index: {_SITE_URL}/api/history/index.json
- Methodology: {_SITE_URL}/methodology.html
- Sitemap: {_SITE_URL}/sitemap.xml

## Snapshot Summary

- Timestamp: {snapshot.timestamp.isoformat()}
- Regions: {len(snapshot.regions):,}
- Checks: {len(rows):,}
- Available: {status_counts.get('available', 0):,}
- Unavailable: {status_counts.get('unavailable', 0):,}
- Partial: {status_counts.get('partial', 0):,}
- Unknown: {status_counts.get('unknown', 0):,}

## Modalities

{modality_lines}

## Snapshot Shape

`api/latest.json` has this shape:

```json
{{
  "timestamp": "ISO-8601 UTC timestamp",
  "regions": {{
    "<azure-region>": {{
      "<service>": {{
        "<feature-key>": {{
          "status": "available | unavailable | partial | unknown",
          "message": "optional probe message",
          "error_code": "optional error code",
          "latency_ms": "optional latency"
        }}
      }}
    }}
  }}
}}
```

## Interpretation Rules

- Treat unavailable as absence from a read-only catalog or listing, not as quota exhaustion or deployment failure.
- Treat unknown as no trustworthy evidence for that region/feature pair.
- Treat unknown-to-known and known-to-unknown history changes as parked probe-quality changes, not rollout wins or regressions.
- Use methodology.html for modality-specific caveats before summarizing availability claims.
- Full daily history snapshots are published as gzip JSON files referenced by `api/history/index.json`.

## History

{history_note}
"""


def _snapshot_lastmod(snapshot: Snapshot) -> str:
    return snapshot.timestamp.date().isoformat()


def _render_index(snapshot: Snapshot, recent_changes: dict[str, Any] | None = None) -> str:
    rows = _flatten_snapshot(snapshot)
    status_counts = _status_counts(rows)
    status_total = sum(status_counts.values())
    unknown_count = status_counts.get("unknown", 0)
    unknown_check_label = "check" if unknown_count == 1 else "checks"
    available_percent = (
        round((status_counts.get("available", 0) / status_total) * 100, 1) if status_total else 0
    )
    regions = _sort_regions(snapshot.regions)
    unique_features = sorted({str(row["feature"]) for row in rows})
    current_history_day = _current_history_day(
        snapshot=snapshot,
        regions=len(regions),
        features=len(unique_features),
        checks=len(rows),
        status_counts=status_counts,
    )
    history_days = _merge_current_history_day(recent_changes, current_history_day)
    modality_rows = "\n".join(_render_modality_row(row) for row in _modality_summaries(rows))
    recent_changes_panel = _render_recent_changes_panel(recent_changes)
    history_resources_panel = _render_history_resources_panel(recent_changes)
    unknown_diagnostics_panel = _render_unknown_diagnostics_panel(rows)
    group_rows = "\n".join(_render_group_row(row) for row in _feature_group_summaries(rows))
    region_metric = _render_metric(
        "Regions", len(regions), _render_count_trend(history_days, "regions", len(regions))
    )
    feature_metric = _render_metric(
        "Unique features",
        len(unique_features),
        _render_count_trend(history_days, "features", len(unique_features)),
    )
    checks_metric = _render_metric(
        "Checks", len(rows), _render_count_trend(history_days, "checks", len(rows))
    )
    available_metric = _render_metric(
        "Available",
        f"{available_percent}%",
        _render_availability_trend(history_days, available_percent),
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="{html.escape(_SITE_DESCRIPTION)}">
  <title>Azure Regional Feature Availability Monitor</title>
  <link rel="canonical" href="{_SITE_URL}/">
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <link rel="alternate" href="/llms.txt" type="text/plain" title="LLM guide">
  <link rel="alternate" type="application/rss+xml" title="Azure regional changes feed" href="/blog/feed.xml">
  {_style_block()}
</head>
<body>
  <main id="main-content">
    <header>
      <div>
        <h1>Azure Regional Feature Availability Monitor</h1>
      </div>
      <nav class="links" aria-label="Dashboard links">
        <a href="methodology.html">Status meanings</a>
        <a href="heatmap.html">Detailed heatmap</a>
        <a href="latency.html">Model latency</a>
        <a href="blog/">Blog</a>
        <a href="api/latest.json" download="azure-region-monitor-latest.json">Download latest JSON</a>
        <a href="{_REPOSITORY_URL}">GitHub repository</a>
      </nav>
    </header>
    <section class="opening-summary" aria-label="Snapshot overview">
      <div class="opening-summary-item">
        <span class="opening-summary-label">Data freshness</span>
        <strong>{html.escape(snapshot.timestamp.isoformat())}</strong>
        <span class="opening-summary-detail">Latest completed snapshot</span>
      </div>
      <div class="opening-summary-item">
        <span class="opening-summary-label">Coverage</span>
        <strong>{len(regions):,} regions &middot; {len(unique_features):,} features</strong>
        <span class="opening-summary-detail">{len(rows):,} regional checks</span>
      </div>
      <div class="opening-summary-item">
        <span class="opening-summary-label">Unknown evidence</span>
        <strong>{unknown_count:,} {unknown_check_label}</strong>
        <span class="opening-summary-detail">Unknown means no trustworthy probe result, not unavailable.</span>
      </div>
    </section>
    {_render_alpha_notice(len(regions))}
    <section class="repo-callout" aria-label="Project repository">
      <div>
        <h2>Open Source Monitor</h2>
        <p>Source code, methodology notes, workflows, and release tracking are public in the GitHub repository.</p>
      </div>
      <a href="{_REPOSITORY_URL}">View repository</a>
    </section>
    <section class="metrics" aria-label="Availability summary">
      {region_metric}
      {feature_metric}
      {checks_metric}
      {available_metric}
    </section>
    <section class="status-strip" aria-label="Status totals">
      {_render_metric("Available", status_counts.get("available", 0))}
      {_render_metric("Unavailable", status_counts.get("unavailable", 0))}
      {_render_metric("Partial", status_counts.get("partial", 0))}
      {_render_metric("Unknown", status_counts.get("unknown", 0))}
    </section>
    {recent_changes_panel}
    {history_resources_panel}
    <section class="layout" aria-label="Coverage overview">
      <div class="panel">
        <div class="panel-header">
          <h2>Modalities</h2>
          <div class="panel-subtitle">Feature families across all regions</div>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Modality</th>
                <th class="number">Features</th>
                <th class="number">Checks</th>
                <th class="number">Available</th>
                <th class="number">Unavailable</th>
                <th class="number">Partial</th>
                <th class="number">Unknown</th>
              </tr>
            </thead>
            <tbody>{modality_rows}</tbody>
          </table>
        </div>
      </div>
      <div class="panel">
        <div class="panel-header">
          <h2>Feature Groups</h2>
          <div class="panel-subtitle">Publisher, version, and SKU-family aggregation</div>
        </div>
        <div class="table-wrap compact-table">
          <table>
            <thead>
              <tr>
                <th>Modality</th>
                <th>Group</th>
                <th class="number">Features</th>
                <th class="number">Available</th>
                <th class="number">Checks</th>
              </tr>
            </thead>
            <tbody>{group_rows}</tbody>
          </table>
        </div>
      </div>
    </section>
    <section class="availability-stack" aria-label="Region modality availability">
      <div class="section-heading">
        <h2>Regional Availability By Modality</h2>
        <div id="regional-availability-status" class="panel-subtitle">Loading group / region matrices from the per-modality API</div>
      </div>
      <div id="regional-availability-root">
        <section class="panel availability-section" aria-label="Regional availability loading">
          <div class="lazy-matrix-placeholder">Loading regional availability matrices.</div>
        </section>
      </div>
    </section>
    <section class="availability-stack" aria-label="Large AKS extension group availability">
      <div class="section-heading">
        <h2>Large AKS Extension Groups</h2>
        <div id="large-extension-status" class="panel-subtitle">Loading extension groups from the per-modality API</div>
      </div>
      <div id="large-extension-groups-root"></div>
    </section>
    {unknown_diagnostics_panel}
  </main>
  <script>
{_index_script()}
  </script>
</body>
</html>
"""


def _render_heatmap_page(snapshot: Snapshot) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="Detailed regional heatmap for Azure feature availability evidence.">
  <title>Azure Regional Feature Heatmap</title>
  <link rel="canonical" href="{_SITE_URL}/heatmap.html">
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <link rel="alternate" href="/llms.txt" type="text/plain" title="LLM guide">
  {_style_block()}
</head>
<body>
  <main id="main-content">
    <header>
      <div>
        <h1>Azure Regional Feature Heatmap</h1>
        <div class="timestamp">Latest snapshot: {html.escape(snapshot.timestamp.isoformat())}</div>
      </div>
      <nav class="links" aria-label="Dashboard links">
        <a href="index.html">Summary</a>
        <a href="methodology.html">Status meanings</a>
        <a href="latency.html">Model latency</a>
        <a href="blog/">Blog</a>
        <a href="api/latest.json" download="azure-region-monitor-latest.json">Download latest JSON</a>
      </nav>
    </header>
    {_render_alpha_notice(len(snapshot.regions))}
    <section class="panel" aria-label="Heatmap filters">
      <div class="panel-header">
        <h2>Filters</h2>
        <div id="load-status" class="panel-subtitle">Loading snapshot...</div>
      </div>
      <div class="toolbar heatmap-toolbar">
        <input id="search" type="search" placeholder="Search region, group, feature, or message" aria-label="Search checks">
        <select id="modality" aria-label="Filter by modality"><option value="">All modalities</option></select>
        <select id="group" aria-label="Filter by group"><option value="">All groups</option></select>
        <select id="status" aria-label="Filter by status">
          <option value="">All statuses</option>
          <option value="available">Available</option>
          <option value="unavailable">Unavailable</option>
          <option value="partial">Partial</option>
          <option value="unknown">Unknown</option>
        </select>
        <select id="page-size" aria-label="Rows per page">
          <option value="50">50 rows</option>
          <option value="100" selected>100 rows</option>
          <option value="250">250 rows</option>
          <option value="500">500 rows</option>
        </select>
      </div>
    </section>
    <section class="panel matrix" aria-label="Detailed regional heatmap">
      <div class="panel-header">
        <h2>Heatmap</h2>
        <div id="heatmap-count" class="panel-subtitle"></div>
      </div>
      <div class="pager">
        <button id="heatmap-prev" type="button">Previous</button>
        <span id="heatmap-page"></span>
        <button id="heatmap-next" type="button">Next</button>
      </div>
      <div class="table-wrap heatmap-wrap">
        <table id="heatmap-table"></table>
      </div>
    </section>
    <section class="panel" aria-label="Paged check details">
      <div class="panel-header">
        <h2>Check Details</h2>
        <div id="detail-count" class="panel-subtitle"></div>
      </div>
      <div class="pager">
        <button id="details-prev" type="button">Previous</button>
        <span id="details-page"></span>
        <button id="details-next" type="button">Next</button>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Region</th>
              <th>Modality</th>
              <th>Group</th>
              <th>Feature</th>
              <th>Status</th>
              <th>Message</th>
            </tr>
          </thead>
          <tbody id="details-rows"></tbody>
        </table>
      </div>
    </section>
  </main>
  <script>
{_heatmap_script()}
  </script>
</body>
</html>
"""


def _render_methodology_page(snapshot: Snapshot) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="Methodology and status semantics for Azure regional availability evidence.">
  <title>Azure Regional Feature Monitor Status Meanings</title>
  <link rel="canonical" href="{_SITE_URL}/methodology.html">
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <link rel="alternate" href="/llms.txt" type="text/plain" title="LLM guide">
  {_style_block()}
</head>
<body>
  <main id="main-content" class="content-page">
    <header>
      <div>
        <h1>Status Meanings</h1>
        <div class="timestamp">Latest snapshot: {html.escape(snapshot.timestamp.isoformat())}</div>
      </div>
      <nav class="links" aria-label="Dashboard links">
        <a href="index.html">Summary</a>
        <a href="heatmap.html">Detailed heatmap</a>
        <a href="latency.html">Model latency</a>
        <a href="blog/">Blog</a>
        <a href="api/latest.json" download="azure-region-monitor-latest.json">Download latest JSON</a>
      </nav>
    </header>
    <section class="panel prose" aria-label="Plain-language status guide">
      <div class="panel-header">
        <h2>Plain-language guide</h2>
        <div class="panel-subtitle">What the dashboard can and cannot prove</div>
      </div>
      <div class="prose-body">
        <div class="note"><strong>Public Alpha.</strong> Data can be incomplete or temporarily wrong. The current scan covers {len(snapshot.regions):,} configured Azure public cloud regions and uses read-only Azure CLI/control-plane evidence. It does not claim to cover sovereign clouds, private previews, every possible API version, or hidden capacity signals.</div>
        <p>This dashboard is a regional rollout monitor. Most checks are read-only catalog checks: they ask Azure which locations, versions, SKUs, or extension types are advertised by Azure control-plane APIs or Azure CLI commands. They are fast and cheap, but they are not the same thing as a full deployment test.</p>
        <h3>Region scope</h3>
        <p>The scheduled full scan uses the monitor's configured public Azure region list, which is refreshed from Azure CLI location metadata as the project evolves. In other words, the dashboard is intended to cover Azure public cloud physical regions in scope for this monitor, but it should not be read as a contractual list of every Azure location, sovereign cloud, private preview region, or capacity cell.</p>
        <h3>Overall statuses</h3>
        <table>
          <thead><tr><th>Status</th><th>Meaning</th><th>What it does not prove</th></tr></thead>
          <tbody>
            <tr><td><span class="status status-available">available</span></td><td>The feature was listed or matched by the read-only probe for that region.</td><td>It does not guarantee that a later deployment will pass quota, capacity, policy, identity, or provider-registration checks.</td></tr>
            <tr><td><span class="status status-unavailable">unavailable</span></td><td>The probe completed successfully, but the feature was absent from the catalog or location list used by that probe.</td><td>It does not necessarily mean the service is impossible forever, globally blocked, or failing because of quota.</td></tr>
            <tr><td><span class="status status-partial">partial</span></td><td>Reserved for checks where some required sub-conditions pass and others fail.</td><td>Current read-only probes rarely emit this because they usually test one listed item at a time.</td></tr>
            <tr><td><span class="status status-unknown">unknown</span></td><td>The probe could not produce reliable evidence, usually because Azure CLI failed, timed out, returned invalid JSON, or the provider endpoint was not available.</td><td>It should not be treated as unavailable. It means the monitor did not get a trustworthy answer.</td></tr>
          </tbody>
        </table>
        <h3>History and signal changes</h3>
        <p>The recent-history panel highlights only clear availability signals: <span class="status status-unavailable">unavailable</span> to <span class="status status-available">available</span> is a new availability signal, and <span class="status status-available">available</span> to <span class="status status-unavailable">unavailable</span> is a regression signal. Transitions into or out of <span class="status status-unknown">unknown</span> are parked as probe-quality changes, because they do not prove a rollout or rollback.</p>
        <h3>Azure Functions Flex Consumption</h3>
        <p>The <code>hostingPlans.flexConsumption</code> row comes from <code>az functionapp list-flexconsumption-locations --output json</code>. Azure CLI describes this command as listing available locations for running function apps on the Flex Consumption plan.</p>
        <p>If a region is absent from that list, the dashboard marks Flex Consumption as <span class="status status-unavailable">unavailable</span>. In plain language, that means Azure did not advertise that region as a Flex Consumption location to this command at scan time. It is not a quota result.</p>
        <p>The runtime rows, such as <code>runtimes.python.3.14</code> or <code>runtimes.node.24</code>, are tied to the Flex location signal. If Flex is not listed for a region, every Functions runtime row is marked unavailable for that region because there is no Flex hosting target in the read-only evidence. If Flex is listed, runtime availability is checked against <code>az functionapp list-runtimes --os linux --output json</code>.</p>
        <div class="note"><strong>Quota is separate.</strong> A region can be listed as available here and still fail a real deployment because of subscription quota, regional capacity, Azure Policy, provider registration, RBAC, or service-specific constraints. A quota or capacity signal needs a separate probe, probably using usage APIs and eventually a controlled create/delete deployment check.</div>
        <h3>Azure per-region model latency coverage</h3>
        <p>The <strong>Azure Per-Region Latency</strong> board only lists regions where an Azure OpenAI model is offered as a single-region <strong>Standard</strong> deployment. That matters because only a single-region Standard (non-global) deployment is processed in its own account's region, which is what makes a timing attributable to that region. <code>GlobalStandard</code> and <code>DataZoneStandard</code> deployments may be processed in any datacenter in their geography, so timing them would not tell you how fast a specific region is.</p>
        <p>This is why many large regions &mdash; for example <code>westeurope</code>, <code>northeurope</code>, <code>southeastasia</code>, <code>koreacentral</code>, and <code>centralindia</code> &mdash; do not appear even though they clearly host Azure OpenAI. In those regions the models are currently offered only as GlobalStandard / DataZoneStandard / ProvisionedManaged, not as single-region Standard, so there is nothing region-attributable to measure. The monitor scans a broad candidate region list each run and automatically adds any region the moment Azure starts offering a Standard SKU there.</p>
        <p>Names like &ldquo;Asia&rdquo;, &ldquo;South Asia&rdquo;, or &ldquo;Europe East&rdquo; are Azure <em>geographies</em> or informal groupings, not deployable region IDs. The comparable real regions are <code>eastasia</code>, <code>southeastasia</code>, <code>centralindia</code>/<code>southindia</code>, and <code>northeurope</code>/<code>westeurope</code>.</p>
        <h3>Other modalities</h3>
        <table>
          <thead><tr><th>Modality</th><th>Available means</th><th>Unavailable means</th></tr></thead>
          <tbody>
            <tr><td>AKS extensions</td><td>The extension type was listed by the AKS extension catalog for the region.</td><td>The extension type was absent from the regional catalog, or the regional <code>locations/extensionTypes</code> endpoint reported that the region is outside its supported locations.</td></tr>
            <tr><td>AKS Kubernetes versions</td><td><code>az aks get-versions</code> listed a Kubernetes version matching the configured prefix.</td><td>The version listing succeeded, but no matching version prefix was present.</td></tr>
            <tr><td>Azure AI models</td><td><code>az cognitiveservices model list --location &lt;region&gt;</code> listed the model/version in the region.</td><td>The model/version was not present in the regional catalog, or the regional <code>locations/models</code> endpoint reported that the region is outside its supported locations.</td></tr>
            <tr><td>Container Apps</td><td><code>az provider show --namespace Microsoft.App --expand resourceTypes/locations</code> advertised the resource type in the region.</td><td>The provider metadata call succeeded, but the resource type was not advertised in that region.</td></tr>
            <tr><td>VM SKUs</td><td>Legacy <code>az vm list-sizes --location &lt;region&gt;</code> listed the SKU, or supported <code>az vm list-skus --location &lt;region&gt; --resource-type virtualMachines --all</code> fallback evidence listed it after a failed or suspiciously small legacy listing.</td><td>The regional VM SKU listing succeeded, no fallback evidence added the SKU, and the SKU was absent from that regional list.</td></tr>
          </tbody>
        </table>
      </div>
    </section>
  </main>
</body>
</html>
"""


def _write_snapshot_shards(api_dir: Path, snapshot: Snapshot) -> None:
    timestamp = snapshot.timestamp.isoformat()
    rows = _flatten_snapshot(snapshot)
    regions = list(snapshot.regions.keys())

    summary = build_summary(timestamp, regions, rows)
    (api_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    manifest, shards = build_modality_shards(timestamp, regions, rows)
    modalities_dir = api_dir / "modalities"
    modalities_dir.mkdir(parents=True, exist_ok=True)
    (modalities_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for slug, payload in shards.items():
        (modalities_dir / f"{slug}.json").write_text(
            json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8"
        )


def _write_latency_api(api_dir: Path, snapshot: Snapshot) -> None:
    rows = build_latency_rows(snapshot)
    payload = {
        "generated_from": snapshot.timestamp.isoformat(),
        "vantage": "GitHub Models global access endpoint",
        "models": rows,
    }
    (api_dir / "latency.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _render_latency_page(
    snapshot: Snapshot,
    latency_series: dict[str, list[dict[str, Any]]] | None = None,
    leaderboard_prev_ranks: dict[str, int] | None = None,
    regional_prev_ranks: dict[str, dict[str, int]] | None = None,
) -> str:
    rows = build_latency_rows(snapshot)
    annotate_rank_changes(rows, leaderboard_prev_ranks or {}, key_field="model")
    series = latency_series or {}
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="Response latency of GitHub Models, measured through a single global access endpoint. Cross-model speed evidence, not Azure per-region latency.">
  <title>LLM Model Latency via GitHub Models</title>
  <link rel="canonical" href="{_SITE_URL}/latency.html">
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <link rel="alternate" href="/llms.txt" type="text/plain" title="LLM guide">
  {_style_block()}
</head>
<body>
  <main id="main-content" class="content-page">
    <header>
      <div>
        <h1>LLM Model Latency via GitHub Models</h1>
        <div class="timestamp">Latest snapshot: {html.escape(snapshot.timestamp.isoformat())}</div>
      </div>
      <nav class="links" aria-label="Dashboard links">
        <a href="index.html">Summary</a>
        <a href="heatmap.html">Detailed heatmap</a>
        <a href="methodology.html">Status meanings</a>
        <a href="blog/">Blog</a>
        <a href="api/latency.json" download="azure-region-monitor-latency.json">Download latency JSON</a>
      </nav>
    </header>
    <div class="note" role="note">
      <strong>What this measures:</strong> response latency of models served by
      <a href="https://github.com/marketplace/models">GitHub Models</a>, called through its
      <strong>single global access endpoint</strong> (<code>models.github.ai</code>). GitHub Models
      does not expose a region selector, so these numbers are <strong>not</strong> Azure
      per-region latency &mdash; they are cross-model speed evidence from one global vantage
      (labelled <code>github-global</code>), and they include network distance from wherever the
      probe runs.
    </div>
    <section class="panel" aria-label="Model latency leaderboard">
      <div class="panel-header">
        <h2>Response Latency Leaderboard</h2>
        <div class="panel-subtitle">Fastest p50 first &middot; GitHub Models global endpoint (<code>github-global</code>) &middot; not Azure per-region latency</div>
      </div>
      {_render_latency_table(rows, series)}
    </section>
    {_render_regional_latency_section(snapshot, regional_prev_ranks or {})}
    <section class="panel prose" aria-label="Model latency methodology">
      <div class="panel-header">
        <h2>How to read this</h2>
        <div class="panel-subtitle">What the latency numbers do and do not mean</div>
      </div>
      <div class="prose-body">
        <p>Each model is sent a small deterministic prompt several times. We record
        <strong>p50</strong> and <strong>p95</strong> round-trip time, <strong>TTFT</strong>
        (time to first token), and output <strong>tokens per second</strong>, then publish the
        medians. <code>p50</code> is the headline number used for ranking.</p>
        <p>These are measurements from a <strong>single global vantage</strong> &mdash; the GitHub
        Models access endpoint &mdash; taken from wherever the probe runs. They mix model speed with
        network distance, so treat them as cross-model speed evidence, <em>not</em> as Azure
        per-region latency, an SLA, or a throughput guarantee. Reasoning models spend hidden tokens
        before their first visible token, so their TTFT is expected to be higher.</p>
        <p><span class="status status-available">available</span> means at least one timed call
        returned a trustworthy response. <span class="status status-unknown">unknown</span> means
        every sample failed, timed out, or returned no tokens.</p>
        <p>The <strong>Trend</strong> column sparkline shows each model&rsquo;s daily p50 over recent
        days. A <span class="spark-down">&#9660;</span> means the model got faster, a
        <span class="spark-up">&#9650;</span> means it got slower; new models show
        &ldquo;collecting&rdquo; until a few days of history accumulate.</p>
        <p>The <strong>Rank</strong> column shows each row&rsquo;s speed position (fastest = #1) and
        how it moved versus the previous snapshot: <span class="rank-up">&#9650;&nbsp;2</span> means
        it climbed two places (relatively faster), <span class="rank-down">&#9660;&nbsp;1</span>
        means it slipped one, <span class="rank-flat">&mdash;</span> means unchanged, and
        <span class="rank-new">new</span> marks a row with no previous ranking.</p>
      </div>
    </section>
  </main>
</body>
</html>
"""


def _render_regional_latency_section(
    snapshot: Snapshot, regional_prev_ranks: dict[str, dict[str, int]] | None = None
) -> str:
    rows = build_regional_latency_rows(snapshot)
    if not rows:
        return ""

    prev_ranks = regional_prev_ranks or {}
    by_model: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_model.setdefault(str(row.get("model") or "model"), []).append(row)

    tables = "\n".join(
        _render_regional_latency_model_table(model, by_model[model], prev_ranks.get(model, {}))
        for model in sorted(by_model)
    )
    return f"""<section class="panel" aria-label="Azure per-region model latency">
      <div class="panel-header">
        <h2>Azure Per-Region Latency</h2>
        <div class="panel-subtitle">Real region-attributable latency &middot; one table per model &middot; fastest region first &middot; vantage = the probe runner</div>
      </div>
      <div class="note" role="note">
        <strong>This is real Azure per-region latency.</strong> Each row is a single-region
        Standard deployment of that model in that Azure region, so the timing is attributable to
        the region. It still includes network distance from the probe runner's vantage, so read it
        as relative region speed rather than an SLA. The <strong>Rank</strong> column shows each
        region's speed position and how it moved since the previous snapshot.
        <br><strong>Why only these regions?</strong> A region appears here only when Azure offers the
        model as a single-region <code>Standard</code> SKU. Many large regions (for example
        <code>westeurope</code>, <code>northeurope</code>, <code>southeastasia</code>,
        <code>koreacentral</code>, <code>centralindia</code>) currently offer these models only as
        <code>GlobalStandard</code>/<code>DataZoneStandard</code>, which can run in any datacenter in
        their geography and so are not region-attributable. See
        <a href="methodology.html">Status meanings</a> for details; new regions surface automatically
        once a Standard SKU appears.
      </div>
      {tables}
    </section>"""


def _render_regional_latency_model_table(
    model: str, rows: list[dict[str, Any]], previous_ranks: dict[str, int] | None = None
) -> str:
    annotate_rank_changes(rows, previous_ranks or {}, key_field="region")
    body = "\n".join(_render_regional_latency_row(row) for row in rows)
    return f"""<div class="latency-model-group">
        <h3>{html.escape(model)} &middot; {len(rows)} {"region" if len(rows) == 1 else "regions"}</h3>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Rank</th>
                <th>Region</th>
                <th>Status</th>
                <th class="number">p50 (ms)</th>
                <th class="number">p95 (ms)</th>
                <th class="number">TTFT p50 (ms)</th>
                <th class="number">Tokens/sec</th>
                <th class="number">Samples</th>
              </tr>
            </thead>
            <tbody>{body}</tbody>
          </table>
        </div>
      </div>"""


def _render_regional_latency_row(row: dict[str, Any]) -> str:
    status = str(row.get("status", "unknown"))
    samples = ""
    if row.get("samples_collected") is not None and row.get("samples_requested") is not None:
        samples = f"{row['samples_collected']}/{row['samples_requested']}"
    return f"""<tr>
                <td>{_render_rank_cell(row)}</td>
                <td><code>{html.escape(str(row.get("region", "")))}</code></td>
                <td><span class="status status-{html.escape(status)}">{html.escape(status)}</span></td>
                <td class="number">{_latency_cell(row.get("latency_ms"))}</td>
                <td class="number">{_latency_cell(row.get("p95_ms"))}</td>
                <td class="number">{_latency_cell(row.get("ttft_ms"))}</td>
                <td class="number">{_tokens_cell(row.get("tokens_per_second"))}</td>
                <td class="number">{html.escape(samples) or "&mdash;"}</td>
              </tr>"""


def _render_rank_cell(row: dict[str, Any]) -> str:
    """Render a rank position plus a movement badge vs the previous snapshot."""

    rank = row.get("rank")
    state = str(row.get("rank_state", "none"))
    if rank is None:
        return '<span class="rank-none">&mdash;</span>'

    position = f'<span class="rank-pos">#{rank}</span>'
    if state == "new":
        badge = '<span class="rank-new">new</span>'
    elif state == "up":
        badge = f'<span class="rank-up">&#9650;&nbsp;{abs(int(row["rank_delta"]))}</span>'
    elif state == "down":
        badge = f'<span class="rank-down">&#9660;&nbsp;{abs(int(row["rank_delta"]))}</span>'
    else:
        badge = '<span class="rank-flat">&mdash;</span>'
    return f"{position} {badge}"


def _render_latency_table(
    rows: list[dict[str, Any]], series: dict[str, list[dict[str, Any]]] | None = None
) -> str:
    if not rows:
        return """<div class="table-wrap"><p class="panel-subtitle" style="padding: 16px;">No model latency data in the latest snapshot yet. Run the model latency workflow to populate this view.</p></div>"""

    series = series or {}
    body = "\n".join(_render_latency_row(row, series.get(str(row.get("model", "")))) for row in rows)
    return f"""<div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Rank</th>
              <th>Model</th>
              <th>Status</th>
              <th class="number">p50 (ms)</th>
              <th class="number">p95 (ms)</th>
              <th class="number">TTFT p50 (ms)</th>
              <th class="number">Tokens/sec</th>
              <th class="number">Samples</th>
              <th>Trend (p50)</th>
            </tr>
          </thead>
          <tbody>{body}</tbody>
        </table>
      </div>"""


def _render_latency_row(
    row: dict[str, Any], points: list[dict[str, Any]] | None = None
) -> str:
    status = str(row.get("status", "unknown"))
    samples = ""
    if row.get("samples_collected") is not None and row.get("samples_requested") is not None:
        samples = f"{row['samples_collected']}/{row['samples_requested']}"
    return f"""<tr>
                <td>{_render_rank_cell(row)}</td>
                <td>{html.escape(str(row.get("model", "")))}</td>
                <td><span class="status status-{html.escape(status)}">{html.escape(status)}</span></td>
                <td class="number">{_latency_cell(row.get("latency_ms"))}</td>
                <td class="number">{_latency_cell(row.get("p95_ms"))}</td>
                <td class="number">{_latency_cell(row.get("ttft_ms"))}</td>
                <td class="number">{_tokens_cell(row.get("tokens_per_second"))}</td>
                <td class="number">{html.escape(samples) or "&mdash;"}</td>
                <td>{_render_latency_sparkline(points)}</td>
              </tr>"""


def _render_latency_sparkline(points: list[dict[str, Any]] | None) -> str:
    values = [
        float(point["p50_ms"])
        for point in (points or [])
        if isinstance(point, dict) and isinstance(point.get("p50_ms"), (int, float))
    ]
    if len(values) < 2:
        return '<span class="spark-empty">collecting&hellip;</span>'

    width, height = 96, 24
    low, high = min(values), max(values)
    span = high - low or 1.0
    last_index = len(values) - 1
    coords = []
    for index, value in enumerate(values):
        x = round(index * (width - 2) / last_index + 1, 1)
        y = round((height - 2) - (value - low) / span * (height - 4), 1)
        coords.append(f"{x},{y}")
    polyline = " ".join(coords)

    first, last = values[0], values[-1]
    delta = last - first
    if delta > 0:
        trend_class, arrow = "spark-up", "&#9650;"
    elif delta < 0:
        trend_class, arrow = "spark-down", "&#9660;"
    else:
        trend_class, arrow = "spark-flat", "&rarr;"
    pct = f"{abs(delta) / first * 100:.0f}%" if first else ""
    title = f"p50 over last {len(values)} days: {round(first):,}ms to {round(last):,}ms"
    return (
        f'<span class="spark" title="{html.escape(title)}">'
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="{html.escape(title)}">'
        f'<polyline points="{polyline}" fill="none" stroke="currentColor" '
        f'stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/></svg>'
        f'<span class="{trend_class}">{arrow} {pct}</span></span>'
    )


def _load_latency_history(history_path: Path) -> dict[str, Any] | None:
    latency_path = history_path / "latency-history.json"
    if not latency_path.exists():
        return None
    try:
        return json.loads(latency_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _latency_cell(value: object) -> str:
    if isinstance(value, (int, float)):
        return f"{round(value):,}"
    return "&mdash;"


def _tokens_cell(value: object) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.1f}"
    return "&mdash;"


def _render_alpha_notice(region_count: int) -> str:
    return f"""<section class="alpha-notice" aria-label="Public alpha data notice">
      <div class="alpha-badge">Public Alpha</div>
      <div>
        <strong>Read the data as rollout evidence, not a deployment guarantee.</strong>
        <p>Current scans cover {region_count:,} configured Azure public cloud regions. Some results can be incomplete or temporarily wrong; <span class="status status-unknown">unknown</span> means the monitor parked that check because a probe failed, timed out, returned invalid JSON, or could not get a trustworthy provider response.</p>
      </div>
      <a href="methodology.html">Methodology</a>
    </section>"""


def _style_block() -> str:
    css = DASHBOARD_CSS_PATH.read_text(encoding="utf-8").rstrip("\n")
    return f"<style>\n{css}\n  </style>"


def _flatten_snapshot(snapshot: Snapshot) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for region, services in sorted(snapshot.regions.items()):
        for service, features in sorted(services.items()):
            for feature, result in sorted(features.items()):
                rows.append(
                    {
                        "region": region,
                        "service": service,
                        "category": _feature_category(feature),
                        "group": _feature_group(feature),
                        "feature": feature,
                        "status": result.status,
                        "latency_ms": result.latency_ms,
                        "message": result.message or result.error_code or "",
                    }
                )
    return rows


def _status_counts(rows: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row["status"])
        counts[status] = counts.get(status, 0) + 1
    return counts


def _render_metric(label: str, value: int | str, detail_html: str = "") -> str:
    detail = f"\n        {detail_html}" if detail_html else ""
    return f"""<div class="metric">
          <div class="metric-value">{html.escape(str(value))}</div>
        <div class="metric-label">{html.escape(label)}</div>
{detail}
      </div>"""


def _current_history_day(
    *,
    snapshot: Snapshot,
    regions: int,
    features: int,
    checks: int,
    status_counts: dict[str, int],
) -> dict[str, Any]:
    return {
        "date": snapshot.timestamp.date().isoformat(),
        "summary_counts": {
            "regions": regions,
            "features": features,
            "checks": checks,
        },
        "status_counts": dict(status_counts),
    }


def _merge_current_history_day(
    recent_changes: dict[str, Any] | None, current_day: dict[str, Any]
) -> list[dict[str, Any]]:
    days: list[dict[str, Any]] = []
    if recent_changes and isinstance(recent_changes.get("days"), list):
        days = [day for day in recent_changes["days"] if isinstance(day, dict)]
    if not days:
        return [current_day]
    if days[0].get("date") == current_day["date"]:
        merged = {**days[0]}
        merged.setdefault("summary_counts", current_day["summary_counts"])
        merged.setdefault("status_counts", current_day["status_counts"])
        return [merged, *days[1:]]
    return [current_day, *days]


def _render_count_trend(days: list[dict[str, Any]], key: str, current_value: int) -> str:
    previous_value = _summary_count(days[1], key) if len(days) > 1 else None
    if previous_value is None:
        return '<div class="metric-detail metric-flat">History baseline starts today</div>'
    delta = current_value - previous_value
    if delta == 0:
        stable_days = _stable_day_count(days, key, current_value)
        day_label = "day" if stable_days == 1 else "days"
        return f'<div class="metric-detail metric-flat">No change for {stable_days} {day_label}</div>'
    direction = "Up" if delta > 0 else "Down"
    css_class = "metric-up" if delta > 0 else "metric-down"
    return (
        f'<div class="metric-detail {css_class}">{direction} '
        f'{abs(delta):,} since previous snapshot</div>'
    )


def _render_availability_trend(days: list[dict[str, Any]], current_percent: float) -> str:
    previous_percent = _availability_percent(days[1]) if len(days) > 1 else None
    if previous_percent is None:
        text = "History baseline starts today"
        css_class = "metric-flat"
    else:
        delta = round(current_percent - previous_percent, 1)
        if delta == 0:
            stable_days = _stable_available_day_count(days, current_percent)
            day_label = "day" if stable_days == 1 else "days"
            text = f"No change for {stable_days} {day_label}"
            css_class = "metric-flat"
        else:
            direction = "Up" if delta > 0 else "Down"
            text = f"{direction} {abs(delta):.1f} pp since previous snapshot"
            css_class = "metric-up" if delta > 0 else "metric-down"
    sparkline = _render_availability_sparkline(days)
    return f'<div class="metric-detail {css_class}">{sparkline}<span>{html.escape(text)}</span></div>'


def _summary_count(day: dict[str, Any], key: str) -> int | None:
    counts = day.get("summary_counts")
    if not isinstance(counts, dict) or key not in counts:
        return None
    try:
        return int(counts[key])
    except (TypeError, ValueError):
        return None


def _stable_day_count(days: list[dict[str, Any]], key: str, current_value: int) -> int:
    stable_days = 0
    for day in days[1:]:
        value = _summary_count(day, key)
        if value != current_value:
            break
        stable_days += 1
    return max(stable_days, 1)


def _availability_percent(day: dict[str, Any]) -> float | None:
    counts = day.get("status_counts")
    if not isinstance(counts, dict):
        return None
    try:
        available = int(counts.get("available", 0))
        total = sum(
            int(counts.get(status, 0))
            for status in ("available", "unavailable", "partial", "unknown")
        )
    except (TypeError, ValueError):
        return None
    if total <= 0:
        return None
    return round((available / total) * 100, 1)


def _stable_available_day_count(days: list[dict[str, Any]], current_percent: float) -> int:
    stable_days = 0
    for day in days[1:]:
        value = _availability_percent(day)
        if value != current_percent:
            break
        stable_days += 1
    return max(stable_days, 1)


def _render_availability_sparkline(days: list[dict[str, Any]]) -> str:
    values = [
        value
        for value in (_availability_percent(day) for day in reversed(days[:10]))
        if value is not None
    ]
    if len(values) < 2:
        return ""
    width = 74
    height = 24
    top_padding = 3
    bottom_padding = 3
    minimum = min(values)
    maximum = max(values)
    span = maximum - minimum
    points = []
    for index, value in enumerate(values):
        x = round((index / (len(values) - 1)) * width, 2)
        if span == 0:
            y = height / 2
        else:
            y = top_padding + (maximum - value) / span * (height - top_padding - bottom_padding)
        points.append((x, round(y, 2)))
    polyline = " ".join(f"{x},{y}" for x, y in points)
    fill_points = f"0,{height} {polyline} {width},{height}"
    return (
        '<svg class="sparkline" viewBox="0 0 74 24" role="img" '
        'aria-label="Recent available percentage trend">'
        f'<polygon class="sparkline-fill" points="{html.escape(fill_points)}"></polygon>'
        f'<polyline class="sparkline-line" points="{html.escape(polyline)}"></polyline>'
        "</svg>"
    )


def _render_unknown_diagnostics_panel(rows: list[dict[str, object]]) -> str:
    unknown_rows = [row for row in rows if row.get("status") == "unknown"]
    total = len(rows)
    unknown_count = len(unknown_rows)
    unknown_percent = round((unknown_count / total) * 100, 2) if total else 0
    if not unknown_rows:
        return """<details class="panel unknown-diagnostics" aria-label="Unknown diagnostics">
      <summary class="unknown-diagnostics-summary">
        <div class="panel-header">
        <h2>Unknowns To Investigate</h2>
        <div class="panel-subtitle">0 unknown checks</div>
        </div>
      </summary>
      <div class="empty">No unknown results in the current snapshot.</div>
    </details>"""

    groups: dict[tuple[str, str], dict[str, object]] = {}
    for row in unknown_rows:
        category = str(row.get("category", "Unknown modality"))
        reason = _unknown_reason(str(row.get("message", "")))
        group = groups.setdefault(
            (category, reason),
            {"category": category, "reason": reason, "count": 0, "regions": set(), "features": set()},
        )
        group["count"] = int(group["count"]) + 1
        group["regions"].add(str(row.get("region", "")))
        group["features"].add(str(row.get("feature", "")))

    diagnostic_rows = "\n".join(
        _render_unknown_diagnostic_row(group)
        for group in sorted(
            groups.values(), key=lambda item: (-int(item["count"]), str(item["category"]), str(item["reason"]))
        )[:8]
    )
    return f"""<details class="panel unknown-diagnostics" aria-label="Unknown diagnostics">
      <summary class="unknown-diagnostics-summary">
        <div class="panel-header">
        <h2>Unknowns To Investigate</h2>
        <div class="panel-subtitle">{unknown_count:,} unknown checks, {unknown_percent}% of current snapshot</div>
        </div>
      </summary>
      {_render_unknown_guidance(unknown_rows, total)}
      <div class="table-wrap">
        <table>
          <thead><tr><th>Modality</th><th class="number">Unknowns</th><th>Reason</th><th>Example regions</th><th>Example features</th></tr></thead>
          <tbody>{diagnostic_rows}</tbody>
        </table>
      </div>
    </details>"""


def _unknown_reason(message: str) -> str:
    normalized = " ".join(message.split())
    if not normalized:
        return "No probe message or error code recorded"
    return _truncate_text(normalized, 180)


def _render_unknown_guidance(unknown_rows: list[dict[str, object]], total: int) -> str:
    region_counts: dict[str, int] = {}
    for row in unknown_rows:
        region = str(row.get("region", ""))
        if region:
            region_counts[region] = region_counts.get(region, 0) + 1
    top_regions = sorted(region_counts.items(), key=lambda item: (-item[1], item[0]))[:3]
    top_region_text = ", ".join(f"{region} ({count:,})" for region, count in top_regions) or "none"
    unknown_percent = round((len(unknown_rows) / total) * 100, 2) if total else 0
    specialized_regions = [region for region, _ in top_regions if _is_specialized_region(region)]
    specialized_note = ""
    if specialized_regions:
        specialized_note = (
            " Preview/staging regions such as "
            f"{html.escape(', '.join(specialized_regions))} often need separate probe handling."
        )
    return (
        '<div class="note"><strong>Why this can happen:</strong> Unknown checks are parked as '
        "probe-quality gaps, not counted as rollout wins or regressions. "
        f"They currently represent {unknown_percent}% of checks; top unknown regions: "
        f"{html.escape(top_region_text)}."
        f"{specialized_note} Investigate repeated failure reasons first, then lower the percentage "
        "with retry tuning, narrower timeouts, better CLI error classification, or provider-specific "
        "fallback probes.</div>"
    )


def _is_specialized_region(region: str) -> bool:
    return region.endswith("stg") or region.endswith("euap") or "stage" in region


def _render_unknown_diagnostic_row(group: dict[str, object]) -> str:
    regions = _compact_examples(sorted(str(region) for region in group["regions"] if region), limit=5)
    features = _compact_examples(sorted(str(feature) for feature in group["features"] if feature), limit=4)
    return f"""<tr>
                <td>{html.escape(str(group["category"]))}</td>
                <td class="number">{int(group["count"]):,}</td>
                <td class="reason-cell">{html.escape(str(group["reason"]))}</td>
                <td class="muted-list">{html.escape(regions)}</td>
                <td class="muted-list">{html.escape(features)}</td>
              </tr>"""


def _compact_examples(values: list[str], limit: int) -> str:
    shown = values[:limit]
    if len(values) > limit:
        shown.append(f"+{len(values) - limit} more")
    return ", ".join(shown) if shown else "-"


def _truncate_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "..."


def _load_recent_changes(history_path: Path) -> dict[str, Any] | None:
    recent_path = history_path / "recent-changes.json"
    if not recent_path.exists():
        return None
    try:
        return json.loads(recent_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _render_recent_changes_panel(recent_changes: dict[str, Any] | None) -> str:
    if not recent_changes:
        return ""

    days = [day for day in recent_changes.get("days", []) if isinstance(day, dict)]
    if not days:
        return ""

    narrative_banner = _render_narrative_banner(days[0])
    rows = "\n".join(_render_recent_change_row(day) for day in days[:10])
    return f"""<section class="panel" aria-label="Recent availability changes">
      <div class="panel-header">
        <h2>Recent Availability Signals</h2>
        <div class="panel-subtitle">Today plus previous clear signal days; unknown transitions are parked</div>
      </div>
      {narrative_banner}
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th class="number">Signals</th>
              <th class="number">New availability</th>
              <th class="number">Regressions</th>
              <th class="number">Parked unknown</th>
              <th>Highlights</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    </section>"""


def _render_narrative_banner(day: dict[str, Any]) -> str:
    narrative = str(day.get("narrative", "")).strip()
    if not narrative:
        return ""
    source = str(day.get("narrative_source", "rule"))
    label = "AI summary" if source == "ai" else "Auto summary"

    # Split the digest into a headline (first line) plus body paragraphs. AI blog-post
    # summaries use blank lines between paragraphs; the rule fallback is a single block.
    blocks = [block.strip() for block in re.split(r"\n\s*\n", narrative) if block.strip()]
    if source == "ai" and blocks:
        headline, *rest = blocks
        # If the model kept everything in one block, treat the first line as the headline.
        if not rest and "\n" in headline:
            first, remainder = headline.split("\n", 1)
            headline, rest = first.strip(), [remainder.strip()]
        body = "".join(
            f"<p>{html.escape(paragraph)}</p>" for paragraph in rest if paragraph
        )
        content = f'<h3 class="narrative-headline">{html.escape(headline)}</h3>{body}'
    else:
        content = f"<p>{html.escape(narrative)}</p>"

    return f"""<div class="narrative" aria-label="Latest change summary">
        <span class="narrative-badge">{html.escape(label)}</span>
        <div class="narrative-body">{content}</div>
      </div>"""


def _render_history_resources_panel(recent_changes: dict[str, Any] | None) -> str:
    latest_day = ""
    if recent_changes and isinstance(recent_changes.get("days"), list):
        days = [day for day in recent_changes["days"] if isinstance(day, dict)]
        latest_day = str(days[0].get("date", "")) if days else ""

    latest_note = f"Latest history day: {html.escape(latest_day)}" if latest_day else "History index"
    return f"""<section class="panel history-resources" aria-label="History resources">
      <div class="panel-header">
        <h2>History Resources</h2>
        <div class="panel-subtitle">{latest_note}</div>
      </div>
      <div class="resource-links">
        <a href="api/history/index.json">History index</a>
        <a href="api/history/recent-changes.json">Recent changes JSON</a>
        <a href="api/latest.json" download="azure-region-monitor-latest.json">Latest snapshot JSON</a>
      </div>
    </section>"""


def _render_recent_change_row(day: dict[str, Any]) -> str:
    counts = day.get("change_type_counts") if isinstance(day.get("change_type_counts"), dict) else {}
    date = str(day.get("date", ""))
    change_path = str(day.get("change_path", ""))
    new_availability = int(counts.get("new_availability", 0))
    regressions = int(counts.get("regression", 0))
    parked_unknown = int(day.get("parked_unknown_changes", counts.get("status_change", 0)))
    signal_changes = new_availability + regressions
    date_cell = html.escape(date)
    if change_path:
        date_cell = f'<a href="api/history/{html.escape(change_path)}">{date_cell}</a>'
    return f"""<tr>
                <td>{date_cell}</td>
                <td class="number"><span class="change-count">{signal_changes:,}</span></td>
                <td class="number"><span class="change-count change-count-new">{new_availability:,}</span></td>
                <td class="number"><span class="change-count change-count-regression">{regressions:,}</span></td>
                <td class="number"><span class="change-count change-count-parked">{parked_unknown:,}</span></td>
                <td>{_render_change_highlights(day.get("highlights", []))}</td>
              </tr>"""


def _render_change_highlights(highlights: object) -> str:
    if not isinstance(highlights, list) or not highlights:
        return '<span class="change-highlights">No changes detected.</span>'

    rendered = []
    for item in highlights[:3]:
        if not isinstance(item, dict):
            continue
        region = str(item.get("region", ""))
        group = str(item.get("group", ""))
        feature = str(item.get("feature", ""))
        current = str(item.get("current", ""))
        previous = str(item.get("previous", ""))
        change_type = str(item.get("change_type", ""))
        label = _compact_feature_label(feature, group)
        css_class = "change-highlight"
        if change_type == "new_availability":
            css_class += " change-highlight-new"
        elif change_type == "regression":
            css_class += " change-highlight-regression"
        rendered.append(
            f'<span class="{css_class}">'
            f"{html.escape(region)} {html.escape(label)} "
            f"{html.escape(previous)} -> {html.escape(current)}"
            "</span>"
        )
    if not rendered:
        return '<span class="change-highlights">No changes detected.</span>'
    rendered_highlights = "".join(rendered)
    return f'<div class="change-highlights">{rendered_highlights}</div>'


def _compact_feature_label(feature: str, group: str) -> str:
    if feature.startswith("extensionTypes."):
        label = feature.removeprefix("extensionTypes.")
        group_prefix = f"{group}."
        return label.removeprefix(group_prefix) if label.startswith(group_prefix) else label
    if feature.startswith("kubernetesVersions."):
        return feature.removeprefix("kubernetesVersions.")
    if feature.startswith("hostingPlans."):
        return feature.removeprefix("hostingPlans.")
    if feature.startswith("runtimes."):
        return feature.removeprefix("runtimes.")
    if feature.startswith("aiModels."):
      return feature.removeprefix("aiModels.")
    if feature.startswith("modelLatency."):
        return feature.removeprefix("modelLatency.")
    if feature.startswith("aiLatency."):
        return feature.removeprefix("aiLatency.")
    if feature.startswith("vmSkus."):
        return feature.removeprefix("vmSkus.")
    return feature


def _feature_category(feature: str) -> str:
    if feature == "extensionCatalog":
        return "AKS extensions"
    if _is_extension_feature(feature):
        return "AKS extensions"
    if feature.startswith("kubernetesVersions."):
        return "AKS Kubernetes versions"
    if feature.startswith("hostingPlans.") or feature.startswith("runtimes."):
      return "Azure Functions"
    if feature.startswith("aiModels."):
      return "Azure AI models"
    if feature.startswith("modelLatency."):
        return "Model latency"
    if feature.startswith("aiLatency."):
        return "Azure model latency"
    if feature.startswith("containerApps."):
        return "Container Apps"
    if feature.startswith("vmSkus."):
        return "VM SKUs"
    return feature.split(".", 1)[0]


def _feature_group(feature: str) -> str:
    if feature.startswith("extensionTypes."):
        parts = feature.removeprefix("extensionTypes.").split(".")
        return parts[0] if parts else "unknown"
    if feature.startswith("extensions."):
        return "curated"
    if feature.startswith("kubernetesVersions."):
        return feature.removeprefix("kubernetesVersions.")
    if feature.startswith("hostingPlans."):
        return "hosting plans"
    if feature.startswith("runtimes."):
        parts = feature.removeprefix("runtimes.").split(".")
        return parts[0] if parts else "runtime"
    if feature.startswith("aiModels."):
      parts = feature.removeprefix("aiModels.").split(".")
      return parts[0] if parts else "unknown"
    if feature.startswith("modelLatency."):
        parts = feature.removeprefix("modelLatency.").split(".")
        return parts[0] if parts else "unknown"
    if feature.startswith("aiLatency."):
        parts = feature.removeprefix("aiLatency.").split(".")
        return parts[0] if parts else "unknown"
    if feature.startswith("containerApps."):
      if feature.endswith("daprComponents"):
        return "dapr"
      if feature.endswith("connectedEnvironments"):
        return "connected environments"
      return "core"
    if feature.startswith("vmSkus."):
        return _vm_sku_family(feature)
    return feature.split(".", 1)[0]


def _vm_sku_family(feature: str) -> str:
    sku = feature.removeprefix("vmSkus.").removeprefix("standard.")
    match = re.match(r"([a-z]+)", sku)
    return match.group(1).upper() if match else "Other"


def _modality_summaries(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    summaries: dict[str, dict[str, object]] = {}
    for row in rows:
        category = str(row["category"])
        summary = summaries.setdefault(
            category,
            {"category": category, "features": set(), "checks": 0, "statuses": {}},
        )
        summary["features"].add(str(row["feature"]))
        summary["checks"] = int(summary["checks"]) + 1
        statuses = summary["statuses"]
        status = str(row["status"])
        statuses[status] = statuses.get(status, 0) + 1
    return sorted(summaries.values(), key=lambda item: str(item["category"]))


def _render_modality_row(row: dict[str, object]) -> str:
    statuses = row["statuses"]
    return f"""<tr>
                <td>{html.escape(str(row["category"]))}</td>
                <td class="number">{len(row["features"])}</td>
                <td class="number">{row["checks"]}</td>
                <td class="number">{statuses.get("available", 0)}</td>
                <td class="number">{statuses.get("unavailable", 0)}</td>
                <td class="number">{statuses.get("partial", 0)}</td>
                <td class="number">{statuses.get("unknown", 0)}</td>
              </tr>"""


def _region_modality_group_summaries(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    summaries: dict[tuple[str, str], dict[str, object]] = {}
    for row in rows:
        region = str(row["region"])
        category = str(row["category"])
        group = str(row["group"])
        summary = summaries.setdefault(
            (category, group), {"category": category, "group": group, "regions": {}}
        )
        region_summary = summary["regions"].setdefault(
          region,
          {"available": 0, "unavailable": 0, "partial": 0, "unknown": 0, "total": 0},
        )
        region_summary["total"] += 1
        status = str(row["status"])
        region_summary[status] = region_summary.get(status, 0) + 1
    return sorted(
        summaries.values(),
        key=lambda item: (str(item["category"]), str(item["group"])),
    )


def _render_regional_availability_tables(rows: list[dict[str, object]], regions: list[str]) -> str:
    summaries = _region_modality_group_summaries(rows)
    summaries_by_modality: dict[str, list[dict[str, object]]] = {}
    for summary in summaries:
        summaries_by_modality.setdefault(str(summary["category"]), []).append(summary)

    return "\n".join(
        _render_modality_availability_table(modality, summaries_by_modality[modality], regions)
        for modality in _sorted_modalities(summaries_by_modality)
    )


def _sorted_modalities(summaries_by_modality: dict[str, list[dict[str, object]]]) -> list[str]:
    preferred_order = [
        "AKS extensions",
        "AKS Kubernetes versions",
        "Azure Functions",
        "Azure AI models",
        "Container Apps",
        "VM SKUs",
    ]
    ordered = [modality for modality in preferred_order if modality in summaries_by_modality]
    ordered.extend(sorted(set(summaries_by_modality) - set(preferred_order)))
    return ordered


def _render_modality_availability_table(
    modality: str, summaries: list[dict[str, object]], regions: list[str]
) -> str:
    region_headers = "\n".join(_render_region_header(region) for region in regions)
    group_rows = "\n".join(_render_region_group_row(row, regions) for row in summaries)
    return f"""<section class="panel availability-section" aria-label="{html.escape(modality)} regional availability">
          <div class="panel-header">
            <h2>{html.escape(modality)}</h2>
            <div class="panel-subtitle">Groups by country, then Azure region</div>
          </div>
          <div class="matrix-scroll-top" aria-hidden="true"><div></div></div>
          <div class="table-wrap availability-matrix">
            <table>
              <thead>
                <tr>
                  <th>Group</th>
                  {region_headers}
                </tr>
              </thead>
              <tbody>{group_rows}</tbody>
            </table>
          </div>
        </section>"""


def _render_region_header(region: str) -> str:
    badge = _region_badge(region)
    country_name = _region_country_name(region)
    flag = _region_flag(badge, country_name)
    label = _region_short_label(region)
    title = f"{country_name} - {region}"
    return f"""<th class="region-header" title="{html.escape(title)}">
                    <span class="region-heading">{flag}<span class="region-label">{html.escape(label)}</span></span>
            </th>"""


def _render_region_group_row(row: dict[str, object], regions: list[str]) -> str:
    region_cells = "\n".join(
    _render_availability_cell(
      row["regions"].get(region), region, str(row["category"]), str(row["group"])
    )
    for region in regions
    )
    return f"""<tr>
                <td><code>{html.escape(str(row["group"]))}</code></td>
                {region_cells}
              </tr>"""


def _render_large_extension_group_tables(rows: list[dict[str, object]], regions: list[str]) -> str:
    summaries = _large_extension_group_summaries(rows)
    if not summaries:
        return ""

    tables = "\n".join(_render_large_extension_group_table(summary, regions) for summary in summaries)
    return f"""<section class="availability-stack" aria-label="Large AKS extension group availability">
      <div class="section-heading">
        <h2>Large AKS Extension Groups</h2>
        <div class="panel-subtitle">Extension groups with more than {_LARGE_EXTENSION_GROUP_THRESHOLD} extensions</div>
      </div>
    </section>
    {tables}"""


def _large_extension_group_summaries(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    summaries: dict[str, dict[str, object]] = {}
    for row in rows:
        feature = str(row["feature"])
        if str(row["category"]) != "AKS extensions" or not feature.startswith("extensionTypes."):
            continue

        group = str(row["group"])
        summary = summaries.setdefault(group, {"group": group, "features": {}})
        feature_summary = summary["features"].setdefault(
            feature,
            {
                "feature": feature,
                "label": _extension_feature_label(feature, group),
                "regions": {},
            },
        )
        feature_summary["regions"][str(row["region"])] = str(row["status"])

    large_summaries = [
        summary
        for summary in summaries.values()
        if len(summary["features"]) > _LARGE_EXTENSION_GROUP_THRESHOLD
    ]
    return sorted(
        large_summaries,
        key=lambda item: (
            not _is_primary_extension_group(str(item["group"])),
            str(item["group"]),
            len(item["features"]),
        ),
    )


def _render_large_extension_group_table(summary: dict[str, object], regions: list[str]) -> str:
    group = str(summary["group"])
    features = sorted(
        summary["features"].values(),
        key=lambda item: str(item["label"]),
    )
    table = _render_extension_feature_table(features, regions)
    heading = f"AKS extensions: {html.escape(group)}"
    subtitle = f"{len(features):,} extensions by country, then Azure region"
    if not _is_primary_extension_group(group):
        return f"""<details class="panel availability-section extension-group-section extension-group-collapsed" aria-label="AKS extension group {html.escape(group)} regional availability">
          <summary class="panel-header extension-group-summary">
            <h2>{heading}</h2>
            <div class="panel-subtitle">{subtitle}</div>
          </summary>
          <div class="lazy-matrix-placeholder">Open to load this extension matrix.</div>
          <template>{table}</template>
        </details>"""

    return f"""<section class="panel availability-section extension-group-section" aria-label="AKS extension group {html.escape(group)} regional availability">
          <div class="panel-header">
            <h2>{heading}</h2>
            <div class="panel-subtitle">{subtitle}</div>
          </div>
          {table}
        </section>"""


def _render_extension_feature_table(features: list[dict[str, object]], regions: list[str]) -> str:
    region_headers = "\n".join(_render_region_header(region) for region in regions)
    feature_rows = "\n".join(_render_extension_feature_row(feature, regions) for feature in features)
    return f"""<div class="matrix-scroll-top" aria-hidden="true"><div></div></div>
          <div class="table-wrap availability-matrix extension-feature-matrix">
            <table>
              <thead>
                <tr>
                  <th>Extension</th>
                  {region_headers}
                </tr>
              </thead>
              <tbody>{feature_rows}</tbody>
            </table>
          </div>"""


def _is_primary_extension_group(group: str) -> bool:
    return group in _PRIMARY_EXTENSION_GROUPS


def _render_extension_feature_row(feature: dict[str, object], regions: list[str]) -> str:
    region_cells = "\n".join(
        _render_status_cell(feature["regions"].get(region), region) for region in regions
    )
    return f"""<tr>
                <td><code>{html.escape(str(feature["label"]))}</code></td>
                {region_cells}
              </tr>"""


def _render_status_cell(status: str | None, region: str) -> str:
    label_by_status = {"available": "A", "unavailable": "U", "partial": "P", "unknown": "?"}
    if status is None:
        return '<td><span class="status-dot status-unknown" title="not reported">-</span></td>'

    css_status = status if status in label_by_status else "unknown"
    title = f"{region}: {status}"
    return (
        f'<td><span class="status-dot status-{html.escape(css_status)}" title="{html.escape(title)}">'
        f'{html.escape(label_by_status.get(status, "?"))}</span></td>'
    )


def _extension_feature_label(feature: str, group: str) -> str:
    label = feature.removeprefix("extensionTypes.")
    group_prefix = f"{group}."
    if label.startswith(group_prefix):
        return label.removeprefix(group_prefix)
    return label


def _region_flag(country_code: str, label: str | None = None) -> str:
    aria = (
        "Unknown country"
        if country_code == "UN"
        else (label or _COUNTRY_NAMES.get(country_code, country_code))
    )
    display = "?" if country_code == "UN" else country_code
    return (
        f'<span class="region-flag-fallback" title="{html.escape(aria)}" '
        f'aria-label="{html.escape(aria)}">{html.escape(display)}</span>'
    )


def _sort_regions(regions: dict[str, object]) -> list[str]:
  return sorted(
    regions,
    key=lambda region: (_region_country_name(region), _region_short_label(region), region),
  )


def _region_badge(region: str) -> str:
    geo = _GEOGRAPHY_REGIONS.get(region.lower().replace(" ", ""))
    if geo:
        return geo["badge"]
    return _region_country_code(region)


def _region_country_name(region: str) -> str:
    geo = _GEOGRAPHY_REGIONS.get(region.lower().replace(" ", ""))
    if geo:
        return geo["name"]
    return _COUNTRY_NAMES.get(_region_country_code(region), "Unknown")


def _region_country_code(region: str) -> str:
    normalized = region.lower().replace(" ", "")
    us_regions = {
        "centralus",
        "centraluseuap",
        "eastus",
        "eastus2",
        "eastus2euap",
        "northcentralus",
        "southcentralus",
        "westcentralus",
        "westus",
        "westus2",
        "westus3",
    }
    if normalized in us_regions:
        return "US"
    if normalized.startswith("canada"):
        return "CA"
    if normalized.startswith("brazil"):
        return "BR"
    if normalized.startswith("mexico"):
        return "MX"
    if normalized.startswith("chile"):
        return "CL"
    if normalized.startswith("denmark"):
      return "DK"
    if normalized.startswith("finland"):
      return "FI"
    if normalized.startswith("greece"):
      return "GR"
    if normalized.startswith("portugal"):
      return "PT"
    if normalized.startswith("uk"):
        return "GB"
    if normalized.startswith("france"):
        return "FR"
    if normalized.startswith("germany"):
        return "DE"
    if normalized.startswith("italy"):
        return "IT"
    if normalized.startswith("spain"):
        return "ES"
    if normalized.startswith("poland"):
        return "PL"
    if normalized.startswith("sweden"):
        return "SE"
    if normalized.startswith("norway"):
        return "NO"
    if normalized.startswith("switzerland"):
        return "CH"
    if normalized.startswith("austria"):
        return "AT"
    if normalized.startswith("belgium"):
        return "BE"
    if normalized in {"northeurope", "westeurope"}:
        return "IE" if normalized == "northeurope" else "NL"
    if normalized.startswith("australia"):
        return "AU"
    if normalized.startswith("newzealand"):
        return "NZ"
    if normalized.startswith("japan"):
        return "JP"
    if normalized.startswith("korea"):
        return "KR"
    if normalized.startswith("india") or normalized in {"centralindia", "southindia", "westindia"}:
        return "IN"
    if normalized.startswith("china"):
        return "CN"
    if normalized.startswith("taiwan"):
        return "TW"
    if normalized.startswith("malaysia"):
        return "MY"
    if normalized.startswith("indonesia"):
        return "ID"
    if normalized.startswith("israel"):
        return "IL"
    if normalized.startswith("qatar"):
        return "QA"
    if normalized.startswith("uae"):
        return "AE"
    if normalized.startswith("southafrica"):
        return "ZA"
    if normalized == "eastasia":
        return "HK"
    if normalized == "southeastasia":
        return "SG"
    return "UN"


def _region_short_label(region: str) -> str:
    normalized = region.lower().replace(" ", "")
    geo = _GEOGRAPHY_REGIONS.get(normalized)
    if geo:
        return geo["label"]
    replacements = {
      "eastus": "east",
      "eastus2": "east2",
      "centralus": "central",
      "northcentralus": "n central",
      "southcentralus": "s central",
      "westcentralus": "w central",
      "westus": "west",
      "westus2": "west2",
      "westus3": "west3",
      "canadacentral": "central",
      "canadaeast": "east",
      "brazilsouth": "south",
      "brazilsoutheast": "se",
      "mexicocentral": "central",
      "chilecentral": "central",
      "denmarkeast": "east",
      "finlandcentral": "central",
      "greececentral": "central",
      "portugalcentral": "central",
      "uksouth": "south",
      "ukwest": "west",
      "francecentral": "central",
      "francesouth": "south",
      "germanywestcentral": "w central",
      "germanynorth": "north",
      "italynorth": "north",
      "spaincentral": "central",
      "polandcentral": "central",
      "swedencentral": "central",
      "norwayeast": "east",
      "norwaywest": "west",
      "switzerlandnorth": "north",
      "switzerlandwest": "west",
      "austriaeast": "east",
      "belgiumcentral": "central",
      "northeurope": "north",
      "westeurope": "west",
      "australiaeast": "east",
      "australiasoutheast": "se",
      "australiacentral": "central",
      "australiacentral2": "central2",
      "newzealandnorth": "north",
      "japaneast": "east",
      "japanwest": "west",
      "koreacentral": "central",
      "koreasouth": "south",
      "centralindia": "central",
      "southindia": "south",
      "westindia": "west",
      "chinanorth3": "north3",
      "chinaeast3": "east3",
      "taiwannorth": "north",
      "taiwannorthwest": "nw",
      "malaysiawest": "west",
      "indonesiacentral": "central",
      "eastasia": "east",
      "southeastasia": "se",
      "israelcentral": "central",
      "qatarcentral": "central",
      "uaecentral": "central",
      "uaenorth": "north",
      "southafricanorth": "north",
      "southafricawest": "west",
    }
    return replacements.get(normalized, normalized)


def _index_script() -> str:
    return r"""
  let availabilityRowsPromise = null;
  let availabilityRows = [];
  let availabilityRegions = [];

    function syncAvailabilityScrollbars() {
      document.querySelectorAll('.availability-section').forEach((section) => {
        const top = section.querySelector('.matrix-scroll-top');
        const body = section.querySelector('.availability-matrix');
        const spacer = top ? top.firstElementChild : null;
        if (!top || !body || !spacer) return;
        spacer.style.width = `${body.scrollWidth}px`;
        if (section.dataset.scrollSynced === 'true') return;
        section.dataset.scrollSynced = 'true';
        let syncing = false;
        const sync = (source, target) => {
          if (syncing) return;
          syncing = true;
          target.scrollLeft = source.scrollLeft;
          syncing = false;
        };
        top.addEventListener('scroll', () => sync(top, body));
        body.addEventListener('scroll', () => sync(body, top));
      });
    }
    function initializeLazyExtensionGroups() {
      document.querySelectorAll('.extension-group-collapsed').forEach((section) => {
        section.addEventListener('toggle', () => {
          if (!section.open || section.dataset.loaded === 'true') return;
          const template = section.querySelector('template');
          const placeholder = section.querySelector('.lazy-matrix-placeholder');
          if (!template || !placeholder) return;
          placeholder.replaceWith(template.content.cloneNode(true));
          section.dataset.loaded = 'true';
          template.remove();
          syncAvailabilityScrollbars();
        });
      });
    }
    function availabilityCategory(feature) {
      if (feature === 'extensionCatalog') return 'AKS extensions';
      if (feature.startsWith('extensions.') || feature.startsWith('extensionTypes.')) return 'AKS extensions';
      if (feature.startsWith('kubernetesVersions.')) return 'AKS Kubernetes versions';
      if (feature.startsWith('hostingPlans.') || feature.startsWith('runtimes.')) return 'Azure Functions';
      if (feature.startsWith('aiModels.')) return 'Azure AI models';
      if (feature.startsWith('aiLatency.')) return 'Azure model latency';
      if (feature.startsWith('containerApps.')) return 'Container Apps';
      if (feature.startsWith('vmSkus.')) return 'VM SKUs';
      return feature.split('.')[0];
    }
    function availabilityGroup(feature) {
      if (feature.startsWith('extensionTypes.')) return feature.replace('extensionTypes.', '').split('.')[0] || 'unknown';
      if (feature.startsWith('extensions.')) return 'curated';
      if (feature.startsWith('kubernetesVersions.')) return feature.replace('kubernetesVersions.', '');
      if (feature.startsWith('hostingPlans.')) return 'hosting plans';
      if (feature.startsWith('runtimes.')) return feature.replace('runtimes.', '').split('.')[0] || 'runtime';
      if (feature.startsWith('aiModels.')) return feature.replace('aiModels.', '').split('.')[0] || 'unknown';
      if (feature.startsWith('aiLatency.')) return feature.replace('aiLatency.', '').split('.')[0] || 'unknown';
      if (feature.startsWith('containerApps.')) {
        if (feature.endsWith('daprComponents')) return 'dapr';
        if (feature.endsWith('connectedEnvironments')) return 'connected environments';
        return 'core';
      }
      if (feature.startsWith('vmSkus.')) {
        const sku = feature.replace('vmSkus.', '').replace('standard.', '');
        const match = sku.match(/^([a-z]+)/i);
        return match ? match[1].toUpperCase() : 'Other';
      }
      return feature.split('.')[0];
    }
    function compactFeatureName(feature, group) {
      if (feature.startsWith('extensionTypes.')) {
        const label = feature.replace('extensionTypes.', '');
        const prefix = `${group}.`;
        return label.startsWith(prefix) ? label.slice(prefix.length) : label;
      }
      return feature
        .replace('kubernetesVersions.', '')
        .replace('hostingPlans.', '')
        .replace('runtimes.', '')
        .replace('aiModels.', '')
        .replace('containerApps.', '')
        .replace('vmSkus.', '');
    }
    function escapeHtml(value) {
      return String(value ?? '').replace(/[&<>'"]/g, (char) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
      }[char]));
    }
    function availabilityRowsFromShard(shard) {
      const label = shard.modality || '';
      return (shard.rows || []).map((item) => {
        const feature = item.feature || '';
        return {
          region: item.region || '',
          service: item.service || '',
          feature,
          category: label || availabilityCategory(feature),
          group: availabilityGroup(feature),
          status: item.status || 'unknown',
        };
      });
    }
    function loadAvailabilityRows() {
      if (!availabilityRowsPromise) {
        availabilityRowsPromise = fetch('api/modalities/manifest.json', { cache: 'force-cache' })
          .then((response) => {
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return response.json();
          })
          .then((manifest) => {
            availabilityRegions = sortRegions(manifest.regions || []);
            const modalities = manifest.modalities || [];
            return Promise.all(
              modalities.map((modality) => fetch(`api/${modality.path}`, { cache: 'force-cache' })
                .then((response) => {
                  if (!response.ok) throw new Error(`HTTP ${response.status}`);
                  return response.json();
                })
                .then(availabilityRowsFromShard)),
            ).then((shardRows) => {
              availabilityRows = shardRows.flat();
              return { rows: availabilityRows, regions: availabilityRegions };
            });
          });
      }
      return availabilityRowsPromise;
    }
    function statusFromCounts(summary) {
      if ((summary.available || 0) > 0) return 'available';
      if ((summary.unavailable || 0) > 0) return 'unavailable';
      if ((summary.partial || 0) > 0) return 'partial';
      return 'unknown';
    }
    function statusInitial(status) {
      return { available: 'A', unavailable: 'U', partial: 'P', unknown: '?' }[status] || '?';
    }
    function regionCountryCode(region) {
      const normalized = region.toLowerCase().replace(/\s/g, '');
      const usRegions = new Set(['centralus', 'centraluseuap', 'eastus', 'eastus2', 'eastus2euap', 'northcentralus', 'southcentralus', 'westcentralus', 'westus', 'westus2', 'westus3']);
      if (usRegions.has(normalized)) return 'US';
      if (normalized.startsWith('canada')) return 'CA';
      if (normalized.startsWith('brazil')) return 'BR';
      if (normalized.startsWith('mexico')) return 'MX';
      if (normalized.startsWith('chile')) return 'CL';
      if (normalized.startsWith('denmark')) return 'DK';
      if (normalized.startsWith('finland')) return 'FI';
      if (normalized.startsWith('greece')) return 'GR';
      if (normalized.startsWith('portugal')) return 'PT';
      if (normalized.startsWith('uk')) return 'GB';
      if (normalized.startsWith('france')) return 'FR';
      if (normalized.startsWith('germany')) return 'DE';
      if (normalized.startsWith('italy')) return 'IT';
      if (normalized.startsWith('spain')) return 'ES';
      if (normalized.startsWith('poland')) return 'PL';
      if (normalized.startsWith('sweden')) return 'SE';
      if (normalized.startsWith('norway')) return 'NO';
      if (normalized.startsWith('switzerland')) return 'CH';
      if (normalized.startsWith('austria')) return 'AT';
      if (normalized.startsWith('belgium')) return 'BE';
      if (normalized === 'northeurope') return 'IE';
      if (normalized === 'westeurope') return 'NL';
      if (normalized.startsWith('australia')) return 'AU';
      if (normalized.startsWith('newzealand')) return 'NZ';
      if (normalized.startsWith('japan')) return 'JP';
      if (normalized.startsWith('korea')) return 'KR';
      if (normalized.startsWith('india') || ['centralindia', 'southindia', 'westindia'].includes(normalized)) return 'IN';
      if (normalized.startsWith('china')) return 'CN';
      if (normalized.startsWith('taiwan')) return 'TW';
      if (normalized.startsWith('malaysia')) return 'MY';
      if (normalized.startsWith('indonesia')) return 'ID';
      if (normalized.startsWith('israel')) return 'IL';
      if (normalized.startsWith('qatar')) return 'QA';
      if (normalized.startsWith('uae')) return 'AE';
      if (normalized.startsWith('southafrica')) return 'ZA';
      if (normalized === 'eastasia') return 'HK';
      if (normalized === 'southeastasia') return 'SG';
      return 'UN';
    }
    const GEOGRAPHY_REGIONS = {
      eastasia: { name: 'East Asia', badge: 'AS', label: 'E Asia' },
      southeastasia: { name: 'Southeast Asia', badge: 'AS', label: 'SE Asia' },
      northeurope: { name: 'North Europe', badge: 'EU', label: 'N Europe' },
      westeurope: { name: 'West Europe', badge: 'EU', label: 'W Europe' },
    };
    function regionBadge(region) {
      const geo = GEOGRAPHY_REGIONS[region.toLowerCase().replace(/\s/g, '')];
      return geo ? geo.badge : regionCountryCode(region);
    }
    function regionCountryName(region) {
      const geo = GEOGRAPHY_REGIONS[region.toLowerCase().replace(/\s/g, '')];
      if (geo) return geo.name;
      return {
        AE: 'United Arab Emirates', AT: 'Austria', AU: 'Australia', BE: 'Belgium', BR: 'Brazil', CA: 'Canada', CH: 'Switzerland', CL: 'Chile', CN: 'China', DE: 'Germany', DK: 'Denmark', ES: 'Spain', FI: 'Finland', FR: 'France', GB: 'United Kingdom', GR: 'Greece', HK: 'Hong Kong', ID: 'Indonesia', IE: 'Ireland', IL: 'Israel', IN: 'India', IT: 'Italy', JP: 'Japan', KR: 'Korea', MX: 'Mexico', MY: 'Malaysia', NL: 'Netherlands', NO: 'Norway', NZ: 'New Zealand', PL: 'Poland', PT: 'Portugal', QA: 'Qatar', SE: 'Sweden', SG: 'Singapore', TW: 'Taiwan', US: 'United States', ZA: 'South Africa', UN: 'Unknown'
      }[regionCountryCode(region)] || 'Unknown';
    }
    function regionShortLabel(region) {
      const normalized = region.toLowerCase().replace(/\s/g, '');
      const geo = GEOGRAPHY_REGIONS[normalized];
      if (geo) return geo.label;
      return {
        eastus: 'east', eastus2: 'east2', centralus: 'central', northcentralus: 'n central', southcentralus: 's central', westcentralus: 'w central', westus: 'west', westus2: 'west2', westus3: 'west3', canadacentral: 'central', canadaeast: 'east', brazilsouth: 'south', brazilsoutheast: 'se', mexicocentral: 'central', chilecentral: 'central', denmarkeast: 'east', finlandcentral: 'central', greececentral: 'central', portugalcentral: 'central', uksouth: 'south', ukwest: 'west', francecentral: 'central', francesouth: 'south', germanywestcentral: 'w central', germanynorth: 'north', italynorth: 'north', spaincentral: 'central', polandcentral: 'central', swedencentral: 'central', norwayeast: 'east', norwaywest: 'west', switzerlandnorth: 'north', switzerlandwest: 'west', austriaeast: 'east', belgiumcentral: 'central', northeurope: 'north', westeurope: 'west', australiaeast: 'east', australiasoutheast: 'se', australiacentral: 'central', australiacentral2: 'central2', newzealandnorth: 'north', japaneast: 'east', japanwest: 'west', koreacentral: 'central', koreasouth: 'south', centralindia: 'central', southindia: 'south', westindia: 'west', chinanorth3: 'north3', chinaeast3: 'east3', taiwannorth: 'north', taiwannorthwest: 'nw', malaysiawest: 'west', indonesiacentral: 'central', eastasia: 'east', southeastasia: 'se', israelcentral: 'central', qatarcentral: 'central', uaecentral: 'central', uaenorth: 'north', southafricanorth: 'north', southafricawest: 'west'
      }[normalized] || normalized;
    }
    function sortRegions(regions) {
      return [...regions].sort((a, b) => regionCountryName(a).localeCompare(regionCountryName(b)) || regionShortLabel(a).localeCompare(regionShortLabel(b)) || a.localeCompare(b));
    }
    function availabilityHealthClass(available, total) {
      if (!total) return 'availability-empty';
      const missing = total - available;
      if (missing === 0) return 'availability-good';
      if (missing === 1) return 'availability-warn';
      if (missing === 2) return 'availability-caution';
      return 'availability-poor';
    }
    function triggerAttributes(region, category, group, title) {
      return `tabindex="0" title="${escapeHtml(title)}" data-region="${escapeHtml(region)}" data-category="${escapeHtml(category)}" data-group="${escapeHtml(group)}"`;
    }
    function renderRegionHeader(region) {
      const badge = regionBadge(region);
      const countryName = regionCountryName(region);
      const display = badge === 'UN' ? '?' : badge;
      return `<th class="region-header" title="${escapeHtml(`${countryName} - ${region}`)}"><span class="region-heading"><span class="region-flag-fallback" title="${escapeHtml(countryName)}" aria-label="${escapeHtml(countryName)}">${escapeHtml(display)}</span><span class="region-label">${escapeHtml(regionShortLabel(region))}</span></span></th>`;
    }
    function summarizeRegionalGroups(rows) {
      const summaries = new Map();
      rows.forEach((row) => {
        const key = `${row.category}|${row.group}`;
        if (!summaries.has(key)) summaries.set(key, { category: row.category, group: row.group, regions: new Map() });
        const summary = summaries.get(key);
        if (!summary.regions.has(row.region)) {
          summary.regions.set(row.region, { available: 0, unavailable: 0, partial: 0, unknown: 0, total: 0 });
        }
        const regionSummary = summary.regions.get(row.region);
        regionSummary.total += 1;
        regionSummary[row.status] = (regionSummary[row.status] || 0) + 1;
      });
      return Array.from(summaries.values()).sort((a, b) => a.category.localeCompare(b.category) || a.group.localeCompare(b.group));
    }
    function sortedModalities(summaries) {
      const preferred = ['AKS extensions', 'AKS Kubernetes versions', 'Azure Functions', 'Azure AI models', 'Container Apps', 'VM SKUs'];
      const available = [...new Set(summaries.map((summary) => summary.category))];
      return [
        ...preferred.filter((modality) => available.includes(modality)),
        ...available.filter((modality) => !preferred.includes(modality)).sort(),
      ];
    }
    function renderAvailabilityCell(summary, region, category, group) {
      if (!summary) return '<td><span class="availability-badge availability-empty">-</span></td>';
      const title = `${region}: ${(summary.available || 0).toLocaleString()} available, ${(summary.unavailable || 0).toLocaleString()} unavailable, ${(summary.partial || 0).toLocaleString()} partial, ${(summary.unknown || 0).toLocaleString()} unknown, ${summary.total.toLocaleString()} total`;
      const attrs = triggerAttributes(region, category, group, title);
      if (summary.total === 1) {
        const status = statusFromCounts(summary);
        return `<td><span class="status-dot status-${escapeHtml(status)} availability-single availability-tooltip-trigger" ${attrs}>${escapeHtml(statusInitial(status))}</span></td>`;
      }
      const healthClass = availabilityHealthClass(summary.available || 0, summary.total);
      return `<td><span class="availability-badge availability-tooltip-trigger ${healthClass}" ${attrs}><span class="availability-count">${(summary.available || 0).toLocaleString()}/${summary.total.toLocaleString()}</span></span></td>`;
    }
    function renderRegionalAvailability(rows, regions) {
      const root = document.getElementById('regional-availability-root');
      const status = document.getElementById('regional-availability-status');
      if (!root) return;
      const summaries = summarizeRegionalGroups(rows);
      const headers = regions.map(renderRegionHeader).join('');
      root.innerHTML = sortedModalities(summaries).map((modality) => {
        const groupRows = summaries
          .filter((summary) => summary.category === modality)
          .map((summary) => `<tr><td><code>${escapeHtml(summary.group)}</code></td>${regions.map((region) => renderAvailabilityCell(summary.regions.get(region), region, summary.category, summary.group)).join('')}</tr>`)
          .join('');
        return `<section class="panel availability-section" aria-label="${escapeHtml(modality)} regional availability">
          <div class="panel-header"><h2>${escapeHtml(modality)}</h2><div class="panel-subtitle">Groups by Azure region, rendered from the per-modality API</div></div>
          <div class="matrix-scroll-top" aria-hidden="true"><div></div></div>
          <div class="table-wrap availability-matrix"><table><thead><tr><th>Group</th>${headers}</tr></thead><tbody>${groupRows}</tbody></table></div>
        </section>`;
      }).join('');
      if (status) status.textContent = `${summaries.length.toLocaleString()} groups loaded from the per-modality API`;
    }
    function renderStatusCell(status, region) {
      const labels = { available: 'A', unavailable: 'U', partial: 'P', unknown: '?' };
      const css = labels[status] ? status : 'unknown';
      return `<td><span class="status-dot status-${escapeHtml(css)}" title="${escapeHtml(`${region}: ${status || 'not reported'}`)}">${escapeHtml(labels[status] || '-')}</span></td>`;
    }
    function renderExtensionFeatureTable(features, regions) {
      const headers = regions.map(renderRegionHeader).join('');
      const rows = features.map((feature) => `<tr><td><code>${escapeHtml(feature.label)}</code></td>${regions.map((region) => renderStatusCell(feature.regions[region], region)).join('')}</tr>`).join('');
      return `<div class="matrix-scroll-top" aria-hidden="true"><div></div></div>
        <div class="table-wrap availability-matrix extension-feature-matrix"><table><thead><tr><th>Extension</th>${headers}</tr></thead><tbody>${rows}</tbody></table></div>`;
    }
    function largeExtensionGroups(rows) {
      const summaries = new Map();
      rows.forEach((row) => {
        if (row.category !== 'AKS extensions' || !row.feature.startsWith('extensionTypes.')) return;
        if (!summaries.has(row.group)) summaries.set(row.group, new Map());
        const features = summaries.get(row.group);
        if (!features.has(row.feature)) features.set(row.feature, { label: compactFeatureName(row.feature, row.group), regions: {} });
        features.get(row.feature).regions[row.region] = row.status;
      });
      return Array.from(summaries.entries())
        .map(([group, features]) => ({ group, features: Array.from(features.values()).sort((a, b) => a.label.localeCompare(b.label)) }))
        .filter((summary) => summary.features.length > 10)
        .sort((a, b) => (a.group !== 'microsoft') - (b.group !== 'microsoft') || a.group.localeCompare(b.group) || a.features.length - b.features.length);
    }
    function renderLargeExtensionGroups(rows, regions) {
      const root = document.getElementById('large-extension-groups-root');
      const status = document.getElementById('large-extension-status');
      if (!root) return;
      const summaries = largeExtensionGroups(rows);
      if (!summaries.length) {
        root.innerHTML = '<section class="panel"><div class="lazy-matrix-placeholder">No large extension groups in this snapshot.</div></section>';
        if (status) status.textContent = 'No large extension groups in this snapshot';
        return;
      }
      root.innerHTML = summaries.map((summary) => `<details class="panel availability-section extension-group-section extension-group-collapsed" data-extension-group="${escapeHtml(summary.group)}">
        <summary class="panel-header extension-group-summary"><h2>AKS extensions: ${escapeHtml(summary.group)}</h2><div class="panel-subtitle">${summary.features.length.toLocaleString()} extensions by Azure region</div></summary>
        <div class="lazy-matrix-placeholder">Open to load this extension matrix.</div>
      </details>`).join('');
      summaries.forEach((summary) => {
        const section = root.querySelector(`[data-extension-group="${CSS.escape(summary.group)}"]`);
        section?.addEventListener('toggle', () => {
          if (!section.open || section.dataset.loaded === 'true') return;
          const placeholder = section.querySelector('.lazy-matrix-placeholder');
          if (!placeholder) return;
          placeholder.outerHTML = renderExtensionFeatureTable(summary.features, regions);
          section.dataset.loaded = 'true';
          syncAvailabilityScrollbars();
        });
      });
      if (status) status.textContent = `${summaries.length.toLocaleString()} large extension groups available on demand`;
    }
    function initializeDynamicAvailability() {
      loadAvailabilityRows()
        .then(({ rows, regions }) => {
          renderRegionalAvailability(rows, regions);
          renderLargeExtensionGroups(rows, regions);
          initializeAvailabilityTooltips();
          syncAvailabilityScrollbars();
        })
        .catch(() => {
          const root = document.getElementById('regional-availability-root');
          const status = document.getElementById('regional-availability-status');
          if (root) root.innerHTML = '<section class="panel"><div class="lazy-matrix-placeholder">Could not load modality data for regional availability.</div></section>';
          if (status) status.textContent = 'Could not load regional matrices';
        });
    }
    function initializeAvailabilityTooltips() {
      const triggers = [...document.querySelectorAll('.availability-tooltip-trigger')];
      if (!triggers.length) return;
      let popover = document.querySelector('.availability-popover');
      if (!popover) {
        popover = document.createElement('div');
        popover.className = 'availability-popover';
        popover.setAttribute('role', 'tooltip');
        document.body.appendChild(popover);
      }
      let activeTrigger = null;

      const placePopover = (trigger) => {
        const rect = trigger.getBoundingClientRect();
        const margin = 10;
        const width = popover.offsetWidth || Math.min(520, window.innerWidth - 24);
        const height = popover.offsetHeight || 280;
        const left = Math.min(Math.max(margin, rect.left), window.innerWidth - width - margin);
        const below = rect.bottom + margin;
        const top = below + height < window.innerHeight ? below : Math.max(margin, rect.top - height - margin);
        popover.style.left = `${left}px`;
        popover.style.top = `${top}px`;
      };

      const renderGroups = (matches, group) => {
        const statuses = ['available', 'unavailable', 'partial', 'unknown'];
        return statuses.map((status) => {
          const items = matches
            .filter((row) => row.status === status)
            .map((row) => compactFeatureName(row.feature, group))
            .sort((a, b) => a.localeCompare(b));
          if (!items.length) return '';
          return `<details ${status === 'available' || status === 'unavailable' ? 'open' : ''}>
            <summary>${escapeHtml(status)} (${items.length.toLocaleString()})</summary>
            <div class="tooltip-feature-list">${items.map((item) => `<code>${escapeHtml(item)}</code>`).join('')}</div>
          </details>`;
        }).join('');
      };

      const show = async (trigger) => {
        activeTrigger = trigger;
        const region = trigger.dataset.region || '';
        const category = trigger.dataset.category || '';
        const group = trigger.dataset.group || '';
        popover.innerHTML = `<h3>${escapeHtml(region)} / ${escapeHtml(group)}</h3><div class="tooltip-meta">Loading feature details...</div>`;
        popover.dataset.visible = 'true';
        placePopover(trigger);
        try {
          const { rows } = await loadAvailabilityRows();
          if (activeTrigger !== trigger) return;
          const matches = rows.filter((row) => row.region === region && row.category === category && row.group === group);
          const available = matches.filter((row) => row.status === 'available').length;
          const unavailable = matches.filter((row) => row.status === 'unavailable').length;
          const partial = matches.filter((row) => row.status === 'partial').length;
          const unknown = matches.filter((row) => row.status === 'unknown').length;
          popover.innerHTML = `<h3>${escapeHtml(region)} / ${escapeHtml(group)}</h3>
            <div class="tooltip-meta">${escapeHtml(category)}: ${available.toLocaleString()} available, ${unavailable.toLocaleString()} unavailable, ${partial.toLocaleString()} partial, ${unknown.toLocaleString()} unknown, ${matches.length.toLocaleString()} total</div>
            ${renderGroups(matches, group) || '<div class="tooltip-meta">No matching checks in latest.json.</div>'}`;
          placePopover(trigger);
        } catch (error) {
          if (activeTrigger !== trigger) return;
          popover.innerHTML = '<div class="tooltip-meta">Could not load modality data for details.</div>';
          placePopover(trigger);
        }
      };

      const hide = () => {
        activeTrigger = null;
        popover.dataset.visible = 'false';
      };

      triggers.forEach((trigger) => {
        if (trigger.dataset.tooltipReady === 'true') return;
        trigger.dataset.tooltipReady = 'true';
        trigger.addEventListener('mouseenter', () => show(trigger));
        trigger.addEventListener('focus', () => show(trigger));
        trigger.addEventListener('click', (event) => { event.preventDefault(); show(trigger); });
        trigger.addEventListener('mouseleave', hide);
        trigger.addEventListener('blur', hide);
      });
      if (document.body.dataset.tooltipGlobalReady !== 'true') {
        document.body.dataset.tooltipGlobalReady = 'true';
        document.addEventListener('keydown', (event) => {
          if (event.key === 'Escape') hide();
        });
        window.addEventListener('scroll', () => activeTrigger && placePopover(activeTrigger), { passive: true });
        window.addEventListener('resize', () => activeTrigger && placePopover(activeTrigger));
      }
    }
    window.addEventListener('load', syncAvailabilityScrollbars);
    window.addEventListener('load', initializeDynamicAvailability);
    window.addEventListener('resize', syncAvailabilityScrollbars);
"""


def _render_availability_cell(
  summary: dict[str, int] | None, region: str, category: str, group: str
) -> str:
    if summary is None:
        badge = '<span class="availability-badge availability-empty">-</span>'
    else:
        available = summary["available"]
        total = summary["total"]
        missing = total - available
        title = f"{region}: {available:,} available, {missing:,} not available, {total:,} total"
    trigger_attrs = (
      f'tabindex="0" title="{html.escape(title)}" '
      f'data-region="{html.escape(region)}" '
      f'data-category="{html.escape(category)}" '
      f'data-group="{html.escape(group)}"'
    )
    if total == 1:
      status = _single_summary_status(summary)
      badge = (
        f'<span class="status-dot status-{html.escape(status)} availability-single '
        f'availability-tooltip-trigger" {trigger_attrs}>{html.escape(_status_initial(status))}</span>'
      )
    else:
      health_class = _availability_health_class(available, total)
      badge = (
        f'<span class="availability-badge availability-tooltip-trigger {health_class}" '
        f'{trigger_attrs}>'
        f'<span class="availability-count">{available:,}/{total:,}</span>'
        "</span>"
      )
    return f"<td>{badge}</td>"


def _single_summary_status(summary: dict[str, int]) -> str:
  for status in ("available", "unavailable", "partial", "unknown"):
    if summary.get(status, 0) > 0:
      return status
  return "unknown"


def _status_initial(status: str) -> str:
  return {"available": "A", "unavailable": "U", "partial": "P", "unknown": "?"}.get(status, "?")


def _availability_health_class(available: int, total: int) -> str:
    if total == 0:
        return "availability-empty"
    missing = total - available
    if missing == 0:
        return "availability-good"
    if missing == 1:
        return "availability-warn"
    if missing == 2:
        return "availability-caution"
    return "availability-poor"


def _feature_group_summaries(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    summaries: dict[tuple[str, str], dict[str, object]] = {}
    for row in rows:
        key = (str(row["category"]), str(row["group"]))
        summary = summaries.setdefault(
            key,
            {"category": key[0], "group": key[1], "features": set(), "checks": 0, "available": 0},
        )
        summary["features"].add(str(row["feature"]))
        summary["checks"] = int(summary["checks"]) + 1
        if row["status"] == "available":
            summary["available"] = int(summary["available"]) + 1
    return sorted(
        summaries.values(),
        key=lambda item: (str(item["category"]), -int(item["checks"]), str(item["group"])),
    )


def _render_group_row(row: dict[str, object]) -> str:
    return f"""<tr>
                <td>{html.escape(str(row["category"]))}</td>
                <td><code>{html.escape(str(row["group"]))}</code></td>
                <td class="number">{len(row["features"]):,}</td>
                <td class="number">{int(row["available"]):,}</td>
                <td class="number">{int(row["checks"]):,}</td>
              </tr>"""


def _is_extension_feature(feature: str) -> bool:
    return feature.startswith("extensions.") or feature.startswith("extensionTypes.")


def _heatmap_script() -> str:
    return r"""
    const state = {
      rows: [],
      regions: [],
      filteredRows: [],
      heatmapRows: [],
      detailsPage: 1,
      heatmapPage: 1,
    };
    const statusLabels = { available: 'A', unavailable: 'U', partial: 'P', unknown: '?', '': '-' };
    const statusOrder = { unknown: 0, partial: 1, unavailable: 2, available: 3 };
    const elements = {
      loadStatus: document.getElementById('load-status'),
      search: document.getElementById('search'),
      modality: document.getElementById('modality'),
      group: document.getElementById('group'),
      status: document.getElementById('status'),
      pageSize: document.getElementById('page-size'),
      detailsRows: document.getElementById('details-rows'),
      detailsCount: document.getElementById('detail-count'),
      detailsPage: document.getElementById('details-page'),
      detailsPrev: document.getElementById('details-prev'),
      detailsNext: document.getElementById('details-next'),
      heatmapTable: document.getElementById('heatmap-table'),
      heatmapCount: document.getElementById('heatmap-count'),
      heatmapPage: document.getElementById('heatmap-page'),
      heatmapPrev: document.getElementById('heatmap-prev'),
      heatmapNext: document.getElementById('heatmap-next'),
    };
    const shardCache = new Map();
    let manifestModalities = [];

    function escapeHtml(value) {
      return String(value ?? '').replace(/[&<>'"]/g, (char) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
      }[char]));
    }
    function category(feature) {
      if (feature === 'extensionCatalog') return 'AKS extensions';
      if (feature.startsWith('extensions.') || feature.startsWith('extensionTypes.')) return 'AKS extensions';
      if (feature.startsWith('kubernetesVersions.')) return 'AKS Kubernetes versions';
      if (feature.startsWith('hostingPlans.') || feature.startsWith('runtimes.')) return 'Azure Functions';
      if (feature.startsWith('aiModels.')) return 'Azure AI models';
      if (feature.startsWith('aiLatency.')) return 'Azure model latency';
      if (feature.startsWith('containerApps.')) return 'Container Apps';
      if (feature.startsWith('vmSkus.')) return 'VM SKUs';
      return feature.split('.')[0];
    }
    function group(feature) {
      if (feature.startsWith('extensionTypes.')) return feature.replace('extensionTypes.', '').split('.')[0] || 'unknown';
      if (feature.startsWith('extensions.')) return 'curated';
      if (feature.startsWith('kubernetesVersions.')) return feature.replace('kubernetesVersions.', '');
      if (feature.startsWith('hostingPlans.')) return 'hosting plans';
      if (feature.startsWith('runtimes.')) return feature.replace('runtimes.', '').split('.')[0] || 'runtime';
      if (feature.startsWith('aiModels.')) return feature.replace('aiModels.', '').split('.')[0] || 'unknown';
      if (feature.startsWith('aiLatency.')) return feature.replace('aiLatency.', '').split('.')[0] || 'unknown';
      if (feature.startsWith('containerApps.')) {
        if (feature.endsWith('daprComponents')) return 'dapr';
        if (feature.endsWith('connectedEnvironments')) return 'connected environments';
        return 'core';
      }
      if (feature.startsWith('vmSkus.')) {
        const sku = feature.replace('vmSkus.', '').replace('standard.', '');
        const match = sku.match(/^([a-z]+)/i);
        return match ? match[1].toUpperCase() : 'Other';
      }
      return feature.split('.')[0];
    }
    function rowsFromShard(shard) {
      const label = shard.modality || '';
      const rows = [];
      for (const item of shard.rows || []) {
        const feature = item.feature || '';
        const row = {
          region: item.region || '',
          service: item.service || '',
          feature,
          category: label || category(feature),
          group: group(feature),
          status: item.status || 'unknown',
          message: item.message || '',
        };
        row.searchText = `${row.region} ${row.service} ${row.category} ${row.group} ${row.feature} ${row.status} ${row.message}`.toLowerCase();
        rows.push(row);
      }
      return rows.sort((a, b) => a.region.localeCompare(b.region) || a.category.localeCompare(b.category) || a.feature.localeCompare(b.feature));
    }
    function populateSelect(select, values) {
      const label = select.options[0].textContent;
      const current = select.value;
      select.innerHTML = `<option value="">${escapeHtml(label)}</option>`;
      values.forEach((value) => {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = value;
        select.appendChild(option);
      });
      if (values.includes(current)) select.value = current;
    }
    function applyFilters() {
      const query = elements.search.value.trim().toLowerCase();
      const modality = elements.modality.value;
      const selectedGroup = elements.group.value;
      const status = elements.status.value;
      state.filteredRows = state.rows.filter((row) => (
        (!query || row.searchText.includes(query)) &&
        (!modality || row.category === modality) &&
        (!selectedGroup || row.group === selectedGroup) &&
        (!status || row.status === status)
      )).sort((a, b) => (statusOrder[a.status] ?? 4) - (statusOrder[b.status] ?? 4) || a.region.localeCompare(b.region) || a.feature.localeCompare(b.feature));
      state.heatmapRows = buildHeatmapRows(state.filteredRows);
      state.detailsPage = 1;
      state.heatmapPage = 1;
      renderDetails();
      renderHeatmap();
    }
    function buildHeatmapRows(rows) {
      const byFeature = new Map();
      rows.forEach((row) => {
        const key = `${row.category}|${row.group}|${row.feature}`;
        if (!byFeature.has(key)) byFeature.set(key, { category: row.category, group: row.group, feature: row.feature, regions: {} });
        byFeature.get(key).regions[row.region] = row.status;
      });
      return Array.from(byFeature.values()).sort((a, b) => a.category.localeCompare(b.category) || a.group.localeCompare(b.group) || a.feature.localeCompare(b.feature));
    }
    function pageBounds(total, page) {
      const size = Number(elements.pageSize.value);
      const pages = Math.max(1, Math.ceil(total / size));
      const safePage = Math.min(Math.max(1, page), pages);
      return { size, pages, page: safePage, start: (safePage - 1) * size, end: safePage * size };
    }
    function renderDetails() {
      const bounds = pageBounds(state.filteredRows.length, state.detailsPage);
      state.detailsPage = bounds.page;
      const visible = state.filteredRows.slice(bounds.start, bounds.end);
      elements.detailsRows.innerHTML = visible.map((row) => `
        <tr>
          <td><code>${escapeHtml(row.region)}</code></td>
          <td>${escapeHtml(row.category)}</td>
          <td><code>${escapeHtml(row.group)}</code></td>
          <td><code>${escapeHtml(row.feature)}</code></td>
          <td><span class="status status-${escapeHtml(row.status)}">${escapeHtml(row.status)}</span></td>
          <td>${escapeHtml(row.message)}</td>
        </tr>`).join('') || '<tr><td colspan="6" class="empty">No checks match the current filters.</td></tr>';
      elements.detailsCount.textContent = `${state.filteredRows.length.toLocaleString()} checks`;
      elements.detailsPage.textContent = `Page ${bounds.page} of ${bounds.pages}`;
      elements.detailsPrev.disabled = bounds.page <= 1;
      elements.detailsNext.disabled = bounds.page >= bounds.pages;
    }
    function renderHeatmap() {
      const bounds = pageBounds(state.heatmapRows.length, state.heatmapPage);
      state.heatmapPage = bounds.page;
      const visible = state.heatmapRows.slice(bounds.start, bounds.end);
      const header = `<thead><tr><th>Group</th><th>Feature</th>${state.regions.map((region) => `<th>${escapeHtml(region)}</th>`).join('')}</tr></thead>`;
      const body = visible.map((row) => `<tr>
        <td><code>${escapeHtml(row.group)}</code></td>
        <td><code>${escapeHtml(row.feature)}</code></td>
        ${state.regions.map((region) => {
          const value = row.regions[region] || '';
          const css = value || 'unknown';
          return `<td><span class="status-dot status-${escapeHtml(css)}" title="${escapeHtml(value || 'not reported')}">${escapeHtml(statusLabels[value] || '?')}</span></td>`;
        }).join('')}
      </tr>`).join('') || `<tr><td colspan="${state.regions.length + 2}" class="empty">No features match the current filters.</td></tr>`;
      elements.heatmapTable.innerHTML = header + `<tbody>${body}</tbody>`;
      elements.heatmapCount.textContent = `${state.heatmapRows.length.toLocaleString()} feature rows`;
      elements.heatmapPage.textContent = `Page ${bounds.page} of ${bounds.pages}`;
      elements.heatmapPrev.disabled = bounds.page <= 1;
      elements.heatmapNext.disabled = bounds.page >= bounds.pages;
    }
    async function loadModalityRows(modality) {
      if (shardCache.has(modality.slug)) return shardCache.get(modality.slug);
      const response = await fetch(`api/${modality.path}`, { cache: 'force-cache' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const shard = await response.json();
      const rows = rowsFromShard(shard);
      shardCache.set(modality.slug, rows);
      return rows;
    }
    function regionsFromRows(rows) {
      return [...new Set(rows.map((row) => row.region).filter(Boolean))].sort();
    }
    async function selectModality(label) {
      if (!label) {
        elements.loadStatus.textContent = `Loading all ${manifestModalities.length} modalities...`;
        const all = await Promise.all(manifestModalities.map(loadModalityRows));
        state.rows = all.flat();
        state.regions = regionsFromRows(state.rows);
        populateSelect(elements.group, [...new Set(state.rows.map((row) => row.group))].sort());
        elements.loadStatus.textContent = `${state.rows.length.toLocaleString()} checks loaded across all modalities`;
        applyFilters();
        return;
      }
      const modality = manifestModalities.find((item) => item.label === label);
      if (!modality) return;
      elements.loadStatus.textContent = `Loading ${label}...`;
      const rows = await loadModalityRows(modality);
      state.rows = rows;
      state.regions = regionsFromRows(rows);
      populateSelect(elements.group, [...new Set(rows.map((row) => row.group))].sort());
      elements.loadStatus.textContent = `${rows.length.toLocaleString()} checks loaded for ${label}`;
      applyFilters();
    }
    async function loadManifest() {
      const response = await fetch('api/modalities/manifest.json', { cache: 'no-store' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const manifest = await response.json();
      manifestModalities = (manifest.modalities || []).slice();
      populateSelect(elements.modality, manifestModalities.map((item) => item.label));
      // Prefer the server-chosen default (a real per-region modality) so the heatmap
      // opens showing all regions; fall back to the smallest shard by rows.
      const preferredSlug = manifest.default || null;
      const preferred = preferredSlug
        ? manifestModalities.find((item) => item.slug === preferredSlug)
        : null;
      const smallest = preferred || manifestModalities.reduce(
        (best, item) => (best === null || item.rows < best.rows ? item : best),
        null,
      );
      if (smallest) {
        elements.modality.value = smallest.label;
        await selectModality(smallest.label);
      } else {
        elements.loadStatus.textContent = 'No modality data available yet.';
      }
    }
    elements.search.addEventListener('input', applyFilters);
    elements.modality.addEventListener('change', () => {
      selectModality(elements.modality.value).catch((error) => {
        elements.loadStatus.textContent = `Could not load modality: ${error}`;
      });
    });
    elements.group.addEventListener('change', applyFilters);
    elements.status.addEventListener('change', applyFilters);
    elements.pageSize.addEventListener('change', applyFilters);
    elements.detailsPrev.addEventListener('click', () => { state.detailsPage -= 1; renderDetails(); });
    elements.detailsNext.addEventListener('click', () => { state.detailsPage += 1; renderDetails(); });
    elements.heatmapPrev.addEventListener('click', () => { state.heatmapPage -= 1; renderHeatmap(); });
    elements.heatmapNext.addEventListener('click', () => { state.heatmapPage += 1; renderHeatmap(); });
    loadManifest().catch((error) => { elements.loadStatus.textContent = `Could not load modality manifest: ${error}`; });
"""


def write_static_summary(output_dir: Path) -> str:
    latest_path = output_dir / "api" / "latest.json"
    snapshot = load_snapshot(latest_path)
    rows = _flatten_snapshot(snapshot)
    return json.dumps(
        {
            "timestamp": snapshot.timestamp.isoformat(),
            "features": len(rows),
            "statuses": _status_counts(rows),
        },
        sort_keys=True,
    )
