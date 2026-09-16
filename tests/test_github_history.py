import copy
import threading
import time
from datetime import UTC, datetime, timedelta

import pytest

from codester import github
from codester.github_activity import GitHubActivity
from codester.poller import Poller
from codester.store import DEFAULTS, Store
from codester.transport import IntegrationError


def sample():
    return {
        "login": "jack",
        "total": 4,
        "days": [{"date": "2026-09-01", "count": 4}],
        "calendar_source": "repository_commits",
        "calendar_limited": False,
        "calendar_repository_count": 10,
        "calendar_updated_at": time.time(),
        "repositories_updated_at": time.time(),
        "organization": "TMPlant",
        "repositories": [{"name": "TMPlant/example", "commits": [0] * 14}],
    }


def setup_cache(tmp_path):
    store = Store(tmp_path)
    config = store.read()
    config["demo"] = False
    config["github"].update(enabled=True, organization="TMPlant", token="first-token")
    store.save(config)
    activity = GitHubActivity(store, lambda: None)
    activity.select(config["github"], "first-token")
    activity.value.update(calendar=sample(), snapshot=sample())
    store.save_github_cache(activity.signature, activity.value)
    return store, config, activity


def test_restart_shows_saved_snapshot_before_network(tmp_path):
    store, config, activity = setup_cache(tmp_path)
    poller = Poller(Store(tmp_path))
    state = poller.snapshot()["services"]["github"]
    assert state["status"] == "stale"
    assert state["data"]["total"] == 4
    assert state["last_success"] is not None
    assert poller.github_activity.worker is None


def test_cache_is_scoped_to_token_and_organization(tmp_path):
    store, config, activity = setup_cache(tmp_path)
    assert activity.cached(config["github"], "first-token")["total"] == 4
    assert activity.cached(config["github"], "other-token") is None
    config["github"]["organization"] = "AnotherOrg"
    assert activity.cached(config["github"], "first-token") is None


def test_unrelated_settings_do_not_clear_history(tmp_path):
    store, config, activity = setup_cache(tmp_path)
    poller = Poller(store)
    config["signoz"]["window_seconds"] = 86400
    store.save(config)
    poller.invalidate()
    assert poller.snapshot()["services"]["github"]["data"]["total"] == 4


def test_sparklines_do_not_wait_for_initial_history(tmp_path, monkeypatch):
    activity = GitHubActivity(Store(tmp_path), lambda: None)
    entered, release = threading.Event(), threading.Event()
    initial = {**sample(), "days": [], "total": 0, "calendar_updated_at": None}
    monkeypatch.setattr(github, "empty_calendar", lambda *args: initial)

    def snapshot(config, token, *, calendar=None, history=None, checkpoint=None):
        if calendar is not None:
            return copy.deepcopy(initial)
        entered.set()
        assert release.wait(3)
        return sample()

    monkeypatch.setattr(github, "snapshot", snapshot)
    try:
        result = activity.fetch(DEFAULTS["github"], "token")
        assert result["repositories"]
        assert result["calendar_loading"]
        assert entered.wait(2)
    finally:
        release.set()
        if activity.worker is not None:
            activity.worker.join(3)
    assert activity.cached(DEFAULTS["github"], "token")["calendar_loading"] is False


def test_background_failure_keeps_checkpoints_for_restart(tmp_path, monkeypatch):
    store = Store(tmp_path)
    activity = GitHubActivity(store, lambda: None)
    activity.select(DEFAULTS["github"], "token")

    def snapshot(config, token, *, history, checkpoint):
        history["org/finished"] = {"days": {"2026-09-01": 2}}
        checkpoint()
        raise IntegrationError("Service timed out.")

    monkeypatch.setattr(github, "snapshot", snapshot)
    activity.build_history(activity.signature, DEFAULTS["github"], "token", {})
    restarted = GitHubActivity(Store(tmp_path), lambda: None)
    restarted.select(DEFAULTS["github"], "token")
    assert "org/finished" in restarted.value["history"]
    assert restarted.value["error"] == "Service timed out."
    assert activity.retry_after > time.time()


def test_scope_change_cancels_old_background_write(tmp_path, monkeypatch):
    activity = GitHubActivity(Store(tmp_path), lambda: None)
    activity.select(DEFAULTS["github"], "old-token")
    old_signature = activity.signature

    def snapshot(config, token, *, history, checkpoint):
        activity.select(config, "new-token")
        checkpoint()

    monkeypatch.setattr(github, "snapshot", snapshot)
    activity.build_history(old_signature, DEFAULTS["github"], "old-token", {})
    assert "calendar" not in activity.value
    assert "error" not in activity.value


def test_incremental_history_replaces_recent_counts_and_retains_old_days(monkeypatch):
    now = datetime(2026, 9, 16, 12, tzinfo=UTC)
    previous = {
        "days": {"2026-08-01": 5, "2026-09-15": 3},
        "updated_at": now.timestamp() - 3600,
        "full_updated_at": now.timestamp() - 86400,
        "pushed_at": "old",
        "limited": False,
    }
    history = {"org/repo": previous}
    queries = []

    def get(url, headers, params, **kwargs):
        queries.append(params)
        return [{"commit": {"author": {"date": "2026-09-15T12:00:00Z"}}}]

    monkeypatch.setattr(github, "get_json", get)
    args = (
        "https://api.github.com",
        {},
        {"full_name": "org/repo", "pushed_at": "new"},
        "jack",
        "2026-03-19T00:00:00Z",
        now,
        history,
    )
    days, limited = github.repository_days(*args)
    assert queries[0]["since"] == "2026-09-10T00:00:00Z"
    assert days == {"2026-08-01": 5, "2026-09-15": 1}
    assert not limited
    assert github.repository_days(*args)[0] == days
    assert len(queries) == 1  # Unchanged repository needs no more commit reads.


def test_offline_gap_is_fetched_and_failed_refresh_preserves_history(monkeypatch):
    now = datetime(2026, 9, 16, 12, tzinfo=UTC)
    history = {
        "org/repo": {
            "days": {"2026-08-01": 5},
            "updated_at": (now - timedelta(days=15)).timestamp(),
            "full_updated_at": (now - timedelta(days=20)).timestamp(),
            "pushed_at": "old",
            "limited": False,
        }
    }
    original = copy.deepcopy(history)

    def fail(url, headers, params, **kwargs):
        assert params["since"] == "2026-08-31T00:00:00Z"
        raise IntegrationError("Network unavailable")

    monkeypatch.setattr(github, "get_json", fail)
    with pytest.raises(IntegrationError):
        github.repository_days(
            "https://api.github.com",
            {},
            {"full_name": "org/repo", "pushed_at": "new"},
            "jack",
            "2026-03-19T00:00:00Z",
            now,
            history,
        )
    assert history == original
