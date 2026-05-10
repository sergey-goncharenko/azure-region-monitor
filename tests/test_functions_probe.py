import subprocess

from azure_region_monitor.config import parse_function_runtime_features
from azure_region_monitor.probes.functions import FunctionsFlexConsumptionCliProbe


def test_functions_probe_marks_flex_runtime_available():
    def cli_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        if command[1:3] == ["functionapp", "list-flexconsumption-locations"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout='[{"name":"eastus","displayName":"East US"}]',
                stderr="",
            )
        assert command[1:3] == ["functionapp", "list-runtimes"]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='[{"name":"python","version":"3.12"}]',
            stderr="",
        )

    probe = FunctionsFlexConsumptionCliProbe(
        runtime_features=parse_function_runtime_features("runtimes.python.3.12=PYTHON|3.12"),
        cli_runner=cli_runner,
    )

    results = list(probe.run("eastus"))

    assert [result.feature for result in results] == [
        "hostingPlans.flexConsumption",
        "runtimes.python.3.12",
    ]
    assert {result.result.status for result in results} == {"available"}


def test_functions_probe_marks_runtime_unavailable_when_region_lacks_flex():
    def cli_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        if command[1:3] == ["functionapp", "list-flexconsumption-locations"]:
            return subprocess.CompletedProcess(command, 0, stdout='[{"name":"westus"}]', stderr="")
        return subprocess.CompletedProcess(command, 0, stdout='[{"runtimeVersion":"PYTHON|3.12"}]', stderr="")

    probe = FunctionsFlexConsumptionCliProbe(
        runtime_features=parse_function_runtime_features("runtimes.python.3.12=PYTHON|3.12"),
        cli_runner=cli_runner,
    )

    results = list(probe.run("eastus"))

    assert results[0].feature == "hostingPlans.flexConsumption"
    assert results[0].result.status == "unavailable"
    assert results[1].feature == "runtimes.python.3.12"
    assert results[1].result.status == "unavailable"


def test_functions_probe_captures_cli_error_as_unknown():
    def cli_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="forbidden")

    probe = FunctionsFlexConsumptionCliProbe(
        runtime_features=parse_function_runtime_features("runtimes.python.3.12=PYTHON|3.12"),
        cli_runner=cli_runner,
    )

    results = list(probe.run("eastus"))

    assert results[0].result.status == "unknown"
    assert results[0].result.error_code == "AzureCliCommandFailed"
    assert results[1].result.status == "unknown"
    assert results[1].result.error_code == "AzureCliCommandFailed"


def test_functions_probe_reuses_cached_cli_results_across_regions():
    calls = 0

    def cli_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if command[1:3] == ["functionapp", "list-flexconsumption-locations"]:
            return subprocess.CompletedProcess(command, 0, stdout='[{"name":"eastus"}]', stderr="")
        return subprocess.CompletedProcess(command, 0, stdout='[{"runtimeVersion":"PYTHON|3.12"}]', stderr="")

    probe = FunctionsFlexConsumptionCliProbe(
        runtime_features=parse_function_runtime_features("runtimes.python.3.12=PYTHON|3.12"),
        cli_runner=cli_runner,
    )

    list(probe.run("eastus"))
    list(probe.run("westus"))

    assert calls == 2


def test_parse_function_runtime_features_from_environment_value():
    features = parse_function_runtime_features(
        "runtimes.python.3.12=PYTHON|3.12, runtimes.node.22=NODE|22"
    )

    assert [feature.feature for feature in features] == ["runtimes.python.3.12", "runtimes.node.22"]
    assert [feature.runtime for feature in features] == ["PYTHON|3.12", "NODE|22"]