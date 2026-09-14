"""Per-installation settings, encrypted secrets, and strict configuration validation."""

import copy
import csv
import json
import os
import re
import sqlite3
import subprocess
import threading
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.fernet import Fernet

DEFAULTS: dict = {
    "demo": True,
    "dashboard_apps": ["codex", "dagster", "signoz"],
    "codex": {"enabled": False, "activity": False},
    "dagster": {"enabled": False, "api_url": "", "browser_url": ""},
    "signoz": {
        "enabled": False,
        "api_url": "",
        "browser_url": "",
        "error_service": "",
        "panels": [{"service": "", "metric": m} for m in ["request_rate", "error_rate", "p95"]],
    },
    "tunnels": [],
}
METRICS = {"request_rate": "Request rate", "error_rate": "Error rate", "p95": "p95 latency"}
DASHBOARD_APPS = frozenset(
    {"codex", "dagster", "signoz", "postgres", "server", "github", "docker"}
)


class ConfigurationError(ValueError):
    """Invalid local settings, safe to show in the settings form."""


def restrict_windows_directory(directory: Path) -> None:
    identity = subprocess.run(
        ["whoami", "/user", "/fo", "csv", "/nh"], check=True, capture_output=True, text=True
    )
    rows = list(csv.reader(identity.stdout.strip().splitlines()))
    if len(rows) != 1 or len(rows[0]) != 2 or not re.fullmatch(r"S-[0-9-]+", rows[0][1]):
        raise RuntimeError("Cannot determine Windows user SID for private settings storage.")
    subprocess.run(
        ["icacls", str(directory), "/inheritance:r", "/grant:r", f"*{rows[0][1]}:(OI)(CI)F"],
        check=True,
        capture_output=True,
    )


def valid_url(value: object) -> str:
    if not isinstance(value, str) or len(value) > 2048:
        raise ConfigurationError("Enter a valid HTTP or HTTPS base URL.")
    value = value.strip().rstrip("/")
    if not value:
        return ""
    try:
        parts = urlsplit(value)
        _ = parts.port
    except ValueError as exc:
        raise ConfigurationError("Invalid URL host or port.") from exc
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or any(c.isspace() for c in value)
    ):
        raise ConfigurationError("Use an HTTP(S) base URL without credentials, query, or fragment.")
    return value


def service_name(value: object) -> str:
    if not isinstance(value, str) or len(value) > 200 or any(ord(c) < 32 for c in value):
        raise ConfigurationError("Service names must be text of at most 200 characters.")
    return value


def tunnel_text(value: object, label: str, pattern: str, maximum: int = 200) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or not re.fullmatch(pattern, value.strip())
    ):
        raise ConfigurationError(f"Enter a valid tunnel {label}.")
    return value.strip()


def tunnel_port(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        raise ConfigurationError(f"Tunnel {label} must be between 1 and 65535.")
    return value


def tunnel_identifier(tunnel: dict) -> str:
    value = tunnel.get("id")
    if value is not None:
        if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9-]{16,64}", value):
            raise ConfigurationError("Invalid SSH tunnel identifier.")
        return value
    basis = "|".join(
        str(tunnel.get(field, ""))
        for field in ("name", "ssh_host", "ssh_port", "username", "local_port")
    )
    return uuid.uuid5(uuid.NAMESPACE_URL, f"codester:ssh:{basis}").hex


