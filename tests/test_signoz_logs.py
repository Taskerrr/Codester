import copy

import pytest

from codester import signoz, signoz_logs
from codester.app import create_app
from codester.signoz_logs import LogFeed, fetch_logs
from codester.store import ConfigurationError, Store
from codester.transport import IntegrationError


def test_logs_query_is_bounded_and_error_filter_is_upstream(monkeypatch):
    calls = []

    def post(url, payload, headers):
        calls.append(payload)
        return {
            "data": {
                "results": [
                    {
                        "rows": [
                            {
                                "timestamp": 1780000000000000000,
                                "data": {
                                    "id": "one",
                                    "body": "<script>alert(1)</script>\ntrace",
                                    "severity_number": 17,
                                    "resources_string": {"service.name": "checkout"},
                                    "attributes_string": {"user.id": "42"},
                                },
                            },
                            {
                                "timestamp": 1780000000000000000,
                                "data": {"id": "one", "body": "duplicate"},
                            },
                            {
                                "timestamp": 1780000000000000001,
                                "data": {"id": "two", "body": {"message": "x" * 5000}},
                            },
                        ]
                    }
                ]
            }
        }

    monkeypatch.setattr(signoz, "post_json", post)
    rows = fetch_logs({"api_url": "https://example.test"}, "private", "errors")
    spec = calls[0]["compositeQuery"]["queries"][0]["spec"]
    assert spec["signal"] == "logs"
    assert spec["limit"] == 100
    assert spec["order"][1]["key"]["name"] == "id"
    assert "severity_number >= 17" in spec["filter"]["expression"]
    assert calls[0]["end"] - calls[0]["start"] == 900000
    assert len(rows) == 2
    assert rows[0]["user_id"] == "42"
    assert rows[0]["app"] == "checkout"
    assert rows[0]["severity"] == "ERROR"
    assert rows[0]["request"] == {"method": "", "path": "", "status": ""}
    assert rows[0]["timestamp"] == "1780000000000000000"
    assert rows[0]["body"].startswith("<script>")  # UI escapes it; API retains plain text.
    assert rows[1]["user_id"] == ""
    assert rows[1]["truncated"] is True
    assert len(rows[1]["body"]) == 4000


@pytest.mark.parametrize("results", [[], [{}], [None], [{"rows": "bad"}]])
def test_unknown_log_shapes_are_not_reported_as_empty(monkeypatch, results):
    monkeypatch.setattr(signoz, "query", lambda *a, **kw: results)
    with pytest.raises(IntegrationError):
        fetch_logs({}, "key", "recent")


def test_empty_raw_logs_are_supported(monkeypatch):
    monkeypatch.setattr(signoz, "query", lambda *a, **kw: [{"rows": None}])
    assert fetch_logs({}, "key", "recent") == []


def test_home_log_query_requests_only_six_rows_and_normalizes_http_fields(monkeypatch):
    calls = []

    def query(config, key, queries, result_type, **kwargs):
        calls.append(queries)
        return [
            {
                "rows": [
                    {
                        "timestamp": 1780000000000000000,
                        "data": {
                            "id": "request-one",
                            "body": "Request complete",
                            "attributes_string": {
                                "http.request.method": "post",
                                "url.path": "/orders/42",
                            },
                            "attributes_number": {"http.response.status_code": 201},
                        },
                    }
                ]
            }
        ]

    monkeypatch.setattr(signoz, "query", query)
    rows = fetch_logs({}, "key", "recent", {"limit": "6"})
    assert calls[0][0]["limit"] == 6
    assert rows[0]["request"] == {"method": "POST", "path": "/orders/42", "status": "201"}


def live_store(tmp_path):
    store = Store(tmp_path)
    config = store.read()
    config["demo"] = False
    config["signoz"]["enabled"] = True
    config["signoz"]["api_url"] = "http://example.test"
    store.save(config)
    return store


