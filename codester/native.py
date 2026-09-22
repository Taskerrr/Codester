"""Install and manage a per-user native Codester instance (macOS/Windows)."""

import argparse
import base64
import json
import os
import plistlib
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from waitress import create_server

from codester.app import create_app
from codester.codex_hook import configuration
from codester.startup import LABEL, launch_agent, powershell, ps_quote, registration_path
from codester.store import Store


def configure_hooks(home: Path, python: Path, directory: Path) -> None:
    home.mkdir(parents=True, exist_ok=True)
    path = home / "hooks.json"
    original = path.read_text(encoding="utf-8") if path.exists() else "{}"
    arguments = [str(python), "-m", "codester.codex_hook", "--data-dir", str(directory)]
    command = shlex.join(arguments) + " 2>/dev/null || true"
    script = (
        "$OutputEncoding = [System.Text.UTF8Encoding]::new($false); $input | & "
        + " ".join(ps_quote(arg) for arg in arguments)
        + " 2>$null; exit 0"
    )
    windows = "powershell.exe -NoProfile -NonInteractive -EncodedCommand " + base64.b64encode(
        script.encode("utf-16-le")
    ).decode("ascii")
    updated = configuration(json.loads(original), command, windows)
    if updated == original:
        return
    backup = home / "hooks.json.before-codester-native"
    if path.exists() and not backup.exists():
        shutil.copy2(path, backup)
    staged = home / "hooks.json.codester-tmp"
    staged.write_text(updated, encoding="utf-8")
    staged.replace(path)


def migrate_docker(root: Path, directory: Path) -> None:
    """Copy a stopped container's complete data; never delete the source volume."""
    result = subprocess.run(
        ["docker", "compose", "ps", "-aq", "codester"],
        cwd=root, capture_output=True, text=True, check=True,
    )
    container = result.stdout.strip()
    if not container or "\n" in container:
        raise ValueError("Expected one existing Codester container in this checkout.")
    subprocess.run(["docker", "compose", "stop", "codester"], cwd=root, check=True)
    # Explicitly disable restart so Docker cannot reclaim port 8765 after a reboot.
    subprocess.run(["docker", "update", "--restart=no", container], check=True)
    directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".codester-import-", dir=directory.parent) as temp:
        staged = Path(temp) / "data"
        staged.mkdir(mode=0o700)
        subprocess.run(["docker", "cp", f"{container}:/data/.", str(staged)], check=True)
        if not (staged / "settings.sqlite").exists():
            raise ValueError("Docker data has no settings database; original native data preserved.")
        if directory.exists():
            backup = directory.with_name(directory.name + f".before-native-{time.time_ns()}")
            directory.rename(backup)
            print(f"Previous native data backed up to {backup}")
        shutil.move(str(staged), directory)
    print("Docker volume preserved. Its Codester container is stopped with automatic restart off.")


def mac_service(action: str, root: Path, python: Path, directory: Path) -> None:
    domain = f"gui/{os.getuid()}"
    path = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
    loaded = subprocess.run(
        ["launchctl", "print", f"{domain}/{LABEL}"], capture_output=True,
    ).returncode == 0
    if loaded:
        subprocess.run(["launchctl", "bootout", f"{domain}/{LABEL}"], check=True)
    if action == "uninstall":
        path.unlink(missing_ok=True)
    if action in {"install", "restart"}:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(plistlib.dumps(launch_agent(root, python, directory)))
        subprocess.run(["launchctl", "bootstrap", domain, str(path)], check=True)


def windows_service(action: str, root: Path, python: Path, directory: Path) -> None:
    # A user Startup shortcut avoids Task Scheduler privileges and execution-policy changes.
    pythonw = python.with_name("pythonw.exe")
    arguments = "-m codester.native run"
    prefix = (
        "$ErrorActionPreference = 'Stop'; "
        "$link = Join-Path ([Environment]::GetFolderPath('Startup')) 'Codester.lnk'; "
    )
    if action in {"stop", "restart", "uninstall", "install"}:
        powershell(prefix + (
            "Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq "
            + ps_quote(str(pythonw))
            + " -and $_.CommandLine -like '*-m codester.native run*' } | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -ErrorAction Stop }; "
            + ("Remove-Item -LiteralPath $link -ErrorAction SilentlyContinue" if action == "uninstall" else "")
        ))
    if action in {"install", "restart"}:
        powershell(prefix + (
            "$shell = New-Object -ComObject WScript.Shell; "
            "$shortcut = $shell.CreateShortcut($link); "
            f"$shortcut.TargetPath = {ps_quote(str(pythonw))}; "
            f"$shortcut.Arguments = {ps_quote(arguments)}; "
            f"$shortcut.WorkingDirectory = {ps_quote(str(root))}; "
            '$shortcut.Save(); $shell.Run(([char]34 + $link + [char]34), 0, $false) | Out-Null'
        ))


