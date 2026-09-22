import json
import os
import plistlib
import re
import sys

import pytest

from codester import native, startup
from codester.app import create_app
from codester.store import ConfigurationError


@pytest.fixture
def installation(tmp_path, monkeypatch):
    directory = tmp_path / "App with space's" / ".data"
    directory.mkdir(parents=True)
    (directory / "native.json").write_text(
        json.dumps({"environment": {"PATH": "keep-me"}}), encoding="utf-8",
    )
    monkeypatch.setenv("CODESTER_NATIVE", "1")
    monkeypatch.setattr(startup.sys, "platform", "darwin")
    path = tmp_path / "LaunchAgents/codester.plist"
    monkeypatch.setattr(startup, "registration_path", lambda: path)
    return directory, path


def test_toggle_does_not_stop_running_service_and_preserves_environment(installation, monkeypatch):
    directory, path = installation
    def no_process(*args, **kwargs):
        pytest.fail("Changing Mac login preferences must not start or stop a process")
    monkeypatch.setattr(startup.subprocess, "run", no_process)
    assert startup.startup_status(directory)["enabled"] is False
    saved = startup.save_startup(directory, dict(enabled=True, open_browser=True))
    assert saved["enabled"] is True
    assert saved["open_browser"] is True
    definition = plistlib.loads(path.read_bytes())
    assert definition["WorkingDirectory"] == str(directory.parent)
    assert definition["ProgramArguments"][0] == str(directory.parent / ".venv/bin/python")
    startup.save_startup(directory, dict(enabled=False, open_browser=True))
    assert not path.exists()
    config = json.loads((directory / "native.json").read_text())
    assert config["environment"] == {"PATH": "keep-me"}
    assert config["login_enabled"] is False
    assert config["open_browser"] is True


def test_uninstalled_or_container_cannot_manage_host_startup(tmp_path, monkeypatch):
    monkeypatch.delenv("CODESTER_NATIVE", raising=False)
    assert startup.startup_status(tmp_path)["supported"] is False
    with pytest.raises(ConfigurationError, match="native installation"):
        startup.save_startup(tmp_path, dict(enabled=True, open_browser=True))


@pytest.mark.parametrize("payload", [None, [], {}, {"enabled": "false", "open_browser": True},
    {"enabled": True, "open_browser": False, "command": "anything"}])
def test_strict_startup_payload(installation, payload):
    directory, path = installation
    with pytest.raises(ConfigurationError):
        startup.save_startup(directory, payload)
    assert not path.exists()


def test_startup_api_requires_csrf_and_does_not_change_dashboard_settings(installation):
    directory, path = installation
    app = create_app(directory, start_poller=False)
    client = app.test_client()
    original = client.get("/api/settings").json
    payload = dict(enabled=True, open_browser=True)
    assert client.put("/api/startup", json=payload).status_code == 403
    assert not path.exists()
    token = re.search(r'name="csrf-token" content="([^"]+)"', client.get("/settings").text)
    assert token is not None
    response = client.put("/api/startup", json=payload, headers={"X-Codester-CSRF": token[1]})
    assert response.status_code == 200
    assert response.json is not None
    assert response.json["enabled"] is True
    assert client.get("/api/settings").json == original


def test_windows_registration_never_starts_or_stops_current_app(installation, monkeypatch):
    directory, path = installation
    monkeypatch.setattr(startup.sys, "platform", "win32")
    scripts = []
    def record_script(script):
        scripts.append(script)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    monkeypatch.setattr(startup, "powershell", record_script)
    startup.save_startup(directory, dict(enabled=True, open_browser=False))
    assert "Stop-Process" not in scripts[0]
    assert "$shell.Run" not in scripts[0]
    assert "pythonw.exe" in scripts[0]
    assert "space''s" in scripts[0]


@pytest.mark.parametrize("open_browser", [True, False])
def test_browser_opens_only_after_server_is_ready(installation, monkeypatch, open_browser):
    directory, _ = installation
    config = json.loads((directory / "native.json").read_text())
    config["open_browser"] = open_browser
    (directory / "native.json").write_text(json.dumps(config))
    order = []
    class Server:
        def run(self):
            order.append("serve")
    def create_server(*args, **kwargs):
        order.append("listening")
        return Server()
    class ImmediateThread:
        def __init__(self, *, target, args, daemon):
            self.target, self.args = target, args
        def start(self):
            self.target(*self.args)
    monkeypatch.setattr(native, "create_app", lambda: None)
    monkeypatch.setattr(native, "create_server", create_server)
    monkeypatch.setattr(native.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(native.webbrowser, "open", lambda url: order.append(url))
    monkeypatch.chdir(directory.parent)
    for key in ("PATH", "CODESTER_SECRET_STORAGE", "CODESTER_DATA_DIR"):
        monkeypatch.setenv(key, os.environ.get(key, ""))
    output, error = sys.stdout, sys.stderr
    try:
        native.run(directory.parent, directory)
    finally:
        sys.stdout, sys.stderr = output, error
    assert order == (["listening", "http://127.0.0.1:8765", "serve"] if open_browser else ["listening", "serve"])
