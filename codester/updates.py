"""Explicit, fast-forward-only source updates. Never reset or migrate user data."""

import os
import subprocess
import threading
from pathlib import Path

from codester.store import ConfigurationError
from codester.subprocesses import hidden_subprocess_creation_flags


class SourceUpdater:
    def __init__(self, root: Path, data_dir: Path) -> None:
        self.root = root.resolve()
        self.data_dir = data_dir.resolve()
        self.lock = threading.Lock()

    def _git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", "-c", f"core.hooksPath={os.devnull}", *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=60,
            creationflags=hidden_subprocess_creation_flags(),
            env={
                **os.environ,
                "GIT_TERMINAL_PROMPT": "0",
                "GCM_INTERACTIVE": "never",
                "GIT_SSH_COMMAND": "ssh -o BatchMode=yes -o StrictHostKeyChecking=yes",
            },
        )
        if result.returncode != 0:
            # Git output may contain credential-bearing remote URLs. Do not return it.
            raise ConfigurationError(
                "Git could not complete the update check. Check repository access, network "
                "and branch tracking in your terminal. No reset or cleanup was attempted."
            )
        return result.stdout.strip()

    def _preflight(self) -> dict:
        if os.environ.get("CODESTER_NATIVE") != "1" or not (self.root / ".git").exists():
            raise ConfigurationError(
                "Source updates require a native Git checkout. Update other installations using their installer."
            )
        if Path(self._git("rev-parse", "--show-toplevel")).resolve() != self.root:
            raise ConfigurationError("Codester must be the root of its Git checkout.")
        if self._git("status", "--porcelain", "--untracked-files=all"):
            raise ConfigurationError(
                "Local changes found. Commit or review them in Git before updating; Codester will not overwrite them."
            )
        branch = self._git("symbolic-ref", "--quiet", "--short", "HEAD")
        upstream = self._git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
        return {
            "branch": branch,
            "upstream": upstream,
            "revision": self._git("rev-parse", "--short", "HEAD"),
        }

    def status(self) -> dict:
        if self.lock.locked():
            return {"supported": False, "message": "An update is already running."}
        try:
            state = self._preflight()
        except (ConfigurationError, OSError, subprocess.SubprocessError) as error:
            message = (
                str(error)
                if isinstance(error, ConfigurationError)
                else "Git is unavailable or timed out. Check your installation."
            )
            return {"supported": False, "message": message}
        return {
            "supported": True,
            **state,
            "message": f"{state['branch']} · {state['revision']}. Ready to pull from {state['upstream']}.",
        }

    def pull(self) -> dict:
        if not self.lock.acquire(blocking=False):
            raise ConfigurationError("An update is already running.")
        try:
            state = self._preflight()
            remote = self._git("config", "--get", f"branch.{state['branch']}.remote")
            if remote == "." or remote.startswith("-"):
                raise ConfigurationError("Choose a remote tracking branch before updating.")
            before = self._git("rev-parse", "HEAD")
            self._git("fetch", "--no-tags", "--", remote)
            target = self._git("rev-parse", "@{upstream}^{commit}")
            if before == target:
                return {"updated": False, "message": "Already up to date."}
            if self._git("merge-base", "HEAD", target) != before:
                raise ConfigurationError(
                    "The local branch has its own commits. Review it in Git; only fast-forward updates are allowed."
                )
            # Reject upstream trees that could introduce tracked settings, credentials,
            # virtual environments or files into the active data directory.
            files = (
                self._git("ls-tree", "-rz", "--name-only", before)
                + "\0"
                + self._git("ls-tree", "-rz", "--name-only", target)
            ).split("\0")
            for filename in files:
                if not filename:
                    continue
                path = (self.root / filename).resolve()
                first = filename.split("/", 1)[0].casefold()
                if (
                    first in {".data", ".venv", ".env"}
                    or first.startswith(".data.")
                    or path == self.data_dir
                    or path.is_relative_to(self.data_dir)
                ):
                    raise ConfigurationError(
                        "Update refused: the incoming revision contains protected local-data paths."
                    )
            changed = self._git("diff", "--name-only", before, target).splitlines()
            # Recheck after the network request. Never stash, reset, clean or force.
            self._preflight()
            if self._git("rev-parse", "HEAD") != before:
                raise ConfigurationError(
                    "The checkout changed during the update. Try again after Git work finishes."
                )
            self._git("merge", "--ff-only", "--no-overwrite-ignore", target)
            dependencies = any(
                name in {"pyproject.toml", "uv.lock", "requirements.txt"} for name in changed
            )
            return {
                "updated": True,
                "message": "Source updated. Settings and credentials were left untouched. "
                + (
                    "Dependencies changed: rerun the native installer before restarting Codester."
                    if dependencies
                    else "Restart Codester to load the new version."
                ),
            }
        except (OSError, subprocess.SubprocessError) as error:
            raise ConfigurationError(
                "Update could not finish or timed out. Check Git status before retrying; no reset or cleanup was attempted."
            ) from error
        finally:
            self.lock.release()
