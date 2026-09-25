import copy
import os
from unittest.mock import Mock

import pytest

from codester.store import DEFAULTS, ConfigurationError, validate
from codester.transport import IntegrationError
from codester.tunnels import TunnelManager, password_helper


def test_helper_found_without_environment_activation(monkeypatch, tmp_path):
    scripts = tmp_path / "Scripts with spaces"
    scripts.mkdir()
    helper = scripts / ("codester-askpass.exe" if os.name == "nt" else "codester-askpass")
    helper.write_text("test helper")
    helper.chmod(0o700)
    monkeypatch.setattr("codester.tunnels.sysconfig.get_path", lambda name: str(scripts))
    monkeypatch.setattr("codester.tunnels.shutil.which", lambda name: None)
    assert password_helper() == str(helper.resolve())


def test_helper_uses_path_only_when_local_entry_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr("codester.tunnels.sysconfig.get_path", lambda name: str(tmp_path))
    monkeypatch.setattr("codester.tunnels.shutil.which", lambda name: "/installed/helper")
    assert password_helper() == "/installed/helper"
    monkeypatch.setattr("codester.tunnels.shutil.which", lambda name: None)
    assert password_helper() is None


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
    monkeypatch.setattr("codester.tunnels.hidden_subprocess_creation_flags", lambda: 123)
    manager = TunnelManager(tmp_path, [tunnel()], autostart=False)
    manager.ssh = "/usr/bin/ssh"

    status = manager.connect()
    assert status["desired"] is True
    assert status["tunnels"][0]["id"] == tunnel()["id"]
    command, options = commands[0]
    assert "BatchMode=yes" in command
    assert "ServerAliveInterval=30" in command
    assert "127.0.0.1:3417:127.0.0.1:3417" in command
    assert command[-1] == "jack@192.168.1.90"
    assert options["stdin"] is not None and options["stderr"] is not None
    assert options["creationflags"] == 123

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


def test_connection_test_reports_openssh_failure(monkeypatch, tmp_path):
    class FailedProcess:
        returncode = 255

        def poll(self):
            return self.returncode

        def communicate(self):
            return b"", b"Permission denied.\n"

    monkeypatch.setattr(
        "codester.tunnels.subprocess.Popen", lambda command, **kwargs: FailedProcess()
    )
    manager = TunnelManager(tmp_path, [tunnel(auth="password")], autostart=False)
    manager.ssh = "/usr/bin/ssh"
    manager.askpass = "/app/.venv/bin/codester-askpass"
    with pytest.raises(IntegrationError, match="Permission denied"):
        manager.test("1234567890abcdef")


def test_editing_tunnels_preserves_unmodified_connections(tmp_path):
    first = tunnel()
    second = tunnel(id="abcdef1234567890", name="Database", local_port=15432)
    manager = TunnelManager(tmp_path, [first], autostart=False)
    process = Mock()
    process.poll.return_value = None
    manager.items[first["name"]]["process"] = process
    manager.items[first["name"]]["ever_connected"] = True
    manager.configure([first, second])
    process.terminate.assert_not_called()
    assert manager.items[first["name"]]["process"] is process
    assert manager.items[first["name"]]["ever_connected"] is True
    manager.configure([dict(first, local_port=3418), second])
    process.terminate.assert_called_once()
    assert manager.items[first["name"]]["process"] is None
    replacement = Mock()
    replacement.poll.return_value = None
    manager.items[second["name"]]["process"] = replacement
    manager.configure([dict(first, local_port=3418)])
    replacement.terminate.assert_called_once()


def test_individual_tunnels_remain_independent_through_reconcile_and_save(monkeypatch, tmp_path):
    first = tunnel()
    second = tunnel(id="abcdef1234567890", name="Database", local_port=15432)
    processes = []

    def popen(*args, **kwargs):
        process = Mock()
        process.poll.return_value = None
        processes.append(process)
        return process

    monkeypatch.setattr("codester.tunnels.subprocess.Popen", popen)
    manager = TunnelManager(tmp_path, [first, second], autostart=False)
    manager.ssh = "/usr/bin/ssh"
    status = manager.connect(first["id"])
    assert [row["desired"] for row in status["tunnels"]] == [True, False]
    assert len(processes) == 1
    manager.connect(second["id"])
    manager.disconnect(first["id"])
    processes[0].terminate.assert_called_once()
    processes[1].terminate.assert_not_called()
    manager._reconcile()
    manager.configure([dict(first, name="Renamed"), second])
    status = manager.status()
    assert [row["desired"] for row in status["tunnels"]] == [False, True]
    assert len(processes) == 2
    assert status["desired"] is True
    manager.disconnect()
    assert not manager.status()["desired"]
    manager._reconcile()
    assert len(processes) == 2
    manager.connect()
    assert all(row["desired"] for row in manager.status()["tunnels"])
    with pytest.raises(ConfigurationError, match="no longer exists"):
        manager.disconnect("missing")


def test_failed_individual_tunnel_does_not_retry_or_stop_other_tunnels(monkeypatch, tmp_path):
    first = tunnel()
    second = tunnel(id="abcdef1234567890", name="Database", local_port=15432)
    failed = Mock(returncode=255)
    failed.poll.return_value = 255
    failed.communicate.return_value = (b"", b"Permission denied")
    healthy = Mock()
    healthy.poll.return_value = None
    popen = Mock(side_effect=[failed, healthy])
    monkeypatch.setattr("codester.tunnels.subprocess.Popen", popen)
    manager = TunnelManager(tmp_path, [first, second], autostart=False)
    manager.ssh = "/usr/bin/ssh"
    manager.connect()
    manager._reconcile()
    manager._reconcile()
    rows = manager.status()["tunnels"]
    assert rows[0]["state"] == "error" and not rows[0]["desired"]
    assert rows[1]["desired"]
    assert popen.call_count == 2
    healthy.terminate.assert_not_called()
