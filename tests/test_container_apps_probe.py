import subprocess

from azure_region_monitor.config import parse_container_apps_resource_features
from azure_region_monitor.probes.container_apps import ContainerAppsProviderCliProbe


def test_container_apps_probe_marks_resource_type_available():
    def cli_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        assert command[1:4] == ["provider", "show", "--namespace"]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                '{"resourceTypes":['
                '{"resourceType":"managedEnvironments","locations":["East US","West Europe"]}'
                "]}"
            ),
            stderr="",
        )

    probe = ContainerAppsProviderCliProbe(
        resource_features=parse_container_apps_resource_features(
            "containerApps.managedEnvironments=managedEnvironments"
        ),
        cli_runner=cli_runner,
    )

    results = list(probe.run("eastus"))

    assert results[0].service == "containerApps"
    assert results[0].feature == "containerApps.managedEnvironments"
    assert results[0].result.status == "available"


def test_container_apps_probe_marks_region_absence_unavailable():
    def cli_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                '{"resourceTypes":['
                '{"resourceType":"managedEnvironments/daprComponents","locations":["West Europe"]}'
                "]}"
            ),
            stderr="",
        )

    probe = ContainerAppsProviderCliProbe(
        resource_features=parse_container_apps_resource_features(
            "containerApps.daprComponents=managedEnvironments/daprComponents"
        ),
        cli_runner=cli_runner,
    )

    results = list(probe.run("eastus"))

    assert results[0].result.status == "unavailable"
    assert "was not advertised in eastus" in results[0].result.message


def test_container_apps_probe_captures_cli_error_as_unknown():
    def cli_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="forbidden")

    probe = ContainerAppsProviderCliProbe(
        resource_features=parse_container_apps_resource_features(
            "containerApps.managedEnvironments=managedEnvironments"
        ),
        cli_runner=cli_runner,
    )

    results = list(probe.run("eastus"))

    assert results[0].result.status == "unknown"
    assert results[0].result.error_code == "AzureCliCommandFailed"


def test_container_apps_probe_reuses_cached_provider_metadata_across_regions():
    calls = 0

    def cli_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                '{"resourceTypes":['
                '{"resourceType":"containerApps","locations":["East US"]}'
                "]}"
            ),
            stderr="",
        )

    probe = ContainerAppsProviderCliProbe(
        resource_features=parse_container_apps_resource_features("containerApps.apps=containerApps"),
        cli_runner=cli_runner,
    )

    list(probe.run("eastus"))
    list(probe.run("westus"))

    assert calls == 1


def test_parse_container_apps_resource_features_from_environment_value():
    features = parse_container_apps_resource_features(
        "containerApps.apps=containerApps, containerApps.jobs=jobs"
    )

    assert [feature.feature for feature in features] == ["containerApps.apps", "containerApps.jobs"]
    assert [feature.resource_type for feature in features] == ["containerApps", "jobs"]