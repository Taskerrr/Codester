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
        return {"data": {"results": [{"rows": [
            {"timestamp": 1780000000000000000, "data": {
                "id": "one", "body": "<script>alert(1)</script>\ntrace", "severity_number": 17,
                "resources_string": {"service.name": "checkout"}, "attributes_string": {"user.id": "42"},
            }},
            {"timestamp": 1780000000000000000, "data": {"id": "one", "body": "duplicate"}},
            {"timestamp": 1780000000000000001, "data": {"id": "two", "body": {"message": "x" * 5000}}},
        ]}]}}
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
