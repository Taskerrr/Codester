import json
import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

from codester.codex_events import ActivityEvents
from codester.native import configure_hooks, launch_agent, migrate_docker
from codester.store import Store


def test_native_hooks_replace_docker_preserve_others_and_work_from_another_directory(tmp_path):
    home = tmp_path / "Codex home's"
    home.mkdir()
    old = {"hooks": {"Stop": [{"hooks": [
        {"type": "command", "command": "other-hook"},
        {"type": "command", "command": "docker exec -i old python -m codester.codex_hook"},
    ]}]}}
    path = home / "hooks.json"
    original = json.dumps(old)
    path.write_text(original, encoding="utf-8")
    directory = tmp_path / "data's space"
    store = Store(directory)
    settings = store.read()
    settings["codex"].update(enabled=True, activity=True)
    store.save(settings)
    configure_hooks(home, Path(sys.executable), directory)
    first = path.read_text(encoding="utf-8")
    configure_hooks(home, Path(sys.executable), directory)
    assert path.read_text(encoding="utf-8") == first
    assert (home / "hooks.json.before-codester-native").read_text(encoding="utf-8") == original
    groups = json.loads(first)["hooks"]["Stop"]
    assert groups[0]["hooks"][0]["command"] == "other-hook"
    assert len(groups) == 2
    command = groups[1]["hooks"][0]["command"]
    assert "docker exec" not in command
    subprocess.run(command, shell=True, cwd=tmp_path, input=json.dumps({
        "hook_event_name": "Stop", "session_id": "native-test", "cwd": "/work/project",
    }), text=True, capture_output=True, check=True)
    assert ActivityEvents(directory).merge([], "")[0][0]["activity_state"] == "idle"


def test_invalid_hooks_are_never_overwritten(tmp_path):
    path = tmp_path / "hooks.json"
    path.write_text('{"hooks": {"Stop": "invalid"}}', encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="left unchanged"):
        configure_hooks(tmp_path, Path(sys.executable), tmp_path / "data")
    assert path.read_bytes() == before


def test_launch_agent_paths_are_not_shell_commands(tmp_path):
    root = tmp_path / "space & quote's"
    config = launch_agent(root, root / ".venv/bin/python", root / ".data")
    restored = plistlib.loads(plistlib.dumps(config))
    assert restored["ProgramArguments"] == [str(root / ".venv/bin/python"), "-m", "codester.native", "run"]
    assert restored["WorkingDirectory"] == str(root)
    assert restored["RunAtLoad"] is True


def test_docker_migration_stops_before_copy_and_backs_up_native_data(tmp_path, monkeypatch):
    directory = tmp_path / ".data"
    directory.mkdir()
    (directory / "settings.sqlite").write_bytes(b"old-native")
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[:2] == ["docker", "cp"]:
            target = Path(args[-1])
            (target / "settings.sqlite").write_bytes(b"docker-settings")
            (target / "secret.key").write_bytes(b"docker-key")
        return subprocess.CompletedProcess(args, 0, stdout="container-id\n")

    monkeypatch.setattr("codester.native.subprocess.run", fake_run)
    migrate_docker(tmp_path, directory)
    assert calls[1] == ["docker", "compose", "stop", "codester"]
    assert calls[2] == ["docker", "update", "--restart=no", "container-id"]
    assert (directory / "settings.sqlite").read_bytes() == b"docker-settings"
    assert (directory / "secret.key").read_bytes() == b"docker-key"
    backup = next(tmp_path.glob(".data.before-native-*"))
    assert (backup / "settings.sqlite").read_bytes() == b"old-native"


def test_failed_copy_preserves_native_data(tmp_path, monkeypatch):
    directory = tmp_path / ".data"
    directory.mkdir()
    (directory / "settings.sqlite").write_bytes(b"original")

    def fake_run(args, **kwargs):
        if args[:2] == ["docker", "cp"]:
            raise subprocess.CalledProcessError(1, args)
        return subprocess.CompletedProcess(args, 0, stdout="container-id\n")

    monkeypatch.setattr("codester.native.subprocess.run", fake_run)
    with pytest.raises(subprocess.CalledProcessError):
        migrate_docker(tmp_path, directory)
    assert (directory / "settings.sqlite").read_bytes() == b"original"
