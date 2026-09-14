"""Local HTTP interface. Only server code receives upstream credentials."""

import atexit
import hmac
import os
import re
import secrets
import threading
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, abort, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from codester import dagster, demo, docker_engine, signoz
from codester.poller import INTERVALS, Poller
from codester.store import METRICS, ConfigurationError, Store
from codester.transport import IntegrationError
from codester.tunnels import TunnelManager


def create_app(data_dir: Path | None = None, *, start_poller: bool = True) -> Flask:
    app = Flask(__name__)
    app.config.update(MAX_CONTENT_LENGTH=32768, TRUSTED_HOSTS=["localhost", "127.0.0.1", "[::1]"])
    store = Store(data_dir or Path(os.environ.get("CODESTER_DATA_DIR", ".data")))
    poller = Poller(store)
    tunnel_manager = TunnelManager(store.path.parent, store.read()["tunnels"], autostart=start_poller)
    token = secrets.token_urlsafe(32)
    docker_lock = threading.Lock()
    app.extensions.update(store=store, poller=poller, tunnel_manager=tunnel_manager)

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
        return jsonify(poller.snapshot())

    @app.get("/api/settings")
    def settings_read():
        return jsonify(store.public())

    @app.put("/api/settings")
    def settings_save():
        with poller.lock:
            store.save(request.get_json())
            poller.invalidate()
            tunnel_manager.configure(store.read()["tunnels"])
        return jsonify(store.public())

    @app.get("/api/tunnels")
    def tunnel_status():
        return jsonify(tunnel_manager.status())

    @app.post("/api/tunnels/connect")
    def tunnel_connect():
        return jsonify(tunnel_manager.connect())

    @app.post("/api/tunnels/disconnect")
    def tunnel_disconnect():
        return jsonify(tunnel_manager.disconnect())

    @app.post("/api/connections/<name>/test")
    def connection_test(name: str):
        if name not in INTERVALS:
            abort(404)
        # Capture URL and credentials together, so settings edits cannot send a new key
        # to an old destination while a test is waiting for the polling worker.
        with poller.operation_locks[name]:
            with poller.lock:
                config = store.read()
                key = store.secret("signoz") if name == "signoz" else ""
            if name != "codex" and not config[name]["api_url"]:
                raise ConfigurationError("Save a connection URL first.")
            poller.fetch(name, config, key)
        return jsonify(ok=True, message="Connection and dashboard queries succeeded.")

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
