"""Local Git checkout inspection and explicit push/deploy actions."""

import copy
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from codester.store import Store
from codester.transport import IntegrationError

STATUS_TIMEOUT = 6
ACTION_TIMEOUT = 600
MAX_OUTPUT = 1_000_000


class RepositoryManager:
    def __init__(self, store: Store):
        self.store = store
        self.lock = threading.RLock()
        self.snapshot_lock = threading.Lock()
        self.actions: dict[str, dict] = {}
        self.cached: dict | None = None
        self.cached_at = 0.0

    def invalidate(self) -> None:
        with self.lock:
            self.cached = None

    def _configured(self, identifier: str) -> dict:
        for repository in self.store.read()["github"]["repositories"]:
            if repository["id"] == identifier:
                return repository
        raise IntegrationError("Repository is no longer configured.")

    def _environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        if os.name != "nt" and Path("/data").is_dir():
            environment.setdefault(
                "GIT_SSH_COMMAND",
                "ssh -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/data/known_hosts",
            )
        return environment

    def _git(self, repository: dict, *args: str, timeout: int = STATUS_TIMEOUT) -> str:
        binary = shutil.which("git")
        if not binary:
            raise IntegrationError("Git is unavailable in this Codester installation.")
        path = Path(repository["path"])
        if not path.is_dir():
            raise IntegrationError("Checkout path is unavailable. Check repository settings.")
        try:
            result = subprocess.run(  # noqa: S603
                [binary, "-c", f"safe.directory={path}", "-C", str(path), *args],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=self._environment(),
            )
        except subprocess.TimeoutExpired as exc:
            raise IntegrationError("Repository command timed out.") from exc
        if len(result.stdout) + len(result.stderr) > MAX_OUTPUT:
            raise IntegrationError("Repository command returned too much output.")
        if result.returncode:
            if args and args[0] == "push":
                raise IntegrationError("Git push failed. Check the upstream and Git credentials.")
            raise IntegrationError("Git could not inspect this checkout.")
        return result.stdout.strip()

    def inspect(self, repository: dict) -> dict:
        head = self._git(repository, "rev-parse", "HEAD")
        branch = self._git(repository, "branch", "--show-current") or "detached"
        changes = len(self._git(repository, "status", "--porcelain").splitlines())
        upstream = ""
        ahead = behind = None
        try:
            upstream = self._git(
                repository,
                "rev-parse",
                "--abbrev-ref",
                "--symbolic-full-name",
                "@{upstream}",
            )
            counts = self._git(
                repository, "rev-list", "--left-right", "--count", "HEAD...@{upstream}"
            )
            left, right = counts.split()
            ahead, behind = int(left), int(right)
        except (IntegrationError, ValueError):
            pass
        deployed = self.store.deployed_head(repository["id"])
        with self.lock:
            action = dict(self.actions.get(repository["id"], {"state": "idle", "message": ""}))
        deploy_configured = bool(repository["deploy_command"])
        return {
            "id": repository["id"],
            "repo": repository["repo"],
            "branch": branch,
            "head": head[:12],
            "changes": changes,
            "upstream": upstream,
            "ahead": ahead,
            "behind": behind,
            "needs_push": bool(ahead),
            "deploy_configured": deploy_configured,
            "deploy_state": (
                "unavailable"
                if not deploy_configured
                else "unknown"
                if not deployed
                else "current"
                if deployed == head and changes == 0
                else "needed"
            ),
            "action": action,
        }

    def snapshot(self) -> dict:
        with self.lock:
            if self.cached is not None and time.monotonic() - self.cached_at < 4:
                return copy.deepcopy(self.cached)
        with self.snapshot_lock:
            with self.lock:
                if self.cached is not None and time.monotonic() - self.cached_at < 4:
                    return copy.deepcopy(self.cached)
            rows = []
            for repository in self.store.read()["github"]["repositories"]:
                if not repository["path"]:
                    continue
                try:
                    rows.append(self.inspect(repository))
                except IntegrationError as exc:
                    with self.lock:
                        action = dict(
                            self.actions.get(
                                repository["id"], {"state": "idle", "message": ""}
                            )
                        )
                    rows.append(
                        {
                            "id": repository["id"],
                            "repo": repository["repo"],
                            "error": str(exc),
                            "action": action,
                        }
                    )
            result = {"repositories": rows}
            with self.lock:
                self.cached = copy.deepcopy(result)
                self.cached_at = time.monotonic()
            return result

    def start(self, identifier: str, action: str) -> dict:
        repository = self._configured(identifier)
        if not repository["path"]:
            raise IntegrationError("No local checkout is configured for this repository.")
        if action not in {"push", "deploy"}:
            raise IntegrationError("Unsupported repository action.")
        if action == "deploy" and not repository["deploy_command"]:
            raise IntegrationError("No deploy command is configured for this repository.")
        with self.lock:
            current = self.actions.get(identifier, {})
            if current.get("state") == "running":
                raise IntegrationError("A repository action is already running.")
            self.actions[identifier] = {
                "state": "running",
                "kind": action,
                "message": "Pushing…" if action == "push" else "Deploying…",
                "started_at": time.time(),
            }
            self.cached = None
        threading.Thread(
            target=self._run_action,
            args=(repository, action),
            daemon=True,
            name=f"repository-{action}-{identifier[:8]}",
        ).start()
        return dict(self.actions[identifier])

    def _run_action(self, repository: dict, action: str) -> None:
        success = False
        message = ""
        try:
            if action == "push":
                self._git(repository, "push", timeout=ACTION_TIMEOUT)
                message = "Push complete"
            else:
                command = repository["deploy_command"]
                shell = (
                    ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command]
                    if os.name == "nt"
                    else ["/bin/sh", "-lc", command]
                )
                result = subprocess.run(  # noqa: S603
                    shell,
                    cwd=repository["path"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=ACTION_TIMEOUT,
                    check=False,
                    env=self._environment(),
                )
                if result.returncode:
                    raise IntegrationError(f"Deploy exited with code {result.returncode}.")
                head = self._git(repository, "rev-parse", "HEAD")
                self.store.set_deployed_head(repository["id"], head)
                message = "Deploy complete"
            success = True
        except subprocess.TimeoutExpired:
            message = "Action timed out after 10 minutes."
        except IntegrationError as exc:
            message = str(exc)
        except OSError:
            message = "Could not start the configured command."
        with self.lock:
            self.actions[repository["id"]] = {
                "state": "success" if success else "error",
                "kind": action,
                "message": message,
                "finished_at": time.time(),
            }
            self.cached = None
