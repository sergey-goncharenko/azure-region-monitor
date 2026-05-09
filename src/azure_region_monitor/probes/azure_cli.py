from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

CliRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class AzureCliError:
    error_code: str
    message: str


def run_az(command: list[str]) -> subprocess.CompletedProcess[str]:
    timeout_seconds = int(os.environ.get("AZURE_CLI_TIMEOUT_SECONDS", "90"))
    try:
        return subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        return subprocess.CompletedProcess(
            command,
            124,
            stdout=error.stdout or "",
            stderr=f"Azure CLI command timed out after {timeout_seconds} seconds.",
        )


def az_executable() -> str:
    return shutil.which("az") or shutil.which("az.cmd") or "az"
