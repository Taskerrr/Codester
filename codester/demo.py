"""Explicitly synthetic, stable fixtures. Never substituted for failed live connections."""

import time


def snapshot(service: str) -> dict:
    now = time.time()
    if service == "codex":
        return {
            "plan": "Demo account",
            "windows": [
                {"used": 28, "minutes": 300, "resets": now + 9360},
                {"used": 46, "minutes": 10080, "resets": now + 223200},
            ],
            "note": "Illustrative subscription usage",
            "tasks": [
                {
                    "id": "demo-task-1",
                    "title": "Add incremental sync to the customer pipeline",
                    "project": "data-platform",
                    "timestamp": now - 84,
                    "status": "Recent activity",
                },
                {
                    "id": "demo-task-2",
                    "title": "Review retry behavior for webhook delivery",
                    "project": "api",
                    "timestamp": now - 840,
                    "status": "Recent activity",
                },
                {
                    "id": "demo-task-3",
                    "title": "Build the Codester touchscreen dashboard",
                    "project": "codester",
                    "timestamp": now - 2640,
                    "status": "Recent activity",
                },
            ],
            "activity_note": "Recent activity is not a confirmed running state.",
        }
    if service == "dagster":
        return {
            "queued": 4,
            "running": 2,
            "failed": 2,
            "oldest": 192,
            "queue": [
                {"id": f"q{i}", "title": name, "status": "QUEUED", "timestamp": now - 192 + i * 20}
                for i, name in enumerate(
                    [
                        "warehouse_daily_refresh",
                        "customer_segments",
                        "invoice_rollup",
                        "search_index_sync",
                    ]
                )
            ],
            "jobs": [
                {"id": "r1", "title": "sync_customer_events", "status": "STARTED", "duration": 322},
                {
                    "id": "r2",
                    "title": "materialize_revenue_model",
                    "status": "STARTED",
                    "duration": 98,
                },
                {
                    "id": "r3",
                    "title": "daily_data_cleanup",
                    "status": "STARTED",
                    "duration": 41,
                },
            ],
            "errors": [
                {
                    "id": "demo-dagster-1",
                    "title": "refresh_product_catalog",
                    "status": "FAILURE",
                    "timestamp": now - 480,
                },
                {
                    "id": "demo-dagster-2",
                    "title": "load_supplier_inventory",
                    "status": "FAILURE",
                    "timestamp": now - 2640,
                },
            ],
        }
    return {
        "panels": [
            {
                "service": "checkout-api",
                "label": "Request rate",
                "metric": "request_rate",
                "value": 42.8,
                "unit": "req/s",
            },
            {
                "service": "checkout-api",
                "label": "Error rate",
                "metric": "error_rate",
                "value": 1.24,
                "unit": "%",
            },
            {
                "service": "worker",
                "label": "p95 latency",
                "metric": "p95",
                "value": 186,
                "unit": "ms",
            },
        ],
        "top_apps": [
            {"service": "Fuel Reporting", "rate": 18.2},
            {"service": "Driver Logbook", "rate": 11.7},
            {"service": "Plant Portal", "rate": 7.4},
        ],
        "top_apps_message": "",
        "errors": [
            {
                "id": "demo-signoz-1",
                "title": "POST /v1/checkout · payment provider timeout",
                "service": "checkout-api",
                "timestamp": now - 120,
                "status": "Error",
            },
            {
                "id": "demo-signoz-2",
                "title": "Inventory refresh exceeded retry limit",
                "service": "worker",
                "timestamp": now - 540,
                "status": "Error",
            },
        ],
        "note": "Last 15 minutes · incoming SERVER spans · sample data",
    }


def detail(service: str, identifier: str) -> dict:
    return {
        "title": "Payment provider timeout"
        if service == "signoz"
        else "Product catalog refresh failed",
        "text": "DEMO DATA\n\nTimeoutError: upstream service did not respond within 30 seconds\n\n"
        '  File "pipeline/catalog.py", line 84, in refresh_catalog\n'
        "    records = client.fetch_catalog(updated_since=cursor)\n"
        '  File "clients/supplier.py", line 42, in fetch_catalog\n'
        '    raise TimeoutError("upstream service did not respond within 30 seconds")\n\n'
        f"Reference: {identifier}\nNext step: inspect upstream availability and retry history.",
        "note": "Synthetic example. Live errors include a link to their source service.",
        "url": "",
    }
