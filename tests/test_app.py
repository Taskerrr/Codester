import copy
import re

import pytest

from codester.app import create_app
from codester.store import DEFAULTS, ConfigurationError, Store, validate


@pytest.mark.parametrize("seconds", [300, 900, 3600, 21600, 86400])
def test_signoz_window_is_saved(tmp_path, seconds):
    store = Store(tmp_path)
    config = store.read()
    config["signoz"]["window_seconds"] = seconds
    store.save(config)
    assert Store(tmp_path).read()["signoz"]["window_seconds"] == seconds


@pytest.mark.parametrize("seconds", [True, 0, -1, 100, "3600", None])
def test_invalid_signoz_window_is_rejected(seconds):
    config = copy.deepcopy(DEFAULTS)
    config["signoz"]["window_seconds"] = seconds
    with pytest.raises(ConfigurationError, match="time window"):
        validate(config)


@pytest.fixture
def app(tmp_path):
    return create_app(tmp_path, start_poller=False)


@pytest.fixture
def client(app):
    return app.test_client()


def csrf(client):
    html = client.get("/").text
    match = re.search(r'name="csrf-token" content="([^"]+)"', html)
    assert match
    return {"X-Codester-CSRF": match[1]}


def settings():
    data = copy.deepcopy(DEFAULTS)
    data["signoz"].update(api_url="http://localhost:8080", api_key="test-super-secret")
    return data


def test_credentials_persist_encrypted_and_are_not_returned(app, client, tmp_path):
    original = settings()
    original["github"]["token"] = "github-test-super-secret"
    response = client.put("/api/settings", json=original, headers=csrf(client))
    assert response.status_code == 200
    assert "test-super-secret" not in response.text
    assert "api_key" not in response.json["signoz"]
    assert response.json["signoz"]["has_key"]
    assert "token" not in response.json["github"]
    assert response.json["github"]["has_token"]
    assert b"test-super-secret" not in (tmp_path / "settings.sqlite").read_bytes()
    assert b"github-test-super-secret" not in (tmp_path / "settings.sqlite").read_bytes()
    restarted = Store(tmp_path)
    assert restarted.secret("signoz") == "test-super-secret"
    assert restarted.secret("github") == "github-test-super-secret"
    assert restarted.read()["signoz"]["api_url"] == "http://localhost:8080"
    assert Store(tmp_path / "other").secret("signoz") == ""
    data = response.json
    data["signoz"]["api_key"] = ""
    client.put("/api/settings", json=data, headers=csrf(client))
    assert restarted.secret("signoz") == "test-super-secret"
    data["signoz"]["clear_key"] = True
    data["github"]["clear_token"] = True
    client.put("/api/settings", json=data, headers=csrf(client))
    assert restarted.secret("signoz") == ""
    assert restarted.secret("github") == ""


def test_reject_cross_origin_and_missing_csrf(client):
    assert client.put("/api/settings", json=settings()).status_code == 403
    assert (
        client.put(
            "/api/settings",
            json=settings(),
            headers={**csrf(client), "Origin": "https://evil.test"},
        ).status_code
        == 403
    )
    assert client.get("/api/settings", headers={"Host": "evil.test"}).status_code == 400
    assert client.get("/api/settings", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://user:pass@localhost",
        "http://localhost?key=secret",
        "javascript:alert(1)",
        "http://localhost:99999",
        "http://local host",
    ],
)
def test_bad_urls_do_not_replace_saved_settings(client, url):
    client.put("/api/settings", json=settings(), headers=csrf(client))
    data = settings()
    data["dagster"]["api_url"] = url
    assert client.put("/api/settings", json=data, headers=csrf(client)).status_code == 400
    assert client.get("/api/settings").json["signoz"]["has_key"]


def test_demo_details_and_unknown_ids(app, client):
    poller = app.extensions["poller"]
    poller.refresh("dagster")
    assert client.get("/api/errors/dagster/demo-dagster-1").json["url"] == ""
    assert client.get("/api/errors/dagster/arbitrary").status_code == 404
    assert client.get("/api/errors/codex/demo-dagster-1").status_code == 404
    assert client.get("/api/dashboard").json["demo"] is True
    activity = client.get("/api/codex/activity").json
    assert activity["tasks"][0]["id"] == "demo-task-1"


def test_security_headers(client):
    response = client.get("/")
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_refresh_endpoint_wakes_upstream_workers(app, client):
    poller = app.extensions["poller"]
    assert all(not wake.is_set() for wake in poller.wakes.values())

    response = client.post("/api/refresh", headers=csrf(client))

    assert response.status_code == 200
    assert all(wake.is_set() for wake in poller.wakes.values())


def test_settings_invalid_panels(client):
    data = settings()
    data["signoz"]["panels"] = [{"service": "api", "metric": "unknown"}]
    assert client.put("/api/settings", json=data, headers=csrf(client)).status_code == 400


