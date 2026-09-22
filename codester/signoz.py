"""SigNoz v5 trace queries: service discovery, server-span health, recent errors."""

import json
import math
import re
import time
from urllib.parse import quote

from codester.store import METRICS, SIGNOZ_WINDOWS
from codester.transport import IntegrationError, post_json


def literal(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def query(
    config: dict, key: str, specs: list[dict], kind: str = "scalar", seconds: int = 900
) -> list[dict]:
    if not key:
        raise IntegrationError("Add a SigNoz query API key in settings (not an ingestion key).")
    now = int(time.time() * 1000)
    payload = {
        "start": now - seconds * 1000,
        "end": now,
        "requestType": kind,
        "compositeQuery": {
            "queries": [
                {"type": "builder_query", "spec": {"signal": "traces", "disabled": False, **spec}}
                for spec in specs
            ]
        },
    }
    response = post_json(
        config["api_url"] + "/api/v5/query_range", payload, {"SIGNOZ-API-KEY": key}
    )
    data = response.get("data")
    if response.get("status") == "error" or not isinstance(data, dict):
        raise IntegrationError(
            "SigNoz returned an unsupported query response. Requires the v5 query API."
        )
    if data.get("warning") or (isinstance(data.get("data"), dict) and data["data"].get("warning")):
        raise IntegrationError(
            "SigNoz reported incomplete query results. Check the query in SigNoz."
        )
    results = (
        data.get("data", {}).get("results")
        if isinstance(data.get("data"), dict)
        else data.get("results")
    )
    if not isinstance(results, list):
        raise IntegrationError(
            "SigNoz response shape is unsupported. Check the installed v5 API version."
        )
    return results


def table_rows(result: dict) -> list[dict]:
    """Decode native v5 scalar columns/data and raw timestamp/data rows."""
    if "rows" in result:
        rows = result["rows"]
        # SigNoz serializes an empty raw result's row slice as JSON null.
        if rows is None:
            return []
        if not isinstance(rows, list) or any(
            not isinstance(r, dict) or not isinstance(r.get("data"), dict) for r in rows
        ):
            raise IntegrationError("SigNoz returned invalid raw rows.")
        return [{**row["data"], "timestamp": row.get("timestamp", row["data"].get("timestamp"))} for row in rows]
    columns, values = result.get("columns"), result.get("data")
    if not isinstance(columns, list) or not isinstance(values, list):
        raise IntegrationError("SigNoz did not return the expected v5 scalar format.")
    if any(not isinstance(c, dict) or not isinstance(c.get("name"), str) for c in columns):
        raise IntegrationError("SigNoz returned invalid scalar columns.")
    names = [c["name"] for c in columns]
    if any(not isinstance(row, list) or len(row) != len(names) for row in values):
        raise IntegrationError("SigNoz returned invalid scalar rows.")
    return [dict(zip(names, row, strict=True)) for row in values]


def services(config: dict, key: str) -> list[str]:
    results = query(
        config,
        key,
        [
            {
                "name": "services",
                "aggregations": [{"expression": "count()", "alias": "spans"}],
                "groupBy": [{"name": "service.name", "fieldContext": "resource"}],
                "limit": 200,
            }
        ],
        seconds=86400,
    )
    names = set()
    for result in results:
        for row in table_rows(result):
            if isinstance(row.get("service.name"), str):
                names.add(row["service.name"])
    return sorted(names)


def scalar(results: list[dict], name: str) -> float | None:
    for result in results:
        columns = result.get("columns", [])
        selected = [
            i
            for i, col in enumerate(columns)
            if col.get("queryName") == name and col.get("columnType") == "aggregation"
        ]
        if not selected:
            continue
        table_rows(result)  # Validate before indexing; empty data means no observations.
        rows = result["data"]
        if not rows or rows[0][selected[0]] is None:
            return None
        number = float(rows[0][selected[0]])
        return number if math.isfinite(number) else None
    raise IntegrationError("SigNoz omitted a requested measurement.")


def top_apps(config: dict, key: str) -> list[dict]:
    """Count incoming requests per service within the selected window."""
    seconds = config.get("window_seconds", 3600)
    results = query(
        config,
        key,
        [
            {
                "name": "top_apps",
                "filter": {"expression": "kind = 2"},
                "aggregations": [{"expression": "count()", "alias": "requests"}],
                "groupBy": [{"name": "service.name", "fieldContext": "resource"}],
                "order": [{"key": {"name": "requests"}, "direction": "desc"}],
                "limit": 200,
            }
        ],
        seconds=seconds,
    )
    apps = []
    for result in results:
        columns = result.get("columns", [])
        service_column = next(
            (
                column.get("name")
                for column in columns
                if column.get("name") == "service.name" or column.get("columnType") == "group"
            ),
            None,
        )
        requests_column = next(
            (
                column.get("name")
                for column in columns
                if column.get("queryName") == "top_apps"
                and column.get("columnType") == "aggregation"
            ),
            None,
        )
        if not service_column or not requests_column:
            continue
        for row in table_rows(result):
            service = row.get(service_column)
            requests = row.get(requests_column)
            if not isinstance(service, str) or not service:
                continue
            if isinstance(requests, int | float):
                count = float(requests)
            elif isinstance(requests, str) and re.fullmatch(
                r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", requests
            ):
                count = float(requests)
            else:
                continue
            if math.isfinite(count) and count >= 0:
                apps.append({"service": service, "rate": count / seconds, "requests": count})
    return sorted(apps, key=lambda app: app["requests"], reverse=True)[:200]


def trace_link(config: dict, trace_id: str) -> str:
    return (config["browser_url"] or config["api_url"]) + "/trace/" + quote(trace_id, safe="")


def error_rows(config: dict, results: list[dict]) -> list[dict]:
    errors = []
    for result in results:
        for row in table_rows(result):
            trace = row.get("trace_id", row.get("traceID", ""))
            if not isinstance(trace, str) or not trace:
                continue
            errors.append(
                {
                    "id": trace,
                    "title": str(row.get("name", "Failed span"))[:200],
                    "service": str(row.get("service.name", "Unknown service")),
                    "timestamp": row.get("timestamp"),
                    "status": "Error",
                    "text": json.dumps(row, indent=2, ensure_ascii=False)[:32000],
                    "url": trace_link(config, trace),
                }
            )
    return errors[:8]


def raw_spec(expression: str, limit: int) -> dict:
    return {
        "name": "errors",
        "filter": {"expression": expression},
        "limit": limit,
        "order": [{"key": {"name": "timestamp"}, "direction": "desc"}],
        "selectFields": [
            {"name": name, "fieldContext": context}
            for name, context in [
                ("service.name", "resource"),
                ("name", "span"),
                ("trace_id", "span"),
                ("span_id", "span"),
                ("timestamp", "span"),
                ("duration_nano", "span"),
            ]
        ],
    }


def snapshot(config: dict, key: str) -> dict:
    seconds = config.get("window_seconds", 3600)
    specs = []
    for index, panel in enumerate(config["panels"]):
        condition = "kind = 2"  # SERVER spans: one incoming request per instrumented service.
        if panel["service"]:
            condition += " AND service.name = " + literal(panel["service"])
        name = f"p{index}"
        expression = "p95(duration_nano)" if panel["metric"] == "p95" else "count()"
        specs.append(
            {
                "name": name,
                "filter": {"expression": condition},
                "aggregations": [{"expression": expression, "alias": "value"}],
            }
        )
        if panel["metric"] == "error_rate":
            specs.append(
                {
                    "name": name + "errors",
                    "filter": {"expression": condition + " AND has_error = true"},
                    "aggregations": [{"expression": "count()", "alias": "value"}],
                }
            )
    results = query(config, key, specs, seconds=seconds) if specs else []
    panels = []
    for index, panel in enumerate(config["panels"]):
        value = scalar(results, f"p{index}")
        metric = panel["metric"]
        if value is not None:
            if metric == "request_rate":
                value /= seconds
            elif metric == "p95":
                value /= 1_000_000
            elif metric == "error_rate":
                errors = scalar(results, f"p{index}errors")
                value = errors / value * 100 if value and errors is not None else None
        panels.append(
            {
                **panel,
                "label": METRICS[metric],
                "value": value,
                "unit": {
                    "p95": "ms",
                    "request_rate": "req/s",
                    "request_count": "requests",
                    "error_rate": "%",
                }[metric],
            }
        )
    condition = "has_error = true"
    if config["error_service"]:
        condition += " AND service.name = " + literal(config["error_service"])
    apps_message = ""
    try:
        apps = top_apps(config, key)
    except IntegrationError:
        apps = []
        apps_message = "Request totals unavailable for this SigNoz version."
    errors = error_rows(
        config, query(config, key, [raw_spec(condition, 8)], "raw", seconds=seconds)
    )
    return {
        "panels": panels,
        "top_apps": apps,
        "top_apps_message": apps_message,
        "errors": errors,
        "window_seconds": seconds,
        "window_label": SIGNOZ_WINDOWS[seconds],
        "note": f"Last {SIGNOZ_WINDOWS[seconds]} · incoming SERVER spans · sampled traces may undercount requests",
    }


def detail(config: dict, key: str, trace_id: str) -> dict:
    results = query(
        config, key, [raw_spec("trace_id = " + literal(trace_id), 30)], "raw", seconds=86400
    )
    rows = [row for result in results for row in table_rows(result)]
    return {
        "title": "Trace " + trace_id,
        "text": json.dumps(rows, indent=2, ensure_ascii=False)[:32000],
        "note": "Up to 30 spans from the last 24 hours. Open SigNoz for full trace and exception details.",
        "url": trace_link(config, trace_id),
    }
