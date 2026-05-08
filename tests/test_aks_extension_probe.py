import subprocess

from azure_region_monitor.config import AksExtensionFeature, parse_aks_extension_features
from azure_region_monitor.probes.aks_extension import AksExtensionCliProbe


def test_aks_extension_probe_marks_listed_extension_available():
    def cli_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        assert command[1:4] == ["k8s-extension", "extension-types", "list-by-location"]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='[{"extensionType":"microsoft.flux"}]',
            stderr="",
        )

    probe = AksExtensionCliProbe(
        features=[AksExtensionFeature("extensions.gitops", "microsoft.flux")],
        cli_runner=cli_runner,
    )

    results = list(probe.run("swedencentral"))

    assert results[0].service == "aks"
    assert results[0].feature == "extensions.gitops"
    assert results[0].result.status == "available"


def test_aks_extension_probe_marks_missing_extension_unavailable():
    def cli_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout="[]", stderr="")

    probe = AksExtensionCliProbe(
        features=[AksExtensionFeature("extensions.gitops", "microsoft.flux")],
        cli_runner=cli_runner,
    )

    results = list(probe.run("eastus"))

    assert results[0].result.status == "unavailable"


def test_aks_extension_probe_captures_cli_error_as_unknown():
    def cli_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="not logged in")

    probe = AksExtensionCliProbe(
        features=[AksExtensionFeature("extensions.gitops", "microsoft.flux")],
        cli_runner=cli_runner,
    )

    results = list(probe.run("westeurope"))

    assert results[0].result.status == "unknown"
    assert results[0].result.error_code == "AzureCliCommandFailed"
    assert results[0].result.message == "not logged in"


def test_parse_aks_extension_features_from_environment_value():
    features = parse_aks_extension_features(
        "extensions.gitops=microsoft.flux,extensions.monitor=microsoft.azuremonitor.containers"
    )

    assert features == [
        AksExtensionFeature("extensions.gitops", "microsoft.flux"),
        AksExtensionFeature("extensions.monitor", "microsoft.azuremonitor.containers"),
    ]