def validate(data: object) -> dict:
    if not isinstance(data, dict):
        raise ConfigurationError("Settings must be a JSON object.")
    result = copy.deepcopy(DEFAULTS)
    if not isinstance(data.get("demo"), bool):
        raise ConfigurationError("Choose demo or live mode.")
    result["demo"] = data["demo"]
    dashboard_apps = data.get("dashboard_apps", DEFAULTS["dashboard_apps"])
    if (
        not isinstance(dashboard_apps, list)
        or len(dashboard_apps) != 3
        or any(not isinstance(app, str) or app not in DASHBOARD_APPS for app in dashboard_apps)
        or len(set(dashboard_apps)) != 3
    ):
        raise ConfigurationError("Choose three different dashboard apps.")
    result["dashboard_apps"] = dashboard_apps
    for name in ("codex", "dagster", "signoz"):
        item = data.get(name)
        if not isinstance(item, dict) or not isinstance(item.get("enabled"), bool):
            raise ConfigurationError(f"Choose whether to enable {name}.")
        result[name]["enabled"] = item["enabled"]
        if name == "codex":
            if not isinstance(item.get("activity"), bool):
                raise ConfigurationError("Choose whether to read local Codex activity.")
            result[name]["activity"] = item["activity"]
            continue
        for field in ("api_url", "browser_url"):
            result[name][field] = valid_url(item.get(field, ""))
        if item["enabled"] and not result[name]["api_url"]:
            raise ConfigurationError(f"Enter the {name} API URL before enabling it.")
    panels = data["signoz"].get("panels", [])
    if not isinstance(panels, list) or len(panels) > 3:
        raise ConfigurationError("Choose up to three SigNoz measurements.")
    result["signoz"]["panels"] = []
    for panel in panels:
        if not isinstance(panel, dict) or panel.get("metric") not in METRICS:
            raise ConfigurationError("Choose a supported SigNoz measurement.")
        result["signoz"]["panels"].append(
            {
                "service": service_name(panel.get("service", "")),
                "metric": panel["metric"],
            }
        )
    result["signoz"]["error_service"] = service_name(data["signoz"].get("error_service", ""))
    tunnels = data.get("tunnels", [])
    if not isinstance(tunnels, list) or len(tunnels) > 20:
        raise ConfigurationError("Add no more than 20 SSH tunnels.")
    result["tunnels"] = []
    names: set[str] = set()
    local_ports: set[int] = set()
    identifiers: set[str] = set()
    for tunnel in tunnels:
        if not isinstance(tunnel, dict):
            raise ConfigurationError("Each SSH tunnel must be an object.")
        name = tunnel_text(tunnel.get("name"), "name", r"[^\x00-\x1f\x7f]+", 80)
        identifier = tunnel_identifier(tunnel)
        auth = tunnel.get("auth", "agent")
        if auth not in {"agent", "password"}:
            raise ConfigurationError("Choose SSH agent or password authentication.")
        ssh_host = tunnel_text(tunnel.get("ssh_host"), "SSH host", r"[A-Za-z0-9._-]+", 253)
        username = tunnel_text(tunnel.get("username"), "username", r"[A-Za-z0-9._-]+", 64)
        remote_host = tunnel_text(
            tunnel.get("remote_host"), "remote host", r"[A-Za-z0-9._-]+", 253
        )
        ssh_port = tunnel_port(tunnel.get("ssh_port"), "SSH port")
        local_port = tunnel_port(tunnel.get("local_port"), "local port")
        remote_port = tunnel_port(tunnel.get("remote_port"), "remote port")
        normalized_name = name.casefold()
        if normalized_name in names:
            raise ConfigurationError("SSH tunnel names must be different.")
        if local_port in local_ports:
            raise ConfigurationError("Each SSH tunnel needs a different local port.")
        if identifier in identifiers:
            raise ConfigurationError("Invalid duplicate SSH tunnel identifier.")
        names.add(normalized_name)
        local_ports.add(local_port)
        identifiers.add(identifier)
        result["tunnels"].append(
            {
                "id": identifier,
                "name": name,
                "auth": auth,
                "ssh_host": ssh_host,
                "ssh_port": ssh_port,
                "username": username,
                "local_port": local_port,
                "remote_host": remote_host,
                "remote_port": remote_port,
            }
        )
    return result


