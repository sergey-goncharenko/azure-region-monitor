from __future__ import annotations

import json
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass

from azure_region_monitor.config import AksExtensionFeature, DEFAULT_AKS_EXTENSION_FEATURES
from azure_region_monitor.models import FeatureResult
from azure_region_monitor.probes.base import ProbeResult

CliRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class AzureCliError:
    error_code: str
    message: str


class AksExtensionCliProbe:
    name = "aks-extension-cli"

    def __init__(
        self,
        features: list[AksExtensionFeature] | None = None,
        cli_runner: CliRunner | None = None,
    ) -> None:
        self._features = features or DEFAULT_AKS_EXTENSION_FEATURES
        self._cli_runner = cli_runner or _run_az

    def run(self, region: str):
        started = time.perf_counter()
        extension_types, error = self._list_extension_types(region)
        latency_ms = round((time.perf_counter() - started) * 1000)

        for feature in self._features:
            if error:
                yield ProbeResult(
                    service="aks",
                    feature=feature.feature,
                    result=FeatureResult(
                        status="unknown",
                        latency_ms=latency_ms,
                        error_code=error.error_code,
                        message=error.message,
                    ),
                )
                continue

            is_available = feature.extension_type.lower() in extension_types
            yield ProbeResult(
                service="aks",
                feature=feature.feature,
                result=FeatureResult(
                    status="available" if is_available else "unavailable",
                    latency_ms=latency_ms,
                    message=f"Checked AKS extension type '{feature.extension_type}' in {region}.",
                ),
            )

    def _list_extension_types(self, region: str) -> tuple[set[str], AzureCliError | None]:
        command = [
            _az_executable(),
            "k8s-extension",
            "extension-types",
            "list-by-location",
            "--location",
            region,
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

        return _extract_extension_type_names(payload), None


def _run_az(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, check=False, text=True)


def _az_executable() -> str:
    return shutil.which("az") or shutil.which("az.cmd") or "az"


def _extract_extension_type_names(payload: object) -> set[str]:
    if not isinstance(payload, list):
        return set()

    names: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        for key in ("extensionType", "name"):
            value = item.get(key)
            if isinstance(value, str):
                names.add(value.lower())
    return names