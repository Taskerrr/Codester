"""Bounded, on-demand SigNoz log searches, shared across browser tabs."""

import hashlib
import json
import re
import threading
import time

from codester import signoz
from codester.store import ConfigurationError, Store
from codester.transport import IntegrationError

LIMIT = 100
HOME_LIMIT = 6
WINDOW = 900
WINDOWS = {300, 900, 3600, 21600, 86400}
CACHE_LIMIT = 16
ERROR_FILTER = "severity_number >= 17 OR severity_text IN ('ERROR', 'error', 'FATAL', 'fatal', 'CRITICAL', 'critical')"
LEVELS = {"TRACE": 1, "DEBUG": 5, "INFO": 9, "WARN": 13, "ERROR": 17, "FATAL": 21}


def filters_from(data: dict | None) -> dict:
    data = data or {}
    result = {}
    for name, limit in (
        ("app", 200),
        ("user_id", 200),
        ("text", 500),
        ("trace_id", 32),
        ("level", 10),
    ):
        value = data.get(name, "")
        if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
            raise ConfigurationError(f"Invalid log {name} filter (maximum {limit} characters).")
        result[name] = value.strip()
    if result["trace_id"] and not re.fullmatch(r"[a-fA-F0-9]{32}", result["trace_id"]):
        raise ConfigurationError("Trace ID must contain 32 hexadecimal characters.")
    result["trace_id"] = result["trace_id"].lower()
    if result["level"] and result["level"] not in LEVELS:
        raise ConfigurationError("Choose a supported severity level.")
    for name, default in (("seconds", WINDOW), ("offset", 0), ("end_ms", 0), ("limit", LIMIT)):
        value = str(data.get(name, default))
        if not re.fullmatch(r"[0-9]{1,13}", value):
            raise ConfigurationError(f"Invalid log {name}.")
        result[name] = int(value)
    if result["seconds"] not in WINDOWS:
        raise ConfigurationError("Choose a log range between 5 minutes and 24 hours.")
    if result["limit"] not in {HOME_LIMIT, LIMIT}:
        raise ConfigurationError("Choose a supported log result limit.")
    if result["offset"] not in range(0, 1000, LIMIT):
        raise ConfigurationError("Browse up to 1,000 logs; narrow the filters to see more.")
    if result["limit"] == HOME_LIMIT and result["offset"]:
        raise ConfigurationError("The Home log preview only supports the latest results.")
    if result["offset"] and not result["end_ms"]:
        raise ConfigurationError("Older log pages require a fixed end time.")
    if result["end_ms"] and not 946684800000 <= result["end_ms"] <= int(time.time() * 1000) + 60000:
        raise ConfigurationError("Invalid log end time.")
    return result


def expression(mode: str, filters: dict) -> str:
    parts = [f"({ERROR_FILTER})"] if mode == "errors" else []
    for name, field in (("app", "service.name"), ("user_id", "user.id"), ("trace_id", "trace_id")):
        if filters[name]:
            parts.append(f"{field} = {signoz.literal(filters[name])}")
    if filters["text"]:
        parts.append("body CONTAINS " + signoz.literal(filters["text"]))
    if filters["level"]:
        level = filters["level"]
        names = [level, level.lower()]
        if level == "WARN":
            names += ["WARNING", "warning"]
        if level == "FATAL":
            names += ["CRITICAL", "critical"]
        start = LEVELS[level]
        parts.append(
            f"(severity_number >= {start} AND severity_number < {start + 4} OR "
            f"severity_text IN ({', '.join(signoz.literal(name) for name in names)}))"
        )
    return " AND ".join(parts)


def attribute(row: dict, name: str, group: str) -> object:
    if name in row:
        return row[name]
    for prefix in (group, f"{group}_string", f"{group}_number", f"{group}_bool"):
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


