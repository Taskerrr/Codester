"""Read-only Dagster GraphQL integration."""

import time
from urllib.parse import quote

from codester.transport import IntegrationError, post_json

RUN_FIELDS = "runId jobName status startTime endTime creationTime"


def graphql(config: dict, query: str, variables: dict | None = None) -> dict:
    base = config["api_url"].rstrip("/")
    url = base if base.endswith("/graphql") else base + "/graphql"
    result = post_json(url, {"query": query, "variables": variables or {}})
    if result.get("errors") or not isinstance(result.get("data"), dict):
        raise IntegrationError(
            "Dagster GraphQL schema rejected the query. Check the installed version."
        )
    return result["data"]


def run_link(config: dict, run_id: str) -> str:
    base = (config["browser_url"] or config["api_url"]).removesuffix("/graphql")
    return base + "/runs/" + quote(run_id, safe="")


def snapshot(config: dict) -> dict:
    # Runs.count gives an exact total even though the displayed rows are bounded.
    query = (
        "query {"
        + " ".join(
            f"{alias}: runsOrError(filter: {{statuses: [{statuses}]}}, limit: 12) "
            f"{{ __typename ... on Runs {{ count results {{ {RUN_FIELDS} }} }} }}"
            for alias, statuses in [
                ("queued", "QUEUED"),
                ("running", "STARTING, STARTED, CANCELING"),
                ("failed", "FAILURE"),
                ("recent", "SUCCESS, FAILURE, CANCELED"),
            ]
        )
        + "}"
    )
    data = graphql(config, query)
    for name in ("queued", "running", "failed", "recent"):
        if data.get(name, {}).get("__typename") != "Runs":
            raise IntegrationError(
                "Dagster could not return runs. Check deployment health and permissions."
            )
    now = time.time()
    oldest = None
    # Follow bounded pages to find the oldest queued run without assuming newest twelve is all.
    rows = list(data["queued"]["results"])
    total = data["queued"]["count"]
    pages = 0
    while len(rows) < total and pages < 2 and rows:
        page = graphql(
            config,
            "query($cursor: String!) { runsOrError(filter: {statuses: [QUEUED]}, "
            "cursor: $cursor, limit: 100) { ... on Runs { results { " + RUN_FIELDS + " } } } }",
            {"cursor": rows[-1]["runId"]},
        )
        more = page.get("runsOrError", {}).get("results", [])
        if not more:
            break
        rows.extend(more)
        pages += 1
    if total and len(rows) >= total:
        oldest = max(0, now - min(row["creationTime"] for row in rows))

    def normalize(row: dict) -> dict:
        started = row.get("startTime") or row["creationTime"]
        return {
            "id": row["runId"],
            "title": row["jobName"],
            "status": row["status"],
            "timestamp": row.get("endTime") or row.get("startTime") or row["creationTime"],
            "duration": max(0, (row.get("endTime") or now) - started),
            "url": run_link(config, row["runId"]),
        }

    return {
        "queued": total,
        "running": data["running"]["count"],
        "failed": data["failed"]["count"],
        "oldest": oldest,
        "queue": [normalize(r) for r in data["queued"]["results"]],
        "jobs": [
            normalize(r)
            for r in (
                data["running"]["results"]
                + data["queued"]["results"]
                + data["recent"]["results"]
            )
        ],
        "errors": [normalize(r) for r in data["failed"]["results"]],
    }


def detail(config: dict, run_id: str) -> dict:
    result = graphql(
        config,
        """query($id: ID!) {
      logsForRun(runId: $id, limit: 100) {
        __typename
        ... on EventConnection { events {
          __typename ... on MessageEvent { message timestamp }
          ... on ExecutionStepFailureEvent { error { message stack } }
          ... on RunFailureEvent { error { message stack } }
        } }
      }
    }""",
        {"id": run_id},
    )
    connection = result.get("logsForRun", {})
    if connection.get("__typename") != "EventConnection":
        raise IntegrationError(
            "Run logs are unavailable or this Dagster version uses a different schema."
        )
    events = connection.get("events", [])
    failures = [e for e in events if "Failure" in e.get("__typename", "")]
    text = "\n\n".join(
        e.get("error", {}).get("message", e.get("message", ""))
        + "\n"
        + "".join(e.get("error", {}).get("stack", []))
        for e in failures
        if e.get("error")
    )
    if not text:
        text = "\n".join(e.get("message", "") for e in events)
    return {
        "title": "Run " + run_id,
        "text": text[:32000] or "No events returned.",
        "note": "Showing up to the first 100 events. Open Dagster for the complete run logs.",
        "url": run_link(config, run_id),
    }
