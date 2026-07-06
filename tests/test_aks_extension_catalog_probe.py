import subprocess

from azure_region_monitor.runner import run_probes
from azure_region_monitor.probes.aks_extension_catalog import AksExtensionCatalogCliProbe


def test_aks_extension_catalog_probe_emits_all_listed_extensions():
    def cli_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        assert command[1:4] == ["k8s-extension", "extension-types", "list-by-location"]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='[{"extensionType":"microsoft.flux"},{"name":"Microsoft.AzureMonitor.Containers"}]',
            stderr="",
        )

    probe = AksExtensionCatalogCliProbe(cli_runner=cli_runner)

    results = list(probe.run("westeurope"))

    assert [result.feature for result in results] == [
        "extensionTypes.microsoft.azuremonitor.containers",
        "extensionTypes.microsoft.flux",
    ]
    assert {result.result.status for result in results} == {"available"}


def test_aks_extension_catalog_probe_captures_cli_error_as_unknown():
    def cli_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="forbidden")

    probe = AksExtensionCatalogCliProbe(cli_runner=cli_runner)

    results = list(probe.run("eastus"))

    assert results[0].feature == "extensionCatalog"
    assert results[0].result.status == "unknown"
    assert results[0].result.error_code == "AzureCliCommandFailed"


def test_aks_extension_catalog_probe_treats_unsupported_location_as_empty_catalog():
    def cli_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        if command[command.index("--location") + 1] == "eastus":
            return subprocess.CompletedProcess(
                command,
                0,
                stdout='[{"extensionType":"microsoft.flux"}]',
                stderr="",
            )
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr=(
                "WARNING: Command group 'k8s-extension extension-types' is in preview and under development. "
                "Reference and support levels: https://aka.ms/CLI_refstatus "
                "ERROR: (NoRegisteredProviderFound) No registered resource provider found for location "
                "'eastusstg' and API version '2023-05-01-preview' for type 'locations/extensionTypes'. "
                "The supported locations are 'eastus'."
            ),
        )

    snapshot = run_probes(
        ["eastus", "eastusstg"],
        [AksExtensionCatalogCliProbe(cli_runner=cli_runner)],
    )

    assert snapshot.regions["eastus"]["aks"]["extensionTypes.microsoft.flux"].status == "available"
    assert (
        snapshot.regions["eastusstg"]["aks"]["extensionTypes.microsoft.flux"].status
        == "unavailable"
    )
    assert "extensionCatalog" not in snapshot.regions["eastusstg"]["aks"]
