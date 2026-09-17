"""Saved, user-controlled commands run through existing SSH identities."""

import copy
import json
import re
import shlex
import sqlite3
import subprocess
import threading
import time
import uuid
from contextlib import closing

from codester.store import ConfigurationError, Store
from codester.tunnels import TunnelManager

OUTPUT_LIMIT = 65536
COMMAND_TIMEOUT = 600


def validate_service(data: dict, hosts: list[dict]) -> dict:
    if not isinstance(data, dict):
        raise ConfigurationError("Supply a service configuration.")
    result = {}
    for field, limit in {"name": 80, "path": 1024, "branch": 200, "notes": 8000}.items():
        value = data.get(field, "main" if field == "branch" else "")
        if not isinstance(value, str) or len(value) > limit or "\x00" in value:
            raise ConfigurationError(f"Invalid service {field}.")
        result[field] = value.strip()
    if not result["name"] or not result["path"]:
        raise ConfigurationError("Give the service a name and server folder.")
    branch = result["branch"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", branch):
        raise ConfigurationError("Choose a comparison branch, such as main.")
    host_id = data.get("host_id")
    if not any(host["id"] == host_id for host in hosts):
        raise ConfigurationError("Choose a saved SSH connection.")
    result["host_id"] = host_id
    commands = data.get("commands", [])
    if not isinstance(commands, list) or len(commands) > 20:
        raise ConfigurationError("Use at most 20 commands per service.")
    result["commands"] = []
    identifiers = set()
    for command in commands:
        if not isinstance(command, dict):
            raise ConfigurationError("Invalid command.")
        identifier = command.get("id", "")
        label = command.get("label", "")
        script = command.get("script", "")
        confirm = command.get("confirm", False)
        if (
            not isinstance(identifier, str)
            or not re.fullmatch(r"[a-f0-9-]{16,64}", identifier)
            or identifier in identifiers
            or not isinstance(label, str)
            or not label.strip()
            or len(label) > 80
            or not isinstance(script, str)
            or not script.strip()
            or len(script) > 8000
            or "\x00" in script
            or not isinstance(confirm, bool)
        ):
            raise ConfigurationError("Give each command a unique ID, name and command text.")
        identifiers.add(identifier)
        result["commands"].append(
            {"id": identifier, "label": label.strip(), "script": script, "confirm": confirm}
        )
    return result


class ServiceManager:
    def __init__(self, store: Store, tunnels: TunnelManager):
        self.store = store
        self.tunnels = tunnels
        self.lock = threading.RLock()
        self.actions: dict[str, dict] = {}
        with closing(sqlite3.connect(store.path)) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS services (id TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS service_actions (id TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            for identifier, value in db.execute("SELECT id, value FROM service_actions").fetchall():
                action = json.loads(value)
                if action["state"] == "running":
                    action.update(
                        state="unknown",
                        message="Codester restarted. Check the server before running again.",
                    )
                    db.execute(
                        "UPDATE service_actions SET value=? WHERE id=?",
                        (json.dumps(action), identifier),
                    )
                self.actions[identifier] = action

    def configured(self) -> list[dict]:
        with closing(sqlite3.connect(self.store.path)) as db:
            return [
                dict(json.loads(value), id=identifier)
                for identifier, value in db.execute("SELECT id, value FROM services ORDER BY rowid")
            ]

    def snapshot(self) -> dict:
        config = self.store.read()
        hosts = [
            {key: host[key] for key in ("id", "name", "ssh_host", "username", "ssh_port")}
            for host in config["tunnels"]
        ]
        with self.lock:
            return {
                "services": self.configured(),
                "hosts": hosts,
                "actions": copy.deepcopy(self.actions),
                "dagster_url": config["dagster"]["browser_url"] or config["dagster"]["api_url"],
            }

    def save(self, identifier: str, data: dict) -> dict:
        service = validate_service(data, self.store.read()["tunnels"])
        with self.lock, closing(sqlite3.connect(self.store.path)) as db, db:
            if self.actions.get(identifier, {}).get("state") == "running":
                raise ConfigurationError(
                    "Wait for this service's command to finish before editing it."
                )
            db.execute(
                "INSERT OR REPLACE INTO services VALUES (?, ?)", (identifier, json.dumps(service))
            )
        return dict(service, id=identifier)

    def delete(self, identifier: str) -> None:
        with self.lock, closing(sqlite3.connect(self.store.path)) as db, db:
            if self.actions.get(identifier, {}).get("state") == "running":
                raise ConfigurationError(
                    "Wait for this service's command to finish before removing it."
                )
            db.execute("DELETE FROM services WHERE id=?", (identifier,))
            db.execute("DELETE FROM service_actions WHERE id=?", (identifier,))
            self.actions.pop(identifier, None)

    def _persist(self, identifier: str) -> None:
        with closing(sqlite3.connect(self.store.path)) as db, db:
            db.execute(
                "INSERT OR REPLACE INTO service_actions VALUES (?, ?)",
                (identifier, json.dumps(self.actions[identifier])),
            )

    def start(self, identifier: str, command_id: str, *, confirmed: bool = False) -> dict:
        with self.lock:
            service = next((row for row in self.configured() if row["id"] == identifier), None)
            if service is None:
                raise ConfigurationError("Service no longer exists.")
            if self.actions.get(identifier, {}).get("state") == "running":
                raise ConfigurationError("A command is already running for this service.")
            config = self.store.read()
            host = next((row for row in config["tunnels"] if row["id"] == service["host_id"]), None)
            if host is None:
                raise ConfigurationError(
                    "The saved SSH connection was removed. Choose another in Edit."
                )
            if command_id == "git-status":
                script = self.git_status_script(service["branch"])
                label = "Compare server Git checkout"
            else:
                command = next(
                    (row for row in service["commands"] if row["id"] == command_id), None
                )
                if command is None:
                    raise ConfigurationError("Command no longer exists.")
                if command["confirm"] and not confirmed:
                    raise ConfigurationError("Confirm this command before running it.")
                script, label = command["script"], command["label"]
            args, environment = self.tunnels.remote_session(
                host, f"cd {shlex.quote(service['path'])} && {{\n{script}\n}}"
            )
            password = (
                self.store.secret(f"tunnel-password:{host['id']}")
                if host["auth"] == "password"
                else ""
            )
            self.actions[identifier] = {
                "run_id": uuid.uuid4().hex,
                "state": "running",
                "label": label,
                "script": script,
                "path": service["path"],
                "host": host["ssh_host"],
                "started_at": time.time(),
                "output": "",
                "message": "Running",
                "truncated": False,
            }
            self._persist(identifier)
            threading.Thread(
                target=self._run, args=(identifier, args, environment, password), daemon=True
            ).start()
            return copy.deepcopy(self.actions[identifier])

    @staticmethod
    def git_status_script(branch: str) -> str:
        reference = shlex.quote(f"refs/remotes/origin/{branch}")
        return (
            "git status --short --branch && git log -1 --format='%h %s' && "
            "printf '\\nServer HEAD vs upstream (ahead behind):\\n' && "
            "{ git rev-list --left-right --count 'HEAD...@{upstream}' || true; } && "
            f"printf '\\nServer HEAD vs origin/{branch} (ahead behind):\\n' && "
            f"git rev-list --left-right --count HEAD...{reference}"
        )

    def _run(self, identifier: str, args: list[str], environment: dict, password: str) -> None:
        process = None
        reader = None
        action = self.actions[identifier]
        try:
            process = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=environment,
            )  # noqa: S603

            def collect() -> None:
                assert process is not None and process.stdout is not None
                while chunk := process.stdout.read1(4096):
                    with self.lock:
                        output = action["output"] + chunk.decode("utf-8", errors="replace")
                        if password:
                            output = output.replace(password, "[redacted]")
                        action["truncated"] |= len(output) > OUTPUT_LIMIT
                        action["output"] = output[-OUTPUT_LIMIT:]

            reader = threading.Thread(target=collect, daemon=True)
            reader.start()
            code = process.wait(timeout=COMMAND_TIMEOUT)
            reader.join(timeout=2)
            state = "success" if code == 0 else "unknown" if code == 255 else "error"
            message = (
                "Command finished. Reload and health checks are separate."
                if code == 0
                else "SSH ended unexpectedly. Check the server before retrying."
                if code == 255
                else f"Command exited with code {code}."
            )
        except subprocess.TimeoutExpired:
            assert process is not None
            process.kill()
            process.wait(timeout=5)
            state, message = (
                "unknown",
                "Timed out after 10 minutes. The remote command may still be running; check the server.",
            )
        except OSError:
            state, message = "error", "Could not start SSH."
        finally:
            if reader is not None:
                reader.join(timeout=2)
            if (
                process is not None
                and process.stdout is not None
                and (reader is None or not reader.is_alive())
            ):
                process.stdout.close()
        with self.lock:
            self.actions[identifier].update(state=state, message=message, finished_at=time.time())
            self._persist(identifier)
