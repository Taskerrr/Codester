"""Bounded local Docker Desktop reads and explicit container controls."""

import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import httpx

from codester.transport import IntegrationError

MAX_OUTPUT = 1_000_000
TIMEOUT = 8


def _socket_path() -> Path | None:
    configured = os.environ.get("CODESTER_DOCKER_SOCKET", "").removeprefix("unix://")
    candidates = [Path(configured)] if configured else []
    candidates.extend([Path("/var/run/docker.sock"), Path.home() / ".docker/run/docker.sock"])
    for path in candidates:
        if path.exists() and stat.S_ISSOCK(path.stat().st_mode):
            return path
    return None


def _cli(args: list[str]) -> str:
    binary = shutil.which("docker")
    if not binary:
        raise IntegrationError("Docker Desktop is unavailable. Start Docker Desktop and retry.")
    try:
        result = subprocess.run(
            [binary, *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise IntegrationError("Docker Desktop did not respond in time.") from exc
    if len(result.stdout) + len(result.stderr) > MAX_OUTPUT:
        raise IntegrationError("Docker returned too much data.")
    if result.returncode:
        raise IntegrationError("Docker Desktop is unavailable or denied access.")
    return result.stdout


def _socket(method: str, path: str) -> object:
    socket_path = _socket_path()
    if socket_path is None:
        raise IntegrationError("Docker Desktop is unavailable. Start Docker Desktop and retry.")
    transport = httpx.HTTPTransport(uds=str(socket_path), retries=0)
    try:
        with httpx.Client(transport=transport, timeout=TIMEOUT) as client:
            response = client.request(method, "http://docker" + path)
            if len(response.content) > MAX_OUTPUT:
                raise IntegrationError("Docker returned too much data.")
            if response.status_code >= 400:
                raise IntegrationError("Docker rejected the container request.")
            if response.status_code == 204 or not response.content:
                return None
            return response.json()
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        raise IntegrationError("Docker Desktop is unavailable or returned invalid data.") from exc


def _normalize_cli(output: str) -> list[dict]:
    containers = []
    for line in output.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise IntegrationError("Docker returned an unsupported container list.") from exc
        if not isinstance(row, dict):
            raise IntegrationError("Docker returned an unsupported container list.")
        identifier = row.get("ID")
        if not isinstance(identifier, str) or not re.fullmatch(r"[0-9a-fA-F]{12,64}", identifier):
            raise IntegrationError("Docker returned an invalid container identifier.")
        state = str(row.get("State", "unknown")).lower()
        containers.append(
            {
                "id": identifier,
                "name": str(row.get("Names") or identifier[:12])[:200],
                "image": str(row.get("Image") or "Unknown image")[:300],
                "state": state,
                "status": str(row.get("Status") or state)[:300],
                "ports": str(row.get("Ports") or "")[:500],
                "running": state == "running",
            }
        )
    return containers


def _normalize_socket(payload: object) -> list[dict]:
    if not isinstance(payload, list):
        raise IntegrationError("Docker returned an unsupported container list.")
    containers = []
    for row in payload[:500]:
        if not isinstance(row, dict):
            raise IntegrationError("Docker returned an unsupported container list.")
        identifier = row.get("Id")
        if not isinstance(identifier, str) or not re.fullmatch(r"[0-9a-fA-F]{12,64}", identifier):
            raise IntegrationError("Docker returned an invalid container identifier.")
        names = row.get("Names")
        name = names[0].lstrip("/") if isinstance(names, list) and names else identifier[:12]
        ports = row.get("Ports") if isinstance(row.get("Ports"), list) else []
        port_text = ", ".join(
            f"{port.get('IP', '') + ':' if port.get('IP') else ''}{port.get('PublicPort', '')}"
            f"→{port.get('PrivatePort', '')}/{port.get('Type', '')}"
            for port in ports[:12]
            if isinstance(port, dict)
        )
        state = str(row.get("State", "unknown")).lower()
        containers.append(
            {
                "id": identifier,
                "name": str(name)[:200],
                "image": str(row.get("Image") or "Unknown image")[:300],
                "state": state,
                "status": str(row.get("Status") or state)[:300],
                "ports": port_text[:500],
                "running": state == "running",
            }
        )
    return containers


def containers() -> list[dict]:
    if shutil.which("docker"):
        output = _cli(["container", "ls", "--all", "--no-trunc", "--format", "{{json .}}"])
        return _normalize_cli(output)
    return _normalize_socket(_socket("GET", "/containers/json?all=1"))


def control(container_id: str, action: str) -> None:
    if not re.fullmatch(r"[0-9a-fA-F]{12,64}", container_id) or action not in {"start", "stop"}:
        raise IntegrationError("Invalid Docker container action.")
    known = {container["id"] for container in containers()}
    if container_id not in known:
        raise IntegrationError("That Docker container is no longer available.")
    if shutil.which("docker"):
        command = ["container", action]
        if action == "stop":
            command.extend(["--time", "10"])
        _cli([*command, container_id])
        return
    suffix = "/start" if action == "start" else "/stop?t=10"
    _socket("POST", f"/containers/{container_id}{suffix}")
