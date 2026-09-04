from azure_region_monitor.blog import (
    blog_sitemap_entries,
    executive_summary,
    render_blog_feed,
    render_blog_index,
    render_blog_post,
    render_social_drafts,
    select_blog_posts,
    split_narrative,
)

SITE = "https://azwatch.operator.lat"
STYLE = "<style>/* test */</style>"


def _history(days):
    return {"days": days}


def _day(
    date,
    narrative,
    source="ai",
    new=0,
    reg=0,
    parked=0,
    highlights=None,
    excerpt="",
    social_drafts=None,
):
    day = {
        "date": date,
        "narrative": narrative,
        "narrative_source": source,
        "change_type_counts": {"new_availability": new, "regression": reg},
        "parked_unknown_changes": parked,
        "highlights": highlights or [],
    }
    if excerpt:
        day["editorial_excerpt"] = excerpt
    if social_drafts is not None:
        day["social_drafts"] = social_drafts
    return day


def test_split_narrative_ai_headline_and_paragraphs():
    headline, paragraphs = split_narrative("Big day\n\nFirst para.\n\nSecond para.", "ai")
    assert headline == "Big day"
    assert paragraphs == ["First para.", "Second para."]


def test_split_narrative_ai_single_block_splits_first_line():
    headline, paragraphs = split_narrative("Headline only\nThen the body.", "ai")
    assert headline == "Headline only"
    assert paragraphs == ["Then the body."]


def test_split_narrative_rule_has_no_headline():
    headline, paragraphs = split_narrative("Latest scan: 3 signals.", "rule")
    assert headline == ""
    assert paragraphs == ["Latest scan: 3 signals."]


def test_split_narrative_demotes_overlong_single_block_headline():
    # An older/rule-style "ai" narrative that is one long paragraph must not become a
    # giant one-line headline; it becomes body text and the post uses a date title.
    long_block = "In the Canada Central region, " + "many VM SKUs were delisted " * 8
    headline, paragraphs = split_narrative(long_block, "ai")
    assert headline == ""
    assert paragraphs == [long_block.strip()]


def test_select_blog_posts_uses_date_title_when_headline_demoted():
    long_block = "x" * 200
    posts = select_blog_posts(_history([_day("2026-07-03", long_block, source="ai")]))
    assert posts[0]["headline"] == ""
    assert posts[0]["title"] == "Azure regional changes — 2026-07-03"


def test_select_blog_posts_filters_and_sorts_newest_first():
    index = _history(
        [
            _day("2026-07-01", "Older day\n\nBody."),
            _day("2026-07-03", "Newer day\n\nBody."),
            _day("2026-07-02", "", source="rule"),  # no narrative -> skipped
            {"date": "2026-06-30"},  # missing narrative -> skipped
        ]
    )
    posts = select_blog_posts(index)
    assert [p["date"] for p in posts] == ["2026-07-03", "2026-07-01"]
    assert posts[0]["headline"] == "Newer day"
    assert posts[0]["slug"] == "blog/2026-07-03.html"


def test_executive_summary_aggregates_multiple_published_days():
    summary = executive_summary(
        [
            _day("2026-07-03", "Newer\n\nBody.", new=4, reg=1),
            _day("2026-07-01", "Older\n\nBody.", new=2, reg=3),
        ]
    )

    assert "2 published change days (2026-07-01 through 2026-07-03)" in summary
    assert "6 new availability signals and 4 regressions" in summary
    assert "more newly listed availability than regressions" in summary
    assert "monitor is newly listing more regional options" in summary
    assert "quota or deployment results" in summary


def test_blog_index_and_posts_render_the_executive_summary():
    posts = select_blog_posts(
        _history(
            [
                _day("2026-07-03", "Newer\n\nBody.", new=2),
                _day("2026-07-01", "Older\n\nBody.", reg=1),
            ]
        )
    )

    index = render_blog_index(posts, SITE, STYLE)
    post = render_blog_post(posts[0], None, posts[1], SITE, STYLE)

    assert 'aria-label="Executive summary"' in index
    assert 'aria-label="Executive summary"' in post
    assert "2 new availability signals and 1 regression" in index


