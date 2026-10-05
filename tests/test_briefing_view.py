import json
import re

from azure_region_monitor.briefing import build_briefing
from azure_region_monitor.blog import render_blog_index, render_blog_post, select_blog_posts
from azure_region_monitor.briefing_view import briefing_excerpt, briefing_headline, render_briefing
from azure_region_monitor.display import plain_feature_name, region_name
from azure_region_monitor.models import Snapshot
from azure_region_monitor.summary import ChangeContext


def _day():
    return {
        "date": "2026-09-06",
        "change_path": "changes/2026-09-06.json",
        "narrative": "Repeated old headline\n\nThe noisiest signal was unavailable 99.1%.",
        "narrative_source": "rule",
        "briefing": {
            "version": 1,
            "current_timestamp": "2026-09-06T08:11:00+00:00",
            "previous_timestamp": "2026-09-05T07:56:00+00:00",
            "baseline_available": True,
            "comparison_days": 1,
            "counts": {
                "new_listings": 267, "delistings": 0, "restorations": 0,
                "observation_gaps": 0, "continuing_absences": 41,
            },
            "regions": ["eastus", "austriaeast", "belgiumcentral", "switzerlandnorth"],
            "modalities": ["VM SKUs", "AKS extensions", "Azure Functions"],
            "groups": [
                {
                    "modality": "VM SKUs",
                    "feature_count": 54, "listing_count": 266,
                    "regions": ["austriaeast", "belgiumcentral", "chilecentral", "denmarkeast", "indiasouthcentral"],
                    "region_counts": {"austriaeast": 52, "belgiumcentral": 54, "chilecentral": 54, "denmarkeast": 54, "indiasouthcentral": 52},
                    "statuses": [{
                        "kind": "new_listings", "feature_count": 54, "listing_count": 266,
                        "regions": ["austriaeast", "belgiumcentral", "chilecentral", "denmarkeast", "indiasouthcentral"],
                        "region_counts": {"austriaeast": 52, "belgiumcentral": 54, "chilecentral": 54, "denmarkeast": 54, "indiasouthcentral": 52},
                        "examples": [{"feature": "vmSkus.standard.d128nds.v6", "coverage_before": {"available": 44}, "coverage_after": {"available": 49}}],
                    }],
                },
                {
                    "modality": "AKS extensions",
                    "feature_count": 1, "listing_count": 1,
                    "regions": ["switzerlandnorth"], "region_counts": {"switzerlandnorth": 1},
                    "statuses": [{
                        "kind": "new_listings", "feature_count": 1, "listing_count": 1,
                        "regions": ["switzerlandnorth"], "region_counts": {"switzerlandnorth": 1},
                        "examples": [{"feature": "extensionTypes.microsoft.vmware", "coverage_before": {"available": 19}, "coverage_after": {"available": 20}}],
                    }],
                },
            ],
        },
    }


def _digest_day(digest):
    return {
        "date": "2026-10-04",
        "change_path": "changes/2026-10-04.json",
        "narrative": "",
        "briefing": {
            "version": 1,
            "current_timestamp": "2026-10-04T08:11:00+00:00",
            "previous_timestamp": "2026-10-03T07:56:00+00:00",
            "baseline_available": True,
            "comparison_days": 1,
            "counts": {
                "new_listings": 0,
                "delistings": 0,
                "restorations": 0,
                "observation_gaps": 13,
                "continuing_absences": 0,
                "scope_changes": 0,
            },
            "regions": ["brazilsouth", "eastasia", "eastus", "northcentralus", "westeurope"],
            "modalities": ["VM SKUs", "GitHub Models"],
            "groups": [],
            "digest": digest,
        },
    }


