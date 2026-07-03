from azure_region_monitor.region_discovery import select_physical_regions


def _loc(name, region_type="Physical"):
    return {"name": name, "metadata": {"regionType": region_type}}


def test_selects_only_physical_regions_sorted():
    locations = [
        _loc("eastus"),
        _loc("southeastasia"),
        _loc("asia", region_type="Logical"),
        _loc("europe", region_type="Logical"),
        _loc("centralindia"),
    ]
    assert select_physical_regions(locations) == ["centralindia", "eastus", "southeastasia"]


def test_deduplicates_and_skips_blank_and_garbage():
    locations = [
        _loc("eastus"),
        _loc("eastus"),
        _loc(""),
        {"name": "no-metadata"},
        {"metadata": {"regionType": "Physical"}},  # no name
        None,
        "not a dict",
    ]
    assert select_physical_regions(locations) == ["eastus"]


def test_case_insensitive_region_type():
    assert select_physical_regions([_loc("eastus", region_type="physical")]) == ["eastus"]


def test_empty_and_non_list_inputs():
    assert select_physical_regions([]) == []
    assert select_physical_regions(None) == []
    assert select_physical_regions("nope") == []