def test_shared_cache_backoff_and_settings_change_clear_old_rows(tmp_path, monkeypatch):
    store = live_store(tmp_path)
    feed = LogFeed(store)
    clock = [100.0]
    calls = []

    def fetch(*args):
        calls.append(args)
        if len(calls) > 1:
            raise IntegrationError("Unavailable")
        return [{"id": "old"}]

    monkeypatch.setattr(signoz_logs.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(signoz_logs, "fetch_logs", fetch)
    assert feed.read("recent")["rows"] == [{"id": "old"}]
    assert feed.read("recent")["status"] == "connected"
    assert len(calls) == 1
    clock[0] += 6
    stale = feed.read("recent")
    assert stale["status"] == "stale" and stale["rows"] == [{"id": "old"}]
    clock[0] += 6
    feed.read("recent")
    assert len(calls) == 2  # backoff shares failed reads across tabs
    config = store.read()
    config["signoz"]["api_url"] = "http://different.test"
    store.save(config)
    assert feed.read("recent")["rows"] == []
    assert feed.read("recent")["status"] == "error"


def test_changed_connection_discards_in_flight_response(tmp_path, monkeypatch):
    store = live_store(tmp_path)

    def fetch(*args):
        config = store.read()
        config["signoz"]["api_url"] = "http://changed.test"
        store.save(config)
        return [{"id": "old-server"}]

    monkeypatch.setattr(signoz_logs, "fetch_logs", fetch)
    data = LogFeed(store).read("recent")
    assert data["status"] == "loading"
    assert data["rows"] == []


def test_demo_disabled_and_invalid_filter_never_query(tmp_path, monkeypatch):
    store = Store(tmp_path)

    def forbidden(*args):
        pytest.fail("Must not query upstream")

    monkeypatch.setattr(signoz_logs, "fetch_logs", forbidden)
    feed = LogFeed(store)
    assert feed.read("recent")["status"] == "demo"
    assert len(feed.read("errors")["rows"]) == 1
    with pytest.raises(ConfigurationError):
        feed.read("anything")
    settings = copy.deepcopy(store.read())
    settings["demo"] = False
    settings["signoz"]["enabled"] = False
    store.save(settings)
    assert feed.read("recent")["status"] == "disabled"
    assert feed.read("recent")["rows"] == []


def test_api_validates_filter_and_marks_demo(tmp_path):
    client = create_app(tmp_path, start_poller=False).test_client()
    assert client.get("/api/signoz/logs?mode=invalid").status_code == 400
    response = client.get("/api/signoz/logs?mode=errors")
    assert response.status_code == 200
    assert response.json is not None and response.json["status"] == "demo"
    home = client.get("/api/signoz/logs?mode=recent&seconds=900&limit=6")
    assert home.status_code == 200
    assert home.json is not None and home.json["limit"] == 6
    assert len(home.json["rows"]) <= 6


def test_debug_search_escapes_literals_and_pins_pagination(monkeypatch):
    calls = []

    def post(url, payload, headers):
        calls.append(payload)
        return {"data": {"results": [{"rows": []}]}}

    monkeypatch.setattr(signoz, "post_json", post)
    end = 1780000000000
    filters = {
        "app": "api' OR 1=1",
        "user_id": "a\\b",
        "text": "timeout_%'",
        "trace_id": "a" * 32,
        "level": "ERROR",
        "seconds": "3600",
        "offset": "100",
        "end_ms": str(end),
    }
    assert fetch_logs({"api_url": "https://example.test"}, "secret", "errors", filters) == []
    payload = calls[0]
    spec = payload["compositeQuery"]["queries"][0]["spec"]
    assert payload["end"] == end and payload["start"] == end - 3600000
    assert spec["offset"] == 100
    expression = spec["filter"]["expression"]
    assert expression.startswith("(severity_number >= 17 OR ")
    assert "service.name = 'api\\' OR 1=1'" in expression
    assert "user.id = 'a\\\\b'" in expression
    assert "body CONTAINS 'timeout_%\\''" in expression
    assert "trace_id = '" + "a" * 32 + "'" in expression


@pytest.mark.parametrize(
    "filters",
    [
        {"seconds": "2"},
        {"offset": "-1"},
        {"offset": "1000"},
        {"offset": "100"},
        {"end_ms": "9999999999999"},
        {"end_ms": "NaN"},
        {"level": "oops"},
        {"trace_id": "a' OR 1=1"},
        {"text": "x" * 501},
        {"app": "a\nb"},
        {"end_ms": "1"},
        {"seconds": "²"},
        {"limit": "7"},
        {"limit": "6", "offset": "100"},
    ],
)
def test_debug_filters_rejected_before_upstream(tmp_path, monkeypatch, filters):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid filters must not query SigNoz")

    monkeypatch.setattr(signoz_logs, "fetch_logs", forbidden)
    with pytest.raises(ConfigurationError):
        LogFeed(live_store(tmp_path)).read("recent", filters)


def test_debug_cache_isolated_by_filter_and_bounded(tmp_path, monkeypatch):
    feed = LogFeed(live_store(tmp_path))
    clock = [100.0]
    calls = []

    def fetch(config, key, mode, filters):
        calls.append(filters)
        if filters["app"] == "broken":
            raise IntegrationError("Offline")
        return [{"id": filters["app"]}]

    monkeypatch.setattr(signoz_logs, "fetch_logs", fetch)
    monkeypatch.setattr(signoz_logs.time, "monotonic", lambda: clock[0])
    assert feed.read("recent", {"app": "api"})["rows"] == [{"id": "api"}]
    assert feed.read("recent", {"app": "api"})["rows"] == [{"id": "api"}]
    assert len(calls) == 1
    assert feed.read("recent", {"app": "broken"})["rows"] == []
    for number in range(30):
        feed.read("recent", {"app": str(number)})
    assert len(feed.cache) == signoz_logs.CACHE_LIMIT
    assert len(feed.deadlines) == signoz_logs.CACHE_LIMIT
    assert len(feed.failures) == signoz_logs.CACHE_LIMIT


def test_debug_details_preserve_trace_and_bound_attributes(monkeypatch):
    trace = "a" * 32

    def query(*args, **kwargs):
        return [
            {
                "rows": [
                    {
                        "timestamp": 1780000000000000000,
                        "data": {
                            "body": "A message",
                            "trace_id": trace,
                            "span_id": "b" * 16,
                            "attributes_string": {
                                "exception.stacktrace": "s" * 5000,
                                "user.id": "42",
                            },
                            "resources_string": {
                                "service.name": "api",
                                "deployment.environment": "dev",
                            },
                        },
                    }
                ]
            }
        ]

    monkeypatch.setattr(signoz, "query", query)
    row = fetch_logs(
        {"api_url": "https://api.test", "browser_url": "https://ui.test"}, "key", "recent"
    )[0]
    assert row["trace_url"] == "https://ui.test/trace/" + trace
    assert row["span_id"] == "b" * 16
    assert row["attributes"]["resources_string.deployment.environment"] == "dev"
    assert len(row["attributes"]["attributes_string.exception.stacktrace"]) == 1000
    assert row["attributes_truncated"]
    attributes, truncated = signoz_logs.fields({f"field{i}": "x" * 1000 for i in range(100)})
    assert truncated and sum(len(k) + len(v) for k, v in attributes.items()) <= 12000


def test_debug_demo_filters_and_api_metadata(tmp_path):
    client = create_app(tmp_path, start_poller=False).test_client()
    response = client.get("/api/signoz/logs?app=checkout&seconds=3600&text=timed")
    assert response.status_code == 200
    data = response.get_json()
    assert data["rows"][0]["app"] == "checkout"
    assert data["end_ms"] - data["start_ms"] == 3600000
    assert data["rows"][0]["trace_id"]
    assert data["source_url"] == "" and data["rows"][0]["trace_url"] == ""
    assert client.get("/api/signoz/logs?app=missing").get_json()["rows"] == []
    assert client.get("/api/signoz/logs?level=WARN").get_json()["rows"] == []
    assert client.get("/api/signoz/logs?seconds=bad").status_code == 400
