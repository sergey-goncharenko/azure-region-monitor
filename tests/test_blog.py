from azure_region_monitor.blog import (
    blog_sitemap_entries,
    daily_executive_summary,
    render_blog_feed,
    render_blog_index,
    render_blog_post,
    render_social_drafts,
    select_blog_posts,
    split_narrative,
    weekly_context,
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
    previous_date=None,
    classifications=None,
):
    day = {
        "date": date,
        "narrative": narrative,
        "narrative_source": source,
        "change_type_counts": {"new_availability": new, "regression": reg},
        "parked_unknown_changes": parked,
        "highlights": highlights or [],
    }
    if previous_date:
        day["previous_date"] = previous_date
    if classifications:
        day["change_context_counts"] = classifications
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


def test_split_narrative_reflows_legacy_rule_digest_by_section():
    narrative = (
        "Latest scan: 12 new availability signals and 3 regressions. "
        "Azure AI models: models rolled out. Examples: eastus. "
        "VM SKUs: VM sizes withdrawn. Examples: westus. "
        "What this means for Azure users: review targets."
    )

    headline, paragraphs = split_narrative(narrative, "rule")

    assert headline == ""
    assert len(paragraphs) == 4
    assert paragraphs[1].startswith("Azure AI models:")
    assert paragraphs[2].startswith("VM SKUs:")
    assert paragraphs[3].startswith("What this means for Azure users:")


def test_split_narrative_uses_sectioned_rule_headline():
    headline, paragraphs = split_narrative(
        "12 new listings and 3 regressions\n\nCompared with yesterday.\n\nWhat this means for Azure users: review targets.",
        "rule",
    )

    assert headline == "12 new listings and 3 regressions"
    assert paragraphs == [
        "Compared with yesterday.",
        "What this means for Azure users: review targets.",
    ]


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


def test_daily_executive_summary_compares_one_day_with_its_predecessor():
    previous = _day("2026-07-02", "Older\n\nBody.", new=2, reg=0)
    current = _day(
        "2026-07-03",
        "Newer\n\nBody.",
        new=4,
        reg=1,
        previous_date="2026-07-02",
        classifications={"deprecation_candidate": 1, "net_new_availability": 4},
    )
    current["change_modality_counts"] = {
        "VM SKUs": {"new_availability": 3, "regression": 0},
        "Azure AI models": {"new_availability": 1, "regression": 1},
    }
    current["highlights"] = [
        {
            "change_type": "regression",
            "modality": "Azure AI models",
            "feature": "aiModels.moonshotai.kimi-k3.2026-07-29",
            "feature_coverage_delta": -31,
            "region": "australiaeast",
        },
        {
            "change_type": "regression",
            "modality": "Azure AI models",
            "feature": "aiModels.moonshotai.kimi-k3.2026-07-29",
            "feature_coverage_delta": -31,
            "region": "brazilsouth",
        },
        {
            "change_type": "new_availability",
            "modality": "VM SKUs",
            "feature": "vmSkus.standard.ncads.h100.v5",
            "feature_coverage_delta": 1,
            "region": "eastus",
        },
    ]
    summary = daily_executive_summary(current, previous)

    assert "Compared with the 2026-07-02 snapshot, the 2026-07-03 scan" in summary
    assert "4 new listings, 1 regression" in summary
    assert "New listings rose from 2 to 4" in summary
    assert "Regressions rose from 0 to 1" in summary
    assert "Where it changed: VM SKUs: 3 new listings, 0 regressions" in summary
    assert "Azure AI models: 1 new listing, 1 regression" in summary
    assert "Representative changes: Kimi K3 model from Moonshot AI (version 2026-07-29)" in summary
    assert "was no longer listed in 31 regions" in summary
    assert "Standard Ncads H100 V5 VM size was newly listed in eastus" in summary
    assert summary.count("Kimi K3 model") == 1
    assert "What changed: 1 deprecation candidate, 4 net-new regional listings" in summary
    assert "\n\nWhat changed:" in summary
    assert "\n\nWhat this means:" in summary
    assert "not quota, capacity, or deployment results" in summary


