"""Bounded PostgreSQL activity reads and explicit, identity-checked session signals."""

import hashlib
import json
import secrets
from contextlib import contextmanager

import psycopg
from itsdangerous import BadSignature, URLSafeTimedSerializer
from psycopg.rows import dict_row

from codester.transport import IntegrationError

ROW_LIMIT = 50
WAIT_LIMIT = 20

ACTIVITY_FIELDS = """
    a.pid, a.usename AS username, a.application_name, a.client_addr::text AS client,
    a.state, a.wait_event_type, a.wait_event,
    a.backend_start::text, a.query_start::text, a.xact_start::text,
    md5(a.query) AS query_hash, left(a.query, 4000) AS query,
    extract(epoch FROM clock_timestamp() - a.query_start)::float8 AS query_seconds,
    extract(epoch FROM clock_timestamp() - a.xact_start)::float8 AS transaction_seconds,
    a.datname = current_database() AS in_database,
    (a.backend_type = 'client backend' AND a.pid <> pg_backend_pid()
      AND (SELECT rolsuper FROM pg_roles WHERE rolname = current_user)
      OR a.backend_type = 'client backend' AND a.pid <> pg_backend_pid()
      AND NOT coalesce((SELECT rolsuper FROM pg_roles WHERE oid = a.usesysid), true)
      AND (pg_has_role(a.usesysid, 'USAGE') OR pg_has_role('pg_signal_backend', 'USAGE'))
    ) AS can_signal
"""


def target_key(config: dict) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


def safe_error(exc: psycopg.Error) -> IntegrationError:
    messages = {
        "28P01": "PostgreSQL rejected the username or password.",
        "28000": "PostgreSQL rejected this connection's authentication settings.",
        "3D000": "The PostgreSQL database does not exist.",
        "42501": "PostgreSQL denied permission. Check monitoring or session-control privileges.",
        "57014": "The PostgreSQL monitoring request timed out.",
    }
    return IntegrationError(
        messages.get(
            exc.sqlstate,
            "PostgreSQL request failed. Check the host, port, database, TLS settings and any SSH tunnel.",
        )
    )


@contextmanager
def connection(config: dict, password: str, *, readonly: bool = True):
    if not config["database"] or not config["username"]:
        raise IntegrationError("Enter the PostgreSQL database and username in Settings first.")
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
            application_name="codester-monitor",
            options=f"-c statement_timeout=4000 -c lock_timeout=1000 -c search_path=pg_catalog -c timezone=UTC -c default_transaction_read_only={'on' if readonly else 'off'}",
            autocommit=True,
            row_factory=dict_row,
        ) as conn:
            yield conn
    except psycopg.Error as exc:
        raise safe_error(exc) from exc


