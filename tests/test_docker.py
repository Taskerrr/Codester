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

    assert calls == [("POST", f"/containers/{identifier}/stop?t=10", {"timeout": 15})]


def compose_container(letter, service, running=True, project="example", **extra):
    return {
        "id": letter * 64,
        "name": f"{project}-{service}-1",
        "image": "example:latest",
        "project": project,
        "service": service,
        "running": running,
        "state": "running" if running else "exited",
        "status": "Up" if running else "Exited",
        "manageable": True,
        **extra,
    }


def test_compose_labels_from_cli_and_socket():
    row = json.loads(container_row())
    row["Labels"] = (
        "unrelated=thing,com.docker.compose.project=my-stack,com.docker.compose.service=web,com.docker.compose.oneoff=False"
    )
    cli = docker_engine._normalize_cli(json.dumps(row))[0]
    socket = docker_engine._normalize_socket(
        [
            {
                "Id": "a" * 64,
                "Names": ["/web"],
                "Labels": {
                    "com.docker.compose.project": "my-stack",
                    "com.docker.compose.service": "web",
                },
            }
        ]
    )[0]
    assert cli["project"] == socket["project"] == "my-stack"
    assert cli["service"] == socket["service"] == "web"
    assert not cli["oneoff"]
    assert docker_engine._normalize_cli(container_row())[0]["project"] == ""


def test_groups_use_labels_not_name_and_keep_oneoffs_separate():
    items = [
        compose_container("a", "daemon"),
        compose_container("b", "web", False),
        compose_container("c", "web", project="other"),
        compose_container("d", "shell", False, oneoff=True),
        compose_container("e", "lookalike", project=""),
    ]
    groups = docker_engine.groups(items)
    assert len(groups) == 4
    project = next(group for group in groups if group["name"] == "example")
    assert project["kind"] == "project" and project["total"] == 2
    assert project["state"] == "partial" and project["running"] == 1
    assert {row["id"] for row in project["containers"]} == {"a" * 64, "b" * 64}
    assert sum(group["kind"] == "container" for group in groups) == 2


def test_project_actions_target_current_members_and_skip_correct_state(monkeypatch):
    items = [
        compose_container("a", "daemon"),
        compose_container("b", "web", False),
        compose_container("c", "other", project="different"),
    ]
    calls = []
    monkeypatch.setattr(docker_engine, "containers", lambda: items)
    monkeypatch.setattr(
        docker_engine, "_control_known", lambda key, action: calls.append((key, action))
    )
    ids = ["a" * 64, "b" * 64]
    result = docker_engine.control_project(docker_engine.project_key("example"), "start", ids)
    assert result["ok"] and calls == [("b" * 64, "start")]
    calls.clear()
    result = docker_engine.control_project(docker_engine.project_key("example"), "stop", ids)
    assert result["ok"] and calls == [("a" * 64, "stop")]


def test_project_membership_change_and_self_are_rejected_before_actions(monkeypatch):
    items = [compose_container("a", "daemon"), compose_container("b", "web")]
    calls = []
    monkeypatch.setattr(docker_engine, "containers", lambda: items)
    monkeypatch.setattr(docker_engine, "_control_known", lambda *args: calls.append(args))
    key = docker_engine.project_key("example")
    with pytest.raises(IntegrationError, match="changed"):
        docker_engine.control_project(key, "stop", ["a" * 64])
    items[1]["manageable"] = False
    with pytest.raises(IntegrationError, match="includes Codester"):
        docker_engine.control_project(key, "stop", ["a" * 64, "b" * 64])
    assert not calls


def test_partial_project_failure_is_reported_without_skipping_other_members(monkeypatch):
    items = [compose_container("a", "daemon"), compose_container("b", "web")]
    monkeypatch.setattr(docker_engine, "containers", lambda: items)

    def control(key, action):
        if key == "b" * 64:
            raise IntegrationError("Docker rejected the container request.")

    monkeypatch.setattr(docker_engine, "_control_known", control)
    result = docker_engine.control_project(
        docker_engine.project_key("example"), "stop", [row["id"] for row in items]
    )
    assert not result["ok"] and result["succeeded"] == ["a" * 64]
    assert result["failed"][0]["name"] == "example-web-1"
    assert "Failed: example-web-1" in result["message"]


def test_paused_project_can_be_stopped(monkeypatch):
    item = compose_container("a", "web", False, state="paused")
    group = docker_engine.groups([item])[0]
    assert group["active"] == 1 and group["state"] == "partial"
    calls = []
    monkeypatch.setattr(docker_engine, "containers", lambda: [item])
    monkeypatch.setattr(docker_engine, "_control_known", lambda *args: calls.append(args))
    docker_engine.control_project(group["id"], "stop", [item["id"]])
    assert calls == [(item["id"], "stop")]


def test_socket_ports_distinguish_host_bindings_ipv6_and_internal_ports():
    row = docker_engine._normalize_socket([{
        "Id": "a" * 64,
        "Ports": [
            {"IP": "127.0.0.1", "PublicPort": 8080, "PrivatePort": 80, "Type": "tcp"},
            {"IP": "::", "PublicPort": 8080, "PrivatePort": 80, "Type": "tcp"},
            {"PrivatePort": 5432, "Type": "tcp"},
            {"IP": "0.0.0.0", "PublicPort": 5353, "PrivatePort": 53, "Type": "udp"},
        ],
    }])[0]
    assert row["ports"] == "127.0.0.1:8080→80/tcp, [::]:8080→80/tcp, 5432/tcp, 0.0.0.0:5353→53/udp"
    assert docker_engine._normalize_cli(container_row())[0]["ports"] == "127.0.0.1:8765->8765/tcp"
