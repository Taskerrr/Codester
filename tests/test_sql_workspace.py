import copy
import os
import re
import threading
import time
import uuid
from unittest.mock import Mock

import pytest

from codester.app import create_app
from codester.sql_workspace import SQLWorkspace
from codester.store import DEFAULTS, ConfigurationError, Store
from codester.transport import IntegrationError


@pytest.fixture
def app(tmp_path):
    return create_app(tmp_path, start_poller=False)


@pytest.fixture
def client(app):
    return app.test_client()


def csrf(client):
    return {
        "X-Codester-CSRF": re.search(r'name="csrf-token" content="([^"]+)"', client.get("/").text)[
            1
        ]
    }


def connection(**overrides):
    return {
        **DEFAULTS["postgres"],
        "name": "Development",
        "environment": "development",
        "database": "postgres",
        "username": "postgres",
        "password": "secret-value",
        **overrides,
    }


def live(workspace):
    config = workspace.store.read()
    config["demo"] = False
    workspace.store.save(config)


def request(workspace, key, **overrides):
    row, _ = workspace.resolve(key)
    return {
        "connection_id": key,
        "revision": row["revision"],
        "query": "SELECT 1",
        "mode": "read",
        "request_id": uuid.uuid4().hex,
        **overrides,
    }


def test_layout_only_changes_layout(app, client):
    store = app.extensions["store"]
    config = copy.deepcopy(DEFAULTS)
    config["postgres"]["password"] = "preserve-me"
    store.save(config)
    before = store.read()
    response = client.put(
        "/api/dashboard/layout",
        json={"apps": ["docker", "postgres", "codex"]},
        headers=csrf(client),
    )
    assert response.status_code == 200
    after = store.read()
    assert after.pop("dashboard_apps") == ["docker", "postgres", "codex"]
    before.pop("dashboard_apps")
    assert before == after
    assert store.secret("postgres") == "preserve-me"
    assert client.get("/api/dashboard").json["layout"] == ["docker", "postgres", "codex"]
    assert client.get("/api/settings").json["dashboard_apps"] == ["docker", "postgres", "codex"]


@pytest.mark.parametrize("apps", [["codex"] * 3, ["bad", "postgres", "codex"], None, ["codex"]])
def test_invalid_layout_is_atomic(app, client, apps):
    before = app.extensions["store"].read()
    assert (
        client.put("/api/dashboard/layout", json={"apps": apps}, headers=csrf(client)).status_code
        == 400
    )
    assert app.extensions["store"].read() == before


def test_connections_store_passwords_privately_and_survive_settings(app, client, tmp_path):
    key = uuid.uuid4().hex
    response = client.put(f"/api/sql/connections/{key}", json=connection(), headers=csrf(client))
    assert response.status_code == 200
    assert "secret-value" not in response.text
    assert response.json["connections"][0]["has_password"] is True
    assert b"secret-value" not in (tmp_path / "settings.sqlite").read_bytes()
    workspace = app.extensions["sql_workspace"]
    assert workspace.resolve(key)[1] == "secret-value"
    workspace.save(key, connection(password="", name="Dev renamed"))
    assert workspace.resolve(key)[1] == "secret-value"
    assert (
        client.put(
            "/api/settings", json=client.get("/api/settings").json, headers=csrf(client)
        ).status_code
        == 200
    )
    reopened = SQLWorkspace(Store(tmp_path))
    assert reopened.resolve(key)[0]["name"] == "Dev renamed"
    workspace.save(key, connection(password="", clear_password=True))
    assert workspace.resolve(key)[1] == ""
    workspace.delete(key)
    assert workspace.connections() == []


def test_invalid_connection_does_not_replace_saved_password(app):
    workspace = app.extensions["sql_workspace"]
    key = uuid.uuid4().hex
    workspace.save(key, connection())
    with pytest.raises(ConfigurationError):
        workspace.save(key, connection(port=0, password="replacement"))
    assert workspace.resolve(key)[1] == "secret-value"
    with pytest.raises(ConfigurationError, match="different"):
        workspace.save(uuid.uuid4().hex, connection())


def test_existing_monitor_connection_is_available_without_copying_secret(app):
    store = app.extensions["store"]
    config = store.read()
    config["postgres"].update(database="existing", username="existing", password="existing-secret")
    store.save(config)
    row, password = app.extensions["sql_workspace"].resolve("monitor")
    assert row["database"] == "existing"
    assert password == "existing-secret"
    assert row["environment"] == "unspecified"