class PostgresMonitor:
    def __init__(self):
        self.signer = URLSafeTimedSerializer(secrets.token_urlsafe(32), salt="postgres-session")

    def _row(self, row: dict, config: dict) -> dict:
        row = dict(row)
        row["token"] = None
        if row.get("can_signal") and row.get("in_database") and row.get("backend_start"):
            payload = {
                key: row[key]
                for key in (
                    "pid",
                    "backend_start",
                    "query_start",
                    "xact_start",
                    "query_hash",
                    "state",
                )
            }
            payload["target"] = target_key(config)
            row["token"] = self.signer.dumps(payload)
        return row

    def snapshot(self, config: dict, password: str) -> dict:
        with connection(config, password) as conn:
            counts = conn.execute("""
                SELECT count(*)::int AS sessions,
                  count(*) FILTER (WHERE state = 'active')::int AS active,
                  count(*) FILTER (WHERE state IN ('idle in transaction', 'idle in transaction (aborted)'))::int AS idle_transactions,
                  count(*) FILTER (WHERE wait_event_type = 'Lock')::int AS waiting,
                  count(*) FILTER (WHERE state IS NULL)::int AS hidden_sessions
                FROM pg_stat_activity WHERE datname = current_database()
                  AND (backend_type = 'client backend' OR backend_type IS NULL) AND pid <> pg_backend_pid()
            """).fetchone()
            metadata = conn.execute("""
                SELECT current_database() AS database, current_user AS username,
                  pg_has_role('pg_read_all_stats', 'USAGE') AS full_visibility,
                  current_setting('track_activities')::boolean AS tracking
            """).fetchone()
            queries = conn.execute(
                f"""
                SELECT {ACTIVITY_FIELDS} FROM pg_stat_activity a
                WHERE a.datname = current_database() AND a.pid <> pg_backend_pid()
                  AND (a.backend_type = 'client backend' OR a.backend_type IS NULL)
                  AND (a.state = 'active' OR a.state IN ('idle in transaction', 'idle in transaction (aborted)'))
                ORDER BY a.query_start NULLS LAST LIMIT %s
            """,
                (ROW_LIMIT,),
            ).fetchall()
            # Only inspect lock-manager blockers for a capped set of actual lock waiters.
            edges = conn.execute(
                """
                WITH waiters AS MATERIALIZED (
                  SELECT pid FROM pg_stat_activity WHERE datname = current_database()
                    AND pid <> pg_backend_pid() AND wait_event_type = 'Lock'
                  ORDER BY query_start LIMIT %s
                ) SELECT DISTINCT w.pid AS waiting_pid, unnest(pg_blocking_pids(w.pid)) AS blocking_pid
                  FROM waiters w LIMIT 100
            """,
                (WAIT_LIMIT,),
            ).fetchall()
            pids = list({pid for edge in edges for pid in edge.values() if pid > 0})
            sessions = (
                conn.execute(
                    f"SELECT {ACTIVITY_FIELDS} FROM pg_stat_activity a WHERE pid = ANY(%s)", (pids,)
                ).fetchall()
                if pids
                else []
            )
            lock_rows = (
                conn.execute(
                    """
                SELECT l.pid, l.locktype, l.mode, l.granted,
                  CASE WHEN l.database = (SELECT oid FROM pg_database WHERE datname = current_database())
                    THEN c.relname ELSE NULL END AS relation
                FROM pg_locks l LEFT JOIN pg_class c ON c.oid = l.relation
                WHERE l.pid = ANY(%s) AND NOT l.granted LIMIT 50
            """,
                    (pids,),
                ).fetchall()
                if pids
                else []
            )
            locks = conn.execute("""
                SELECT count(*) FILTER (WHERE l.granted)::int AS held_locks,
                       count(*) FILTER (WHERE NOT l.granted)::int AS waiting_locks
                FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid
                WHERE a.datname = current_database() AND a.pid <> pg_backend_pid()
                  AND (a.backend_type = 'client backend' OR a.backend_type IS NULL)
            """).fetchone()
        return {
            **counts,
            **metadata,
            **locks,
            "queries": [self._row(row, config) for row in queries],
            "blocking": edges,
            "lock_sessions": [self._row(row, config) for row in sessions],
            "locks": lock_rows,
            "query_limit": ROW_LIMIT,
            "wait_limit": WAIT_LIMIT,
        }

    def control(self, config: dict, password: str, token: str, action: str) -> dict:
        if action not in {"cancel", "terminate"}:
            raise IntegrationError("Unknown PostgreSQL action.")
        try:
            identity = self.signer.loads(token, max_age=90)
        except BadSignature as exc:
            raise IntegrationError(
                "This activity reading expired. Refresh before trying again."
            ) from exc
        if identity.get("target") != target_key(config):
            raise IntegrationError(
                "The PostgreSQL connection changed. Refresh before trying again."
            )
        function = "pg_cancel_backend" if action == "cancel" else "pg_terminate_backend"
        with connection(config, password, readonly=False) as conn:
            result = conn.execute(
                f"""
                SELECT {function}(a.pid) AS sent FROM pg_stat_activity a
                WHERE a.pid = %s AND a.pid <> pg_backend_pid()
                  AND a.backend_type = 'client backend' AND a.datname = current_database()
                  AND a.backend_start = %s::timestamptz
                  AND a.query_start IS NOT DISTINCT FROM %s::timestamptz
                  AND a.xact_start IS NOT DISTINCT FROM %s::timestamptz
                  AND md5(a.query) IS NOT DISTINCT FROM %s
                  AND a.state IS NOT DISTINCT FROM %s
                  AND (%s = 'terminate' OR a.state = 'active')
            """,
                (
                    identity["pid"],
                    identity["backend_start"],
                    identity["query_start"],
                    identity["xact_start"],
                    identity["query_hash"],
                    identity["state"],
                    action,
                ),
            ).fetchone()
        if result is None:
            raise IntegrationError(
                "That query or session has changed or ended. Refresh before trying again."
            )
        if not result["sent"]:
            raise IntegrationError(
                "PostgreSQL could not send the signal. Refresh the session list."
            )
        return {
            "message": f"{'Cancel' if action == 'cancel' else 'Termination'} requested for PID {identity['pid']}. Refreshing activity."
        }