def test_select_blog_posts_handles_empty_or_missing():
    assert select_blog_posts(None) == []
    assert select_blog_posts({}) == []
    assert select_blog_posts({"days": []}) == []


def test_blog_index_lists_every_post_with_links():
    posts = select_blog_posts(
        _history([_day("2026-07-03", "A\n\nbody a"), _day("2026-07-01", "B\n\nbody b")])
    )
    html = render_blog_index(posts, SITE, STYLE)
    assert "Daily Blog" in html
    assert 'href="/blog/2026-07-03.html"' in html
    assert 'href="/blog/2026-07-01.html"' in html
    assert 'type="application/rss+xml"' in html


def test_blog_index_empty_state_when_no_posts():
    html = render_blog_index([], SITE, STYLE)
    assert "No change summaries have been published yet" in html


def test_blog_post_renders_headline_paragraphs_and_prev_next():
    posts = select_blog_posts(
        _history(
            [
                _day("2026-07-03", "Newest\n\nn body", new=2),
                _day("2026-07-02", "Middle\n\nm body", reg=1),
                _day("2026-07-01", "Oldest\n\no body"),
            ]
        )
    )
    # Middle post: newer=2026-07-03, older=2026-07-01.
    html = render_blog_post(posts[1], posts[0], posts[2], SITE, STYLE)
    assert "Middle" in html
    assert "<p>m body</p>" in html
    assert 'href="/blog/2026-07-01.html"' in html  # older
    assert 'href="/blog/2026-07-03.html"' in html  # newer
    assert f'<link rel="canonical" href="{SITE}/blog/2026-07-02.html">' in html
    assert '<meta property="og:type" content="article">' in html
    assert '<meta name="twitter:card" content="summary">' in html
    assert '<script type="application/ld+json">' in html
    assert '"@type": "BlogPosting"' in html


def test_blog_post_includes_highlights():
    highlights = [
        {
            "region": "eastus",
            "feature": "aiModels.openai.gpt-5.2025",
            "previous": "unavailable",
            "current": "available",
            "change_type": "new_availability",
            "classification_label": "net-new regional availability",
            "expansion_label": "first observed in North America",
            "history_days": 30,
            "missing_days": 30,
            "unavailable_pct": 100.0,
            "feature_current_available_regions": 2,
            "feature_total_regions": 10,
            "feature_current_coverage_pct": 20.0,
            "feature_coverage_delta": 2,
            "region_group": "North America",
            "region_group_current_available_regions": 2,
            "same_day_new_regions": ["eastus", "westus3"],
            "still_available_regions": ["eastus", "westus3"],
            "details_label": "Azure OpenAI model availability",
            "details_url": "https://learn.microsoft.com/azure/ai-foundry/openai/concepts/models",
            "feature_note": "Use this to evaluate model capabilities, regional deployment options, latency, and data residency.",
        },
    ]
    posts = select_blog_posts(_history([_day("2026-07-03", "Head\n\nbody", highlights=highlights)]))
    html = render_blog_post(posts[0], None, None, SITE, STYLE)
    assert "Engineering context" in html
    assert "eastus" in html
    assert "aiModels.openai.gpt-5.2025" in html
    assert "net-new regional availability" in html
    assert "unavailable 30/30 prior days (100.0%)" in html
    assert "coverage 2/10 monitored regions (20.0%, +2 regions)" in html
    assert "Also newly available in eastus, westus3" in html
    assert "Azure OpenAI model availability" in html


def test_blog_feed_is_valid_rss_with_one_item_per_post():
    import xml.etree.ElementTree as ET

    posts = select_blog_posts(
        _history([_day("2026-07-03", "A\n\nbody a"), _day("2026-07-01", "B\n\nbody b")])
    )
    feed = render_blog_feed(posts, SITE)
    root = ET.fromstring(feed)
    channel = root.find("channel")
    items = channel.findall("item")
    assert len(items) == 2
    links = [item.find("link").text for item in items]
    assert f"{SITE}/blog/2026-07-03.html" in links
    assert f"{SITE}/blog/2026-07-01.html" in links
    # pubDate is RFC-822 with a year.
    assert "2026" in items[0].find("pubDate").text


