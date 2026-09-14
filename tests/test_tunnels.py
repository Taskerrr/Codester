import copy

import pytest

from codester.store import DEFAULTS, ConfigurationError, validate
from codester.tunnels import TunnelManager


def tunnel(**changes):
    result = {
        "id": "1234567890abcdef",
        "name": "Dagster",
        "auth": "agent",
        "ssh_host": "192.168.1.90",
        "ssh_port": 22,
        "username": "jack",
        "local_port": 3417,
        "remote_host": "127.0.0.1",
        "remote_port": 3417,
    }
    result.update(changes)
    return result


def test_tunnel_settings_validate_and_reject_collisions():
    data = copy.deepcopy(DEFAULTS)
    data["tunnels"] = [tunnel()]
    assert validate(data)["tunnels"][0]["local_port"] == 3417

    data["tunnels"].append(tunnel(name="SigNoz", local_port=3417))
    with pytest.raises(ConfigurationError, match="different local port"):
        validate(data)

    data["tunnels"] = [tunnel(ssh_host="-oProxyCommand=bad")]
    with pytest.raises(ConfigurationError, match="valid tunnel SSH host"):
        validate(data)


def test_manager_builds_loopback_forward_and_stops(monkeypatch, tmp_path):
    commands = []

    class Process:
        returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = 0

        def wait(self, timeout):
            return self.returncode

        def kill(self):
            self.returncode = -9

    def popen(command, **kwargs):
        commands.append((command, kwargs))
        return Process()

    monkeypatch.setattr("codester.tunnels.subprocess.Popen", popen)
    manager = TunnelManager(tmp_path, [tunnel()], autostart=False)
    manager.ssh = "/usr/bin/ssh"

    status = manager.connect()
    assert status["desired"] is True
    command, options = commands[0]
    assert "BatchMode=yes" in command
    assert "ServerAliveInterval=30" in command
    assert "127.0.0.1:3417:127.0.0.1:3417" in command
    assert command[-1] == "jack@192.168.1.90"
    assert options["stdin"] is not None and options["stderr"] is not None

    status = manager.disconnect()
    assert status["state"] == "disconnected"
    assert status["desired"] is False


def test_connect_requires_configuration_and_openssh(tmp_path):
    manager = TunnelManager(tmp_path, [], autostart=False)
    with pytest.raises(ConfigurationError, match="at least one"):
        manager.connect()

    manager.configure([tunnel()])
    manager.ssh = None
    with pytest.raises(ConfigurationError, match="OpenSSH"):
        manager.connect()


def test_password_auth_uses_askpass_without_command_secret(monkeypatch, tmp_path):
    captured = {}

    class Process:
        returncode = None

        def poll(self):
            return None

    def popen(command, **kwargs):
        captured.update(command=command, **kwargs)
        return Process()

    monkeypatch.setattr("codester.tunnels.subprocess.Popen", popen)
    manager = TunnelManager(tmp_path, [tunnel(auth="password")], autostart=False)
    manager.ssh = "/usr/bin/ssh"
    manager.askpass = "/app/.venv/bin/codester-askpass"
    manager.connect()

    assert "BatchMode=no" in captured["command"]
    assert "PreferredAuthentications=password,keyboard-interactive" in captured["command"]
    assert "ssh-test-super-secret" not in " ".join(captured["command"])
    assert captured["env"]["SSH_ASKPASS"] == manager.askpass
    assert captured["env"]["CODESTER_SSH_SECRET"] == "tunnel-password:1234567890abcdef"


def test_initial_ssh_failure_stops_retry_and_reports_error(monkeypatch, tmp_path):
    class FailedProcess:
        returncode = 255

        def poll(self):
            return self.returncode

        def communicate(self):
            return b"", b"Permission denied (password).\n"

    launches = 0

    def popen(command, **kwargs):
        nonlocal launches
        launches += 1
        return FailedProcess()

    monkeypatch.setattr("codester.tunnels.subprocess.Popen", popen)
    manager = TunnelManager(tmp_path, [tunnel(auth="password")], autostart=False)
    manager.ssh = "/usr/bin/ssh"
    manager.askpass = "/app/.venv/bin/codester-askpass"
    manager.connect()
    manager._reconcile()
    manager._reconcile()

    status = manager.status()
    assert launches == 1
    assert status["state"] == "error"
    assert status["desired"] is False
    assert status["tunnels"][0]["message"] == "Permission denied (password)."
    assert manager.disconnect()["state"] == "disconnected"
