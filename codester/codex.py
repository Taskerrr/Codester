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


def modified_time(path: Path) -> float:
    return path.stat().st_mtime


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
    home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
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
            rows = db.execute(
                "SELECT id,title,updated_at,cwd FROM threads WHERE source='vscode' "
                "AND archived=0 ORDER BY updated_at DESC LIMIT 6"
            ).fetchall()
        return [
            {
                "id": row[0],
                "title": row[1][:160],
                "timestamp": row[2],
                "project": Path(row[3]).name,
                "status": "Recent activity",
            }
            for row in rows
        ], "Local VS Code history; updated time is not proof a task is running."
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
