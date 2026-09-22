"""Bounded, on-demand SigNoz log reads, shared across browser tabs."""

import hashlib
import json
import threading
import time

from codester import signoz
from codester.store import ConfigurationError, Store
from codester.transport import IntegrationError

LIMIT = 100
WINDOW = 900
ERROR_FILTER = "severity_number >= 17 OR severity_text IN ('ERROR', 'error', 'FATAL', 'fatal', 'CRITICAL', 'critical')"


def attribute(row: dict, name: str, group: str) -> object:
    if name in row:
        return row[name]
    for prefix in (group, f"{group}_string", f"{group}_number"):
        if f"{prefix}.{name}" in row:
            return row[f"{prefix}.{name}"]
        nested = row.get(prefix)
        if isinstance(nested, dict) and name in nested:
            return nested[name]
    return None


def text(value: object, limit: int) -> str:
    if value is None:
        return ""
    rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return rendered[:limit]


def fetch_logs(config: dict, key: str, mode: str) -> list[dict]:
    results = signoz.query(config, key, [{
        "name": "logs",
        "signal": "logs",
        "filter": {"expression": ERROR_FILTER if mode == "errors" else ""},
        "order": [{"key": {"name": field}, "direction": "desc"} for field in ("timestamp", "id")],
        "limit": LIMIT,
        "offset": 0,
    }], "raw", seconds=WINDOW)
    if not results or any(not isinstance(result, dict) or "rows" not in result for result in results):
        raise IntegrationError("SigNoz did not return the expected log rows. Check the v5 Logs API.")
    rows = []
    seen = set()
    for result in results:
        for row in signoz.table_rows(result):
            body = text(row.get("body"), 4001)
            normalized = {
                "timestamp": text(row.get("timestamp"), 64),
                "app": text(attribute(row, "service.name", "resources"), 200),
                "user_id": text(attribute(row, "user.id", "attributes"), 200),
                "severity": text(row.get("severity_text"), 32),
                "body": body[:4000],
                "truncated": len(body) > 4000,
            }
            severity = row.get("severity_number")
            if not normalized["severity"] and str(severity).isdigit():
                number = int(str(severity))
                normalized["severity"] = next((label for start, label in
                    ((21, "FATAL"), (17, "ERROR"), (13, "WARN"), (9, "INFO"), (5, "DEBUG"), (1, "TRACE"))
                    if number >= start), "")
            identifier = text(row.get("id"), 256) or hashlib.sha256(
                json.dumps(normalized, sort_keys=True).encode()
            ).hexdigest()
            if identifier in seen:
                continue
            seen.add(identifier)
            rows.append({"id": identifier, **normalized})
            if len(rows) == LIMIT:
                return rows
    return rows


class LogFeed:
    def __init__(self, store: Store):
        self.store = store
        self.lock = threading.Lock()
        self.signature: tuple | None = None
        self.cache: dict[str, dict] = {}
        self.deadlines: dict[str, float] = {}
        self.failures: dict[str, int] = {}

    def identity(self) -> tuple[dict, str, tuple]:
        settings = self.store.read()
        config = settings["signoz"]
        key = self.store.secret("signoz") if not settings["demo"] and config["enabled"] else ""
        return settings, key, (settings["demo"], json.dumps(config, sort_keys=True), key)

    def read(self, mode: str) -> dict:
        if mode not in {"recent", "errors"}:
            raise ConfigurationError("Choose Recent or Errors logs.")
        with self.lock:
            settings, key, signature = self.identity()
            if signature != self.signature:
                self.cache.clear()
                self.deadlines.clear()
                self.failures.clear()
                self.signature = signature
            base = dict(rows=[], status="disabled", message="Enable SigNoz in Settings to see logs.",
                        last_success=None, limit=LIMIT, window_seconds=WINDOW, mode=mode)
            if settings["demo"]:
                return {**base, "status": "demo", "message": "Demo logs", "last_success": time.time(), "rows": [
                    dict(id="demo-error", timestamp=str(time.time()), app="checkout", user_id="user-42",
                         severity="ERROR", body="Payment provider timed out", truncated=False),
                    *([] if mode == "errors" else [dict(id="demo-info", timestamp=str(time.time() - 2),
                         app="web", user_id="user-17", severity="INFO", body="Session started", truncated=False)]),
                ]}
            if not settings["signoz"]["enabled"]:
                return base
            if time.monotonic() < self.deadlines.get(mode, 0):
                return self.cache[mode]
            try:
                rows = fetch_logs(settings["signoz"], key, mode)
                result = {**base, "rows": rows, "status": "connected", "message": "", "last_success": time.time()}
                self.failures[mode] = 0
            except IntegrationError as exc:
                previous = self.cache.get(mode, base)
                result = {**previous, "status": "stale" if previous["last_success"] else "error", "message": str(exc)}
                self.failures[mode] = min(self.failures.get(mode, 0) + 1, 4)
            if self.identity()[2] != signature:
                return {**base, "status": "loading", "message": "Connection changed. Refreshing logs…"}
            self.cache[mode] = result
            self.deadlines[mode] = time.monotonic() + min(5 * 2 ** self.failures[mode], 60)
            return result
