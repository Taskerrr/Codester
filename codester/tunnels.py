"""Managed loopback-only OpenSSH forwards with keepalives and reconnects."""

import os
import shutil
import socket
import subprocess
import sysconfig
import threading
import time
from pathlib import Path
from typing import Any

from codester.store import ConfigurationError
from codester.subprocesses import hidden_subprocess_creation_flags
from codester.transport import IntegrationError


def password_helper() -> str | None:
    """Direct launches need not activate the environment or modify PATH."""
    filename = "codester-askpass.exe" if os.name == "nt" else "codester-askpass"
    installed = Path(sysconfig.get_path("scripts")) / filename
    if installed.is_file() and os.access(installed, os.X_OK):
        return str(installed.resolve())
    return shutil.which("codester-askpass")


class TunnelManager:
    def __init__(self, directory: Path, tunnels: list[dict], *, autostart: bool = True):
        self.data_directory = directory
        self.directory = directory / "ssh"
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            self.directory.chmod(0o700)
        self.known_hosts = self.directory / "known_hosts"
        self.ssh = shutil.which("ssh")
        self.askpass = password_helper()
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.stopping = threading.Event()
        self.desired = False
        self.items: dict[str, dict[str, Any]] = {}
        self.thread: threading.Thread | None = None
        self.configure(tunnels)
        if autostart:
            self.thread = threading.Thread(target=self._run, name="ssh-tunnels", daemon=True)
            self.thread.start()

    def configure(self, tunnels: list[dict]) -> None:
        with self.lock:
            if [item["config"] for item in self.items.values()] == tunnels:
                return
            previous = {item["config"]["id"]: item for item in self.items.values()}
            unchanged = {
                tunnel["id"] for tunnel in tunnels
                if tunnel["id"] in previous and previous[tunnel["id"]]["config"] == tunnel
            }
            for identifier, item in previous.items():
                if identifier not in unchanged:
                    self._stop_process(item)
            self.items = {
                tunnel["name"]: previous[tunnel["id"]] if tunnel["id"] in unchanged else {
                    "config": tunnel.copy(),
                    "process": None,
                    "started": None,
                    "failures": 0,
                    "retry_at": 0.0,
                    "message": "",
                    "ever_connected": False,
                    "blocked": False,
                    "desired": previous[tunnel["id"]]["desired"] if tunnel["id"] in previous else self.desired,
                }
                for tunnel in tunnels
            }
            self.desired = any(item["desired"] for item in self.items.values())
        self.wake.set()

    def _selected(self, identifier: str | None) -> list[dict[str, Any]]:
        if identifier is None:
            return list(self.items.values())
        selected = [item for item in self.items.values() if item["config"]["id"] == identifier]
        if not selected:
            raise ConfigurationError("This SSH tunnel no longer exists. Refresh and try again.")
        return selected

    def connect(self, identifier: str | None = None) -> dict:
        with self.lock:
            selected = self._selected(identifier)
            if not self.items:
                raise ConfigurationError("Add and save at least one SSH tunnel first.")
            if not self.ssh:
                raise ConfigurationError("OpenSSH is not installed or is not available on PATH.")
            if any(item["config"]["auth"] == "password" for item in selected) and not self.askpass:
                raise ConfigurationError("The Codester SSH password helper is unavailable.")
            self.desired = True
            for item in selected:
                item["desired"] = True
                item["retry_at"] = 0.0
                item["message"] = ""
                item["blocked"] = False
            self._reconcile()
            result = self.status()
        self.wake.set()
        return result

    def disconnect(self, identifier: str | None = None) -> dict:
        with self.lock:
            for item in self._selected(identifier):
                item["desired"] = False
                self._stop_process(item)
            self.desired = any(item["desired"] for item in self.items.values())
            return self.status()

    def test(self, identifier: str) -> dict:
        active_port: int | None = None
        with self.lock:
            item = next(
                (entry for entry in self.items.values() if entry["config"]["id"] == identifier),
                None,
            )
            if item is None:
                raise ConfigurationError("Save this SSH tunnel before testing it.")
            config = item["config"].copy()
            process = item["process"]
            if process is not None and process.poll() is None and item["ever_connected"]:
                active_port = config["local_port"]
        if active_port is not None:
            try:
                with socket.create_connection(("127.0.0.1", active_port), timeout=2):
                    return {"ok": True, "message": "Connected and responding."}
            except OSError as exc:
                raise IntegrationError(
                    "SSH is connected, but the forwarded service did not respond."
                ) from exc
        if not self.ssh:
            raise ConfigurationError("OpenSSH is not installed or is not available on PATH.")
        if config["auth"] == "password" and not self.askpass:
            raise ConfigurationError("The Codester SSH password helper is unavailable.")
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            test_port = reservation.getsockname()[1]
        config["local_port"] = test_port
        process = subprocess.Popen(  # noqa: S603
            self._command(config),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            start_new_session=os.name != "nt",
            env=self._environment(config),
            creationflags=hidden_subprocess_creation_flags(),
        )
        deadline = time.monotonic() + 15
        try:
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    stderr = process.communicate()[1] or b""
                    detail = " ".join(stderr.decode(errors="replace").split())[:300]
                    raise IntegrationError(detail or "SSH authentication failed.")
                try:
                    with socket.create_connection(("127.0.0.1", test_port), timeout=0.4):
                        return {"ok": True, "message": "SSH and forwarded service responded."}
                except OSError:
                    time.sleep(0.2)
            raise IntegrationError("SSH connected, but the forwarded service did not respond.")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)

    def status(self) -> dict:
        with self.lock:
            now = time.monotonic()
            rows = []
            for item in self.items.values():
                process = item["process"]
                alive = process is not None and process.poll() is None
                settled = alive and item["started"] is not None and now - item["started"] >= 12
                if item["blocked"]:
                    state = "error"
                elif not item["desired"]:
                    state = "disconnected"
                elif settled:
                    state = "connected"
                elif alive:
                    state = "connecting"
                else:
                    state = "reconnecting"
                rows.append(
                    {
                        "id": item["config"]["id"],
                        "name": item["config"]["name"],
                        "local_port": item["config"]["local_port"],
                        "ssh_host": item["config"]["ssh_host"],
                        "remote_host": item["config"]["remote_host"],
                        "remote_port": item["config"]["remote_port"],
                        "desired": item["desired"],
                        "state": state,
                        "message": item["message"],
                    }
                )
            states = {row["state"] for row in rows}
            if not rows:
                state = "unconfigured"
            elif states == {"error"}:
                state = "error"
            elif not self.desired:
                state = "disconnected"
            elif states == {"connected"}:
                state = "connected"
            elif "connected" in states:
                state = "partial"
            elif "connecting" in states:
                state = "connecting"
            else:
                state = "reconnecting"
            return {"state": state, "desired": self.desired, "tunnels": rows}

    def stop(self) -> None:
        self.stopping.set()
        self.wake.set()
        with self.lock:
            self.desired = False
            self._stop_processes()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=2)

    def _command(self, config: dict) -> list[str]:
        assert self.ssh
        password_auth = config["auth"] == "password"
        command = [
            self.ssh,
            "-N",
            "-T",
            "-o",
            f"BatchMode={'no' if password_auth else 'yes'}",
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            "ServerAliveInterval=30",
            "-o",
            "ServerAliveCountMax=3",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            f"UserKnownHostsFile={self.known_hosts}",
        ]
        if password_auth:
            command.extend(
                [
                    "-o",
                    "PreferredAuthentications=password,keyboard-interactive",
                    "-o",
                    "PubkeyAuthentication=no",
                    "-o",
                    "NumberOfPasswordPrompts=1",
                ]
            )
        command.extend(
            [
                "-p",
                str(config["ssh_port"]),
                "-L",
                (
                    f"127.0.0.1:{config['local_port']}:"
                    f"{config['remote_host']}:{config['remote_port']}"
                ),
                f"{config['username']}@{config['ssh_host']}",
            ]
        )
        return command

    def remote_session(self, config: dict, script: str) -> tuple[list[str], dict[str, str]]:
        """Reuse the saved SSH identity without creating or changing any forwards."""
        if not self.ssh:
            raise ConfigurationError("OpenSSH is not installed or is not available on PATH.")
        if config["auth"] == "password" and not self.askpass:
            raise ConfigurationError("The Codester SSH password helper is unavailable.")
        command = self._command(config)
        command.remove("-N")
        index = command.index("-L")
        del command[index:index + 2]
        command.append(script)
        return command, self._environment(config)

    def _environment(self, config: dict) -> dict[str, str]:
        environment = os.environ.copy()
        if config["auth"] == "password":
            assert self.askpass
            environment.update(
                SSH_ASKPASS=self.askpass,
                SSH_ASKPASS_REQUIRE="force",
                DISPLAY=environment.get("DISPLAY", "codester"),
                CODESTER_DATA_DIR=str(self.data_directory.resolve()),
                CODESTER_SSH_SECRET=f"tunnel-password:{config['id']}",
            )
        return environment

    def _launch(self, item: dict[str, Any], now: float) -> None:
        try:
            item["process"] = subprocess.Popen(  # noqa: S603
                self._command(item["config"]),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                start_new_session=os.name != "nt",
                env=self._environment(item["config"]),
                creationflags=hidden_subprocess_creation_flags(),
            )
            item["started"] = now
            item["message"] = ""
        except OSError:
            item["process"] = None
            item["failures"] += 1
            item["retry_at"] = now + min(60, 2 ** min(item["failures"], 6))
            item["message"] = "Could not start OpenSSH."

    def _reconcile(self) -> None:
        now = time.monotonic()
        for item in self.items.values():
            process = item["process"]
            if (
                process is not None
                and process.poll() is None
                and item["started"] is not None
                and now - item["started"] >= 12
            ):
                item["ever_connected"] = True
            if process is not None and process.poll() is not None:
                code = process.returncode
                stderr = process.communicate()[1] or b""
                detail = " ".join(stderr.decode(errors="replace").split())[:300]
                item["process"] = None
                item["started"] = None
                item["failures"] += 1
                item["blocked"] = not item["ever_connected"]
                item["retry_at"] = (
                    float("inf")
                    if item["blocked"]
                    else now + min(60, 2 ** min(item["failures"], 6))
                )
                auth_hint = (
                    "saved password" if item["config"]["auth"] == "password" else "SSH agent key"
                )
                item["message"] = detail or (
                    f"SSH exited ({code}). Check the host, network, and {auth_hint}."
                )
            if (
                item["desired"]
                and not item["blocked"]
                and item["process"] is None
                and now >= item["retry_at"]
            ):
                self._launch(item, now)
            elif not item["desired"] and item["process"] is not None:
                self._stop_process(item)
            if item["blocked"]:
                item["desired"] = False
        self.desired = any(item["desired"] for item in self.items.values())

    def _stop_process(self, item: dict[str, Any]) -> None:
        process = item["process"]
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        item["process"] = None
        item["started"] = None
        item["failures"] = 0
        item["retry_at"] = 0.0
        item["message"] = ""
        item["blocked"] = False

    def _stop_processes(self) -> None:
        for item in self.items.values():
            item["desired"] = False
            self._stop_process(item)

    def _run(self) -> None:
        while not self.stopping.is_set():
            with self.lock:
                self._reconcile()
            self.wake.wait(timeout=1)
            self.wake.clear()