def service(action: str, root: Path, directory: Path) -> None:
    python = root / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")
    if sys.platform == "darwin":
        mac_service(action, root, python, directory)
    else:
        windows_service(action, root, python, directory)


def wait_for_health() -> None:
    for _ in range(30):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8765/api/health", timeout=1) as response:
                if response.status == 200:
                    print("Codester is running at http://127.0.0.1:8765.")
                    return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(1)
    raise RuntimeError("Codester did not become healthy. Check the installed data directory for startup.log and native.log.")


def run(root: Path, directory: Path) -> None:
    config = json.loads((directory / "native.json").read_text(encoding="utf-8"))
    os.environ.update(config["environment"])
    os.environ["CODESTER_SECRET_STORAGE"] = "native"
    os.environ["CODESTER_DATA_DIR"] = str(directory)
    os.environ["CODESTER_NATIVE"] = "1"
    os.chdir(root)
    # pythonw has no stdout/stderr; keep startup and application failures visible on disk.
    log = directory / "native.log"
    if log.exists() and log.stat().st_size > 5 * 1024 * 1024:
        log.replace(directory / "native.previous.log")
    with log.open("a", encoding="utf-8", buffering=1) as output:
        sys.stdout = output
        sys.stderr = output
        try:
            server = create_server(create_app(), host="127.0.0.1", port=8765, threads=8)
            if config.get("open_browser", False):
                threading.Thread(
                    target=webbrowser.open, args=("http://127.0.0.1:8765",), daemon=True,
                ).start()
            server.run()
        except Exception:
            traceback.print_exc()
            raise SystemExit(1) from None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install", "restart", "stop", "uninstall", "run"])
    parser.add_argument("--from-docker", action="store_true", help="Copy Docker data; back up native data")
    args = parser.parse_args()
    if sys.platform not in {"darwin", "win32"}:
        parser.error("Automatic startup supports macOS and Windows; use scripts/start.sh on Linux.")
    source = Path(__file__).resolve().parent.parent
    root = (Path.home() / "Library/Application Support/Codester") if sys.platform == "darwin" else source
    directory = root / ".data"
    if args.action == "run":
        run(root, directory)
        return
    if args.from_docker and args.action != "install":
        parser.error("--from-docker is only valid with install")
    if args.action == "restart" and not (directory / "native.json").exists():
        parser.error("Run the installer before restarting.")
    service("stop", root, directory)
    if args.action in {"stop", "uninstall"}:
        service(args.action, root, directory)
        print("Codester stopped." if args.action == "stop" else "Login startup removed; data and hooks retained.")
        return
    if args.from_docker:
        migrate_docker(Path(os.environ.get("CODESTER_SOURCE_ROOT", str(source))), directory)
    # launchctl bootout can return before the old process releases its listener.
    for _ in range(50):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", 8765)) != 0:
                break
        time.sleep(0.1)
    else:
        raise RuntimeError("Port 8765 is in use. Stop that server, or install with --from-docker.")
    os.environ["CODESTER_SECRET_STORAGE"] = "native"
    store = Store(directory)  # Verify/migrate credentials before registering startup.
    if args.action == "install":
        home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser().absolute()
        configure_hooks(home, root / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python"), directory)
        environment = {"PATH": os.environ.get("PATH", ""), "CODEX_HOME": str(home)}
        for key in ("CODESTER_CODEX_BIN", "CODESTER_CODEX_ACTIVITY_HOME", "CODESTER_DOCKER_SOCKET"):
            if key in os.environ:
                environment[key] = os.environ[key]
        config_path = directory / "native.json"
        config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
        config["environment"] = environment
        config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        settings = store.read()
        settings["demo"] = False
        settings["codex"].update(enabled=True, activity=True)
        store.save(settings)
    service(args.action, root, directory)
    preferences = json.loads((directory / "native.json").read_text(encoding="utf-8"))
    if not preferences.get("login_enabled", True):
        registration_path().unlink(missing_ok=True)
    wait_for_health()
    print("Review the updated activity hooks in Codex (/hooks); other hooks were preserved.")


if __name__ == "__main__":
    main()
