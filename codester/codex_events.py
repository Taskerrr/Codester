"""Direct lifecycle deliveries, stored beside Codester's own settings."""

import sqlite3
import time
from pathlib import Path

EVENT_STATES = {
    "UserPromptSubmit": "active",
    "Stop": "idle",
    "Interrupt": "stopped",
    "SessionEnd": "idle",
}


class ActivityEvents:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = directory / "codex-activity.sqlite"
        with sqlite3.connect(self.path) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS activity ("
                "session_id TEXT PRIMARY KEY, turn_id TEXT, event TEXT NOT NULL, "
                "project TEXT NOT NULL, observed_at REAL NOT NULL)"
            )

    def record(self, payload: object) -> bool:
        if not isinstance(payload, dict):
            return False
        event = payload.get("hook_event_name")
        session = payload.get("session_id")
        turn = payload.get("turn_id", "")
        cwd = payload.get("cwd")
        if (
            not isinstance(event, str)
            or event not in EVENT_STATES
            or not isinstance(session, str)
            or not 1 <= len(session) <= 128
            or not isinstance(turn, str)
            or len(turn) > 128
            or not isinstance(cwd, str)
            or not 1 <= len(cwd) <= 4096
        ):
            return False
        project = cwd.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1][:160]
        with sqlite3.connect(self.path, timeout=2) as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute(
                "SELECT turn_id FROM activity WHERE session_id=?", (session,)
            ).fetchone()
            # A late completion from an older turn must not stop a newer turn.
            if previous and event in {"Stop", "Interrupt"} and previous[0] and turn != previous[0]:
                return False
            db.execute(
                "INSERT OR REPLACE INTO activity VALUES (?,?,?,?,?)",
                (session, turn, event, project, time.time()),
            )
            db.execute(
                "DELETE FROM activity WHERE session_id NOT IN "
                "(SELECT session_id FROM activity ORDER BY observed_at DESC LIMIT 100)"
            )
        return True

    def merge(self, tasks: list[dict], note: str) -> tuple[list[dict], str]:
        with sqlite3.connect(self.path, timeout=2) as db:
            rows = db.execute(
                "SELECT session_id,event,project,observed_at,turn_id FROM activity "
                "ORDER BY observed_at DESC LIMIT 100"
            ).fetchall()
        if not rows:
            return tasks, note
        merged = {task["id"]: dict(task) for task in tasks}
        for session, event, project, observed_at, turn_id in rows:
            state = EVENT_STATES[event]
            task = merged.setdefault(session, {"id": session, "title": "Codex session"})
            # Stop hooks are not guaranteed on failures. A terminal rollout for
            # this exact turn, after this delivery, is stronger than a start hook.
            terminal_at = task.get("activity_timestamp")
            if (
                task.get("activity_turn_id") == turn_id
                and turn_id
                and task.get("activity_state") in {"idle", "stopped", "limited", "error"}
                and isinstance(terminal_at, (float, int))
                and terminal_at >= observed_at
            ):
                task["timestamp"] = terminal_at
                continue
            task.update(
                project=project,
                timestamp=observed_at,
                activity_state=state,
                activity_source="hook",
                inferred_active=state == "active",
                status={"active": "Active", "idle": "Idle", "stopped": "Stopped"}[state],
            )
        return sorted(merged.values(), key=lambda task: task["timestamp"], reverse=True)[:6], (
            "Direct Codex events are connected. Sessions without delivered events use local history."
        )

    def status(self) -> dict:
        with sqlite3.connect(self.path) as db:
            row = db.execute(
                "SELECT event,observed_at FROM activity ORDER BY observed_at DESC LIMIT 1"
            ).fetchone()
        return {
            "connected": row is not None,
            "last_event": row[0] if row else None,
            "last_received_at": row[1] if row else None,
        }
