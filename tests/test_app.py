import copy
import re

import pytest

from codester.app import create_app
from codester.store import DEFAULTS, Store


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
    response = client.put("/api/settings", json=settings(), headers=csrf(client))
    assert response.status_code == 200
    assert "test-super-secret" not in response.text
    assert "api_key" not in response.json["signoz"]
    assert response.json["signoz"]["has_key"]
    assert b"test-super-secret" not in (tmp_path / "settings.sqlite").read_bytes()
    restarted = Store(tmp_path)
    assert restarted.secret("signoz") == "test-super-secret"
    assert restarted.read()["signoz"]["api_url"] == "http://localhost:8080"
    assert Store(tmp_path / "other").secret("signoz") == ""
    data = response.json
    data["signoz"]["api_key"] = ""
    client.put("/api/settings", json=data, headers=csrf(client))
    assert restarted.secret("signoz") == "test-super-secret"
    data["signoz"]["clear_key"] = True
    client.put("/api/settings", json=data, headers=csrf(client))
    assert restarted.secret("signoz") == ""


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


def test_security_headers(client):
    response = client.get("/")
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_settings_invalid_panels(client):
    data = settings()
    data["signoz"]["panels"] = [{"service": "api", "metric": "unknown"}]
    assert client.put("/api/settings", json=data, headers=csrf(client)).status_code == 400


def test_private_permissions(tmp_path):
    import os

    if os.name == "nt":
        pytest.skip("POSIX modes do not describe Windows ACLs")
    Store(tmp_path)
    assert (tmp_path.stat().st_mode & 0o777) == 0o700
    assert ((tmp_path / "secret.key").stat().st_mode & 0o777) == 0o600


def test_service_discovery_uses_saved_real_connection(app, client, monkeypatch):
    client.put("/api/settings", json=settings(), headers=csrf(client))

    def discover(config, key):
        assert config["api_url"] == "http://localhost:8080"
        assert key == "test-super-secret"
        return ["api", "worker"]

    monkeypatch.setattr("codester.signoz.services", discover)
    response = client.post("/api/signoz/services", headers=csrf(client))
    assert response.json["services"] == ["api", "worker"]