def _digest(gained_features=2, lost_features=0):
    return {
        "version": 1,
        "totals": {
            "gained_features": gained_features,
            "gained_listings": 5 if gained_features else 0,
            "lost_features": lost_features,
            "lost_listings": 2 if lost_features else 0,
            "catalog_gap_listings": 0,
            "measurement_gap_listings": 13,
        },
        "modalities": [
            {
                "modality": "VM SKUs",
                "gained_features": gained_features,
                "gained_listings": 5 if gained_features else 0,
                "gained_regions": ["brazilsouth", "eastasia", "eastus", "northcentralus"],
                "lost_features": lost_features,
                "lost_listings": 2 if lost_features else 0,
                "lost_regions": ["westeurope"] if lost_features else [],
                "features": [
                    {
                        "feature": "vmSkus.standard.d248ds.v7",
                        "label": "Standard D248ds V7 VM size",
                        "modality": "VM SKUs",
                        "short": "General purpose, 248 vCPUs, local temp disk",
                        "specificity": "exact",
                        "details_url": "https://learn.microsoft.com/azure/virtual-machines/sizes",
                        "gained_regions": ["brazilsouth", "eastasia", "eastus", "northcentralus"],
                        "restored_regions": ["eastasia"],
                        "lost_regions": [],
                        "coverage_before": 9,
                        "coverage_after": 11,
                        "first_seen": True,
                        "new_geographies": ["Asia Pacific"],
                        "learn_reference": {
                            "title": "Dv7 series",
                            "url": "https://learn.microsoft.com/azure/virtual-machines/dv7-series",
                            "excerpt": "Dv7 sizes",
                        },
                    },
                    {
                        "feature": "vmSkus.standard.x",
                        "label": "<script>unsafe</script>",
                        "modality": "VM SKUs",
                        "short": "Escaped short text",
                        "specificity": "unverified",
                        "details_url": "http://learn.microsoft.com/not-safe",
                        "gained_regions": ["eastasia"],
                        "restored_regions": ["eastasia"],
                        "lost_regions": [],
                        "coverage_before": 1,
                        "coverage_after": 2,
                        "first_seen": False,
                        "new_geographies": [],
                        "learn_reference": None,
                    },
                ],
            },
        ],
        "gaps": [
            {
                "modality": "GitHub Models",
                "measurement": True,
                "feature_count": 13,
                "listing_count": 13,
                "regions": ["github-global"],
            }
        ],
    }


def _clustered_digest(*, varying=False):
    second_regions = ["westus3"] if varying else ["eastus"]
    second_after = 4 if varying else 3
    return {
        "version": 1,
        "totals": {
            "gained_features": 2,
            "gained_listings": 2,
            "lost_features": 0,
            "lost_listings": 0,
            "catalog_gap_listings": 0,
            "measurement_gap_listings": 0,
        },
        "modalities": [
            {
                "modality": "VM SKUs",
                "gained_features": 2,
                "gained_listings": 2,
                "gained_regions": sorted({"eastus", *second_regions}),
                "lost_features": 0,
                "lost_listings": 0,
                "lost_regions": [],
                "features": [
                    {
                        "feature": "vmSkus.standard.d2s.v7",
                        "label": "Standard D2s V7 VM size",
                        "modality": "VM SKUs",
                        "short": "General purpose, 2 vCPUs, premium SSD capable (v7)",
                        "cluster": {"key": "vm:D:v7", "label": "Dv7-series · general purpose"},
                        "specificity": "family",
                        "details_url": None,
                        "gained_regions": ["eastus"],
                        "restored_regions": [],
                        "lost_regions": [],
                        "coverage_before": 2,
                        "coverage_after": 3,
                        "first_seen": False,
                        "new_geographies": [],
                        "learn_reference": None,
                    },
                    {
                        "feature": "vmSkus.standard.d4s.v7",
                        "label": "Standard D4s V7 VM size",
                        "modality": "VM SKUs",
                        "short": "General purpose, 4 vCPUs, premium SSD capable (v7)",
                        "cluster": {"key": "vm:D:v7", "label": "Dv7-series · general purpose"},
                        "specificity": "family",
                        "details_url": None,
                        "gained_regions": second_regions,
                        "restored_regions": second_regions,
                        "lost_regions": [],
                        "coverage_before": 2,
                        "coverage_after": second_after,
                        "first_seen": False,
                        "new_geographies": [],
                        "learn_reference": None,
                    },
                ],
            },
        ],
        "gaps": [],
    }


def test_digest_headline_prefers_gains_and_measurement_gaps_do_not_hijack():
    day = _digest_day(_digest())
    page = render_briefing(day)
    assert briefing_headline(day["briefing"]) == "2 VM sizes gained regions · nothing dropped"
    assert 'class="briefing-headline--gain"' in page
    assert "Evidence gaps need attention" not in page
    assert "13 GitHub Models latency checks returned no result" in page
    assert "measurement gap, not catalog evidence" in page
    assert briefing_excerpt(day["briefing"]) == (
        "2 VM sizes gained regions (Brazil South, East Asia, East US, North Central US); "
        "nothing dropped; 13 measurement gaps were not catalog evidence. "
        "Catalog evidence, not deployment results."
    )


