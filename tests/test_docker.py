import json
from types import SimpleNamespace

import pytest

from codester import docker_engine
from codester.transport import IntegrationError


def container_row(state="running"):
    return json.dumps(
        {
            "ID": "a" * 64,
            "Names": "codester",
            "Image": "codester:latest",
            "State": state,
            "Status": "Up 4 minutes" if state == "running" else "Exited (0)",
            "Ports": "127.0.0.1:8765->8765/tcp",
        }
    )


def test_docker_cli_list_and_stop_are_bounded(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        output = container_row() if "ls" in argv else ""
        return SimpleNamespace(returncode=0, stdout=output, stderr="")

    monkeypatch.setattr(docker_engine.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(docker_engine.subprocess, "run", run)
    containers = docker_engine.containers()
    assert containers[0]["name"] == "codester"
    assert containers[0]["running"] is True
    docker_engine.control("a" * 64, "stop")
    assert calls[-1][-4:] == ["stop", "--time", "10", "a" * 64]


def test_docker_rejects_invalid_output_and_actions(monkeypatch):
    with pytest.raises(IntegrationError, match="unsupported"):
        docker_engine._normalize_cli("not-json")
    with pytest.raises(IntegrationError, match="Invalid"):
        docker_engine.control("../../socket", "stop")


def test_socket_stats_normalize_cpu_and_memory_cache():
    result = docker_engine._normalize_socket_stats(
        {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 300, "percpu_usage": [1, 1]},
                "system_cpu_usage": 1_000,
                "online_cpus": 2,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 200},
                "system_cpu_usage": 600,
            },
            "memory_stats": {
                "usage": 1_000,
                "limit": 4_000,
                "stats": {"inactive_file": 200},
            },
        }
    )
    assert result == {
        "cpu_percent": 50.0,
        "memory_used": 800,
        "memory_limit": 4000,
        "memory_percent": 20.0,
    }


def test_cli_stats_normalize_display_values():
    result = docker_engine._normalize_cli_stats(
        json.dumps(
            {
                "ID": "a" * 64,
                "CPUPerc": "1.25%",
                "MemUsage": "84.2MiB / 7.65GiB",
                "MemPerc": "1.07%",
            }
        )
    )
    assert result["a" * 64]["cpu_percent"] == 1.25
    assert result["a" * 64]["memory_used_text"] == "84.2MiB"
    assert result["a" * 64]["memory_used"] == 88_290_099


def test_control_rejects_codester_itself(monkeypatch):
    identifier = "a" * 64
    monkeypatch.setattr(
        docker_engine,
        "containers",
        lambda: [{"id": identifier, "manageable": False}],
    )

    with pytest.raises(IntegrationError, match="own container"):
        docker_engine.control(identifier, "stop")


def test_socket_stop_waits_past_grace_period(monkeypatch):
    identifier = "a" * 64
    calls = []
    monkeypatch.setattr(docker_engine.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        docker_engine,
        "containers",
        lambda: [{"id": identifier, "manageable": True}],
    )
    monkeypatch.setattr(
        docker_engine,
        "_socket",
        lambda method, path, **kwargs: calls.append((method, path, kwargs)),
    )

    docker_engine.control(identifier, "stop")

    assert calls == [
        ("POST", f"/containers/{identifier}/stop?t=10", {"timeout": 15})
    ]
