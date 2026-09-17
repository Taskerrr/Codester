import json
import re
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import closing

import pytest

from codester.app import create_app
from codester.services import OUTPUT_LIMIT, ServiceManager, validate_service
from codester.store import ConfigurationError, Store
from codester.tunnels import TunnelManager

HOST = {
    "id": "a" * 16,
    "name": "Server",
    "auth": "password",
    "ssh_host": "example.internal",
    "ssh_port": 22,
    "username": "operator",
    "local_port": 3000,
    "remote_host": "localhost",
    "remote_port": 3000,
}
SERVICE = {
    "name": "Dagster",
    "host_id": HOST["id"],
    "path": "/srv/Dagster's code",
    "branch": "main",
    "notes": "Reload manually",
    "commands": [{"id": "b" * 16, "label": "Pull", "script": "git pull", "confirm": False}],
}
IDENTIFIER = "c" * 16


@pytest.fixture
def manager(tmp_path):
    store = Store(tmp_path)
    config = store.read()
    config["tunnels"] = [dict(HOST, password="test-password-secret")]
    store.save(config)
    tunnels = TunnelManager(tmp_path, [HOST], autostart=False)
    tunnels.ssh = "ssh"
    tunnels.askpass = "askpass"
    result = ServiceManager(store, tunnels)
    result.save(IDENTIFIER, SERVICE)
    return result


def wait_finished(manager):
    deadline = time.monotonic() + 5
    while manager.snapshot()["actions"][IDENTIFIER]["state"] == "running":
        assert time.monotonic() < deadline
        time.sleep(0.01)
    return manager.snapshot()["actions"][IDENTIFIER]


def test_session_reuses_identity_without_forwarding(manager):
    args, env = manager.tunnels.remote_session(HOST, "pwd")
    assert "-N" not in args and "-L" not in args
    assert args[-2:] == ["operator@example.internal", "pwd"]
    assert "StrictHostKeyChecking=accept-new" in args
    assert env["CODESTER_SSH_SECRET"] == "tunnel-password:" + HOST["id"]
    assert "test-password-secret" not in json.dumps([args, env])


def test_saved_commands_only_and_quoted_working_directory(manager, monkeypatch):
    called = []
    entered = threading.Event()
    release = threading.Event()

    def fake_run(identifier, args, environment, password):
        called.append(args)
        entered.set()
        release.wait(2)

    monkeypatch.setattr(manager, "_run", fake_run)
    with pytest.raises(ConfigurationError, match="no longer exists"):
        manager.start(IDENTIFIER, "not-a-saved-command")
    assert called == []
    manager.start(IDENTIFIER, "b" * 16)
    assert entered.wait(2)
    assert called[0][-1] == "cd '/srv/Dagster'\"'\"'s code' && {\ngit pull\n}"
    with pytest.raises(ConfigurationError, match="already running"):
        manager.start(IDENTIFIER, "b" * 16)
    with pytest.raises(ConfigurationError, match="finish"):
        manager.delete(IDENTIFIER)
    with pytest.raises(ConfigurationError, match="finish"):
        manager.save(IDENTIFIER, SERVICE)
    release.set()


def test_confirmation_and_missing_host(manager):
    command = dict(SERVICE["commands"][0], confirm=True)
    manager.save(IDENTIFIER, dict(SERVICE, commands=[command]))
    with pytest.raises(ConfigurationError, match="Confirm"):
        manager.start(IDENTIFIER, command["id"])
    config = manager.store.read()
    config["tunnels"] = []
    manager.store.save(config)
    with pytest.raises(ConfigurationError, match="removed"):
        manager.start(IDENTIFIER, command["id"], confirmed=True)


@pytest.mark.parametrize("code,state", [(0, "success"), (1, "error"), (255, "unknown")])
def test_output_failure_and_history_survive_restart(manager, monkeypatch, code, state):
    import os

    monkeypatch.setattr(
        manager.tunnels,
        "remote_session",
        lambda *_: (
            [
                sys.executable,
                "-c",
                f"print('test-password-secret'); print('line two'); raise SystemExit({code})",
            ],
            os.environ.copy(),
        ),
    )
    manager.start(IDENTIFIER, "b" * 16)
    action = wait_finished(manager)
    assert action["state"] == state
    assert "[redacted]" in action["output"] and "line two" in action["output"]
    assert "test-password-secret" not in json.dumps(manager.snapshot())
    restored = ServiceManager(manager.store, manager.tunnels)
    assert restored.snapshot()["actions"][IDENTIFIER]["output"] == action["output"]


def test_timeout_is_unknown(manager, monkeypatch):
    import os

    monkeypatch.setattr("codester.services.COMMAND_TIMEOUT", 0.5)
    monkeypatch.setattr(
        manager.tunnels,
        "remote_session",
        lambda *_: (
            [sys.executable, "-u", "-c", "import time; time.sleep(10)"],
            os.environ.copy(),
        ),
    )
    manager.start(IDENTIFIER, "b" * 16)
    action = wait_finished(manager)
    assert action["state"] == "unknown"
    assert "may still be running" in action["message"]
    assert len(action["output"]) <= OUTPUT_LIMIT


def test_interrupted_action_is_not_reported_as_success(manager):
    with closing(sqlite3.connect(manager.store.path)) as db, db:
        db.execute(
            "INSERT INTO service_actions VALUES (?,?)",
            (IDENTIFIER, json.dumps({"state": "running", "output": "partial"})),
        )
    restarted = ServiceManager(manager.store, manager.tunnels)
    assert restarted.snapshot()["actions"][IDENTIFIER]["state"] == "unknown"


@pytest.mark.parametrize(
    "changes",
    [
        {"branch": "main; touch /tmp/bad"},
        {"host_id": "missing"},
        {"path": "\x00"},
        {"commands": [{"script": "pwd"}]},
    ],
)
def test_invalid_configuration(changes):
    with pytest.raises(ConfigurationError):
        validate_service(dict(SERVICE, **changes), [HOST])


def test_routes_require_csrf_and_reading_never_executes(manager, monkeypatch):
    app = create_app(manager.store.path.parent, start_poller=False)
    client = app.test_client()
    token = re.search(r'name="csrf-token" content="([^"]+)"', client.get("/services").text)[1]
    headers = {"X-Codester-CSRF": token}
    called = []
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: called.append(args))
    assert client.get("/api/services").status_code == 200
    assert client.put(f"/api/services/{IDENTIFIER}", json=SERVICE).status_code == 403
    assert client.post(f"/api/services/{IDENTIFIER}/run/{'b' * 16}").status_code == 403
    assert client.delete(f"/api/services/{IDENTIFIER}").status_code == 403
    assert (
        client.put(f"/api/services/{IDENTIFIER}", json=SERVICE, headers=headers).status_code == 200
    )
    assert client.get("/api/services").json["services"][0]["name"] == "Dagster"
    assert not called
    assert client.delete(f"/api/services/{IDENTIFIER}", headers=headers).status_code == 200


def test_output_is_bounded(manager, monkeypatch):
    import os

    monkeypatch.setattr(
        manager.tunnels,
        "remote_session",
        lambda *_: ([sys.executable, "-u", "-c", "print('x'*100000)"], os.environ.copy()),
    )
    manager.start(IDENTIFIER, "b" * 16)
    action = wait_finished(manager)
    assert action["state"] == "success"
    assert action["truncated"]
    assert len(action["output"]) == OUTPUT_LIMIT
