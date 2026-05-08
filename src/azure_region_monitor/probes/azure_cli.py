from __future__ import annotations

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
    return subprocess.run(command, capture_output=True, check=False, text=True)


def az_executable() -> str:
    return shutil.which("az") or shutil.which("az.cmd") or "az"
