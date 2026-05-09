import subprocess

from azure_region_monitor.probes import azure_cli


class TimeoutProcess:
    pid = 12345
    returncode = None

    def __init__(self) -> None:
        self.communicate_calls = 0

    def communicate(self, timeout=None):
        self.communicate_calls += 1
        if self.communicate_calls == 1:
            raise subprocess.TimeoutExpired(cmd=["az", "account", "show"], timeout=timeout)
        return "", ""

    def kill(self) -> None:
        pass


def test_run_az_returns_completed_process_on_timeout(monkeypatch):
    killed = []

    def slow_process(*args, **kwargs):
        return TimeoutProcess()

    monkeypatch.setenv("AZURE_CLI_TIMEOUT_SECONDS", "1")
    monkeypatch.setattr(subprocess, "Popen", slow_process)
    monkeypatch.setattr(azure_cli, "_kill_process", lambda process: killed.append(process.pid))

    completed = azure_cli.run_az(["az", "account", "show"])

    assert completed.returncode == 124
    assert completed.stderr == "Azure CLI command timed out after 1 seconds."
    assert killed == [12345]