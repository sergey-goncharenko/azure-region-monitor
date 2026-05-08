import subprocess

from azure_region_monitor.config import parse_aks_kubernetes_version_prefixes
from azure_region_monitor.probes.aks_versions import AksKubernetesVersionCliProbe


def test_aks_version_probe_marks_matching_minor_available():
    def cli_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        assert command[1:3] == ["aks", "get-versions"]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='{"orchestrators":[{"orchestratorVersion":"1.34.2"}]}',
            stderr="",
        )

    probe = AksKubernetesVersionCliProbe(version_prefixes=["1.34"], cli_runner=cli_runner)

    results = list(probe.run("westeurope"))

    assert results[0].service == "aks"
    assert results[0].feature == "kubernetesVersions.1.34"
    assert results[0].result.status == "available"
    assert "1.34.2" in (results[0].result.message or "")


def test_aks_version_probe_marks_missing_minor_unavailable():
    def cli_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='{"orchestrators":[{"orchestratorVersion":"1.33.5"}]}',
            stderr="",
        )

    probe = AksKubernetesVersionCliProbe(version_prefixes=["1.34"], cli_runner=cli_runner)

    results = list(probe.run("eastus"))

    assert results[0].result.status == "unavailable"


def test_aks_version_probe_extracts_nested_version_values():
    def cli_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='{"values":[{"version":"1.35.1"},{"patchVersions":{"1.35.2":{}}}]}',
            stderr="",
        )

    probe = AksKubernetesVersionCliProbe(version_prefixes=["1.35"], cli_runner=cli_runner)

    results = list(probe.run("swedencentral"))

    assert results[0].result.status == "available"
    assert "1.35.1" in (results[0].result.message or "")
    assert "1.35.2" in (results[0].result.message or "")


def test_aks_version_probe_captures_cli_error_as_unknown():
    def cli_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="forbidden")

    probe = AksKubernetesVersionCliProbe(version_prefixes=["1.34"], cli_runner=cli_runner)

    results = list(probe.run("westeurope"))

    assert results[0].result.status == "unknown"
    assert results[0].result.error_code == "AzureCliCommandFailed"


def test_parse_aks_kubernetes_version_prefixes_from_environment_value():
    assert parse_aks_kubernetes_version_prefixes("1.33, 1.34") == ["1.33", "1.34"]