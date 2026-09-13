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
