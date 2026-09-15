"""Account limits via Codex; optional read-only local VS Code thread metadata."""

import json
import os
import queue
import shutil
import sqlite3
import subprocess
import threading
import time
from pathlib import Path

from codester.transport import IntegrationError

ACTIVE_ACTIVITY_SECONDS = 180
ROLLOUT_MAX_SCAN_BYTES = 32 * 1024 * 1024
ROLLOUT_TAIL_BYTES = 131_072


def modified_time(path: Path) -> float:
    return path.stat().st_mtime


def _lifecycle_event(line: bytes) -> str | None:
    if b'"event_msg"' not in line:
        return None
    try:
        item = json.loads(line)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(item, dict):
        return None
    payload = item.get("payload")
    if item.get("type") != "event_msg" or not isinstance(payload, dict):
        return None
    return {
        "task_started": "active",
        "task_complete": "idle",
        "turn_aborted": "stopped",
    }.get(payload.get("type"))


def _read_rollout_state(path: Path) -> str | None:
    # Read backwards from this open file's EOF on every poll. A cached state can
    # miss completion when intervening output pushes the event outside the tail.
    with path.open("rb") as stream:
        end = stream.seek(0, os.SEEK_END)
        lower_bound = max(0, end - ROLLOUT_MAX_SCAN_BYTES)
        fragment = b""
        while end > lower_bound:
            start = max(lower_bound, end - ROLLOUT_TAIL_BYTES)
            stream.seek(start)
            lines = (stream.read(end - start) + fragment).split(b"\n")
            # Preserve a record crossing a chunk boundary, including large
            # task_complete records that embed the final assistant message.
            fragment = lines[0] if start else b""
            for line in reversed(lines[1:] if start else lines):
                state = _lifecycle_event(line)
                if state is not None:
                    return state
            end = start
    return None


def rollout_activity(home: Path, stored_path: object) -> str | None:
    if not isinstance(stored_path, str) or not stored_path:
        return None
    candidates = [Path(stored_path)]
    normalized = stored_path.replace("\\", "/")
    if "/.codex/" in normalized:
        candidates.append(home / normalized.split("/.codex/", 1)[1])
    root = home.resolve()
    for candidate in candidates:
        try:
            if not candidate.is_file():
                continue
            resolved = candidate.resolve()
            if not resolved.is_relative_to(root) or not resolved.is_file():
                continue
            return _read_rollout_state(resolved)
        except OSError:
            continue
    return None


def executable() -> str | None:
    configured = os.environ.get("CODESTER_CODEX_BIN")
    if configured:
        return configured if Path(configured).is_file() else None
    found = shutil.which("codex")
    if found:
        return found
    root = Path.home() / ".vscode" / "extensions"
    if not root.is_dir():
        return None
    candidates: list[Path] = [
        p
        for p in root.glob("openai.chatgpt-*/bin/*/codex*")
        if p.is_file() and p.name in {"codex", "codex.exe"}
    ]
    candidates.sort(key=modified_time, reverse=True)
    return str(candidates[0]) if candidates else None