def test_execution_rejects_demo_unconfirmed_and_changed_target(app, monkeypatch):
    workspace = app.extensions["sql_workspace"]
    key = uuid.uuid4().hex
    workspace.save(key, connection())
    connect = Mock()
    monkeypatch.setattr("codester.sql_workspace.psycopg.connect", connect)
    with pytest.raises(ConfigurationError, match="demo"):
        workspace.execute(request(workspace, key))
    live(workspace)
    with pytest.raises(ConfigurationError, match="Confirm"):
        workspace.execute(request(workspace, key, mode="write"))
    stale = request(workspace, key)
    workspace.save(key, connection(host="other-host"))
    with pytest.raises(ConfigurationError, match="changed"):
        workspace.execute(stale)
    connect.assert_not_called()


def test_mutations_require_csrf(client):
    for path, method, data in [
        ("/api/dashboard/layout", "put", {"apps": ["codex", "docker", "postgres"]}),
        ("/api/sql/run", "post", {}),
        (f"/api/sql/connections/{uuid.uuid4().hex}", "put", connection()),
        (f"/api/sql/cancel/{uuid.uuid4().hex}", "post", {}),
    ]:
        assert getattr(client, method)(path, json=data).status_code == 403


def test_cancel_only_affects_active_request(app):
    workspace = app.extensions["sql_workspace"]
    key = uuid.uuid4().hex
    assert not workspace.cancel(key)
    conn = Mock()
    workspace.active[key] = {"connection": conn, "cancelled": False}
    assert workspace.cancel(key)
    conn.cancel_safe.assert_called_once_with(timeout=5)
    assert workspace.active[key]["cancelled"]


@pytest.fixture
def database_workspace(app):
    port = os.environ.get("CODESTER_TEST_PG_PORT")
    if not port:
        pytest.skip("Set CODESTER_TEST_PG_PORT to a disposable PostgreSQL instance.")
    workspace = app.extensions["sql_workspace"]
    key = uuid.uuid4().hex
    workspace.save(
        key, connection(port=int(port), password="codester-test-only", sslmode="disable")
    )
    live(workspace)
    return workspace, key


def test_live_sql_types_duplicate_columns_empty_and_large_results(database_workspace):
    workspace, key = database_workspace
    result = workspace.execute(
        request(
            workspace,
            key,
            query="SELECT 9007199254740993::bigint AS value, NULL AS value, '你好' AS unicode, '{\"a\":1}'::jsonb AS document",
        )
    )
    assert result["columns"] == ["value", "value", "unicode", "document"]
    assert result["rows"] == [["9007199254740993", None, "你好", '{"a": 1}']]
    empty = workspace.execute(request(workspace, key, query="SELECT 1 AS x WHERE false"))
    assert empty["columns"] == ["x"] and empty["rows"] == []
    large = workspace.execute(
        request(workspace, key, query="SELECT n, repeat('x', 1000) FROM generate_series(1, 600) n")
    )
    assert large["truncated"] and len(large["rows"]) == 500 and large["row_count"] == 600
    cell = workspace.execute(request(workspace, key, query="SELECT repeat('x', 5000)"))
    assert len(cell["rows"][0][0]) == 4001 and cell["truncated"]


def test_live_sql_write_readonly_and_multiple_statements(database_workspace):
    workspace, key = database_workspace
    table = f"codester_test_{uuid.uuid4().hex}"

    def run(query, **kw):
        return workspace.execute(request(workspace, key, query=query, **kw))

    with pytest.raises(IntegrationError, match="write mode"):
        run(f"CREATE TABLE {table} (id int)")
    run(f"CREATE TABLE {table} (id int)", mode="write", confirmed=True)
    try:
        inserted = run(f"INSERT INTO {table} VALUES (1), (2)", mode="write", confirmed=True)
        assert inserted["affected_rows"] == 2
        assert run(f"SELECT count(*) FROM {table}")["rows"] == [["2"]]
        with pytest.raises(IntegrationError):
            run(f"DELETE FROM {table}")
        with pytest.raises(IntegrationError, match="one statement"):
            run(f"DELETE FROM {table}; SELECT 1", mode="write", confirmed=True)
        assert run(f"SELECT count(*) FROM {table}")["rows"] == [["2"]]
        returning = run(
            f"UPDATE {table} SET id = id + 1 RETURNING id", mode="write", confirmed=True
        )
        assert returning["rows"] == [["2"], ["3"]]
    finally:
        run(f"DROP TABLE {table}", mode="write", confirmed=True)


