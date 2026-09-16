import json
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, datetime

import httpx
import pytest

from codester import codex, dagster, github, signoz
from codester.transport import IntegrationError, post_json

CONFIG = {
    "api_url": "http://host.docker.internal:8000",
    "browser_url": "http://localhost:8000",
    "panels": [
        {"service": "customer's-api", "metric": m} for m in ["request_rate", "error_rate", "p95"]
    ],
    "error_service": "api",
}


def scalar_result(name, value):
    return {
        "columns": [
            {
                "name": "count()",
                "columnType": "aggregation",
                "queryName": name,
                "aggregationIndex": 0,
            }
        ],
        "data": [[value]],
    }


def test_github_activity_and_repository_sparklines(monkeypatch):
    monkeypatch.setattr(
        github,
        "post_json",
        lambda url, payload, headers: {
            "data": {
                "viewer": {
                    "login": "jack",
                    "contributionsCollection": {
                        "contributionCalendar": {
                            "totalContributions": 3,
                            "weeks": [
                                {
                                    "contributionDays": [
                                        {"date": "2026-09-14", "contributionCount": 1},
                                        {"date": "2026-09-15", "contributionCount": 2},
                                    ]
                                }
                            ],
                        }
                    },
                }
            }
        },
    )
    calls = []

    def get(url, headers, params, **kwargs):
        calls.append((url, params))
        if url.endswith("/user/repos"):
            return [
                {
                    "full_name": "jack/codester",
                    "private": True,
                    "description": "Dashboard",
                    "pushed_at": "2026-09-15T10:00:00Z",
                }
            ]
        return [{"commit": {"author": {"date": datetime.now(UTC).isoformat()}}}]

    monkeypatch.setattr(github, "get_json", get)
    result = github.snapshot(
        {"api_url": "https://api.github.com", "browser_url": "https://github.com"},
        "secret",
    )
    assert result["login"] == "jack"
    assert result["total"] == 3
    assert result["repositories"][0]["name"] == "jack/codester"
    assert sum(result["repositories"][0]["commits"]) == 1
    assert result["repositories"][0]["url"] == "https://github.com/jack/codester"
    assert len(calls) == 2


def test_github_requires_token_and_rejects_graphql_errors(monkeypatch):
    with pytest.raises(IntegrationError, match="token"):
        github.snapshot({"api_url": "https://api.github.com"}, "")
    monkeypatch.setattr(github, "post_json", lambda *args: {"errors": [{"message": "no"}]})
    with pytest.raises(IntegrationError, match="contribution history"):
        github.snapshot({"api_url": "https://api.github.com"}, "secret")


def test_github_uses_visible_repository_commits_when_private_calendar_is_empty(monkeypatch):
    today = datetime.now(UTC).date().isoformat()
    monkeypatch.setattr(
        github,
        "post_json",
        lambda *args: {
            "data": {
                "viewer": {
                    "login": "jack",
                    "contributionsCollection": {
                        "contributionCalendar": {
                            "totalContributions": 0,
                            "weeks": [
                                {
                                    "contributionDays": [
                                        {"date": today, "contributionCount": 0}
                                    ]
                                }
                            ],
                        }
                    },
                }
            }
        },
    )

    def get(url, headers, params, **kwargs):
        if url.endswith("/user/repos"):
            return [{"full_name": "jack/private", "private": True}]
        return [{"commit": {"author": {"date": f"{today}T12:00:00Z"}}}]

    monkeypatch.setattr(github, "get_json", get)
    result = github.snapshot(
        {"api_url": "https://api.github.com", "browser_url": "https://github.com"},
        "secret",
    )

    assert result["total"] == 1
    assert result["days"] == [{"date": today, "count": 1}]
    assert result["calendar_source"] == "repository_commits"
    assert result["calendar_repository_count"] == 1
    assert result["calendar_limited"] is False


