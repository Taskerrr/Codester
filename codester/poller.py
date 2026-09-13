"""One independent polling worker per service, regardless of browser/tab count."""

import copy
import threading
import time

from codester import codex, dagster, demo, signoz
from codester.store import Store
from codester.transport import IntegrationError

INTERVALS = {"codex": 60, "dagster": 10, "signoz": 30}


class Poller:
    def __init__(self, store: Store):
        self.store = store
        self.lock = threading.RLock()
        self.operation_locks = {name: threading.Lock() for name in INTERVALS}
        self.wakes = {name: threading.Event() for name in INTERVALS}
        self.stopped = threading.Event()
        self.generation = 0
        self.state: dict[str, dict] = {
            name: {
                "status": "loading",
                "message": "Waiting for first read…",
                "last_success": None,
                "data": None,
            }
            for name in INTERVALS
        }
        self.threads: list[threading.Thread] = []

    def start(self) -> None:
        for name in INTERVALS:
            thread = threading.Thread(
                target=self.run, args=(name,), daemon=True, name=f"poll-{name}"
            )
            self.threads.append(thread)
            thread.start()

    def stop(self) -> None:
        self.stopped.set()
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
                    "data": None,
                }
                self.wakes[name].set()

    def fetch(self, name: str, config: dict, key: str = "") -> dict:
        if name == "codex":
            return codex.snapshot(config[name])
        if name == "dagster":
            return dagster.snapshot(config[name])
        return signoz.snapshot(config[name], key)

    def refresh(self, name: str) -> bool:
        with self.operation_locks[name]:
            with self.lock:
                generation = self.generation
                config = self.store.read()
                key = self.store.secret("signoz") if name == "signoz" else ""
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
                    self.state[name] = result
            return success

    def run(self, name: str) -> None:
        failures = 0
        while not self.stopped.is_set():
            # Clear before refresh so a settings change during I/O is retained.
            self.wakes[name].clear()
            success = self.refresh(name)
            failures = 0 if success else min(failures + 1, 5)
            delay = min(INTERVALS[name] * 2**failures, 300)
            self.wakes[name].wait(delay)

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "demo": self.store.read()["demo"],
                "services": copy.deepcopy(self.state),
                "server_time": time.time(),
                "revision": self.generation,
            }
