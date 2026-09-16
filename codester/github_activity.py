"""Persistent GitHub history with an independent, resumable background refresh."""

import copy
import hashlib
import json
import threading
import time
from collections.abc import Callable

from codester import github
from codester.store import Store
from codester.transport import IntegrationError

CALENDAR_INTERVAL = 3600
CALENDAR_FIELDS = (
    "login",
    "total",
    "days",
    "calendar_source",
    "calendar_limited",
    "calendar_repository_count",
    "calendar_updated_at",
)


class GitHubActivity:
    def __init__(self, store: Store, wake: Callable[[], None]):
        self.store = store
        self.wake = wake
        self.lock = threading.RLock()
        self.stopped = threading.Event()
        self.worker: threading.Thread | None = None
        self.signature = ""
        self.value: dict = {}
        self.retry_after = 0.0

    def select(self, config: dict, token: str) -> None:
        scope = {name: config.get(name, "") for name in ("api_url", "browser_url", "organization")}
        scope["repositories"] = [repo["repo"] for repo in config.get("repositories", [])]
        signature = hashlib.sha256(
            (json.dumps(scope, sort_keys=True) + "\0" + token).encode()
        ).hexdigest()
        with self.lock:
            if signature != self.signature:
                self.signature = signature
                self.value = self.store.read_github_cache(signature) or {
                    "version": 1,
                    "history": {},
                }
                self.retry_after = 0

    def cached(self, config: dict, token: str) -> dict | None:
        self.select(config, token)
        with self.lock:
            result = self.value.get("snapshot")
            return copy.deepcopy(result) if isinstance(result, dict) else None

    def fetch(self, config: dict, token: str) -> dict:
        self.select(config, token)
        with self.lock:
            signature = self.signature
            calendar = copy.deepcopy(self.value.get("calendar") or self.value.get("snapshot"))
        if calendar is None:
            calendar = github.empty_calendar(config, token)
        # Only three recent repositories are on the critical path, even on first startup.
        result = github.snapshot(config, token, calendar=calendar)
        with self.lock:
            if signature != self.signature or self.stopped.is_set():
                return result
            completed = self.value.get("calendar")
            if completed is not None:
                result.update({name: completed[name] for name in CALENDAR_FIELDS})
            result["calendar_loading"] = completed is None
            result["calendar_error"] = self.value.get("error", "")
            self.value["snapshot"] = copy.deepcopy(result)
            self.store.save_github_cache(signature, self.value)
            due = (
                completed is None
                or time.time() - completed["calendar_updated_at"] >= CALENDAR_INTERVAL
            )
            if (
                due
                and time.time() >= self.retry_after
                and (self.worker is None or not self.worker.is_alive())
            ):
                history = copy.deepcopy(self.value.get("history", {}))
                self.worker = threading.Thread(
                    target=self.build_history,
                    args=(signature, copy.deepcopy(config), token, history),
                    daemon=True,
                    name="github-history",
                )
                self.worker.start()
        return result

    def build_history(self, signature: str, config: dict, token: str, history: dict) -> None:
        def checkpoint() -> None:
            with self.lock:
                if self.stopped.is_set() or signature != self.signature:
                    raise IntegrationError("GitHub history refresh cancelled.")
                self.value["history"] = copy.deepcopy(history)
                self.store.save_github_cache(signature, self.value)

        try:
            calendar = github.snapshot(config, token, history=history, checkpoint=checkpoint)
            with self.lock:
                if self.stopped.is_set() or signature != self.signature:
                    return
                self.value["calendar"] = calendar
                self.value["history"] = history
                self.value["error"] = ""
                if self.value.get("snapshot") is not None:
                    self.value["snapshot"].update(
                        {name: calendar[name] for name in CALENDAR_FIELDS}
                    )
                    self.value["snapshot"].update(calendar_loading=False, calendar_error="")
                self.store.save_github_cache(signature, self.value)
        except Exception as exc:
            # Thread boundary: retain successful checkpoints and never publish raw errors or keys.
            with self.lock:
                if self.stopped.is_set() or signature != self.signature:
                    return
                self.value["error"] = (
                    str(exc)
                    if isinstance(exc, IntegrationError)
                    else "Contribution history unavailable. Retrying shortly."
                )
                self.retry_after = time.time() + 300
                self.store.save_github_cache(signature, self.value)
        self.wake()

    def stop(self) -> None:
        self.stopped.set()
