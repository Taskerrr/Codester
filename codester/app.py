"""Local HTTP interface. Only server code receives upstream credentials."""

import atexit
import hmac
import os
import re
import secrets
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, abort, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from codester import codex, dagster, demo, docker_engine, signoz
from codester.codex_events import ActivityEvents
from codester.credentials import CredentialStoreError
from codester.poller import INTERVALS, Poller
from codester.repositories import RepositoryManager
from codester.services import ServiceManager
from codester.sql_workspace import SQLWorkspace
from codester.startup import save_startup, startup_status
from codester.store import METRICS, ConfigurationError, Store
from codester.transport import IntegrationError
from codester.tunnels import TunnelManager


def create_app(data_dir: Path | None = None, *, start_poller: bool = True) -> Flask:
    app = Flask(__name__)
    app.config.update(MAX_CONTENT_LENGTH=32768, TRUSTED_HOSTS=["localhost", "127.0.0.1", "[::1]"])
    store = Store(data_dir or Path(os.environ.get("CODESTER_DATA_DIR", ".data")))
    activity_events = ActivityEvents(store.path.parent)
    poller = Poller(store)
    tunnel_manager = TunnelManager(store.path.parent, store.read()["tunnels"], autostart=start_poller)
    repository_manager = RepositoryManager(store)
    service_manager = ServiceManager(store, tunnel_manager)
    sql_workspace = SQLWorkspace(store)
    token = secrets.token_urlsafe(32)
    docker_lock = threading.Lock()
    app.extensions.update(
        store=store,
        poller=poller,
        tunnel_manager=tunnel_manager,
        repository_manager=repository_manager,
        service_manager=service_manager,
        sql_workspace=sql_workspace,
        codex_activity_events=activity_events,
    )

    @app.before_request
    def protect_local_app() -> None:
        origin = request.headers.get("Origin")
        if origin and urlsplit(origin).netloc != request.host:
            abort(403)
        if request.headers.get("Sec-Fetch-Site") == "cross-site":
            abort(403)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if not hmac.compare_digest(request.headers.get("X-Codester-CSRF", ""), token):
                abort(403)

    @app.after_request
    def headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    @app.errorhandler(Exception)
    def error(exc: Exception):
        if isinstance(exc, HTTPException):
            return jsonify(error=exc.name), exc.code
        if isinstance(exc, IntegrationError):
            return jsonify(error=str(exc)), 502
        if isinstance(exc, ConfigurationError):
            return jsonify(error=str(exc)), 400
        if isinstance(exc, CredentialStoreError):
            return jsonify(error=str(exc)), 503
        return jsonify(
            error="Request failed. Check local configuration and integration compatibility."
        ), 500

    @app.get("/")
    def index():
        return render_template("dashboard.html", csrf=token)

    @app.get("/settings")
    def settings_page():
        return render_template("settings.html", csrf=token, metrics=METRICS)

    @app.get("/docker")
    def docker_page():
        return render_template("docker.html", csrf=token)

    @app.get("/api/health")
    def health():
        return jsonify(status="ok")

    @app.get("/api/dashboard")
    def dashboard():
        result = poller.snapshot()
        settings = store.read()
        codex_data: dict | None = result["services"]["codex"].get("data")
        if not result["demo"] and settings["codex"]["enabled"] and settings["codex"]["activity"]:
            if codex_data is None:
                codex_data = {"windows": []}
                result["services"]["codex"]["data"] = codex_data
            codex_data["tasks"], codex_data["activity_note"] = activity_events.merge(
                *codex.local_activity()
            )
            codex_data["integration"] = activity_events.status()
        return jsonify(result)

    @app.post("/api/refresh")
    def refresh_services():
        for wake in poller.wakes.values():
            wake.set()
        return jsonify(ok=True)

    @app.get("/api/codex/activity")
    def codex_activity():
        settings = store.read()
        if settings["demo"]:
            sample = demo.snapshot("codex")
            return jsonify(tasks=sample["tasks"], note=sample["activity_note"])
        if not settings["codex"]["enabled"] or not settings["codex"]["activity"]:
            return jsonify(tasks=[], note="Local activity is off.")
        tasks, note = activity_events.merge(*codex.local_activity())
        return jsonify(tasks=tasks, note=note, integration=activity_events.status())

    @app.get("/api/startup")
    def startup_read():
        return jsonify(startup_status(store.path.parent))

    @app.put("/api/startup")
    def startup_save():
        try:
            return jsonify(save_startup(store.path.parent, request.get_json(silent=True)))
        except (OSError, subprocess.SubprocessError):
            return jsonify(error="Could not update login startup. Check your account permissions and try again."), 503

    @app.get("/api/settings")
    def settings_read():
        return jsonify(store.public())

    @app.put("/api/settings")
    def settings_save():
        with poller.lock:
            store.save(request.get_json())
            poller.invalidate()
            repository_manager.invalidate()
            tunnel_manager.configure(store.read()["tunnels"])
        return jsonify(store.public())

    @app.get("/postgres")
    def postgres_page():
        return render_template("postgres.html", csrf=token)

    @app.put("/api/dashboard/layout")
    def dashboard_layout():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ConfigurationError("Choose three dashboard apps.")
        return jsonify(layout=store.save_dashboard_apps(data.get("apps")))

    @app.get("/api/sql/connections")
    def sql_connections():
        return jsonify(connections=sql_workspace.connections(), demo=store.read()["demo"])

    @app.put("/api/sql/connections/<identifier>")
    def sql_connection_save(identifier: str):
        return jsonify(connections=sql_workspace.save(identifier, request.get_json(silent=True)))

    @app.delete("/api/sql/connections/<identifier>")
    def sql_connection_delete(identifier: str):
        sql_workspace.delete(identifier)
        return jsonify(ok=True)

    @app.post("/api/sql/run")
    def sql_run():
        return jsonify(sql_workspace.execute(request.get_json(silent=True)))

    @app.post("/api/sql/cancel/<identifier>")
    def sql_cancel(identifier: str):
        return jsonify(cancelled=sql_workspace.cancel(identifier))

    @app.get("/api/sql/connections/<identifier>/activity")
    def sql_activity(identifier: str):
        if store.read()["demo"]:
            return postgres_activity()
        config, password = sql_workspace.resolve(identifier)
        data = poller.postgres.snapshot(config, password)
        now = time.time()
        return jsonify(state=dict(status="connected", data=data, last_success=now), demo=False, server_time=now)

    @app.post("/api/sql/connections/<identifier>/<action>")
    def sql_session_control(identifier: str, action: str):
        if action not in {"cancel", "terminate"}:
            abort(404)
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not isinstance(data.get("token"), str) or len(data["token"]) > 4096:
            raise ConfigurationError("Select a current PostgreSQL session first.")
        if store.read()["demo"]:
            raise ConfigurationError("Session controls require a live connection.")
        config, password = sql_workspace.resolve(identifier)
        return jsonify(poller.postgres.control(config, password, data["token"], action))

    @app.get("/api/postgres")
    def postgres_activity():
        snapshot = poller.snapshot()
        return jsonify(state=snapshot["services"]["postgres"], demo=snapshot["demo"], server_time=snapshot["server_time"])

    @app.post("/api/postgres/<action>")
    def postgres_control(action: str):
        if action not in {"cancel", "terminate"}:
            abort(404)
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not isinstance(data.get("token"), str) or len(data["token"]) > 4096:
            raise ConfigurationError("Select a current PostgreSQL session first.")
        with poller.operation_locks["postgres"]:
            with poller.lock:
                config = store.read()
                if config["demo"] or not config["postgres"]["enabled"]:
                    raise ConfigurationError("Session controls require a live PostgreSQL connection.")
                if poller.state["postgres"]["status"] != "connected":
                    raise ConfigurationError("Refresh the PostgreSQL connection before changing a session.")
                password = store.secret("postgres")
            result = poller.postgres.control(config["postgres"], password, data["token"], action)
        poller.wakes["postgres"].set()
        return jsonify(result)

    @app.get("/services")
    def services_page():
        return render_template("services.html", csrf=token)

    @app.get("/api/services")
    def services_snapshot():
        return jsonify(service_manager.snapshot())

    @app.put("/api/services/<identifier>")
    def service_save(identifier: str):
        if not re.fullmatch(r"[a-f0-9-]{16,64}", identifier):
            abort(404)
        return jsonify(service_manager.save(identifier, request.get_json()))

    @app.delete("/api/services/<identifier>")
    def service_delete(identifier: str):
        service_manager.delete(identifier)
        return jsonify(ok=True)

    @app.post("/api/services/<identifier>/run/<command_id>")
    def service_run(identifier: str, command_id: str):
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            raise ConfigurationError("Invalid command request.")
        return jsonify(service_manager.start(identifier, command_id, confirmed=data.get("confirmed") is True))

    @app.get("/api/tunnels")
    def tunnel_status():
        return jsonify(tunnel_manager.status())

    @app.post("/api/tunnels/connect")
    def tunnel_connect():
        return jsonify(tunnel_manager.connect())

    @app.post("/api/tunnels/disconnect")
    def tunnel_disconnect():
        return jsonify(tunnel_manager.disconnect())

    @app.post("/api/tunnels/<identifier>/test")
    def tunnel_test(identifier: str):
        if not re.fullmatch(r"[a-f0-9-]{16,64}", identifier):
            abort(404)
        return jsonify(tunnel_manager.test(identifier))

    @app.post("/api/tunnels/<identifier>/<action>")
    def tunnel_control(identifier: str, action: str):
        if not re.fullmatch(r"[a-f0-9-]{16,64}", identifier) or action not in {"connect", "disconnect"}:
            abort(404)
        operation = tunnel_manager.connect if action == "connect" else tunnel_manager.disconnect
        return jsonify(operation(identifier))

    @app.post("/api/connections/<name>/test")
    def connection_test(name: str):
        if name not in INTERVALS:
            abort(404)
        # Capture URL and credentials together, so settings edits cannot send a new key
        # to an old destination while a test is waiting for the polling worker.
        with poller.operation_locks[name]:
            with poller.lock:
                config = store.read()
                key = store.secret(name) if name in {"signoz", "github", "postgres"} else ""
            if name not in {"codex", "postgres"} and not config[name]["api_url"]:
                raise ConfigurationError("Save a connection URL first.")
            data = poller.fetch(name, config, key)
        message = "Connection and dashboard queries succeeded."
        if name == "github":
            message = (
                "Connected · full GitHub contribution calendar."
                if data.get("calendar_source") == "github"
                else "Connected · repo commits shown. For the full calendar, use a classic "
                "token with read:user."
            )
            if data.get("organization"):
                message = (
                    f"Connected to {data['organization']}: your commits across "
                    f"{data['calendar_repository_count']} token-visible repositories. "
                    "Personal repositories excluded; three latest shown."
                )
            if data.get("calendar_limited"):
                message += " Results are partial: a repository or commit query limit was reached."
        return jsonify(ok=True, message=message)

    @app.post("/api/signoz/services")
    def service_list():
        with poller.operation_locks["signoz"]:
            with poller.lock:
                config = store.read()["signoz"]
                key = store.secret("signoz")
            if not config["api_url"]:
                raise ConfigurationError("Save the SigNoz connection first.")
            names = signoz.services(config, key)
        return jsonify(services=names, note="Services observed in the last 24 hours (up to 200).")

    @app.get("/api/docker/containers")
    def docker_containers():
        with docker_lock:
            containers = docker_engine.containers()
            stats = docker_engine.resource_stats(containers)
            for container in containers:
                container.update(stats.get(container["id"], {}))
        return jsonify(
            containers=containers,
            groups=docker_engine.groups(containers),
            running=sum(container["running"] for container in containers),
            total=len(containers),
            cpu_percent=round(
                sum(container.get("cpu_percent") or 0 for container in containers), 1
            ),
            memory_used=sum(
                container.get("memory_used") or 0 for container in containers
            ),
            memory_limit=max(
                (container.get("memory_limit") or 0 for container in containers),
                default=0,
            ),
        )

    @app.post("/api/docker/containers/<container_id>/<action>")
    def docker_control(container_id: str, action: str):
        if not re.fullmatch(r"[0-9a-fA-F]{12,64}", container_id) or action not in {
            "start",
            "stop",
        }:
            abort(404)
        with docker_lock:
            docker_engine.control(container_id, action)
        return jsonify(ok=True)

    @app.post("/api/docker/projects/<project_id>/<action>")
    def docker_project_control(project_id: str, action: str):
        if not re.fullmatch(r"[a-f0-9]{64}", project_id) or action not in {"start", "stop"}:
            abort(404)
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ConfigurationError("Select a Docker project first.")
        with docker_lock:
            result = docker_engine.control_project(project_id, action, data.get("container_ids"))
        return jsonify(result)

    @app.get("/api/github/repositories")
    def github_repositories():
        return jsonify(repository_manager.snapshot())

    @app.get("/api/github/updates")
    def github_updates():
        return jsonify(service_manager.repository_updates())

    @app.post("/api/github/updates/<identifier>")
    def github_update(identifier: str):
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not isinstance(data.get("revision"), str):
            raise ConfigurationError("Supply the saved repository update revision.")
        return jsonify(service_manager.start_repository(
            identifier, data["revision"], confirmed=data.get("confirmed") is True
        )), 202

    @app.post("/api/github/repositories/<identifier>/<action>")
    def github_repository_action(identifier: str, action: str):
        if not re.fullmatch(r"[a-f0-9-]{16,64}", identifier) or action not in {
            "push",
            "deploy",
        }:
            abort(404)
        return jsonify(repository_manager.start(identifier, action)), 202

    @app.get("/api/errors/<name>/<identifier>")
    def error_detail(name: str, identifier: str):
        if name not in {"dagster", "signoz"} or not re.fullmatch(
            r"[a-zA-Z0-9_-]{1,128}", identifier
        ):
            abort(404)
        # IDs must come from the current bounded dashboard, not arbitrary upstream lookups.
        with poller.operation_locks[name]:
            with poller.lock:
                snapshot = poller.snapshot()
                data = snapshot["services"][name]["data"] or {}
                if identifier not in {item["id"] for item in data.get("errors", [])}:
                    abort(404)
                if snapshot["demo"]:
                    return jsonify(demo.detail(name, identifier))
                config = store.read()[name]
                key = store.secret("signoz") if name == "signoz" else ""
                generation = poller.generation
            result = (
                dagster.detail(config, identifier)
                if name == "dagster"
                else signoz.detail(config, key, identifier)
            )
            with poller.lock:
                if generation != poller.generation:
                    abort(409)
        return jsonify(result)

    if start_poller:
        poller.start()
        atexit.register(poller.stop)
        atexit.register(tunnel_manager.stop)
    return app
