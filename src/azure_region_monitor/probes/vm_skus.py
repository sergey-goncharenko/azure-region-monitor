from __future__ import annotations

import json
import re
import time

from azure_region_monitor.config import DEFAULT_VM_SKUS
from azure_region_monitor.models import FeatureResult
from azure_region_monitor.probes.azure_cli import AzureCliError, CliRunner, az_executable, run_az
from azure_region_monitor.probes.base import ProbeResult


MIN_REASONABLE_REGIONAL_SKU_COUNT = 100


class VmSkuCliProbe:
    name = "vm-sku-cli"
    normalize_missing_features = True

    def __init__(self, skus: list[str] | None = None, cli_runner: CliRunner | None = None) -> None:
        self._skus = DEFAULT_VM_SKUS if skus is None else skus
        self._cli_runner = cli_runner or run_az

    def run(self, region: str):
        started = time.perf_counter()
        listed_skus, error, used_legacy_fallback = self._list_sizes(region)
        latency_ms = round((time.perf_counter() - started) * 1000)

        if not self._skus:
            yield from self._run_all_listed_skus(
                region,
                listed_skus,
                error,
                latency_ms,
                used_legacy_fallback=used_legacy_fallback,
            )
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

            is_available = sku.lower() in listed_skus
            yield ProbeResult(
                service="compute",
                feature=feature,
                result=FeatureResult(
                    status="available" if is_available else "unavailable",
                    latency_ms=latency_ms,
                    message=_sku_message(
                        region,
                        sku,
                        is_available,
                        used_legacy_fallback=used_legacy_fallback,
                    ),
                ),
            )

    def _run_all_listed_skus(
        self,
        region: str,
        listed_skus: set[str],
        error: AzureCliError | None,
        latency_ms: int,
        *,
        used_legacy_fallback: bool,
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
                    message=_sku_message(
                        region,
                        sku,
                        True,
                        used_legacy_fallback=used_legacy_fallback,
                    ),
                ),
            )

    def _list_sizes(self, region: str) -> tuple[set[str], AzureCliError | None, bool]:
        legacy_skus, legacy_error = self._list_legacy_sizes(region)

        if legacy_error is None and len(legacy_skus) >= MIN_REASONABLE_REGIONAL_SKU_COUNT:
            return legacy_skus, None, True

        listed_skus, list_skus_error = self._run_sku_command(
            [
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
        )

        if legacy_error is None and list_skus_error is None:
            return legacy_skus | listed_skus, None, True

        if legacy_error is None:
            return set(), AzureCliError(
                "AzureCliIncompleteCatalog",
                "Legacy az vm list-sizes returned a suspiciously small catalog and "
                f"az vm list-skus fallback failed: {list_skus_error.message if list_skus_error else 'no error'}",
            ), True

        if list_skus_error is None and len(listed_skus) >= MIN_REASONABLE_REGIONAL_SKU_COUNT:
            return listed_skus, None, False

        if list_skus_error is None:
            return set(), AzureCliError(
                "AzureCliIncompleteCatalog",
                "Legacy az vm list-sizes failed and az vm list-skus returned a suspiciously small catalog.",
            ), False

        return set(), _combine_errors(legacy_error, list_skus_error), False

    def _list_legacy_sizes(self, region: str) -> tuple[set[str], AzureCliError | None]:
        return self._run_sku_command(
            [
                az_executable(),
                "vm",
                "list-sizes",
                "--location",
                region,
                "--query",
                "[].name",
                "--output",
                "json",
            ]
        )

    def _run_sku_command(self, command: list[str]) -> tuple[set[str], AzureCliError | None]:
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


def _combine_errors(primary: AzureCliError, fallback: AzureCliError) -> AzureCliError:
    return AzureCliError(
        primary.error_code,
        f"Legacy az vm list-sizes failed: {primary.message} az vm list-skus fallback failed: {fallback.message}",
    )


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


def _sku_message(
    region: str,
    sku: str,
    is_available: bool,
    *,
    used_legacy_fallback: bool,
) -> str:
    source = (
        "legacy az vm list-sizes and az vm list-skus fallback evidence"
        if used_legacy_fallback
        else "az vm list-skus"
    )
    if is_available:
        return f"VM SKU '{sku}' is listed by {source} in {region}."
    return f"VM SKU '{sku}' was not listed by {source} in {region}."


def _feature_slug(sku: str) -> str:
    return re.sub(r"[^a-z0-9]+", ".", sku.lower()).strip(".")