def test_signoz_v5_values_filters_and_units(monkeypatch):
    requests = []

    def post(url, payload, headers):
        requests.append(payload)
        assert headers == {"SIGNOZ-API-KEY": "secret"}
        if payload["requestType"] == "raw":
            results = [
                {
                    "queryName": "errors",
                    "rows": [
                        {
                            "timestamp": "2026-09-13T12:00:00Z",
                            "data": {
                                "trace_id": "abc123",
                                "name": "POST /checkout",
                                "service.name": "api",
                            },
                        }
                    ],
                }
            ]
        elif payload["compositeQuery"]["queries"][0]["spec"]["name"] == "top_apps":
            results = [
                {
                    "columns": [
                        {"name": "service.name", "columnType": "group", "queryName": "top_apps"},
                        {"name": "count()", "columnType": "aggregation", "queryName": "top_apps"},
                    ],
                    "data": [["checkout", 600], ["worker", 300]],
                }
            ]
        else:
            results = [
                scalar_result("p0", 900),
                scalar_result("p1", 200),
                scalar_result("p1errors", 4),
                scalar_result("p2", 123_000_000),
            ]
        return {"data": {"type": payload["requestType"], "data": {"results": results}}}

    monkeypatch.setattr(signoz, "post_json", post)
    result = signoz.snapshot(CONFIG, "secret")
    assert [p["value"] for p in result["panels"]] == [1, 2, 123]
    assert result["top_apps"] == [
        {"service": "checkout", "rate": 2},
        {"service": "worker", "rate": 1},
    ]
    assert result["errors"][0]["url"] == "http://localhost:8000/trace/abc123"
    assert (
        "customer\\'s-api"
        in requests[0]["compositeQuery"]["queries"][0]["spec"]["filter"]["expression"]
    )
    assert (
        "has_error = true"
        in requests[2]["compositeQuery"]["queries"][0]["spec"]["filter"]["expression"]
    )
    assert requests[0]["end"] - requests[0]["start"] == 900000
    assert requests[1]["end"] - requests[1]["start"] == 300000


def test_signoz_service_discovery(monkeypatch):
    monkeypatch.setattr(
        signoz,
        "post_json",
        lambda *args: {
            "data": {
                "type": "scalar",
                "data": {
                    "results": [
                        {
                            "columns": [
                                {
                                    "name": "service.name",
                                    "columnType": "group",
                                    "queryName": "services",
                                },
                                {
                                    "name": "count()",
                                    "columnType": "aggregation",
                                    "queryName": "services",
                                },
                            ],
                            "data": [["worker", 5], ["api", 2]],
                        }
                    ]
                },
            }
        },
    )
    assert signoz.services(CONFIG, "key") == ["api", "worker"]


def test_signoz_missing_values_never_become_zero():
    assert signoz.scalar([scalar_result("A", None)], "A") is None
    assert signoz.scalar([scalar_result("A", "NaN")], "A") is None
    with pytest.raises(IntegrationError):
        signoz.scalar([], "missing")
    with pytest.raises(IntegrationError):
        signoz.table_rows({"data": [["mismatch"]], "columns": []})


@pytest.mark.parametrize("rows", [None, []])
def test_signoz_empty_raw_results_are_not_connection_failures(rows):
    result = {"queryName": "errors", "nextCursor": "", "rows": rows}
    assert signoz.table_rows(result) == []
    assert signoz.error_rows(CONFIG, [result]) == []


@pytest.mark.parametrize("rows", [{}, "invalid", [None], [{"data": None}]])
def test_signoz_malformed_raw_results_still_fail(rows):
    with pytest.raises(IntegrationError, match="invalid raw rows"):
        signoz.table_rows({"rows": rows})


def test_signoz_requires_query_key():
    with pytest.raises(IntegrationError, match="not an ingestion key"):
        signoz.query(CONFIG, "", [])


def test_dagster_counts_queue_pagination_and_browser_link(monkeypatch):
    now = time.time()

    def row(identifier, created, status="QUEUED"):
        return dict(
            runId=identifier,
            jobName="a_job",
            status=status,
            startTime=None,
            endTime=None,
            creationTime=created,
        )

    calls = []

    def gql(config, query, variables=None):
        calls.append(query)
        assert "mutation" not in query
        if variables:
            return {"runsOrError": {"results": [row("old", now - 300)]}}
        completed = row("done", now - 500, "SUCCESS")
        completed["startTime"] = now - 490
        completed["endTime"] = now - 450
        return {
            "queued": {"__typename": "Runs", "count": 2, "results": [row("new", now - 30)]},
            "running": {
                "__typename": "Runs",
                "count": 1,
                "results": [row("r", now - 60, "STARTED")],
            },
            "failed": {"__typename": "Runs", "count": 0, "results": []},
            "recent": {
                "__typename": "Runs",
                "count": 1,
                "results": [completed],
            },
        }

    monkeypatch.setattr(dagster, "graphql", gql)
    data = dagster.snapshot(CONFIG)
    assert data["queued"] == 2
    assert data["failed"] == 0
    assert 299 <= data["oldest"] <= 302
    assert data["jobs"][0]["url"] == "http://localhost:8000/runs/r"
    assert [job["id"] for job in data["jobs"]] == ["r", "new", "done"]
    assert data["jobs"][2]["duration"] == 40
    assert len(calls) == 2


def test_dagster_schema_errors_are_actionable(monkeypatch):
    monkeypatch.setattr(
        dagster, "post_json", lambda *args: {"errors": [{"message": "unknown field and secret"}]}
    )
    with pytest.raises(IntegrationError, match="schema rejected"):
        dagster.graphql(CONFIG, "query {}")


