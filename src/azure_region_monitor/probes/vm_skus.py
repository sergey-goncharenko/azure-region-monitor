from __future__ import annotations

import json
import re
import time

from azure_region_monitor.config import DEFAULT_VM_SKUS
from azure_region_monitor.models import FeatureResult
from azure_region_monitor.probes.azure_cli import AzureCliError, CliRunner, az_executable, run_az
from azure_region_monitor.probes.base import ProbeResult


class VmSkuCliProbe:
    name = "vm-sku-cli"
    normalize_missing_features = True

    def __init__(self, skus: list[str] | None = None, cli_runner: CliRunner | None = None) -> None:
        self._skus = DEFAULT_VM_SKUS if skus is None else skus
        self._cli_runner = cli_runner or run_az

    def run(self, region: str):
        started = time.perf_counter()
        listed_skus, error = self._list_sizes(region)
        latency_ms = round((time.perf_counter() - started) * 1000)

        if not self._skus:
            yield from self._run_all_listed_skus(region, listed_skus, error, latency_ms)
            return

        for sku in self._skus:
            feature = f"vmSkus.{_feature_slug(sku)}"
            if error:
                yield ProbeResult(
                    service="compute",
                    feature=feature,
                    result=FeatureResult(
                        status="unknown",
                        latency_ms=latency_ms,
                        error_code=error.error_code,
                        message=error.message,
                    ),
                )
                continue

            yield ProbeResult(
                service="compute",
                feature=feature,
                result=FeatureResult(
                    status="available" if sku.lower() in listed_skus else "unavailable",
                    latency_ms=latency_ms,
                    message=_sku_message(region, sku, sku.lower() in listed_skus),
                ),
            )

    def _run_all_listed_skus(
        self,
        region: str,
        listed_skus: set[str],
        error: AzureCliError | None,
        latency_ms: int,
    ):
        if error:
            yield ProbeResult(
                service="compute",
                feature="vmSkuCatalog",
                result=FeatureResult(
                    status="unknown",
                    latency_ms=latency_ms,
                    error_code=error.error_code,
                    message=error.message,
                ),
            )
            return

        for sku in sorted(listed_skus):
            yield ProbeResult(
                service="compute",
                feature=f"vmSkus.{_feature_slug(sku)}",
                result=FeatureResult(
                    status="available",
                    latency_ms=latency_ms,
                    message=f"VM SKU '{sku}' is listed by az vm list-skus in {region}.",
                ),
            )

    def _list_sizes(self, region: str) -> tuple[set[str], AzureCliError | None]:
        command = [
            az_executable(),
            "vm",
            "list-skus",
            "--location",
            region,
            "--resource-type",
            "virtualMachines",
            "--all",
            "--query",
            "[].name",
            "--output",
            "json",
        ]

        try:
            completed = self._cli_runner(command)
        except FileNotFoundError:
            return set(), AzureCliError("AzureCliNotFound", "Azure CLI executable 'az' was not found.")

        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "Azure CLI command failed.").strip()
            return set(), AzureCliError("AzureCliCommandFailed", message)

        try:
            payload = json.loads(completed.stdout or "[]")
        except json.JSONDecodeError as error:
            return set(), AzureCliError("AzureCliInvalidJson", str(error))

        return _extract_vm_size_names(payload), None


def _extract_vm_size_names(payload: object) -> set[str]:
    if not isinstance(payload, list):
        return set()

    skus: set[str] = set()
    for item in payload:
        if isinstance(item, str):
            skus.add(item.lower())
            continue
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if isinstance(name, str):
            skus.add(name.lower())
    return skus


def _sku_message(region: str, sku: str, is_available: bool) -> str:
    if is_available:
        return f"VM SKU '{sku}' is listed by az vm list-skus in {region}."
    return f"VM SKU '{sku}' was not listed by az vm list-skus in {region}."


def _feature_slug(sku: str) -> str:
    return re.sub(r"[^a-z0-9]+", ".", sku.lower()).strip(".")