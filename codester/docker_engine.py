"""Bounded local Docker Desktop reads and explicit container controls."""

import json
import os
import re
import shutil
import stat
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from math import isfinite
from pathlib import Path

import httpx

from codester.transport import IntegrationError

MAX_OUTPUT = 1_000_000
TIMEOUT = 8
MAX_STATS_CONTAINERS = 50


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


def _socket(method: str, path: str, *, timeout: int = TIMEOUT) -> object:
    socket_path = _socket_path()
    if socket_path is None:
        raise IntegrationError("Docker Desktop is unavailable. Start Docker Desktop and retry.")
    transport = httpx.HTTPTransport(uds=str(socket_path), retries=0)
    try:
        with httpx.Client(transport=transport, timeout=timeout) as client:
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
                "manageable": not _is_self(identifier),
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
                "manageable": not _is_self(identifier),
            }
        )
    return containers


def _is_self(identifier: str) -> bool:
    hostname = os.environ.get("HOSTNAME", "")
    return bool(re.fullmatch(r"[0-9a-fA-F]{12,64}", hostname)) and identifier.startswith(
        hostname
    )


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if isfinite(result) else None


def _normalize_socket_stats(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise IntegrationError("Docker returned unsupported resource statistics.")
    cpu = payload.get("cpu_stats")
    previous = payload.get("precpu_stats")
    cpu_percent = None
    if isinstance(cpu, dict) and isinstance(previous, dict):
        usage = cpu.get("cpu_usage")
        previous_usage = previous.get("cpu_usage")
        total = _number(usage.get("total_usage")) if isinstance(usage, dict) else None
        previous_total = (
            _number(previous_usage.get("total_usage"))
            if isinstance(previous_usage, dict)
            else None
        )
        system = _number(cpu.get("system_cpu_usage"))
        previous_system = _number(previous.get("system_cpu_usage"))
        online = _number(cpu.get("online_cpus"))
        if online is None and isinstance(usage, dict):
            per_cpu = usage.get("percpu_usage")
            online = float(len(per_cpu)) if isinstance(per_cpu, list) else None
        if (
            total is not None
            and previous_total is not None
            and system is not None
            and previous_system is not None
            and online is not None
        ):
            cpu_delta = total - previous_total
            system_delta = system - previous_system
            if cpu_delta >= 0 and system_delta > 0 and online > 0:
                cpu_percent = cpu_delta / system_delta * online * 100

    memory = payload.get("memory_stats")
    memory_used = memory_limit = memory_percent = None
    if isinstance(memory, dict):
        memory_used = _number(memory.get("usage"))
        memory_limit = _number(memory.get("limit"))
        details = memory.get("stats")
        if memory_used is not None and isinstance(details, dict):
            cache = _number(details.get("inactive_file"))
            if cache is None:
                cache = _number(details.get("cache"))
            if cache is not None:
                memory_used = max(0.0, memory_used - cache)
        if memory_used is not None and memory_limit and memory_limit > 0:
            memory_percent = memory_used / memory_limit * 100
    return {
        "cpu_percent": round(cpu_percent, 2) if cpu_percent is not None else None,
        "memory_used": round(memory_used) if memory_used is not None else None,
        "memory_limit": round(memory_limit) if memory_limit is not None else None,
        "memory_percent": round(memory_percent, 2) if memory_percent is not None else None,
    }


def _normalize_cli_stats(output: str) -> dict[str, dict]:
    result = {}
    for line in output.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise IntegrationError("Docker returned unsupported resource statistics.") from exc
        identifier = row.get("ID") if isinstance(row, dict) else None
        if not isinstance(identifier, str) or not re.fullmatch(
            r"[0-9a-fA-F]{12,64}", identifier
        ):
            raise IntegrationError("Docker returned unsupported resource statistics.")
        memory = str(row.get("MemUsage", "")).split("/")
        memory_used_text = memory[0].strip()[:40] if memory else ""
        memory_limit_text = memory[1].strip()[:40] if len(memory) > 1 else ""
        result[identifier] = {
            "cpu_percent": _percent(row.get("CPUPerc")),
            "memory_used": _bytes(memory_used_text),
            "memory_limit": _bytes(memory_limit_text),
            "memory_used_text": memory_used_text,
            "memory_limit_text": memory_limit_text,
            "memory_percent": _percent(row.get("MemPerc")),
        }
    return result


def _percent(value: object) -> float | None:
    try:
        result = float(str(value).strip().removesuffix("%"))
    except ValueError:
        return None
    return round(result, 2) if isfinite(result) and result >= 0 else None


def _bytes(value: str) -> int | None:
    match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*([kmgt]?i?b)\s*", value.lower())
    if not match:
        return None
    units = {
        "b": 0,
        "kb": 1,
        "kib": 1,
        "mb": 2,
        "mib": 2,
        "gb": 3,
        "gib": 3,
        "tb": 4,
        "tib": 4,
    }
    return round(float(match.group(1)) * 1024 ** units[match.group(2)])


def containers() -> list[dict]:
    if shutil.which("docker"):
        output = _cli(["container", "ls", "--all", "--no-trunc", "--format", "{{json .}}"])
        return _normalize_cli(output)
    return _normalize_socket(_socket("GET", "/containers/json?all=1"))


def resource_stats(items: list[dict]) -> dict[str, dict]:
    running = [item for item in items if item["running"]][:MAX_STATS_CONTAINERS]
    if not running:
        return {}
    if shutil.which("docker"):
        output = _cli(
            ["stats", "--no-stream", "--no-trunc", "--format", "{{json .}}"]
        )
        return _normalize_cli_stats(output)

    result = {}
    with ThreadPoolExecutor(max_workers=min(4, len(running))) as executor:
        requests = {
            executor.submit(
                _socket,
                "GET",
                f"/containers/{item['id']}/stats?stream=false",
            ): item["id"]
            for item in running
        }
        for request in as_completed(requests):
            identifier = requests[request]
            try:
                result[identifier] = _normalize_socket_stats(request.result())
            except IntegrationError:
                continue
    return result


def control(container_id: str, action: str) -> None:
    if not re.fullmatch(r"[0-9a-fA-F]{12,64}", container_id) or action not in {"start", "stop"}:
        raise IntegrationError("Invalid Docker container action.")
    known = {container["id"]: container for container in containers()}
    if container_id not in known:
        raise IntegrationError("That Docker container is no longer available.")
    if not known[container_id]["manageable"]:
        raise IntegrationError("Codester cannot stop or start its own container.")
    if shutil.which("docker"):
        command = ["container", action]
        if action == "stop":
            command.extend(["--time", "10"])
        _cli([*command, container_id])
        return
    suffix = "/start" if action == "start" else "/stop?t=10"
    _socket("POST", f"/containers/{container_id}{suffix}", timeout=15)