def test_dagster_detail_null_errors_and_bounded_output(monkeypatch):
    monkeypatch.setattr(
        dagster,
        "graphql",
        lambda *args: {
            "logsForRun": {
                "__typename": "EventConnection",
                "events": [
                    {"__typename": "RunFailureEvent", "error": None, "message": "Failed"},
                    {
                        "__typename": "ExecutionStepFailureEvent",
                        "error": {"message": "x" * 40000, "stack": ["trace"]},
                    },
                ],
            }
        },
    )
    result = dagster.detail(CONFIG, "abc")
    assert len(result["text"]) <= 32000
    assert "100" in result["note"]


@pytest.mark.parametrize(
    "status,match",
    [
        (401, "Access denied"),
        (403, "Access denied"),
        (404, "not supported"),
        (422, "not supported"),
        (429, "rate limit"),
        (500, "HTTP 500"),
        (302, "HTTP 302"),
    ],
)
def test_http_failures_never_echo_secrets(monkeypatch, status, match):
    response = httpx.Response(
        status, content=b"test-super-secret", request=httpx.Request("POST", "http://localhost")
    )

    class Stream:
        def __enter__(self):
            return response

        def __exit__(self, *args):
            response.close()

    monkeypatch.setattr(httpx, "stream", lambda *args, **kwargs: Stream())
    with pytest.raises(IntegrationError, match=match) as error:
        post_json("http://localhost", {})
    assert "test-super-secret" not in str(error.value)


@pytest.mark.parametrize("exc", [httpx.ConnectError("secret"), httpx.ReadTimeout("secret")])
def test_tunnel_failure(monkeypatch, exc):
    def fail(*args, **kwargs):
        raise exc

    monkeypatch.setattr(httpx, "stream", fail)
    with pytest.raises(IntegrationError, match="tunnel"):
        post_json("http://localhost", {})


def test_non_json_response(monkeypatch):
    response = httpx.Response(200, content=b"<html>login secret</html>")

    class Stream:
        def __enter__(self):
            return response

        def __exit__(self, *args):
            response.close()

    monkeypatch.setattr(httpx, "stream", lambda *args, **kwargs: Stream())
    with pytest.raises(IntegrationError, match="Expected JSON"):
        post_json("http://localhost", {})


def test_codex_metadata_is_readonly_and_infers_recent_activity(tmp_path, monkeypatch):
    path = tmp_path / "state_5.sqlite"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE threads (id TEXT,title TEXT,source TEXT,updated_at INTEGER,cwd TEXT,archived INTEGER)"
        )
        db.executemany(
            "INSERT INTO threads VALUES (?,?,?,?,?,?)",
            [
                ("v", "Task", "vscode", int(time.time()), "/work/repo", 0),
                ("old", "Old task", "vscode", int(time.time()) - 181, "/work/repo", 0),
                ("c", "CLI", "cli", 1, "/work", 0),
            ],
        )
    before = path.read_bytes()
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    tasks, note = codex.local_activity()
    assert len(tasks) == 2
    assert tasks[0]["status"] == "Active (inferred)"
    assert tasks[0]["inferred_active"] is True
    assert tasks[1]["status"] == "Idle"
    assert tasks[1]["inferred_active"] is False
    assert "inferred" in note
    assert path.read_bytes() == before


def test_codex_rollout_lifecycle_overrides_timestamp_guess(tmp_path, monkeypatch):
    rollout = tmp_path / "sessions" / "rollout.jsonl"
    rollout.parent.mkdir()
    rollout.write_text(
        '{"type":"event_msg","payload":{"type":"task_started"}}\n'
        + json.dumps({"type": "response_item", "payload": {"text": "x" * 300_000}})
        + "\n"
    )
    database = tmp_path / "state_5.sqlite"
    with sqlite3.connect(database) as db:
        db.execute(
            "CREATE TABLE threads (id TEXT,title TEXT,source TEXT,updated_at INTEGER,cwd TEXT,"
            "archived INTEGER,rollout_path TEXT)"
        )
        db.execute(
            "INSERT INTO threads VALUES (?,?,?,?,?,?,?)",
            ("v", "Task", "vscode", int(time.time()), "/work/repo", 0, str(rollout)),
        )
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))

    active, _ = codex.local_activity()
    with rollout.open("a") as stream:
        stream.write('{"type":"event_msg","payload":{"type":"task_complete"}}\n')
    idle, _ = codex.local_activity()

    assert active[0]["activity_state"] == "active"
    assert active[0]["inferred_active"] is True
    assert idle[0]["activity_state"] == "idle"
    assert idle[0]["inferred_active"] is False
    assert idle[0]["activity_source"] == "rollout"


