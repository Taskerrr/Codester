import json
import os
import subprocess
import sys

import pytest

from codester import codex
from codester.app import create_app
from codester.codex_events import ActivityEvents
from codester.codex_hook import HOOK_EVENTS, configuration
from codester.store import Store


def event(kind, session="first", turn="turn-1", cwd="/work/project-one"):
    return {"hook_event_name": kind, "session_id": session, "turn_id": turn, "cwd": cwd}


def enable(directory):
    store = Store(directory)
    settings = store.read()
    settings["demo"] = False
    settings["codex"].update(enabled=True, activity=True)
    store.save(settings)


def test_completed_hook_overrides_stale_rollout_in_both_apis(tmp_path, monkeypatch):
    app = create_app(tmp_path, start_poller=False)
    enable(tmp_path)
    stale = [
        {
            "id": "first",
            "title": "Original task",
            "project": "project-one",
            "timestamp": 9999999999,
            "activity_state": "active",
            "inferred_active": True,
        }
    ]
    monkeypatch.setattr(codex, "local_activity", lambda: (stale, "Old log"))
    events = app.extensions["codex_activity_events"]
    events.record(event("UserPromptSubmit"))
    events.record(event("Stop"))
    client = app.test_client()
    activity = client.get("/api/codex/activity").json
    assert activity["tasks"][0]["activity_state"] == "idle"
    assert activity["tasks"][0]["activity_source"] == "hook"
    assert activity["tasks"][0]["title"] == "Original task"
    # Activity still displays when account usage is unavailable.
    dashboard = client.get("/api/dashboard").json
    assert dashboard["services"]["codex"]["data"]["tasks"] == activity["tasks"]
    assert stale[0]["activity_state"] == "active"


def test_sessions_are_independent_and_old_turn_completion_is_ignored(tmp_path):
    events = ActivityEvents(tmp_path)
    events.record(event("UserPromptSubmit"))
    events.record(event("UserPromptSubmit", session="second", cwd=r"C:\work\other"))
    events.record(event("UserPromptSubmit", turn="turn-2"))
    assert not events.record(event("Stop"))
    events.record(event("Stop", turn="turn-2"))
    tasks, _ = events.merge([], "")
    by_id = {task["id"]: task for task in tasks}
    assert by_id["first"]["activity_state"] == "idle"
    assert by_id["second"]["activity_state"] == "active"
    assert by_id["second"]["project"] == "other"


def test_continuation_and_interrupt(tmp_path):
    events = ActivityEvents(tmp_path)
    for kind, state in [
        ("UserPromptSubmit", "active"),
        ("Stop", "idle"),
        ("UserPromptSubmit", "active"),
        ("Interrupt", "stopped"),
    ]:
        events.record(event(kind))
        assert events.merge([], "")[0][0]["activity_state"] == state
    assert ActivityEvents(tmp_path).merge([], "")[0][0]["activity_state"] == "stopped"


@pytest.mark.parametrize(
    "payload", [None, [], {}, event("SubagentStop"), {**event("Stop"), "cwd": None}]
)
def test_invalid_or_subagent_events_do_not_change_main_session(tmp_path, payload):
    events = ActivityEvents(tmp_path)
    assert not events.record(payload)
    assert events.merge([], "") == ([], "")


def test_install_is_idempotent_preserves_other_hooks_and_does_not_trust():
    other = {"type": "command", "command": "existing-security-check", "timeout": 15}
    original = {"description": "My hooks", "hooks": {"Stop": [{"hooks": [other]}]}}
    command = "docker exec -i codester python -m codester.codex_hook"
    first = configuration(original, command, "windows-command")
    assert configuration(json.loads(first), command, "windows-command") == first
    configured = json.loads(first)
    assert configured["description"] == "My hooks"
    assert configured["hooks"]["Stop"][0]["hooks"] == [other]
    for kind in HOOK_EVENTS:
        assert configured["hooks"][kind][-1]["hooks"][0]["command"] == command
    assert "trust" not in configured


def test_invalid_existing_configuration_is_rejected():
    with pytest.raises(ValueError, match="left unchanged"):
        configuration({"hooks": {"Stop": "bad"}}, "command", "windows")


