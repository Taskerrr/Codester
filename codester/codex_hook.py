"""Short-lived Codex hook command; uses only Codester's bundled dependencies."""

import argparse
import base64
import json
import os
import shlex
import sqlite3
import sys
from pathlib import Path

from codester.codex_events import ActivityEvents
from codester.store import Store

HOOK_EVENTS = ("UserPromptSubmit", "Stop", "Interrupt", "SessionEnd")
MARKER = "-m codester.codex_hook"


def configuration(content: object, command: str, windows_command: str) -> str:
    """Merge our hooks without replacing other integrations or approving trust."""
    if not isinstance(content, dict) or not isinstance(content.get("hooks", {}), dict):
        raise ValueError("Existing hooks.json is not a hook configuration; left unchanged.")
    hooks = content.setdefault("hooks", {})
    for event in HOOK_EVENTS:
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            raise ValueError(f"Existing {event} hooks are invalid; left unchanged.")
        retained = []
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                raise ValueError(f"Existing {event} hook group is invalid; left unchanged.")
            handlers = [
                h
                for h in group["hooks"]
                if not (isinstance(h, dict) and MARKER in str(h.get("command", "")))
            ]
            if handlers:
                retained.append({**group, "hooks": handlers})
        retained.append(
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": command,
                        "commandWindows": windows_command,
                        "timeout": 3,
                    }
                ]
            }
        )
        hooks[event] = retained
    return json.dumps(content, indent=2) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--configure", action="store_true")
    parser.add_argument("--enable-activity", action="store_true")
    parser.add_argument("--docker-bin", default="docker")
    parser.add_argument("--container", default="codester-codester-1")
    args = parser.parse_args()
    if args.enable_activity:
        directory = args.data_dir or Path(os.environ.get("CODESTER_DATA_DIR", ".data"))
        store = Store(directory)
        settings = store.read()
        settings["demo"] = False
        settings["codex"].update(enabled=True, activity=True)
        store.save(settings)
        return
    if args.configure:
        command = (
            shlex.join(
                [
                    args.docker_bin,
                    "exec",
                    "-i",
                    args.container,
                    "python",
                    "-m",
                    "codester.codex_hook",
                ]
            )
            + " 2>/dev/null || true"
        )
        # Explicit PowerShell works independently of the user's configured Codex shell.
        docker = args.docker_bin.replace("'", "''")
        container = args.container.replace("'", "''")
        script = (
            "$OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
            f"$input | & '{docker}' exec -i '{container}' python -m codester.codex_hook "
            "2>$null; exit 0"
        )
        windows_command = (
            "powershell.exe -NoProfile -NonInteractive -EncodedCommand "
            + base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        )
        content = json.load(sys.stdin)
        print(configuration(content, command, windows_command), end="")
        return
    # Hook input can include prompt/response text. Only lifecycle metadata is retained;
    # never print the input or make an unavailable dashboard block the user's turn.
    try:
        payload = json.loads(sys.stdin.buffer.read(4 * 1024 * 1024))
        directory = args.data_dir or Path(os.environ.get("CODESTER_DATA_DIR", ".data"))
        settings = Store(directory).read()
        if settings["codex"]["enabled"] and settings["codex"]["activity"]:
            ActivityEvents(directory).record(payload)
    except (OSError, ValueError, sqlite3.Error):
        pass
    print("{}")


if __name__ == "__main__":
    main()
