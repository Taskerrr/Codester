"""User login preferences; registration changes never stop the running server."""

import base64
import json
import os
import plistlib
import subprocess
import sys
import threading
from pathlib import Path

from codester.store import ConfigurationError
from codester.subprocesses import hidden_subprocess_creation_flags

LABEL = "local.codester.dashboard"
LOCK = threading.Lock()


def powershell(script: str) -> None:
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        check=True,
        creationflags=hidden_subprocess_creation_flags(),
    )


def ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def launch_agent(root: Path, python: Path, directory: Path) -> dict:
    return {
        "Label": LABEL,
        "ProgramArguments": [str(python), "-m", "codester.native", "run"],
        "WorkingDirectory": str(root),
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 10,
        "EnvironmentVariables": {"CODESTER_DATA_DIR": str(directory)},
        "StandardOutPath": str(directory / "startup.log"),
        "StandardErrorPath": str(directory / "startup.log"),
    }


def registration_path() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
    return Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup/Codester.lnk"


def startup_status(directory: Path) -> dict:
    supported = (
        sys.platform in {"darwin", "win32"}
        and os.environ.get("CODESTER_NATIVE") == "1"
        and (directory / "native.json").is_file()
    )
    if not supported:
        return dict(supported=False, enabled=False, open_browser=False,
                    message="Run the native installer on this computer to manage login startup here.")
    config = json.loads((directory / "native.json").read_text(encoding="utf-8"))
    return dict(supported=True, enabled=registration_path().is_file(),
                open_browser=config.get("open_browser", False), message="")


def save_startup(directory: Path, payload: object) -> dict:
    if (not isinstance(payload, dict) or set(payload) != {"enabled", "open_browser"}
            or any(type(value) is not bool for value in payload.values())):
        raise ConfigurationError("Choose whether to start at login and open the browser.")
    with LOCK:
        if not startup_status(directory)["supported"]:
            raise ConfigurationError("Login controls require a native installation on this computer.")
        root = directory.parent
        path = registration_path()
        config_path = directory / "native.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["open_browser"] = payload["open_browser"]
        config["login_enabled"] = payload["enabled"]
        if payload["enabled"]:
            path.parent.mkdir(parents=True, exist_ok=True)
            if sys.platform == "darwin":
                # Writing the next-login definition does not boot out the current agent.
                staged = path.with_suffix(".tmp")
                staged.write_bytes(plistlib.dumps(launch_agent(root, root / ".venv/bin/python", directory)))
                staged.replace(path)
            else:
                powershell(
                    "$ErrorActionPreference = 'Stop'; "
                    "$shell = New-Object -ComObject WScript.Shell; "
                    f"$shortcut = $shell.CreateShortcut({ps_quote(str(path))}); "
                    f"$shortcut.TargetPath = {ps_quote(str(root / '.venv/Scripts/pythonw.exe'))}; "
                    "$shortcut.Arguments = '-m codester.native run'; "
                    f"$shortcut.WorkingDirectory = {ps_quote(str(root))}; $shortcut.Save()"
                )
        else:
            path.unlink(missing_ok=True)
        staged_config = directory / "native.json.tmp"
        staged_config.write_text(json.dumps(config, indent=2), encoding="utf-8")
        staged_config.replace(config_path)
        return startup_status(directory)