def test_digest_headline_leads_with_losses_and_uses_red_tone():
    day = _digest_day(_digest(lost_features=1))
    page = render_briefing(day)
    assert briefing_headline(day["briefing"]).startswith("1 VM size dropped regions")
    assert 'class="briefing-headline--loss"' in page
    assert "▼ 1 VM size −2 listings" in page
    assert "▲ 2 VM sizes +5 listings" in page


def test_digest_feature_with_gain_and_loss_renders_both_region_deltas():
    digest = _digest(gained_features=1, lost_features=1)
    feature = digest["modalities"][0]["features"][0]
    feature["gained_regions"] = ["westus3"]
    feature["restored_regions"] = []
    feature["lost_regions"] = ["eastus"]
    digest["modalities"][0]["gained_regions"] = ["westus3"]
    digest["modalities"][0]["lost_regions"] = ["eastus"]

    page = render_briefing(_digest_day(digest))

    assert "<strong>Dropped:</strong>" in page
    assert "<strong>Gained:</strong>" in page
    assert "− East US" in page
    assert "+ West US 3" in page


def test_digest_regions_tooltip_restored_badges_and_safe_learn_links():
    page = render_briefing(_digest_day(_digest()))
    assert 'title="Brazil South, East Asia (returned), East US, North Central US"' in page
    assert 'aria-label="+4 regions: Brazil South, East Asia (returned), East US, North Central US"' in page
    assert "East Asia (returned)" in page
    assert "briefing-region-chip-gain" in page
    assert "9 &rarr; 11 regions" in page
    assert "first listing" in page
    assert "first in Asia Pacific" not in page
    assert 'href="https://learn.microsoft.com/azure/virtual-machines/dv7-series"' in page
    assert 'href="http://learn.microsoft.com/not-safe"' not in page


def test_first_listing_collapses_geography_badges_and_expansions_keep_them():
    digest = _digest()
    feature = digest["modalities"][0]["features"][0]
    feature["new_geographies"] = ["Africa", "Asia", "Europe"]
    page = render_briefing(_digest_day(digest))
    assert "first listing · 3 geographies" in page
    assert "first in Africa" not in page

    feature["first_seen"] = False
    page = render_briefing(_digest_day(digest))
    assert "first in Africa" in page
    assert "first in Europe" in page
    assert "first listing" not in page


def test_learn_search_fallback_is_not_rendered_as_a_reference():
    digest = _digest()
    feature = digest["modalities"][0]["features"][0]
    feature["learn_reference"] = None
    feature["details_url"] = "https://learn.microsoft.com/en-us/search/?terms=vmSkus.standard.d248ds.v7"
    page = render_briefing(_digest_day(digest))
    assert "search/?terms=vmSkus.standard.d248ds.v7" not in page.split("briefing-full-evidence")[0]


def test_digest_clusters_shared_and_varying_region_deltas():
    shared = render_briefing(_digest_day(_clustered_digest()))
    assert "Dv7-series · general purpose" in shared
    assert "2 VM sizes: D2s, D4s" in shared
    assert "2 &rarr; 3 regions" in shared
    assert "varies by size" not in shared
    assert "briefing-badge-returned" in shared
    assert "briefing-digest-cluster-details" in shared

    varying = render_briefing(_digest_day(_clustered_digest(varying=True)))
    assert "+ East US" in varying
    assert "+ West US 3 (returned)" in varying
    assert "2 &rarr; 3–4 regions" in varying
    assert "varies by size" in varying


def test_digest_restored_only_cluster_does_not_show_first_listing_badges():
    features = ["vmSkus.standard.d2s.v7", "vmSkus.standard.d4s.v7"]
    previous = Snapshot.model_validate({
        "timestamp": "2026-09-05T08:00:00Z",
        "regions": {"eastus": {"compute": {
            feature: {"status": "unavailable"} for feature in features
        }}},
    })
    current = Snapshot.model_validate({
        "timestamp": "2026-09-06T08:00:00Z",
        "regions": {"eastus": {"compute": {
            feature: {"status": "available"} for feature in features
        }}},
    })
    contexts = {
        ("eastus", "compute", feature): ChangeContext(
            classification="restored_availability",
            available_days=1,
            last_available_date="2026-09-01",
        )
        for feature in features
    }

    page = render_briefing({
        "date": "2026-09-06",
        "change_path": "changes/2026-09-06.json",
        "briefing": build_briefing(current, previous, contexts=contexts),
    })

    assert "Dv7-series · general purpose" in page
    assert "first listing" not in page
    assert "first in North America" not in page
    assert "(2 returned)" in page


