import copy
import os
import re
import threading
import time
import uuid

import psycopg
import pytest
from psycopg import sql

from codester.app import create_app
from codester.postgres import PostgresMonitor
from codester.store import DEFAULTS, ConfigurationError, Store, validate
from codester.transport import IntegrationError


def test_password_uses_vault_and_settings_do_not_expose_it(tmp_path):
    store = Store(tmp_path)
    config = store.read()
    config["postgres"].update(database="app", username="monitor", password="pg-test-secret")
    store.save(config)
    assert store.secret("postgres") == "pg-test-secret"
    assert store.public()["postgres"]["has_password"]
    assert "password" not in store.read()["postgres"]
    assert b"pg-test-secret" not in store.path.read_bytes()
    config = store.public()
    config["postgres"]["password"] = ""
    store.save(config)
    assert store.secret("postgres") == "pg-test-secret"
    config["postgres"]["clear_password"] = True
    store.save(config)
    assert store.secret("postgres") == ""


@pytest.mark.parametrize(
    "changes",
    [
        {"port": 0},
        {"port": True},
        {"host": "host=x password=y"},
        {"refresh_seconds": 1},
        {"sslmode": []},
        {"enabled": True, "username": ""},
    ],
)
def test_invalid_postgres_settings(changes):
    config = copy.deepcopy(DEFAULTS)
    config["postgres"].update(changes)
    with pytest.raises(ConfigurationError):
        validate(config)


def test_tokens_expire_and_cannot_change_connection(monkeypatch):
    monitor = PostgresMonitor()
    config = DEFAULTS["postgres"]
    with monkeypatch.context() as context:
        context.setattr(
            "itsdangerous.timed.TimestampSigner.get_timestamp", lambda self: int(time.time()) - 100
        )
        old = monitor.signer.dumps({"target": "anything"})
    with pytest.raises(IntegrationError, match="expired"):
        monitor.control(config, "", old, "terminate")
    with pytest.raises(IntegrationError, match="expired"):
        monitor.control(config, "", "invented-token", "cancel")
    token = monitor.signer.dumps({"target": "different-connection"})
    with pytest.raises(IntegrationError, match="connection changed"):
        monitor.control(config, "", token, "terminate")


def test_actions_require_csrf_live_enabled_and_connected(tmp_path, monkeypatch):
    app = create_app(tmp_path, start_poller=False)
    client = app.test_client()
    csrf = re.search(r'name="csrf-token" content="([^"]+)"', client.get("/postgres").text)[1]
    headers = {"X-Codester-CSRF": csrf}
    calls = []
    poller = app.extensions["poller"]
    monkeypatch.setattr(
        poller.postgres, "control", lambda *args: calls.append(args) or {"message": "sent"}
    )
    assert client.post("/api/postgres/terminate", json={"token": "test"}).status_code == 403
    assert (
        client.post("/api/postgres/terminate", json={"token": "test"}, headers=headers).status_code
        == 400
    )
    store = app.extensions["store"]
    config = store.read()
    config["demo"] = False
    config["postgres"].update(enabled=True, username="monitor", database="app")
    store.save(config)
    poller.state["postgres"]["status"] = "stale"
    assert (
        client.post("/api/postgres/cancel", json={"token": "test"}, headers=headers).status_code
        == 400
    )
    assert not calls
    poller.state["postgres"]["status"] = "connected"
    assert (
        client.post("/api/postgres/cancel", json={"token": "test"}, headers=headers).status_code
        == 200
    )
    assert len(calls) == 1
    assert (
        client.post("/api/postgres/drop", json={"token": "test"}, headers=headers).status_code
        == 404
    )
    assert client.get("/api/postgres").status_code == 200


@pytest.fixture
def pg_config():
    port = os.environ.get("CODESTER_TEST_POSTGRES_PORT")
    if not port:
        pytest.skip("Set CODESTER_TEST_POSTGRES_PORT for the isolated local PostgreSQL container")
    return dict(
        DEFAULTS["postgres"],
        enabled=True,
        host="127.0.0.1",
        port=int(port),
        database="postgres",
        username="postgres",
        sslmode="disable",
    )


def connect(config, **kwargs):
    return psycopg.connect(
        host="127.0.0.1",
        port=config["port"],
        dbname=config["database"],
        user=config["username"],
        password="codester-test-only",
        connect_timeout=5,
        **kwargs,
    )


def await_snapshot(monitor, config, predicate):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        data = monitor.snapshot(config, "codester-test-only")
        if predicate(data):
            return data
        time.sleep(0.05)
    raise AssertionError("Expected PostgreSQL activity did not appear")


def test_real_query_cancellation_and_stale_identity(pg_config):
    monitor = PostgresMonitor()
    errors = []
    with connect(pg_config, autocommit=True) as worker:

        def run():
            try:
                worker.execute("SELECT pg_sleep(30)")
            except psycopg.errors.QueryCanceled as exc:
                errors.append(exc)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        try:
            data = await_snapshot(
                monitor,
                pg_config,
                lambda data: any(row["pid"] == worker.info.backend_pid for row in data["queries"]),
            )
            row = next(row for row in data["queries"] if row["pid"] == worker.info.backend_pid)
            assert row["token"] and "pg_sleep" in row["query"]
            assert data["active"] >= 1
            assert (
                "requested"
                in monitor.control(pg_config, "codester-test-only", row["token"], "cancel")[
                    "message"
                ]
            )
            thread.join(timeout=5)
            assert errors and not thread.is_alive()
            worker.execute("SELECT 1")
            with pytest.raises(IntegrationError, match="changed or ended"):
                monitor.control(pg_config, "codester-test-only", row["token"], "terminate")
        finally:
            if thread.is_alive():
                worker.cancel()
                thread.join(timeout=5)