def test_dashboard_layout_persists_and_rejects_duplicates(client):
    data = settings()
    data["dashboard_apps"] = ["docker", "codex", "postgres"]
    response = client.put("/api/settings", json=data, headers=csrf(client))
    assert response.status_code == 200
    assert response.json["dashboard_apps"] == ["docker", "codex", "postgres"]
    assert client.get("/api/dashboard").json["layout"] == ["docker", "codex", "postgres"]

    data["dashboard_apps"] = ["docker", "docker", "codex"]
    assert client.put("/api/settings", json=data, headers=csrf(client)).status_code == 400


def test_tunnel_settings_and_controls(app, client, monkeypatch):
    data = settings()
    data["tunnels"] = [
        {
            "id": "1234567890abcdef",
            "name": "Dagster",
            "auth": "password",
            "password": "ssh-test-super-secret",
            "ssh_host": "192.168.1.90",
            "ssh_port": 22,
            "username": "jack",
            "local_port": 3417,
            "remote_host": "127.0.0.1",
            "remote_port": 3417,
        }
    ]
    assert client.put("/api/settings", json=data, headers=csrf(client)).status_code == 200
    public = client.get("/api/settings")
    assert public.json["tunnels"][0]["name"] == "Dagster"
    assert public.json["tunnels"][0]["has_password"] is True
    assert "ssh-test-super-secret" not in public.text
    assert b"ssh-test-super-secret" not in app.extensions["store"].path.read_bytes()

    manager = app.extensions["tunnel_manager"]
    monkeypatch.setattr(
        manager,
        "connect",
        lambda: {"state": "connecting", "desired": True, "tunnels": []},
    )
    monkeypatch.setattr(
        manager,
        "disconnect",
        lambda: {"state": "disconnected", "desired": False, "tunnels": []},
    )
    monkeypatch.setattr(
        manager,
        "test",
        lambda identifier: {"ok": True, "message": f"Tested {identifier}"},
    )
    assert client.get("/api/tunnels").status_code == 200
    assert client.post("/api/tunnels/connect", headers=csrf(client)).json["desired"] is True
    assert client.post("/api/tunnels/disconnect", headers=csrf(client)).json["desired"] is False
    response = client.post(
        "/api/tunnels/1234567890abcdef/test", headers=csrf(client)
    )
    assert response.json["ok"] is True
    assert client.post("/api/tunnels/not-valid/test", headers=csrf(client)).status_code == 404


def test_docker_page_and_controls(app, client, monkeypatch):
    containers = [
        {
            "id": "a" * 64,
            "name": "web",
            "image": "example/web:latest",
            "state": "running",
            "status": "Up 2 minutes",
            "ports": "8080→80/tcp",
            "running": True,
        }
    ]
    actions = []
    monkeypatch.setattr("codester.docker_engine.containers", lambda: containers)
    monkeypatch.setattr(
        "codester.docker_engine.resource_stats",
        lambda items: {
            "a" * 64: {
                "cpu_percent": 1.5,
                "memory_used": 128,
                "memory_limit": 1024,
            }
        },
    )
    monkeypatch.setattr(
        "codester.docker_engine.control",
        lambda container_id, action: actions.append((container_id, action)),
    )
    assert client.get("/docker").status_code == 200
    response = client.get("/api/docker/containers")
    assert response.json["running"] == 1 and response.json["total"] == 1
    assert response.json["memory_used"] == 128
    assert response.json["memory_limit"] == 1024
    response = client.post(
        f"/api/docker/containers/{'a' * 64}/stop", headers=csrf(client)
    )
    assert response.status_code == 200
    assert actions == [("a" * 64, "stop")]
    assert client.post(
        f"/api/docker/containers/{'a' * 64}/remove", headers=csrf(client)
    ).status_code == 404


def test_private_permissions(tmp_path):
    import os

    if os.name == "nt":
        pytest.skip("POSIX modes do not describe Windows ACLs")
    Store(tmp_path)
    assert (tmp_path.stat().st_mode & 0o777) == 0o700
    assert ((tmp_path / "settings.sqlite").stat().st_mode & 0o777) == 0o600
    assert not (tmp_path / "secret.key").exists()


def test_service_discovery_uses_saved_real_connection(app, client, monkeypatch):
    client.put("/api/settings", json=settings(), headers=csrf(client))

    def discover(config, key):
        assert config["api_url"] == "http://localhost:8080"
        assert key == "test-super-secret"
        return ["api", "worker"]

    monkeypatch.setattr("codester.signoz.services", discover)
    response = client.post("/api/signoz/services", headers=csrf(client))
    assert response.json["services"] == ["api", "worker"]


def test_individual_tunnel_controls_require_csrf_and_valid_action(app, client, monkeypatch):
    manager = app.extensions["tunnel_manager"]
    calls = []
    monkeypatch.setattr(manager, "connect", lambda identifier: calls.append(identifier) or {"ok": True})
    path = "/api/tunnels/1234567890abcdef/connect"
    assert client.post(path).status_code == 403
    assert not calls
    assert client.post(path, headers=csrf(client)).status_code == 200
    assert calls == ["1234567890abcdef"]
    assert client.post("/api/tunnels/1234567890abcdef/delete", headers=csrf(client)).status_code == 404
    assert client.post("/api/tunnels/invalid/connect", headers=csrf(client)).status_code == 404
