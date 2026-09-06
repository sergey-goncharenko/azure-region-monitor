import json
import re

from azure_region_monitor.briefing import build_briefing
from azure_region_monitor.blog import render_blog_index, render_blog_post, select_blog_posts
from azure_region_monitor.briefing_view import briefing_headline, render_briefing
from azure_region_monitor.display import plain_feature_name, region_name
from azure_region_monitor.models import Snapshot


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
                    "kind": "new_listings", "modality": "VM SKUs",
                    "feature_count": 54, "listing_count": 266,
                    "regions": ["austriaeast", "belgiumcentral", "chilecentral", "denmarkeast", "indiasouthcentral"],
                    "region_counts": {"austriaeast": 52, "belgiumcentral": 54, "chilecentral": 54, "denmarkeast": 54, "indiasouthcentral": 52},
                    "examples": [{"feature": "vmSkus.standard.d128nds.v6", "coverage_before": {"available": 44}, "coverage_after": {"available": 49}}],
                },
                {
                    "kind": "new_listings", "modality": "AKS extensions",
                    "feature_count": 1, "listing_count": 1,
                    "regions": ["switzerlandnorth"], "region_counts": {"switzerlandnorth": 1},
                    "examples": [{"feature": "extensionTypes.microsoft.vmware", "coverage_before": {"available": 19}, "coverage_after": {"available": 20}}],
                },
            ],
        },
    }


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
    day["briefing"]["groups"][0]["examples"][0]["feature"] = "<script>bad()</script>"
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