def test_daily_summary_recovers_additions_from_legacy_rule_narrative():
    day = _day(
        "2026-09-05",
        (
            "Latest scan: 453 new availability signals and 41 regressions. "
            "Azure AI models: models/versions delisted (31 signals; 31 deprecation candidates). "
            "Examples: australiaeast · model (moonshotai.kimi-k3.2026-07-29). "
            "VM SKUs: VM sizes withdrawn (10 signals; 10 deprecation candidates). "
            "Examples: indiasouthcentral · VM size (m128dms.v2). "
            "Azure AI models: newer models/versions rolling out (29 signals; 29 net-new listings). "
            "Examples: australiaeast · model (openai.gpt-6-astra.2026-09-03). "
            "VM SKUs: VM sizes now offered (424 signals; 422 net-new listings). "
            "Examples: centraluseuap · VM size (ng16ads.v620.v1)."
        ),
        source="rule",
        new=453,
        reg=41,
        previous_date="2026-09-04",
    )
    day["highlights"] = [
        {
            "change_type": "regression",
            "modality": "Azure AI models",
            "feature": "aiModels.moonshotai.kimi-k3.2026-07-29",
            "feature_coverage_delta": -31,
            "region": "australiaeast",
        },
        {
            "change_type": "regression",
            "modality": "VM SKUs",
            "feature": "vmSkus.standard.m128dms.v2",
            "feature_coverage_delta": -1,
            "region": "indiasouthcentral",
        },
    ]

    summary = daily_executive_summary(day)

    assert "Where it changed: VM SKUs: 424 new listings, 10 regressions" in summary
    assert "Azure AI models: 29 new listings, 31 regressions" in summary
    assert "GPT-6 Astra model from OpenAI (version 2026-09-03)" in summary
    assert "was among the new regional listings" in summary
    assert summary.count("Kimi K3 model") == 1


def test_weekly_context_is_limited_to_seven_calendar_days():
    days = [
        _day("2026-07-03", "Current\n\nBody.", new=4, reg=1),
        _day("2026-07-02", "Previous\n\nBody.", new=2, reg=3),
        _day("2026-06-26", "Too old\n\nBody.", new=10_000, reg=10_000),
    ]

    trend = weekly_context(days, "2026-07-03")

    assert "7-day context (2026-06-27 to 2026-07-03)" in trend
    assert "2 recorded scans" in trend
    assert "6 new listings and 4 regressions" in trend
    assert "10,000" not in trend


def test_blog_index_and_posts_render_day_specific_summary_and_weekly_context():
    posts = select_blog_posts(
        _history(
            [
                _day(
                    "2026-07-03",
                    "Newer\n\nBody.",
                    new=2,
                    previous_date="2026-07-01",
                ),
                _day("2026-07-01", "Older\n\nBody.", reg=1),
            ]
        )
    )

    index = render_blog_index(posts, SITE, STYLE)
    post = render_blog_post(posts[0], None, posts[1], SITE, STYLE)

    assert 'aria-label="Daily executive summary"' in index
    assert 'aria-label="Daily executive summary"' in post
    assert "Compared with the 2026-07-01 snapshot, the 2026-07-03 scan" in index
    assert "New listings rose from 0 to 2" in index
    assert "7-day context" in index
    assert "Across 2 published change days" not in index
    assert "the 2026-07-03 scan" in posts[0]["executive_summary"]
    assert "The 2026-07-01 scan" in posts[1]["executive_summary"]
    assert "the 2026-07-03 scan" not in posts[1]["executive_summary"]
    assert "The 2026-07-01 scan recorded" in posts[1]["executive_summary"]
    assert "Compared with the previous snapshot" not in posts[1]["executive_summary"]
    assert "<strong>What this means:</strong>" in post


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
