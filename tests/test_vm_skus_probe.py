import subprocess

from azure_region_monitor.config import parse_vm_skus
from azure_region_monitor.probes.vm_skus import VmSkuCliProbe


def test_vm_sku_probe_marks_unrestricted_listed_sku_available():
    def cli_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        assert command[1:3] == ["vm", "list-skus"]
        assert command[command.index("--location") + 1] == "westeurope"
        assert "--resource-type" in command
        assert "virtualMachines" in command
        assert "--all" in command
        assert command[command.index("--query") + 1] == "[].name"
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=_sku_payload("Standard_D2s_v5", extra_count=100),
            stderr="",
        )

    probe = VmSkuCliProbe(skus=["Standard_D2s_v5"], cli_runner=cli_runner)

    results = list(probe.run("westeurope"))

    assert results[0].service == "compute"
    assert results[0].feature == "vmSkus.standard.d2s.v5"
    assert results[0].result.status == "available"


def test_vm_sku_probe_marks_missing_sku_unavailable():
    def cli_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=_sku_payload("Standard_B2s", extra_count=100),
            stderr="",
        )

    probe = VmSkuCliProbe(skus=["Standard_D2s_v5"], cli_runner=cli_runner)

    results = list(probe.run("eastus"))

    assert results[0].result.status == "unavailable"


def test_vm_sku_probe_captures_cli_error_as_unknown():
    def cli_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="forbidden")

    probe = VmSkuCliProbe(skus=["Standard_D2s_v5"], cli_runner=cli_runner)

    results = list(probe.run("westeurope"))

    assert results[0].result.status == "unknown"
    assert results[0].result.error_code == "AzureCliCommandFailed"


def test_vm_sku_probe_uses_legacy_fallback_when_list_skus_fails():
    def cli_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        if command[1:3] == ["vm", "list-skus"]:
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="provider failed")
        return subprocess.CompletedProcess(command, 0, stdout='["Standard_D2s_v5"]', stderr="")

    probe = VmSkuCliProbe(skus=["Standard_D2s_v5"], cli_runner=cli_runner)

    results = list(probe.run("westeurope"))

    assert results[0].result.status == "available"
    assert "legacy az vm list-sizes fallback" in results[0].result.message


def test_vm_sku_probe_unions_legacy_fallback_when_list_skus_omits_size():
    def cli_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        if command[1:3] == ["vm", "list-skus"]:
            return subprocess.CompletedProcess(command, 0, stdout="[]", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout='["Standard_D2s_v5"]', stderr="")

    probe = VmSkuCliProbe(skus=["Standard_D2s_v5"], cli_runner=cli_runner)

    results = list(probe.run("westeurope"))

    assert results[0].result.status == "available"
    assert "legacy az vm list-sizes fallback" in results[0].result.message


def test_vm_sku_probe_can_emit_all_listed_skus():
    def cli_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=_sku_payload("Standard_D2s_v5", "Standard_B2s", extra_count=100),
            stderr="",
        )

    probe = VmSkuCliProbe(skus=[], cli_runner=cli_runner)

    results = list(probe.run("eastus"))
    features = {result.feature for result in results}

    assert "vmSkus.standard.b2s" in features
    assert "vmSkus.standard.d2s.v5" in features
    assert {result.result.status for result in results} == {"available"}


def test_vm_sku_probe_captures_all_sku_catalog_error_as_unknown():
    def cli_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="forbidden")

    probe = VmSkuCliProbe(skus=[], cli_runner=cli_runner)

    results = list(probe.run("westeurope"))

    assert results[0].feature == "vmSkuCatalog"
    assert results[0].result.status == "unknown"
    assert results[0].result.error_code == "AzureCliCommandFailed"


def test_parse_vm_skus_from_environment_value():
    assert parse_vm_skus("Standard_B2s, Standard_D2s_v5") == ["Standard_B2s", "Standard_D2s_v5"]


def test_parse_vm_skus_all_mode():
    assert parse_vm_skus("all") == []
    assert parse_vm_skus("*") == []


def _sku_payload(*skus: str, extra_count: int = 0) -> str:
    payload = list(skus)
    payload.extend(f"Standard_Test_{index}" for index in range(extra_count))
    return str(payload).replace("'", '"')