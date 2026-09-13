import copy
import threading

from codester.poller import Poller
from codester.store import DEFAULTS, Store
from codester.transport import IntegrationError


def live(store):
    config = copy.deepcopy(DEFAULTS)
    config["demo"] = False
    config["dagster"].update(enabled=True, api_url="http://localhost:8000")
    store.save(config)


def test_failure_keeps_last_good_data_and_does_not_affect_other_services(tmp_path, monkeypatch):
    store = Store(tmp_path)
    live(store)
    poller = Poller(store)
    monkeypatch.setattr(poller, "fetch", lambda *args: {"queued": 7})
    assert poller.refresh("dagster")
    timestamp = poller.snapshot()["services"]["dagster"]["last_success"]

    def fail(*args):
        raise IntegrationError("Tunnel closed")

    monkeypatch.setattr(poller, "fetch", fail)
    assert not poller.refresh("dagster")
    poller.refresh("codex")
    result = poller.snapshot()["services"]
    assert result["dagster"]["status"] == "stale"
    assert result["dagster"]["data"] == {"queued": 7}
    assert result["dagster"]["last_success"] == timestamp
    assert result["codex"]["status"] == "disabled"


def test_config_change_discards_inflight_results(tmp_path, monkeypatch):
    store = Store(tmp_path)
    live(store)
    poller = Poller(store)
    started = threading.Event()
    release = threading.Event()

    def fetch(*args):
        started.set()
        assert release.wait(2)
        return {"old_connection": "data"}

    monkeypatch.setattr(poller, "fetch", fetch)
    thread = threading.Thread(target=poller.refresh, args=("dagster",))
    thread.start()
    assert started.wait(2)
    poller.invalidate()
    release.set()
    thread.join(2)
    assert poller.snapshot()["services"]["dagster"]["data"] is None


def test_demo_is_explicit_and_does_not_call_upstream(tmp_path, monkeypatch):
    poller = Poller(Store(tmp_path))

    def unexpected(*args):
        raise AssertionError("Demo called upstream")

    monkeypatch.setattr(poller, "fetch", unexpected)
    poller.refresh("signoz")
    assert poller.snapshot()["services"]["signoz"]["status"] == "demo"


def test_failure_backoff_and_success_reset(tmp_path, monkeypatch):
    poller = Poller(Store(tmp_path))
    outcomes = iter([False, False, True])
    delays = []
    monkeypatch.setattr(poller, "refresh", lambda name: next(outcomes))

    def wait(delay):
        delays.append(delay)
        if len(delays) == 3:
            poller.stopped.set()
        return False

    monkeypatch.setattr(poller.wakes["dagster"], "wait", wait)
    poller.run("dagster")
    assert delays == [20, 40, 10]


def test_poll_captures_key_with_its_destination(tmp_path, monkeypatch):
    store = Store(tmp_path)
    config = copy.deepcopy(DEFAULTS)
    config["demo"] = False
    config["signoz"].update(enabled=True, api_url="http://old-server", api_key="old-key")
    store.save(config)
    poller = Poller(store)
    observed = []

    def fetch(name, snapshot, key):
        config["signoz"].update(api_url="http://new-server", api_key="new-key")
        with poller.lock:
            store.save(config)
            poller.invalidate()
        observed.append((snapshot["signoz"]["api_url"], key))
        return {}

    monkeypatch.setattr(poller, "fetch", fetch)
    poller.refresh("signoz")
    assert observed == [("http://old-server", "old-key")]
    assert poller.snapshot()["services"]["signoz"]["data"] is None
