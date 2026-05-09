from azure_region_monitor.models import FeatureResult
from azure_region_monitor.probes.base import ProbeResult
from azure_region_monitor.runner import run_probes


class CatalogProbe:
    name = "catalog"
    normalize_missing_features = True

    def run(self, region):
        if region == "broken":
            yield ProbeResult(
                service="aks",
                feature="extensionCatalog",
                result=FeatureResult(
                    status="unknown",
                    error_code="AzureCliCommandFailed",
                    message="Catalog failed.",
                ),
            )
            return
        if region == "empty":
            return

        yield ProbeResult(
            service="aks",
            feature="extensionTypes.microsoft.flux",
            result=FeatureResult(status="available"),
        )


def test_run_probes_fills_catalog_failures_as_unknown_checks():
    snapshot = run_probes(["healthy", "broken"], [CatalogProbe()])

    broken_feature = snapshot.regions["broken"]["aks"]["extensionTypes.microsoft.flux"]

    assert broken_feature.status == "unknown"
    assert broken_feature.error_code == "AzureCliCommandFailed"
    assert broken_feature.message == "Catalog failed."


def test_run_probes_fills_missing_catalog_features_as_unavailable():
    snapshot = run_probes(["healthy", "empty"], [CatalogProbe()])

    empty_feature = snapshot.regions["empty"]["aks"]["extensionTypes.microsoft.flux"]

    assert empty_feature.status == "unavailable"