def test_digest_escapes_untrusted_text_and_keeps_legacy_view_collapsed():
    page = render_briefing(_digest_day(_digest()))
    assert "<script>unsafe</script>" not in page
    assert "&lt;script&gt;unsafe&lt;/script&gt;" in page
    assert "<details class=\"briefing-content briefing-full-evidence\">" in page
    assert "Full evidence, filters and history" in page
    assert "Planning compute here?" not in page


def test_digest_no_change_is_neutral_and_missing_digest_falls_back():
    digest = _digest(gained_features=0)
    digest["modalities"][0]["features"] = []
    digest["modalities"][0]["gained_regions"] = []
    digest["gaps"] = []
    day = _digest_day(digest)
    page = render_briefing(day)
    assert briefing_headline(day["briefing"]) == "No regional listing changes since 2026-10-03"
    assert 'class="briefing-headline--neutral"' in page
    assert "No regional listing changes since 2026-10-03." in page
    fallback = render_briefing(_day())
    assert "Since the previous scan" in fallback
    assert "Full evidence, filters and history" not in fallback


def test_briefing_answers_reader_questions_without_conflating_features_and_listings():
    page = render_briefing(_day())
    assert "54 VM sizes gained listings across 5 regions" in page
    assert '<span data-feature-count>54</span> <span data-feature-unit>VM sizes</span>' in page
    assert '<strong data-listing-count>266</strong> feature-region <span data-record-unit>records</span>' in page
    for name in ("Austria East", "Belgium Central", "Chile Central", "Denmark East", "India South Central", "Switzerland North"):
        assert name in page
    assert "19 &rarr; 20 regions" in page
    assert "2026-09-05 to 2026-09-06" in page
    assert "not mean previous absences recovered" in page
    assert "41 tracked listings remain absent" in page
    assert "noisiest" not in page
    assert "GitOps" not in page
    assert "confirmed retirement" in page
    assert "One listing = one feature in one region" in page


def test_same_fact_brief_is_used_on_blog_index_and_post_without_repeated_narrative():
    posts = select_blog_posts({"days": [_day()]})
    index = render_blog_index(posts, "https://example.test", "")
    page = render_blog_post(posts[0], None, None, "https://example.test", "")
    for rendered in (index, page):
        assert rendered.count('aria-label="Daily change briefing"') == 1
        assert "noisiest" not in rendered
        assert "Repeated old headline" not in rendered
        assert "/assets/briefing.js" in rendered
    assert "Snapshot comparison" in index
    assert "267 new feature-region listings" in index


def test_briefing_can_render_without_model_output():
    day = _day()
    day["narrative"] = ""
    posts = select_blog_posts({"days": [day]})
    assert len(posts) == 1
    assert posts[0]["title"] == "54 VM sizes gained listings across 5 regions"


def test_unknown_and_delistings_take_priority_over_a_large_rollout():
    briefing = _day()["briefing"]
    briefing["counts"]["delistings"] = 2
    assert "2 regional listings disappeared" in briefing_headline(briefing)
    briefing["counts"]["observation_gaps"] = 5
    assert briefing_headline(briefing).startswith("Evidence gaps need attention")
    briefing["baseline_available"] = False
    assert briefing_headline(briefing).startswith("Baseline missing")


def test_missing_baseline_does_not_render_zero_as_a_successful_comparison():
    day = _day()
    day["briefing"]["baseline_available"] = False
    day["briefing"]["previous_timestamp"] = None
    page = render_briefing(day)
    assert "Change counts are not available without a baseline" in page
    assert 'aria-label="Scan-wide counts"' not in page


def test_gap_and_scope_are_explicit_and_unchanged_regions_remain_filterable():
    day = _day()
    day["briefing"]["comparison_days"] = 3
    day["briefing"]["scope"] = {"added_regions": ["eastus"], "added_checks": 7, "removed_checks": 2}
    page = render_briefing(day)
    assert "spans 3 days, not just yesterday" in page
    assert "Monitoring scope changed" in page
    assert 'value="eastus">East US' in page
    assert 'value="Azure Functions"' in page
    assert "Added check records: 7; removed check records: 2" in page