def test_live_cancellation_releases_query_slot(database_workspace):
    workspace, key = database_workspace
    data = request(workspace, key, query="SELECT pg_sleep(15)")
    errors = []

    def run():
        try:
            workspace.execute(data)
        except IntegrationError as error:
            errors.append(str(error))

    thread = threading.Thread(target=run)
    thread.start()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with workspace.lock:
            ready = workspace.active.get(data["request_id"], {}).get("connection") is not None
        if ready:
            break
        time.sleep(0.02)
    time.sleep(0.1)
    assert workspace.cancel(data["request_id"])
    thread.join(timeout=6)
    assert not thread.is_alive()
    assert errors and "cancelled" in errors[0]
    assert workspace.execute(request(workspace, key))["rows"] == [["1"]]


def test_named_activity_and_controls_use_selected_connection(app, client, monkeypatch):
    workspace = app.extensions["sql_workspace"]
    key = uuid.uuid4().hex
    workspace.save(key, connection())
    live(workspace)
    monitor = app.extensions["poller"].postgres
    snapshot = Mock(return_value={"database": "postgres"})
    control = Mock(return_value={"message": "Cancel requested"})
    monkeypatch.setattr(monitor, "snapshot", snapshot)
    monkeypatch.setattr(monitor, "control", control)
    response = client.get(f"/api/sql/connections/{key}/activity")
    assert response.status_code == 200 and response.json["state"]["status"] == "connected"
    assert snapshot.call_args.args[0]["id"] == key
    assert snapshot.call_args.args[1] == "secret-value"
    response = client.post(
        f"/api/sql/connections/{key}/cancel",
        json={"token": "signed-session-token"},
        headers=csrf(client),
    )
    assert response.status_code == 200
    assert control.call_args.args[0]["id"] == key
    assert control.call_args.args[2:] == ("signed-session-token", "cancel")
    config = workspace.store.read()
    config["demo"] = True
    workspace.store.save(config)
    assert (
        client.post(
            f"/api/sql/connections/{key}/cancel",
            json={"token": "signed-session-token"},
            headers=csrf(client),
        ).status_code
        == 400
    )


def test_http_sql_execution_and_cancel(app, client, monkeypatch):
    execute = Mock(return_value={"columns": ["value"], "rows": [["1"]]})
    monkeypatch.setattr(app.extensions["sql_workspace"], "execute", execute)
    response = client.post("/api/sql/run", json={"query": "SELECT 1"}, headers=csrf(client))
    assert response.status_code == 200
    execute.assert_called_once_with({"query": "SELECT 1"})
    assert client.post(f"/api/sql/cancel/{uuid.uuid4().hex}", headers=csrf(client)).json == {
        "cancelled": False
    }


def test_live_transaction_boundary_and_error_cleanup(database_workspace):
    workspace, key = database_workspace
    for query in [
        "SHOW server_version",
        "EXPLAIN SELECT 1",
        "SELECT ';' AS semicolon",
        "SELECT 1 /* ; comment */",
    ]:
        assert workspace.execute(request(workspace, key, query=query))["rows"]
    with pytest.raises(IntegrationError, match="Table or relation"):
        workspace.execute(request(workspace, key, query="SELECT * FROM codester_does_not_exist"))
    assert not workspace.active
    assert workspace.execute(request(workspace, key))["rows"] == [["1"]]


def test_live_preview_byte_limit_keeps_a_prefix(database_workspace, monkeypatch):
    workspace, key = database_workspace
    monkeypatch.setattr("codester.sql_workspace.RESULT_LIMIT", 20)
    result = workspace.execute(
        request(workspace, key, query="SELECT repeat('x', 10) FROM generate_series(1, 10)")
    )
    assert len(result["rows"]) == 2 and result["row_count"] == 10 and result["truncated"]
    result = workspace.execute(request(workspace, key, query="SELECT repeat('x', 30)"))
    assert result["rows"] == [] and result["row_count"] == 1 and result["truncated"]


def test_live_cancellation_before_dispatch_does_not_execute(database_workspace):
    workspace, key = database_workspace
    conn = Mock()
    with pytest.raises(IntegrationError, match="before execution"):
        workspace._results(conn, "SELECT 1", {"cancelled": True})
    conn.pgconn.send_query_params.assert_not_called()