def test_codex_activity_home_can_differ_from_auth_home(tmp_path, monkeypatch):
    activity_home = tmp_path / "activity"
    activity_home.mkdir()
    with sqlite3.connect(activity_home / "state_5.sqlite") as db:
        db.execute(
            "CREATE TABLE threads (id TEXT,title TEXT,source TEXT,updated_at INTEGER,cwd TEXT,archived INTEGER)"
        )
        db.execute(
            "INSERT INTO threads VALUES (?,?,?,?,?,?)",
            ("current", "Current task", "vscode", int(time.time()), "/work/repo", 0),
        )
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "auth"))
    monkeypatch.setenv("CODESTER_CODEX_ACTIVITY_HOME", str(activity_home))

    tasks, _ = codex.local_activity()

    assert [task["id"] for task in tasks] == ["current"]


def test_codex_rpc_lifecycle_and_secret_projection(tmp_path, monkeypatch):
    binary = tmp_path / "codex"
    binary.write_text("""#!/usr/bin/env python3
import sys,json
for line in sys.stdin:
 r=json.loads(line)
 if 'id' not in r: continue
 result={} if r['method']=='initialize' else {'accountId':'private','rateLimits':{'planType':'plus','primary':{'usedPercent':17,'windowDurationMins':300,'resetsAt':10000},'credits':{'balance':'private'}}}
 print(json.dumps({'id':r['id'],'result':result}),flush=True)
""")
    binary.chmod(0o700)
    original_popen = subprocess.Popen
    monkeypatch.setattr(
        codex.subprocess,
        "Popen",
        lambda argv, **kwargs: original_popen([sys.executable, str(binary), *argv[1:]], **kwargs),
    )
    monkeypatch.setattr(codex, "executable", lambda: str(binary))
    result = codex.account_limits()
    assert result["windows"][0]["used"] == 17
    assert "private" not in json.dumps(result)


def test_oversized_response_rejected(monkeypatch):
    response = httpx.Response(200, content=b"x" * 2_000_001)

    class Stream:
        def __enter__(self):
            return response

        def __exit__(self, *args):
            response.close()

    monkeypatch.setattr(httpx, "stream", lambda *args, **kwargs: Stream())
    with pytest.raises(IntegrationError, match="size or time limit"):
        post_json("http://localhost", {})


def test_unknown_codex_schema_degrades_activity_only(tmp_path, monkeypatch):
    with sqlite3.connect(tmp_path / "state_999.sqlite") as db:
        db.execute("CREATE TABLE threads (future_column TEXT)")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    tasks, note = codex.local_activity()
    assert not tasks and "schema is unsupported" in note


def test_signoz_partial_result_is_not_reported_healthy(monkeypatch):
    monkeypatch.setattr(
        signoz, "post_json", lambda *args: {"data": {"warning": "partial", "data": {"results": []}}}
    )
    with pytest.raises(IntegrationError, match="incomplete"):
        signoz.query(CONFIG, "key", [])


@pytest.mark.parametrize("event,expected", [("task_complete", "idle"), ("turn_aborted", "stopped")])
def test_codex_completion_before_tail_is_not_hidden_by_cached_start(tmp_path, event, expected):
    rollout = tmp_path / "rollout.jsonl"
    rollout.write_text(
        '{"type":"event_msg","payload":{"type":"task_started"}}\n', encoding="utf-8"
    )
    assert codex.rollout_activity(tmp_path, str(rollout)) == "active"
    with rollout.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"type": "event_msg", "payload": {"type": event}}) + "\n")
        stream.write(json.dumps({"type": "response_item", "payload": "x" * 300_000}) + "\n")
    assert codex.rollout_activity(tmp_path, str(rollout)) == expected


def test_codex_large_completion_record_and_partial_write(tmp_path):
    rollout = tmp_path / "rollout.jsonl"
    rollout.write_text(
        '{"type":"event_msg","payload":{"type":"task_started"}}\n', encoding="utf-8"
    )
    completion = json.dumps(
        {"type": "event_msg", "payload": {"type": "task_complete", "last_agent_message": "x" * 300_000}}
    )
    with rollout.open("a", encoding="utf-8") as stream:
        stream.write(completion[:-2])
    assert codex.rollout_activity(tmp_path, str(rollout)) == "active"
    with rollout.open("a", encoding="utf-8") as stream:
        stream.write(completion[-2:] + "\n")
    assert codex.rollout_activity(tmp_path, str(rollout)) == "idle"


def test_codex_rollout_replacement_does_not_reuse_active_state(tmp_path):
    rollout = tmp_path / "rollout.jsonl"
    rollout.write_text(
        '{"type":"event_msg","payload":{"type":"task_started"}}\n', encoding="utf-8"
    )
    assert codex.rollout_activity(tmp_path, str(rollout)) == "active"
    rollout.write_text('{"type":"session_meta","payload":{}}\n', encoding="utf-8")
    assert codex.rollout_activity(tmp_path, str(rollout)) is None