def test_blog_index_and_feed_prefer_persisted_authored_excerpt():
    import xml.etree.ElementTree as ET

    authored_excerpt = "A purpose-written excerpt for the index and feed."
    posts = select_blog_posts(
        _history(
            [
                _day(
                    "2026-07-03",
                    "Headline\n\nA much longer narrative body that should not be mechanically truncated.",
                    excerpt=authored_excerpt,
                )
            ]
        )
    )

    assert authored_excerpt in render_blog_index(posts, SITE, STYLE)
    feed = ET.fromstring(render_blog_feed(posts, SITE))
    assert feed.findtext("./channel/item/description") == authored_excerpt


def test_blog_sitemap_entries_cover_index_and_posts():
    posts = select_blog_posts(
        _history([_day("2026-07-03", "A\n\nbody a"), _day("2026-07-01", "B\n\nbody b")])
    )
    entries = blog_sitemap_entries(posts)
    paths = [path for path, _priority, _lastmod in entries]
    assert "/blog/" in paths
    assert "/blog/2026-07-03.html" in paths
    assert "/blog/2026-07-01.html" in paths
    # Index lastmod is the newest post date.
    index_entry = next(e for e in entries if e[0] == "/blog/")
    assert index_entry[2] == "2026-07-03"


def test_blog_sitemap_entries_empty_without_posts():
    assert blog_sitemap_entries([]) == []


def test_social_drafts_include_review_note_and_platform_drafts():
    highlights = [
        {
            "region": "eastus",
            "feature": "vmSkus.standard.ncads.h100.v5",
            "previous": "unavailable",
            "current": "available",
            "change_type": "new_availability",
            "classification_label": "net-new regional availability",
            "expansion_label": "first observed in North America",
            "history_days": 30,
            "missing_days": 30,
            "unavailable_pct": 100.0,
            "feature_current_available_regions": 2,
            "feature_total_regions": 10,
            "feature_current_coverage_pct": 20.0,
            "feature_coverage_delta": 2,
        }
    ]
    posts = select_blog_posts(
        _history(
            [
                _day(
                    "2026-07-03",
                    "GPU expands\n\nH100 VM coverage moved in two monitored regions.",
                    new=2,
                    highlights=highlights,
                )
            ]
        )
    )

    drafts = render_social_drafts(posts, SITE)

    assert "Review-only drafts" in drafts
    assert "not proof of quota, capacity, deployment failure, or SLA impact" in drafts
    assert "#### LinkedIn draft" in drafts
    assert "#### Short-post draft" in drafts
    assert "Coverage: 2/10 monitored regions (20.0%, +2 regions)." in drafts
    assert f"Full digest: {SITE}/blog/2026-07-03.html" in drafts


def test_social_drafts_use_persisted_editorial_package():
    posts = select_blog_posts(
        _history(
            [
                _day(
                    "2026-07-03",
                    "Headline\n\nBody.",
                    new=1,
                    social_drafts={
                        "linkedin": "Persisted LinkedIn editorial copy.",
                        "short_post": "Persisted short editorial copy.",
                    },
                )
            ]
        )
    )

    drafts = render_social_drafts(posts, SITE)

    assert "Source: Editorial package" in drafts
    assert "Persisted LinkedIn editorial copy." in drafts
    assert "Persisted short editorial copy." in drafts
    assert "Signal counts:" not in drafts
    assert f"Full digest: {SITE}/blog/2026-07-03.html" in drafts


def test_social_drafts_use_structured_fallback_for_legacy_history():
    posts = select_blog_posts(_history([_day("2026-07-03", "Headline\n\nBody.", new=1)]))

    drafts = render_social_drafts(posts, SITE)

    assert "Source: Structured legacy fallback" in drafts
    assert "Signal counts:" in drafts
