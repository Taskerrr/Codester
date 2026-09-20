"""Named SQL connections and bounded, cancellable single-statement execution."""

import json
import re
import sqlite3
import threading
import time
from contextlib import closing

import psycopg
from psycopg import generators
from psycopg.pq import ExecStatus

from codester.postgres import target_key
from codester.store import ConfigurationError, Store, validate
from codester.transport import IntegrationError

ROW_LIMIT = 500
CELL_LIMIT = 4000
RESULT_LIMIT = 2_000_000


def identifier(value: str) -> str:
    if not re.fullmatch(r"[a-f0-9-]{16,64}", value):
        raise ConfigurationError("Invalid SQL connection or request identifier.")
    return value


class SQLWorkspace:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.lock = threading.RLock()
        self.active: dict[str, dict] = {}
        with closing(sqlite3.connect(store.path)) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS sql_connections (id TEXT PRIMARY KEY, value TEXT)"
            )

    def connections(self) -> list[dict]:
        with self.store.lock, closing(sqlite3.connect(self.store.path)) as db:
            rows = [
                json.loads(row[0])
                for row in db.execute("SELECT value FROM sql_connections ORDER BY rowid")
            ]
            saved = {row[0] for row in db.execute("SELECT name FROM secrets")}
            monitor = self.store.read()["postgres"]
        if monitor["database"] and monitor["username"]:
            rows.insert(
                0,
                {
                    **monitor,
                    "id": "monitor",
                    "name": "Monitoring connection",
                    "environment": "unspecified",
                },
            )
        for row in rows:
            row["revision"] = target_key(row)
            row["has_password"] = self.secret_name(row["id"]) in saved
        return rows

    @staticmethod
    def secret_name(key: str) -> str:
        return "postgres" if key == "monitor" else f"sql-password:{key}"

    def resolve(self, key: str) -> tuple[dict, str]:
        with self.store.lock:
            config = next((row for row in self.connections() if row["id"] == key), None)
            if config is None:
                raise ConfigurationError("Choose a saved SQL connection.")
            return config, self.store.secret(self.secret_name(key))

    def save(self, key: str, data: object) -> list[dict]:
        identifier(key)
        if not isinstance(data, dict):
            raise ConfigurationError("Supply a connection configuration.")
        name = data.get("name")
        environment = data.get("environment")
        if (
            not isinstance(name, str)
            or not name.strip()
            or len(name) > 80
            or any(ord(c) < 32 for c in name)
        ):
            raise ConfigurationError("Give the connection a name of up to 80 characters.")
        if environment not in ("development", "production"):
            raise ConfigurationError("Choose development or production.")
        password = data.get("password", "")
        clear = data.get("clear_password", False)
        if (
            not isinstance(password, str)
            or len(password) > 4096
            or "\x00" in password
            or not isinstance(clear, bool)
        ):
            raise ConfigurationError("Invalid SQL password or removal choice.")
        config = self.store.read()
        config["postgres"] = {**data, "enabled": True}
        connection = {
            **validate(config)["postgres"],
            "id": key,
            "name": name.strip(),
            "environment": environment,
        }
        with self.store._secret_transaction() as db:
            current = self.connections()
            if any(
                row["id"] != key and row["name"].casefold() == name.strip().casefold()
                for row in current
            ):
                raise ConfigurationError("Connection names must be different.")
            if len([row for row in current if row["id"] != "monitor"]) >= 20 and not any(
                row["id"] == key for row in current
            ):
                raise ConfigurationError("Save at most 20 SQL connections.")
            db.execute(
                "INSERT OR REPLACE INTO sql_connections VALUES (?, ?)",
                (key, json.dumps(connection)),
            )
            if clear:
                db.execute("DELETE FROM secrets WHERE name=?", (self.secret_name(key),))
            elif password:
                db.execute(
                    "INSERT OR REPLACE INTO secrets VALUES (?, ?)",
                    (self.secret_name(key), self.store.cipher.encrypt(password.encode())),
                )
        return self.connections()

    def delete(self, key: str) -> None:
        identifier(key)
        with self.store._secret_transaction() as db:
            db.execute("DELETE FROM sql_connections WHERE id=?", (key,))
            db.execute("DELETE FROM secrets WHERE name=?", (self.secret_name(key),))

    def cancel(self, request_id: str) -> bool:
        identifier(request_id)
        with self.lock:
            job = self.active.get(request_id)
            if job is None:
                return False
            job["cancelled"] = True
            connection = job["connection"]
            if connection is not None:
                try:
                    connection.cancel_safe(timeout=5)
                except psycopg.Error as exc:
                    raise IntegrationError(
                        "Cancellation could not be confirmed. The query timeout still applies."
                    ) from exc
        return True

    def _expire(self, request_id: str) -> None:
        try:
            self.cancel(request_id)
        except IntegrationError:
            # The server-side statement timeout remains active if cancellation fails.
            pass

    def execute(self, data: object) -> dict:
        if not isinstance(data, dict):
            raise ConfigurationError("Supply a SQL statement.")
        query = data.get("query")
        if not isinstance(query, str) or not query.strip() or len(query) > 20000 or "\x00" in query:
            raise ConfigurationError("Enter one SQL statement of up to 20,000 characters.")
        request_id = data.get("request_id")
        if not isinstance(request_id, str):
            raise ConfigurationError("Supply a query request identifier.")
        identifier(request_id)
        mode = data.get("mode", "read")
        if mode not in ("read", "write") or (mode == "write" and data.get("confirmed") is not True):
            raise ConfigurationError("Confirm the target connection before running in write mode.")
        if self.store.read()["demo"]:
            raise ConfigurationError("Turn off demo mode in Settings before running SQL.")
        config, password = self.resolve(data.get("connection_id", ""))
        if data.get("revision") != config["revision"]:
            raise ConfigurationError(
                "The connection changed. Reopen the SQL workspace before running SQL."
            )
        job = {"connection": None, "cancelled": False}
        with self.lock:
            if self.active:
                raise ConfigurationError("A SQL query is already running. Wait or cancel it first.")
            self.active[request_id] = job
        started = time.monotonic()
        timer = threading.Timer(35, self._expire, args=(request_id,))
        timer.daemon = True
        timer.start()
        try:
            with psycopg.connect(
                host=config["host"],
                port=config["port"],
                dbname=config["database"],
                user=config["username"],
                password=password,
                sslmode=config["sslmode"],
                sslrootcert=config.get("sslrootcert") or None,
                connect_timeout=5,
                application_name="codester-sql",
                autocommit=True,
                options="-c statement_timeout=30000 -c lock_timeout=3000 -c client_encoding=UTF8",
            ) as conn:
                with self.lock:
                    if job["cancelled"]:
                        raise IntegrationError("SQL request cancelled before execution.")
                    job["connection"] = conn
                try:
                    if mode == "read":
                        conn.execute("BEGIN READ ONLY")
                    result = self._results(conn, query, job)
                    if mode == "read":
                        conn.execute("ROLLBACK")
                finally:
                    # A cancelling request cannot race this connection's close.
                    with self.lock:
                        job["connection"] = None
            return {
                **result,
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                "connection_name": config["name"],
                "environment": config["environment"],
            }
        except psycopg.Error as exc:
            messages = {
                "25006": "This statement requires write mode.",
                "57014": "Query cancelled or timed out. Refresh data before retrying a write.",
                "42601": "SQL syntax error. Run one statement at a time.",
                "42501": "The database role does not have permission for this statement.",
                "42P01": "Table or relation not found. Check the database and schema name.",
                "42703": "Column not found. Check the column names.",
                "23505": "The statement violates a unique constraint.",
                "23503": "The statement violates a foreign key constraint.",
                "55P03": "Timed out waiting for a database lock.",
            }
            message = messages.get(
                exc.sqlstate,
                "SQL request failed. Check the connection and statement. If a write was running, verify its outcome before retrying.",
            )
            raise IntegrationError(message) from exc
        finally:
            timer.cancel()
            with self.lock:
                self.active.pop(request_id, None)

    def _results(self, conn: psycopg.Connection, query: str, job: dict) -> dict:
        """Drain single-row protocol results; retain only a bounded textual preview."""
        pg = conn.pgconn
        with self.lock:
            if job["cancelled"]:
                raise IntegrationError("SQL request cancelled before execution.")
            pg.send_query_params(query.encode("utf-8"), None)
            pg.set_single_row_mode()
        conn.wait(generators.send(pg))
        if job["cancelled"]:
            conn.cancel_safe(timeout=5)
        columns: list[str] = []
        rows: list[list[str | None]] = []
        total = 0
        size = 0
        clipped = False
        preview_full = False
        status = ""
        affected = None
        while result := conn.wait(generators.fetch(pg)):
            if result.status == ExecStatus.FATAL_ERROR:
                raise psycopg.errors.error_from_result(result, encoding="utf-8")
            if result.status not in (
                ExecStatus.SINGLE_TUPLE,
                ExecStatus.TUPLES_OK,
                ExecStatus.COMMAND_OK,
            ):
                raise IntegrationError(
                    "COPY and interactive commands are not supported. Run one SQL statement."
                )
            if result.nfields and not columns:
                columns = [
                    (result.fname(i) or b"").decode("utf-8", errors="replace")
                    for i in range(result.nfields)
                ]
            if result.status == ExecStatus.SINGLE_TUPLE:
                total += 1
                if len(rows) >= ROW_LIMIT or preview_full:
                    clipped = True
                    continue
                row: list[str | None] = []
                row_size = 0
                for i in range(result.nfields):
                    value = result.get_value(0, i)
                    text = value.decode("utf-8", errors="replace") if value is not None else None
                    if text is not None and len(text) > CELL_LIMIT:
                        text = text[:CELL_LIMIT] + "…"
                        clipped = True
                    row.append(text)
                    row_size += len(text.encode("utf-8")) if text is not None else 0
                if size + row_size > RESULT_LIMIT:
                    clipped = preview_full = True
                else:
                    rows.append(row)
                    size += row_size
            else:
                status = (result.command_status or b"").decode("utf-8", errors="replace")
                affected = result.command_tuples
        return {
            "columns": columns,
            "rows": rows,
            "row_count": total,
            "affected_rows": affected,
            "status": status,
            "truncated": clipped,
            "row_limit": ROW_LIMIT,
        }