class Store:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name == "nt":
            restrict_windows_directory(directory)
        else:
            directory.chmod(0o700)
        self.path = directory / "settings.sqlite"
        self.lock = threading.RLock()
        key_path = directory / "secret.key"
        if not key_path.exists():
            # Exclusive creation prevents two starters from replacing each other's encryption key.
            with key_path.open("xb") as handle:
                if os.name != "nt":
                    key_path.chmod(0o600)
                handle.write(Fernet.generate_key())
        self.cipher = Fernet(key_path.read_bytes())
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, value TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS secrets (name TEXT PRIMARY KEY, value BLOB)")
            db.execute("INSERT OR IGNORE INTO settings VALUES (1, ?)", (json.dumps(DEFAULTS),))
        if os.name != "nt":
            self.path.chmod(0o600)

    def read(self) -> dict:
        with self.lock, sqlite3.connect(self.path) as db:
            data = json.loads(db.execute("SELECT value FROM settings WHERE id=1").fetchone()[0])
        data.setdefault("dashboard_apps", list(DEFAULTS["dashboard_apps"]))
        data.setdefault("tunnels", [])
        for tunnel in data["tunnels"]:
            tunnel.setdefault("id", tunnel_identifier(tunnel))
            tunnel.setdefault("auth", "agent")
        return data

    def public(self) -> dict:
        data = self.read()
        data["signoz"]["has_key"] = bool(self.secret("signoz"))
        for tunnel in data["tunnels"]:
            tunnel["has_password"] = bool(
                self.secret(f"tunnel-password:{tunnel_identifier(tunnel)}")
            )
        return data

    def secret(self, name: str) -> str:
        with self.lock, sqlite3.connect(self.path) as db:
            row = db.execute("SELECT value FROM secrets WHERE name=?", (name,)).fetchone()
            return self.cipher.decrypt(row[0]).decode() if row else ""

    def save(self, data: object) -> None:
        settings = validate(data)
        assert isinstance(data, dict)
        key = data["signoz"].get("api_key", "")
        clear = data["signoz"].get("clear_key", False)
        if not isinstance(key, str) or len(key) > 8192 or "\n" in key or "\r" in key:
            raise ConfigurationError("Invalid API key.")
        if not isinstance(clear, bool):
            raise ConfigurationError("Invalid key removal choice.")
        raw_tunnels = data.get("tunnels", [])
        assert isinstance(raw_tunnels, list)
        # Blank means preserve, explicit clear means delete.
        with self.lock, sqlite3.connect(self.path) as db:
            retained_secrets: set[str] = set()
            for raw, tunnel in zip(raw_tunnels, settings["tunnels"], strict=True):
                assert isinstance(raw, dict)
                password = raw.get("password", "")
                clear_password = raw.get("clear_password", False)
                if (
                    not isinstance(password, str)
                    or len(password) > 4096
                    or "\n" in password
                    or "\r" in password
                ):
                    raise ConfigurationError("Invalid SSH password.")
                if not isinstance(clear_password, bool):
                    raise ConfigurationError("Invalid SSH password removal choice.")
                secret_name = f"tunnel-password:{tunnel['id']}"
                retained_secrets.add(secret_name)
                existing = db.execute(
                    "SELECT 1 FROM secrets WHERE name=?", (secret_name,)
                ).fetchone()
                if tunnel["auth"] == "password" and not password and (clear_password or not existing):
                    raise ConfigurationError(f"Enter an SSH password for {tunnel['name']}.")
                if tunnel["auth"] != "password" or clear_password:
                    db.execute("DELETE FROM secrets WHERE name=?", (secret_name,))
                elif password:
                    db.execute(
                        "INSERT OR REPLACE INTO secrets VALUES (?, ?)",
                        (secret_name, self.cipher.encrypt(password.encode())),
                    )
            for (secret_name,) in db.execute(
                "SELECT name FROM secrets WHERE name LIKE 'tunnel-password:%'"
            ).fetchall():
                if secret_name not in retained_secrets:
                    db.execute("DELETE FROM secrets WHERE name=?", (secret_name,))
            db.execute("UPDATE settings SET value=? WHERE id=1", (json.dumps(settings),))
            if clear:
                db.execute("DELETE FROM secrets WHERE name='signoz'")
            elif key.strip():
                db.execute(
                    "INSERT OR REPLACE INTO secrets VALUES ('signoz', ?)",
                    (self.cipher.encrypt(key.strip().encode()),),
                )
