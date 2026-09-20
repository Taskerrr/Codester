"""Explicitly synthetic, stable fixtures. Never substituted for failed live connections."""

import time


def snapshot(service: str) -> dict:
    now = time.time()
    if service == "postgres":
        running = {"pid": 4101, "username": "app", "application_name": "api", "client": "10.0.0.12", "state": "active", "wait_event_type": "Lock", "wait_event": "transactionid", "query": "UPDATE orders SET status = 'processed' WHERE id = 42", "query_seconds": 24, "transaction_seconds": 24, "token": None}
        blocker = {"pid": 4090, "username": "app", "application_name": "worker", "client": "10.0.0.13", "state": "idle in transaction", "query": "UPDATE orders SET status = 'pending' WHERE id = 42", "query_seconds": 95, "transaction_seconds": 100, "token": None}
        return {"database": "demo", "username": "monitor", "sessions": 12, "active": 1, "idle_transactions": 1, "waiting": 1, "hidden_sessions": 0, "full_visibility": True, "tracking": True, "held_locks": 18, "waiting_locks": 1, "queries": [running, blocker], "blocking": [{"waiting_pid": 4101, "blocking_pid": 4090}], "lock_sessions": [running, blocker], "locks": [{"pid": 4101, "locktype": "transactionid", "mode": "ShareLock", "granted": False, "relation": None}], "query_limit": 50, "wait_limit": 20}
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
                    "inferred_active": True,
                    "status": "Active (inferred)",
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
            "activity_note": "Active is inferred from a local update within the last three minutes.",
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
    if service == "github":
        counts = [0, 1, 0, 3, 2, 0, 0, 1, 4, 2, 0, 1, 0, 0, 2, 1, 5, 3, 0, 0, 1]
        days = []
        for offset in range(181, -1, -1):
            day = time.localtime(now - offset * 86400)
            count = counts[(181 - offset) % len(counts)]
            days.append(
                {
                    "date": time.strftime("%Y-%m-%d", day),
                    "count": count,
                }
            )
        return {
            "login": "taskerrr",
            "total": sum(day["count"] for day in days),
            "days": days,
            "url": "https://github.com/Taskerrr",
            "repositories": [
                {
                    "name": "Taskerrr/Codester",
                    "description": "Touchscreen developer dashboard",
                    "private": False,
                    "pushed_at": now - 420,
                    "commits": [0, 1, 0, 2, 1, 0, 3, 2, 0, 1, 4, 1, 2, 3],
                    "url": "https://github.com/Taskerrr/Codester",
                    "local": {
                        "id": "demo-repository-1",
                        "branch": "main",
                        "changes": 2,
                        "ahead": 1,
                        "behind": 0,
                        "needs_push": True,
                        "deploy_configured": True,
                        "deploy_state": "needed",
                        "action": {"state": "idle", "message": ""},
                        "demo": True,
                    },
                },
                {
                    "name": "Taskerrr/data-platform",
                    "description": "Shared orchestration projects",
                    "private": True,
                    "pushed_at": now - 7400,
                    "commits": [1, 0, 1, 0, 3, 1, 0, 0, 2, 1, 1, 0, 2, 1],
                    "url": "https://github.com/Taskerrr/data-platform",
                    "local": {
                        "id": "demo-repository-2",
                        "branch": "main",
                        "changes": 0,
                        "ahead": 0,
                        "behind": 0,
                        "needs_push": False,
                        "deploy_configured": True,
                        "deploy_state": "current",
                        "action": {"state": "idle", "message": ""},
                        "demo": True,
                    },
                },
                {
                    "name": "Taskerrr/internal-tools",
                    "description": "Small team utilities",
                    "private": True,
                    "pushed_at": now - 86400,
                    "commits": [0, 0, 2, 1, 0, 0, 1, 0, 0, 1, 0, 2, 0, 1],
                    "url": "https://github.com/Taskerrr/internal-tools",
                    "local": {
                        "id": "demo-repository-3",
                        "branch": "develop",
                        "changes": 0,
                        "ahead": 0,
                        "behind": 1,
                        "needs_push": False,
                        "deploy_configured": False,
                        "deploy_state": "unavailable",
                        "action": {"state": "idle", "message": ""},
                        "demo": True,
                    },
                },
            ],
        }
    return {
        "panels": [
            {
                "service": "checkout-api",
                "label": "Total requests",
                "metric": "request_count",
                "value": 154080,
                "unit": "requests",
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
            {"service": "Fuel Reporting", "rate": 18.2, "requests": 65520},
            {"service": "Driver Logbook", "rate": 11.7, "requests": 42120},
            {"service": "Plant Portal", "rate": 7.4, "requests": 26640},
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
        "window_seconds": 3600,
        "window_label": "1 hour",
        "note": "Last hour · incoming SERVER spans · sample data",
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
