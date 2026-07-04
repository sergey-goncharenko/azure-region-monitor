from azure_region_monitor.blog import (
    blog_sitemap_entries,
    render_blog_feed,
    render_blog_index,
    render_blog_post,
    select_blog_posts,
    split_narrative,
)

SITE = "https://azwatch.operator.lat"
STYLE = "<style>/* test */</style>"


def _history(days):
    return {"days": days}


def _day(date, narrative, source="ai", new=0, reg=0, parked=0, highlights=None):
    return {
        "date": date,
        "narrative": narrative,
        "narrative_source": source,
        "change_type_counts": {"new_availability": new, "regression": reg},
        "parked_unknown_changes": parked,
        "highlights": highlights or [],
    }


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


def test_blog_post_includes_highlights():
    highlights = [
        {
            "region": "eastus",
            "feature": "aiModels.openai.gpt-5.2025",
            "previous": "unavailable",
            "current": "available",
            "change_type": "new_availability",
            "classification_label": "net-new regional availability",
        },
    ]
    posts = select_blog_posts(_history([_day("2026-07-03", "Head\n\nbody", highlights=highlights)]))
    html = render_blog_post(posts[0], None, None, SITE, STYLE)
    assert "Notable changes" in html
    assert "eastus" in html
    assert "aiModels.openai.gpt-5.2025" in html
    assert "net-new regional availability" in html


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