def request_fields(row: dict) -> dict[str, str]:
    aliases = {
        "method": ("http.request.method", "http.method"),
        "path": ("url.path", "http.route", "http.target"),
        "status": ("http.response.status_code", "http.status_code"),
    }
    result = {}
    for label, names in aliases.items():
        value = next(
            (
                attribute(row, name, "attributes")
                for name in names
                if attribute(row, name, "attributes") is not None
            ),
            None,
        )
        result[label] = text(value, 240 if label == "path" else 16)
    result["method"] = result["method"].upper()
    return result


def fields(row: dict) -> tuple[dict, bool]:
    """Keep resource/log fields bounded independently of the message preview."""
    result = {}
    budget = 12000
    truncated = False
    for key, value in row.items():
        if key in {"body", "id", "timestamp"}:
            continue
        entries = value.items() if isinstance(value, dict) else [("", value)]
        for child, item in entries:
            name = f"{key}.{child}" if child else key
            rendered = text(item, 1001)
            if len(result) >= 60 or budget < len(name) + len(rendered):
                return result, True
            truncated |= len(rendered) > 1000 or len(name) > 200
            result[name[:200]] = rendered[:1000]
            budget -= len(name) + len(rendered)
    return result, truncated


def fetch_logs(config: dict, key: str, mode: str, filters: dict | None = None) -> list[dict]:
    filters = filters_from(filters)
    results = signoz.query(
        config,
        key,
        [
            {
                "name": "logs",
                "signal": "logs",
                "filter": {"expression": expression(mode, filters)},
                "order": [
                    {"key": {"name": field}, "direction": "desc"} for field in ("timestamp", "id")
                ],
                "limit": filters["limit"],
                "offset": filters["offset"],
            }
        ],
        "raw",
        seconds=filters["seconds"],
        end_ms=filters["end_ms"] or None,
    )
    if not results or any(
        not isinstance(result, dict) or "rows" not in result for result in results
    ):
        raise IntegrationError(
            "SigNoz did not return the expected log rows. Check the v5 Logs API."
        )
    rows = []
    seen = set()
    for result in results:
        for row in signoz.table_rows(result):
            body = text(row.get("body"), 4001)
            trace_id = text(row.get("trace_id", row.get("traceID")), 64)
            trace_id = trace_id.lower() if re.fullmatch(r"[a-fA-F0-9]{32}", trace_id) else ""
            attributes, attributes_truncated = fields(row)
            normalized = {
                "timestamp": text(row.get("timestamp"), 64),
                "app": text(attribute(row, "service.name", "resources"), 200),
                "user_id": text(attribute(row, "user.id", "attributes"), 200),
                "severity": text(row.get("severity_text"), 32),
                "body": body[:4000],
                "truncated": len(body) > 4000,
                "trace_id": trace_id,
                "span_id": text(row.get("span_id", row.get("spanID")), 64),
                "trace_url": signoz.trace_link(
                    {
                        "browser_url": config.get("browser_url", ""),
                        "api_url": config.get("api_url", ""),
                    },
                    trace_id,
                )
                if trace_id and (config.get("browser_url") or config.get("api_url"))
                else "",
                "attributes": attributes,
                "attributes_truncated": attributes_truncated,
                "request": request_fields(row),
            }
            severity = row.get("severity_number")
            if not normalized["severity"] and str(severity).isdigit():
                number = int(str(severity))
                normalized["severity"] = next(
                    (label for label, start in reversed(LEVELS.items()) if number >= start), ""
                )
            identifier = (
                text(row.get("id"), 256)
                or hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()
            )
            if identifier not in seen:
                seen.add(identifier)
                rows.append({"id": identifier, **normalized})
            if len(rows) == filters["limit"]:
                return rows
    return rows


