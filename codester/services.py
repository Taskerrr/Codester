"""Saved, user-controlled commands run through existing SSH identities."""

import copy
import hashlib
import json
import re
import shlex
import sqlite3
import subprocess
import threading
import time
import uuid
from contextlib import closing
from io import BufferedReader

from codester.store import ConfigurationError, Store
from codester.tunnels import TunnelManager

OUTPUT_LIMIT = 65536
COMMAND_TIMEOUT = 600


def validate_service(data: dict, hosts: list[dict]) -> dict:
    if not isinstance(data, dict):
        raise ConfigurationError("Supply a service configuration.")
    result: dict = {}
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
            return self._start_script(identifier, host, service["path"], script, label)

    def _start_script(
        self, identifier: str, host: dict, path: str, script: str, label: str,
        *, timeout: int | None = None,
    ) -> dict:
        """Start one saved command under the shared execution lock."""
        with self.lock:
            if self.actions.get(identifier, {}).get("state") == "running":
                raise ConfigurationError("An update is already running for this repository.")
            args, environment = self.tunnels.remote_session(
                host, f"cd {shlex.quote(path)} && {{\n{script}\n}}"
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
                "path": path,
                "host": host["ssh_host"],
                "started_at": time.time(),
                "output": "",
                "message": "Running",
                "truncated": False,
                "timeout": COMMAND_TIMEOUT if timeout is None else timeout,
            }
            self._persist(identifier)
            threading.Thread(
                target=self._run, args=(identifier, args, environment, password), daemon=True
            ).start()
            return copy.deepcopy(self.actions[identifier])

    @staticmethod
    def repository_script(repository: dict) -> str:
        """Resolve the configured action without reading or executing remote files."""
        if repository.get("update_mode", "command") != "script":
            return repository.get("update_script", "")
        path = repository.get("update_script_file", "")
        if not path:
            return ""
        script = shlex.quote("./" + path)
        lines = [
            "set -euo pipefail",
            'prefix=$(git rev-parse --show-prefix)',
            'test -z "$prefix" || { echo "Use the repository root as Server folder." >&2; exit 1; }',
            'exec 9> "$(git rev-parse --git-path codester-deploy.lock)"',
            'flock -n 9 || { echo "A deployment is already running in this checkout." >&2; exit 1; }',
            'changes=$(git status --porcelain)',
            'test -z "$changes" || { echo "Checkout has uncommitted changes. Commit or remove them before deploying." >&2; exit 1; }',
        ]
        if repository.get("update_pull"):
            lines += ['printf "Pulling latest commit…\\n"', "git pull --ff-only"]
        lines += [
            f"git ls-files --error-unmatch -- {script} >/dev/null",
            f'test -f {script} || {{ echo "Deployment script is missing." >&2; exit 1; }}',
            f'test ! -L {script} || {{ echo "Deployment script must not be a symbolic link." >&2; exit 1; }}',
            'CODESTER_DEPLOY_COMMIT=$(git rev-parse HEAD)',
            "export CODESTER_DEPLOY_COMMIT",
            'printf "Deploying commit %s\\n" "$CODESTER_DEPLOY_COMMIT"',
            f"bash -e -o pipefail -- {script}",
        ]
        # A fresh shell keeps fail-fast semantics even inside the runner's cd && group.
        return "bash -c " + shlex.quote("\n".join(lines))

    @staticmethod
    def repository_revision(repository: dict, host: dict | None) -> str:
        target = {
            key: repository.get(key)
            for key in ("repo", "update_host_id", "update_path", "update_script", "update_confirm",
                        "update_mode", "update_script_file", "update_pull")
        }
        target["host"] = host
        return hashlib.sha256(json.dumps(target, sort_keys=True).encode()).hexdigest()

    def repository_updates(self) -> dict:
        config = self.store.read()
        rows = []
        with self.lock:
            for repository in config["github"]["repositories"]:
                host = next(
                    (
                        row
                        for row in config["tunnels"]
                        if row["id"] == repository.get("update_host_id")
                    ),
                    None,
                )
                rows.append(
                    {
                        "id": repository["id"],
                        "repo": repository["repo"],
                        "url": config["github"]["browser_url"].rstrip("/")
                        + "/"
                        + repository["repo"],
                        "configured": bool(self.repository_script(repository) and host),
                        "target": f"{host['username']}@{host['ssh_host']}:{host['ssh_port']}"
                        if host
                        else "",
                        "path": repository.get("update_path", ""),
                        "script": self.repository_script(repository),
                        "mode": repository.get("update_mode", "command"),
                        "script_file": repository.get("update_script_file", ""),
                        "pull": repository.get("update_pull", False),
                        "confirm": repository.get("update_confirm", False),
                        "revision": self.repository_revision(repository, host),
                        "action": copy.deepcopy(self.actions.get("github:" + repository["id"])),
                    }
                )
        return {"repositories": rows, "demo": config["demo"]}

    def start_repository(self, identifier: str, revision: str, *, confirmed: bool = False) -> dict:
        with self.lock:
            config = self.store.read()
            if config["demo"]:
                raise ConfigurationError(
                    "Turn off demo mode in Settings before updating a repository."
                )
            repository = next(
                (row for row in config["github"]["repositories"] if row["id"] == identifier), None
            )
            if repository is None:
                raise ConfigurationError("Repository is no longer configured.")
            host = next(
                (row for row in config["tunnels"] if row["id"] == repository.get("update_host_id")),
                None,
            )
            script = self.repository_script(repository)
            if host is None or not script:
                raise ConfigurationError(
                    "Configure an SSH connection and update script in Settings."
                )
            if revision != self.repository_revision(repository, host):
                raise ConfigurationError(
                    "Update settings changed. Review the target and try again."
                )
            if repository.get("update_confirm") and not confirmed:
                raise ConfigurationError("Confirm this repository update before running it.")
            return self._start_script(
                "github:" + identifier,
                host,
                repository["update_path"],
                script,
                ("Deploy " if repository.get("update_mode") == "script" else "Update ") + repository["repo"],
                timeout=1800 if repository.get("update_mode") == "script" else COMMAND_TIMEOUT,
            )

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
                assert process is not None and isinstance(process.stdout, BufferedReader)
                while chunk := process.stdout.read1(4096):
                    with self.lock:
                        output = action["output"] + chunk.decode("utf-8", errors="replace")
                        if password:
                            output = output.replace(password, "[redacted]")
                        action["truncated"] |= len(output) > OUTPUT_LIMIT
                        action["output"] = output[-OUTPUT_LIMIT:]

            reader = threading.Thread(target=collect, daemon=True)
            reader.start()
            timeout = action.get("timeout", COMMAND_TIMEOUT)
            code = process.wait(timeout=timeout)
            reader.join(timeout=2)
            state = "success" if code == 0 else "unknown" if code == 255 else "error"
            message = (
                "Command finished successfully. Check the output for deployment and health results."
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
                f"Timed out after {action.get('timeout', COMMAND_TIMEOUT) // 60} minutes. The remote command may still be running; check the server.",
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