def account_limits() -> dict:
    binary = executable()
    if not binary:
        raise IntegrationError(
            "Codex executable not found. Install the VS Code extension or set CODESTER_CODEX_BIN."
        )
    messages: queue.Queue = queue.Queue(maxsize=128)
    try:
        process = subprocess.Popen(
            [binary, "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
        )
    except OSError as exc:
        raise IntegrationError(
            "Cannot start Codex. Check CODESTER_CODEX_BIN and executable permissions."
        ) from exc
    assert process.stdout is not None and process.stdin is not None

    def reader() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict) and "id" in item:
                try:
                    messages.put_nowait(item)
                except queue.Full:
                    return

    worker = threading.Thread(target=reader, daemon=True)
    worker.start()

    def request(identifier: int, method: str, params: dict | None = None) -> dict:
        assert process.stdin is not None
        process.stdin.write(
            json.dumps({"id": identifier, "method": method, "params": params}) + "\n"
        )
        process.stdin.flush()
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            reply = messages.get(timeout=max(0.01, deadline - time.monotonic()))
            if reply.get("id") != identifier:
                continue
            if "error" in reply:
                raise IntegrationError(
                    "Codex account read failed. Sign in with ChatGPT using Codex on this machine, then retry."
                )
            return reply.get("result", {})
        raise IntegrationError("Codex account read timed out.")

    try:
        request(1, "initialize", {"clientInfo": {"name": "codester", "version": "0.1.0"}})
        process.stdin.write('{"method":"initialized"}\n')
        process.stdin.flush()
        result = request(2, "account/rateLimits/read")
        limits = result.get("rateLimits")
        if not isinstance(limits, dict):
            raise IntegrationError("Codex returned no subscription limits for this account.")
        windows = []
        for key in ("primary", "secondary"):
            window = limits.get(key)
            if isinstance(window, dict):
                windows.append(
                    {
                        "used": window.get("usedPercent"),
                        "minutes": window.get("windowDurationMins"),
                        "resets": window.get("resetsAt"),
                    }
                )
        return {
            "plan": limits.get("planType"),
            "windows": windows,
            "note": "Account limits reported by Codex."
            if windows
            else "No usage windows reported by Codex.",
        }
    except (queue.Empty, BrokenPipeError, OSError) as exc:
        raise IntegrationError(
            "Codex did not respond. Check its installation and ChatGPT sign-in."
        ) from exc
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
        worker.join(timeout=1)
        process.stdout.close()
        process.stdin.close()


def local_activity() -> tuple[list[dict], str]:
    home = Path(
        os.environ.get(
            "CODESTER_CODEX_ACTIVITY_HOME",
            os.environ.get("CODEX_HOME", str(Path.home() / ".codex")),
        )
    )
    databases = list(home.glob("state_*.sqlite")) if home.is_dir() else []
    if not databases:
        return (
            [],
            "No local Codex thread database found. WSL and remote VS Code use a separate home.",
        )
    path = max(databases, key=lambda p: p.stat().st_mtime)
    # Read the live database with its WAL; never copy, migrate, or write Codex state.
    try:
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1) as db:
            fields = {row[1] for row in db.execute("PRAGMA table_info(threads)")}
            if not {"id", "title", "source", "updated_at", "cwd", "archived"} <= fields:
                return (
                    [],
                    "Local Codex database schema is unsupported. Account usage remains available.",
                )
            rollout_column = ",rollout_path" if "rollout_path" in fields else ""
            rows = db.execute(
                f"SELECT id,title,updated_at,cwd{rollout_column} "
                "FROM threads WHERE source='vscode' "
                "AND archived=0 ORDER BY updated_at DESC LIMIT 6"
            ).fetchall()
        observed_at = time.time()
        tasks = []
        for row in rows:
            event_state = rollout_activity(home, row[4]) if len(row) > 4 else None
            inferred_active = 0 <= observed_at - row[2] <= ACTIVE_ACTIVITY_SECONDS
            active = event_state == "active" or (event_state is None and inferred_active)
            tasks.append(
                {
                    "id": row[0],
                    "title": row[1][:160],
                    "timestamp": row[2],
                    "project": Path(row[3]).name,
                    "inferred_active": active,
                    "activity_state": event_state or ("active" if active else "idle"),
                    "activity_source": "rollout" if event_state is not None else "recency",
                    "status": (
                        "Active"
                        if event_state == "active"
                        else "Active (inferred)"
                        if active
                        else "Stopped"
                        if event_state == "stopped"
                        else "Idle"
                    ),
                }
            )
        return tasks, (
            "Turn state comes from local Codex lifecycle events; older schemas use inferred recency."
        )
    except (sqlite3.Error, OSError) as exc:
        return [], "Local activity unavailable (database locked or unreadable): " + type(
            exc
        ).__name__


def snapshot(config: dict) -> dict:
    result = account_limits()
    result["tasks"], result["activity_note"] = (
        local_activity()
        if config["activity"]
        else ([], "Local activity is off. Enable it in settings to show recent VS Code tasks.")
    )
    return result
