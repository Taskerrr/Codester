"""One independent polling worker per service, regardless of browser/tab count."""

import copy
import threading
import time

from codester import codex, dagster, demo, signoz
from codester.github_activity import GitHubActivity
from codester.store import Store
from codester.transport import IntegrationError

INTERVALS = {"codex": 60, "dagster": 10, "signoz": 30, "github": 60}


class Poller:
    def __init__(self, store: Store):
        self.store = store
        self.lock = threading.RLock()
        self.operation_locks = {name: threading.Lock() for name in INTERVALS}
        self.wakes = {name: threading.Event() for name in INTERVALS}
        self.stopped = threading.Event()
        self.generation = 0
        self.github_activity = GitHubActivity(store, self.wakes["github"].set)
        self.state: dict[str, dict] = {
            name: {
                "status": "loading",
                "message": "Waiting for first read…",
                "last_success": None,
                "refreshing": False,
                "next_refresh": None,
                "refresh_interval": INTERVALS[name],
                "data": None,
            }
            for name in INTERVALS
        }
        self.threads: list[threading.Thread] = []
        self.restore_github()

    def restore_github(self) -> None:
        config = self.store.read()
        if config["demo"] or not config["github"]["enabled"]:
            return
        saved = self.github_activity.cached(config["github"], self.store.secret("github"))
        if saved is not None:
            self.state["github"].update(
                status="stale",
                message="Saved GitHub data; checking for updates.",
                data=saved,
                last_success=saved.get("repositories_updated_at"),
            )

    def start(self) -> None:
        for name in INTERVALS:
            thread = threading.Thread(
                target=self.run, args=(name,), daemon=True, name=f"poll-{name}"
            )
            self.threads.append(thread)
            thread.start()

    def stop(self) -> None:
        self.stopped.set()
        self.github_activity.stop()
        for wake in self.wakes.values():
            wake.set()

    def invalidate(self) -> None:
        with self.lock:
            self.generation += 1
            for name in self.state:
                self.state[name] = {
                    "status": "loading",
                    "message": "Reading updated connection…",
                    "last_success": None,
                    "refreshing": False,
                    "next_refresh": None,
                    "refresh_interval": INTERVALS[name],
                    "data": None,
                }
                self.wakes[name].set()
            self.restore_github()

    def fetch(self, name: str, config: dict, key: str = "") -> dict:
        if name == "codex":
            return codex.snapshot(config[name])
        if name == "dagster":
            return dagster.snapshot(config[name])
        if name == "signoz":
            return signoz.snapshot(config[name], key)
        return self.github_activity.fetch(config[name], key)

    def refresh(self, name: str) -> bool:
        with self.operation_locks[name]:
            with self.lock:
                generation = self.generation
                config = self.store.read()
                key = self.store.secret(name) if name in {"signoz", "github"} else ""
                self.state[name].update(refreshing=True, next_refresh=None)
            result = {
                "status": "disabled",
                "message": "Connect in settings to start monitoring.",
                "last_success": None,
                "data": None,
            }
            success = True
            try:
                if config["demo"]:
                    result = {
                        "status": "demo",
                        "message": "Sample data",
                        "last_success": time.time(),
                        "data": demo.snapshot(name),
                    }
                elif config[name]["enabled"]:
                    data = self.fetch(name, config, key)
                    result = {
                        "status": "connected",
                        "message": "Connected",
                        "last_success": time.time(),
                        "data": data,
                    }
            except Exception as exc:
                # Background-worker boundary: never leak upstream bodies, keys, or tracebacks.
                success = False
                message = (
                    str(exc)
                    if isinstance(exc, IntegrationError)
                    else "Unexpected response. Check integration compatibility."
                )
                with self.lock:
                    previous = copy.deepcopy(self.state[name])
                result = {
                    **previous,
                    "status": "stale" if previous["data"] else "error",
                    "message": message,
                }
            with self.lock:
                if generation == self.generation:
                    self.state[name] = {
                        **result,
                        "refreshing": False,
                        "next_refresh": None,
                        "refresh_interval": INTERVALS[name],
                    }
            return success

    def run(self, name: str) -> None:
        failures = 0
        while not self.stopped.is_set():
            # Clear before refresh so a settings change during I/O is retained.
            self.wakes[name].clear()
            success = self.refresh(name)
            failures = 0 if success else min(failures + 1, 5)
            delay = min(INTERVALS[name] * 2**failures, 300)
            with self.lock:
                if not self.wakes[name].is_set():
                    self.state[name].update(
                        next_refresh=time.time() + delay, refresh_interval=delay
                    )
            self.wakes[name].wait(delay)

    def snapshot(self) -> dict:
        with self.lock:
            settings = self.store.read()
            return {
                "demo": settings["demo"],
                "layout": settings["dashboard_apps"],
                "services": copy.deepcopy(self.state),
                "server_time": time.time(),
                "revision": self.generation,
            }