def test_compact_payload_escapes_untrusted_identifiers_and_excludes_raw_records():
    day = _day()
    day["briefing"]["records"] = [{"message": "RAW_RECORD_NOT_IN_MAIN_HTML"}]
    day["briefing"]["groups"][0]["modality"] = '</script><img src=x onerror="alert(1)">'
    day["briefing"]["groups"][0]["statuses"][0]["examples"][0]["feature"] = "<script>bad()</script>"
    rendered = render_briefing(day)
    payload = re.search(r'class="briefing-data">(.*?)</script>', rendered).group(1)
    assert "</script>" not in payload
    assert "RAW_RECORD_NOT_IN_MAIN_HTML" not in rendered
    assert "<script>bad()" not in rendered
    assert json.loads(payload)["evidenceUrl"] == "/api/history/changes/2026-09-06.json"


def test_reader_names_preserve_unknown_identifiers_instead_of_guessing():
    assert region_name("switzerlandnorth") == "Switzerland North"
    assert region_name("eastus2") == "East US 2"
    assert region_name("southafricanorth") == "South Africa North"
    assert region_name("unrecognized-place") == "unrecognized-place"
    assert plain_feature_name("extensionTypes.microsoft.vmware") == "microsoft.vmware AKS extension"


def test_real_briefing_contract_renders_a_single_extension_and_coverage():
    feature = "extensionTypes.microsoft.vmware"
    previous = Snapshot.model_validate({
        "timestamp": "2026-09-05T08:00:00Z",
        "regions": {"switzerlandnorth": {"aks": {feature: {"status": "unavailable"}}}},
    })
    current = Snapshot.model_validate({
        "timestamp": "2026-09-06T08:00:00Z",
        "regions": {"switzerlandnorth": {"aks": {feature: {"status": "available"}}}},
    })
    day = {"date": "2026-09-06", "change_path": "changes/2026-09-06.json",
           "briefing": build_briefing(current, previous)}
    rendered = render_briefing(day)
    assert "microsoft.vmware AKS extension" in rendered
    assert "0 &rarr; 1 regions" in rendered
    assert 'data-record-unit>record</span>' in rendered
    assert "Azure Arc-enabled VMware vSphere" in rendered
    assert "vCenter" in rendered
    assert "/azure-arc/vmware-vsphere/overview" in rendered
    assert "First observed in this comparison" in rendered


def test_related_statuses_share_a_modality_card_without_losing_status_details():
    before = Snapshot.model_validate({
        "timestamp": "2026-09-05T08:00:00Z",
        "regions": {"eastus": {"compute": {
            "vmSkus.standard.new": {"status": "unavailable"},
            "vmSkus.standard.old": {"status": "available"},
        }}},
    })
    after = Snapshot.model_validate({
        "timestamp": "2026-09-06T08:00:00Z",
        "regions": {"eastus": {"compute": {
            "vmSkus.standard.new": {"status": "available"},
            "vmSkus.standard.old": {"status": "unavailable"},
        }}},
    })

    rendered = render_briefing({
        "date": "2026-09-06",
        "change_path": "changes/2026-09-06.json",
        "briefing": build_briefing(after, before),
    })

    assert rendered.count('class="briefing-card"') == 1
    assert "New listings" in rendered
    assert "New delistings" in rendered
    assert rendered.count('data-status-regions>East US</p>') == 2
    assert 'data-explore-group="0"' in rendered


def test_specific_vm_context_is_visible_in_the_shared_briefing():
    feature = "vmSkus.standard.d128nlds.v6"
    before = Snapshot.model_validate({
        "timestamp": "2026-09-05T08:00:00Z",
        "regions": {"eastus": {"compute": {feature: {"status": "unavailable"}}}},
    })
    after = before.model_copy(deep=True)
    after.timestamp = after.timestamp.replace(day=6)
    after.regions["eastus"]["compute"][feature].status = "available"
    page = render_briefing({
        "date": "2026-09-06", "change_path": "changes/2026-09-06.json",
        "briefing": build_briefing(after, before),
    })
    assert "128 vCPUs and 256 GiB RAM" in page
    assert "Low-memory" in page
    assert "dnldsv6-series" in page
    assert "Documented feature" in page


def test_display_model_name_joins_claude_minor_versions_only():
    from azure_region_monitor.display import display_model_name

    assert display_model_name("claude-sonnet-4-5") == "Claude Sonnet 4.5"
    assert display_model_name("claude-opus-4") == "Claude Opus 4"
    assert display_model_name("gpt-4o-2024-08-06").startswith("GPT-4o")
    assert display_model_name("phi-3-5-mini") == "phi 3 5 mini"