def demo_rows(mode: str, filters: dict, end_ms: int) -> list[dict]:
    trace = "a1b2c3d4e5f60718293a4b5c6d7e8f90"
    rows = [
        dict(
            id="demo-error",
            app="checkout",
            user_id="user-42",
            severity="ERROR",
            body="Payment provider timed out\nTimeoutError: request exceeded 5000ms\n  at checkout/payment.py:84\n  at checkout/handler.py:127",
            trace_id=trace,
            attributes={
                "resources.service.name": "checkout",
                "resources.deployment.environment": "development",
                "attributes.http.request.method": "POST",
                "attributes.url.path": "/api/checkout",
                "attributes.http.response.status_code": "504",
                "attributes.user.id": "user-42",
                "attributes.exception.type": "TimeoutError",
            },
            request={"method": "POST", "path": "/api/checkout", "status": "504"},
        ),
        dict(
            id="demo-info",
            app="web",
            user_id="user-17",
            severity="INFO",
            body="Session started",
            trace_id="",
            attributes={"resources.service.name": "web"},
            request={"method": "", "path": "", "status": ""},
        ),
    ]
    matching = []
    for index, row in enumerate(rows):
        if mode == "errors" and row["severity"] != "ERROR":
            continue
        if any(
            filters[name] and filters[name] != row[name] for name in ("app", "user_id", "trace_id")
        ):
            continue
        if filters["level"] and filters["level"] != row["severity"]:
            continue
        if filters["text"] and filters["text"] not in row["body"]:
            continue
        matching.append(
            {
                **row,
                "timestamp": str(end_ms / 1000 - index * 2),
                "truncated": False,
                "span_id": "1234567890abcdef" if row["trace_id"] else "",
                "trace_url": "",
                "attributes_truncated": False,
            }
        )
    return matching[filters["offset"] : filters["offset"] + filters["limit"]]


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

    def read(self, mode: str, filters: dict | None = None) -> dict:
        if mode not in {"recent", "errors"}:
            raise ConfigurationError("Choose Recent or Errors logs.")
        filters = filters_from(filters)
        cache_key = json.dumps([mode, filters], sort_keys=True)
        with self.lock:
            settings, key, signature = self.identity()
            if signature != self.signature:
                self.cache.clear()
                self.deadlines.clear()
                self.failures.clear()
                self.signature = signature
            end_ms = filters["end_ms"] or int(time.time() * 1000)
            config = settings["signoz"]
            base = dict(
                rows=[],
                status="disabled",
                message="Enable SigNoz in Settings to see logs.",
                last_success=None,
                limit=filters["limit"],
                window_seconds=filters["seconds"],
                mode=mode,
                filters=filters,
                offset=filters["offset"],
                end_ms=end_ms,
                start_ms=end_ms - filters["seconds"] * 1000,
                source_url=(config.get("browser_url") or config.get("api_url") or "").rstrip("/"),
                page_full=False,
            )
            if settings["demo"]:
                return {
                    **base,
                    "status": "demo",
                    "message": "Demo logs",
                    "source_url": "",
                    "last_success": time.time(),
                    "rows": demo_rows(mode, filters, end_ms),
                }
            if not config["enabled"]:
                return base
            if time.monotonic() < self.deadlines.get(cache_key, 0):
                return self.cache[cache_key]
            try:
                rows = fetch_logs(config, key, mode, {**filters, "end_ms": end_ms})
                result = {
                    **base,
                    "rows": rows,
                    "status": "connected",
                    "message": "",
                    "last_success": time.time(),
                    "page_full": len(rows) == filters["limit"],
                }
                self.failures[cache_key] = 0
            except IntegrationError as exc:
                previous = self.cache.get(cache_key, base)
                result = {
                    **previous,
                    "status": "stale" if previous["last_success"] else "error",
                    "message": str(exc),
                }
                self.failures[cache_key] = min(self.failures.get(cache_key, 0) + 1, 4)
            if self.identity()[2] != signature:
                return {
                    **base,
                    "status": "loading",
                    "message": "Connection changed. Refreshing logs…",
                }
            if cache_key not in self.cache and len(self.cache) >= CACHE_LIMIT:
                oldest = next(iter(self.cache))
                self.cache.pop(oldest)
                self.deadlines.pop(oldest, None)
                self.failures.pop(oldest, None)
            self.cache[cache_key] = result
            self.deadlines[cache_key] = time.monotonic() + min(
                5 * 2 ** self.failures[cache_key], 60
            )
            return result
