import subprocess

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
