import json
import os
import re
import shlex
import sys
import threading
import time

import pytest

from codester.app import create_app
from codester.services import ServiceManager
from codester.store import ConfigurationError

HOST_ID = "a" * 16
REPO_ID = "b" * 16


@pytest.fixture
def app(tmp_path):
    app = create_app(tmp_path, start_poller=False)
    store = app.extensions["store"]
    config = store.read()
    config["demo"] = False
    config["tunnels"] = [
        {
            "id": HOST_ID,
            "name": "Deploy server",
            "ssh_host": "example.invalid",
            "username": "operator",
            "ssh_port": 22,
            "auth": "agent",
            "local_port": 3210,
            "remote_host": "localhost",
            "remote_port": 3210,
        }
    ]
    config["github"]["repositories"] = [
        {
            "id": REPO_ID,
            "repo": "owner/project",
            "path": "",
            "update_host_id": HOST_ID,
            "update_path": "/srv/project's code",
            "update_script": "git pull --ff-only &&\nprintf done",
            "update_confirm": True,
        }
    ]
    store.save(config)
    return app


def saved_row(manager):
    return manager.repository_updates()["repositories"][0]


def test_read_only_snapshot_and_csrf(app, monkeypatch):
    manager = app.extensions["service_manager"]
    calls = []
    monkeypatch.setattr(manager.tunnels, "remote_session", lambda *args: calls.append(args))
    client = app.test_client()
    token = re.search(r'name="csrf-token" content="([^"]+)"', client.get("/").text)[1]
    response = client.get("/api/github/updates")
    row = response.json["repositories"][0]
    assert row["configured"] and row["confirm"]
    assert client.get("/api/github/repositories").json["repositories"] == []
    assert not calls
    assert client.post(f"/api/github/updates/{REPO_ID}", json={}).status_code == 403
    headers = {"X-Codester-CSRF": token}
    for data in ([], {}, {"revision": row["revision"], "confirmed": False}):
        assert (
            client.post(f"/api/github/updates/{REPO_ID}", json=data, headers=headers).status_code
            == 400
        )
    assert not calls


def test_update_uses_saved_script_and_identity_and_blocks_duplicates(app, monkeypatch):
    manager = app.extensions["service_manager"]
    gate = threading.Event()
    captured = []

    def session(host, script):
        captured.append((host, script))
        return ["ssh"], {}

    def execute(*args):
        gate.wait(2)

    monkeypatch.setattr(manager.tunnels, "remote_session", session)
    monkeypatch.setattr(manager, "_run", execute)
    row = saved_row(manager)
    try:
        action = manager.start_repository(REPO_ID, row["revision"], confirmed=True)
        assert action["state"] == "running"
        assert captured[0][0]["id"] == HOST_ID
        assert captured[0][1] == f"cd {shlex.quote(row['path'])} && {{\n{row['script']}\n}}"
        with pytest.raises(ConfigurationError, match="already running"):
            manager.start_repository(REPO_ID, row["revision"], confirmed=True)
        assert len(captured) == 1
    finally:
        gate.set()


def test_demo_stale_missing_and_confirmation_reject_before_ssh(app, monkeypatch):
    manager = app.extensions["service_manager"]
    row = saved_row(manager)
    calls = []
    monkeypatch.setattr(manager.tunnels, "remote_session", lambda *args: calls.append(args))
    with pytest.raises(ConfigurationError, match="Confirm"):
        manager.start_repository(REPO_ID, row["revision"])
    with pytest.raises(ConfigurationError, match="changed"):
        manager.start_repository(REPO_ID, "old-revision", confirmed=True)
    with pytest.raises(ConfigurationError, match="no longer"):
        manager.start_repository("missing", row["revision"], confirmed=True)
    config = manager.store.read()
    config["demo"] = True
    manager.store.save(config)
    with pytest.raises(ConfigurationError, match="demo"):
        manager.start_repository(REPO_ID, row["revision"], confirmed=True)
    assert not calls