def test_real_hook_process_keeps_only_metadata_and_respects_opt_out(tmp_path):
    enable(tmp_path)
    payload = {
        **event("Stop"),
        "last_assistant_message": "private-response-unique",
        "prompt": "private-prompt-unique",
    }
    command = [sys.executable, "-m", "codester.codex_hook", "--data-dir", str(tmp_path)]
    result = subprocess.run(command, input=json.dumps(payload), capture_output=True, text=True)
    assert result.returncode == 0
    assert result.stdout == "{}\n"
    assert result.stderr == ""
    contents = (tmp_path / "codex-activity.sqlite").read_bytes()
    assert b"private-response-unique" not in contents
    assert b"private-prompt-unique" not in contents
    assert ActivityEvents(tmp_path).merge([], "")[0][0]["activity_state"] == "idle"
    store = Store(tmp_path)
    settings = store.read()
    settings["codex"]["activity"] = False
    store.save(settings)
    subprocess.run(
        command,
        input=json.dumps(event("UserPromptSubmit")),
        capture_output=True,
        text=True,
        check=True,
    )
    assert ActivityEvents(tmp_path).merge([], "")[0][0]["activity_state"] == "idle"


def test_hook_failure_is_silent_and_does_not_block_codex(tmp_path):
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("file", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "codester.codex_hook", "--data-dir", str(blocked)],
        input=json.dumps(event("Stop")),
        capture_output=True,
        text=True,
        env={**os.environ},
    )
    assert result.returncode == 0
    assert result.stdout == "{}\n"
    assert result.stderr == ""


def test_installer_enables_live_activity_without_changing_account_login(tmp_path):
    Store(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "codester.codex_hook",
            "--data-dir",
            str(tmp_path),
            "--enable-activity",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    settings = Store(tmp_path).read()
    assert settings["demo"] is False
    assert settings["codex"] == {"enabled": True, "activity": True}


@pytest.mark.parametrize("state", ["limited", "error", "idle", "stopped"])
def test_terminal_rollout_recovers_missing_stop_hook(tmp_path, monkeypatch, state):
    monkeypatch.setattr("codester.codex_events.time.time", lambda: 100.0)
    events = ActivityEvents(tmp_path)
    events.record(event("UserPromptSubmit"))
    terminal = {
        "id": "first",
        "title": "Task",
        "project": "project-one",
        "timestamp": 100,
        "activity_state": state,
        "inferred_active": False,
        "activity_source": "rollout",
        "activity_turn_id": "turn-1",
        "activity_timestamp": 110.0,
        "status": "Usage limit reached" if state == "limited" else state,
    }
    task = events.merge([terminal], "")[0][0]
    assert task["activity_state"] == state
    assert task["inferred_active"] is False
    assert task["timestamp"] == 110.0
    # A newly submitted turn must not be stopped by that older failure.
    events.record(event("UserPromptSubmit", turn="turn-2"))
    assert events.merge([terminal], "")[0][0]["activity_state"] == "active"
    # A continuation in the same turn also outranks an earlier terminal record.
    monkeypatch.setattr("codester.codex_events.time.time", lambda: 120.0)
    events.record(event("UserPromptSubmit"))
    assert events.merge([terminal], "")[0][0]["activity_state"] == "active"


def test_usage_limit_error_in_real_rollout_shape(tmp_path):
    rollout = tmp_path / "rollout.jsonl"
    rollout.write_text(
        json.dumps(
            {
                "timestamp": "2026-09-15T15:04:40.740Z",
                "type": "event_msg",
                "payload": {
                    "type": "task_complete",
                    "turn_id": "failed-turn",
                    "last_agent_message": None,
                    "error": {
                        "message": "You've hit your usage limit.",
                        "codex_error_info": "usage_limit_exceeded",
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = codex.rollout_event(tmp_path, str(rollout))
    assert result == {"state": "limited", "turn_id": "failed-turn", "timestamp": 1789484680.740}
    assert codex.rollout_activity(tmp_path, str(rollout)) == "limited"