def test_real_blocker_termination_releases_transaction_lock(pg_config):
    monitor = PostgresMonitor()
    name = "codester_lock_test_" + uuid.uuid4().hex
    table = sql.Identifier(name)
    with connect(pg_config, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE TABLE {} (id int PRIMARY KEY, value int)").format(table))
        admin.execute(sql.SQL("INSERT INTO {} VALUES (1,0)").format(table))
        blocker = connect(pg_config)
        waiter = connect(pg_config, autocommit=True)
        errors = []
        try:
            blocker.execute(sql.SQL("UPDATE {} SET value=1 WHERE id=1").format(table))
            blocker_pid = blocker.info.backend_pid
            waiter_pid = waiter.info.backend_pid

            def run():
                try:
                    waiter.execute(sql.SQL("UPDATE {} SET value=2 WHERE id=1").format(table))
                except psycopg.Error as exc:
                    errors.append(exc)

            thread = threading.Thread(target=run, daemon=True)
            thread.start()
            data = await_snapshot(
                monitor,
                pg_config,
                lambda data: (
                    {"waiting_pid": waiter_pid, "blocking_pid": blocker_pid} in data["blocking"]
                ),
            )
            assert data["waiting"] >= 1 and data["held_locks"] > 0
            assert any(lock["pid"] == waiter_pid and not lock["granted"] for lock in data["locks"])
            row = next(row for row in data["lock_sessions"] if row["pid"] == blocker_pid)
            assert row["state"] == "idle in transaction"
            with pytest.raises(IntegrationError, match="changed or ended"):
                monitor.control(pg_config, "codester-test-only", row["token"], "cancel")
            assert (
                "Termination requested"
                in monitor.control(pg_config, "codester-test-only", row["token"], "terminate")[
                    "message"
                ]
            )
            thread.join(timeout=5)
            assert not thread.is_alive() and not errors
            assert admin.execute(sql.SQL("SELECT value FROM {}").format(table)).fetchone()[0] == 2
        finally:
            blocker.close()
            if not waiter.closed:
                waiter.cancel()
            waiter.close()
            admin.execute(sql.SQL("DROP TABLE {}").format(table))


def test_real_limited_visibility_and_database_scope(pg_config):
    role_name = "codester_monitor_" + uuid.uuid4().hex
    role = sql.Identifier(role_name)
    with connect(pg_config, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD 'codester-test-only'").format(role))
        try:
            monitor = PostgresMonitor()
            limited = dict(pg_config, username=role_name)
            data = monitor.snapshot(limited, "codester-test-only")
            assert data["hidden_sessions"] >= 1
            assert not data["full_visibility"]
            assert all(not row["token"] for row in data["queries"])
            admin.execute(sql.SQL("GRANT pg_read_all_stats TO {}").format(role))
            data = monitor.snapshot(limited, "codester-test-only")
            assert data["full_visibility"]
            assert data["hidden_sessions"] == 0
            other_database = dict(pg_config, database="template1")
            data = monitor.snapshot(other_database, "codester-test-only")
            assert data["sessions"] == 0
        finally:
            admin.execute(sql.SQL("DROP ROLE {}").format(role))


def test_real_non_superuser_signalling_requires_role(pg_config):
    monitor_name = "codester_reader_" + uuid.uuid4().hex
    app_name = "codester_app_" + uuid.uuid4().hex
    with connect(pg_config, autocommit=True) as admin:
        for name in (monitor_name, app_name):
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD 'codester-test-only'").format(
                    sql.Identifier(name)
                )
            )
        admin.execute(sql.SQL("GRANT pg_read_all_stats TO {}").format(sql.Identifier(monitor_name)))
        worker = connect(dict(pg_config, username=app_name), autocommit=True)
        errors = []

        def run():
            try:
                worker.execute("SELECT pg_sleep(30)")
            except psycopg.errors.QueryCanceled as exc:
                errors.append(exc)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        try:
            monitor = PostgresMonitor()
            config = dict(pg_config, username=monitor_name)
            data = await_snapshot(
                monitor,
                config,
                lambda data: any(row["pid"] == worker.info.backend_pid for row in data["queries"]),
            )
            row = next(row for row in data["queries"] if row["pid"] == worker.info.backend_pid)
            assert row["query"] and row["token"] is None
            admin.execute(
                sql.SQL("GRANT pg_signal_backend TO {}").format(sql.Identifier(monitor_name))
            )
            data = monitor.snapshot(config, "codester-test-only")
            row = next(row for row in data["queries"] if row["pid"] == worker.info.backend_pid)
            assert row["token"]
            monitor.control(config, "codester-test-only", row["token"], "cancel")
            thread.join(timeout=5)
            assert errors and not thread.is_alive()
        finally:
            if thread.is_alive():
                worker.cancel()
                thread.join(timeout=5)
            worker.close()
            for name in (monitor_name, app_name):
                admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(name)))