@pytest.mark.parametrize("exit_code, expected", [(0, "success"), (2, "error"), (255, "unknown")])
def test_output_result_and_restart_persistence(app, monkeypatch, exit_code, expected):
    manager = app.extensions["service_manager"]
    monkeypatch.setattr(
        manager.tunnels,
        "remote_session",
        lambda *_: (
            [sys.executable, "-c", f"print('<build output>'); raise SystemExit({exit_code})"],
            os.environ.copy(),
        ),
    )
    row = saved_row(manager)
    manager.start_repository(REPO_ID, row["revision"], confirmed=True)
    deadline = time.monotonic() + 5
    while saved_row(manager)["action"]["state"] == "running":
        assert time.monotonic() < deadline
        time.sleep(0.01)
    action = saved_row(manager)["action"]
    assert action["state"] == expected
    assert "<build output>" in action["output"]
    restarted = ServiceManager(manager.store, manager.tunnels)
    assert saved_row(restarted)["action"]["run_id"] == action["run_id"]
    assert "deployed" not in json.dumps(action)


@pytest.mark.parametrize(
    "changes",
    [
        {"update_host_id": "missing"},
        {"update_path": "relative"},
        {"update_script": ""},
        {"update_confirm": "yes"},
        {"update_script": "\x00"},
    ],
)
def test_invalid_update_configuration(app, changes):
    store = app.extensions["store"]
    config = store.read()
    config["github"]["repositories"][0].update(changes)
    with pytest.raises(ConfigurationError):
        store.save(config)


def configure_script(app, **changes):
    store = app.extensions["store"]
    config = store.read()
    config["github"]["repositories"][0].update(
        update_mode="script", update_script_file="scripts/deploy.sh", update_script=""
    )
    config["github"]["repositories"][0].update(changes)
    store.save(config)
    return config["github"]["repositories"][0]


def test_repository_script_preview_and_execution(app, monkeypatch):
    configure_script(app, update_script_file="scripts/deploy site's.sh", update_pull=True)
    manager = app.extensions["service_manager"]
    captured = []
    monkeypatch.setattr(manager.tunnels, "remote_session", lambda host, script: (captured.append(script) or ["ssh"], {}))
    monkeypatch.setattr(manager, "_run", lambda *args: None)
    row = saved_row(manager)
    assert row["mode"] == "script" and row["configured"] and row["pull"]
    assert "git pull --ff-only" in row["script"]
    assert "CODESTER_DEPLOY_COMMIT" in row["script"]
    action = manager.start_repository(REPO_ID, row["revision"], confirmed=True)
    assert action["timeout"] == 1800
    assert action["label"] == "Deploy owner/project"
    assert action["script"] == row["script"]
    assert captured == [f"cd {shlex.quote(row['path'])} && {{\n{row['script']}\n}}"]


@pytest.mark.parametrize("field,value", [
    ("update_script_file", "scripts/other.sh"), ("update_pull", True),
    ("update_mode", "command"),
])
def test_script_configuration_changes_require_new_revision(app, monkeypatch, field, value):
    configure_script(app, update_script="printf legacy")
    manager = app.extensions["service_manager"]
    revision = saved_row(manager)["revision"]
    config = manager.store.read()
    config["github"]["repositories"][0][field] = value
    manager.store.save(config)
    with pytest.raises(ConfigurationError, match="changed"):
        manager.start_repository(REPO_ID, revision, confirmed=True)


@pytest.mark.parametrize("path", ["", "/tmp/deploy.sh", "../deploy.sh", "scripts/../deploy.sh",
                                  "scripts//deploy.sh", "-script", "C:/deploy.sh", "scripts\\deploy.sh", "a\nb"])
def test_invalid_repository_script_paths(app, path):
    with pytest.raises(ConfigurationError):
        configure_script(app, update_script_file=path)


def test_legacy_command_mode_is_preserved(app):
    row = saved_row(app.extensions["service_manager"])
    assert row["mode"] == "command"
    assert row["script"] == "git pull --ff-only &&\nprintf done"
    assert "git pull" not in ServiceManager.repository_script({
        "update_mode": "script", "update_script_file": "scripts/deploy.sh", "update_pull": False,
    })
