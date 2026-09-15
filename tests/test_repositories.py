import copy
import shutil
import subprocess
import time

import pytest

from codester.repositories import RepositoryManager
from codester.store import DEFAULTS, Store


def git(path, *args):
    return subprocess.run(
        ["git", "-C", str(path), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.mark.skipif(shutil.which("git") is None, reason="Git is unavailable")
def test_repository_status_push_and_deploy_tracking(tmp_path):
    remote = tmp_path / "remote.git"
    checkout = tmp_path / "checkout"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "init", str(checkout)], check=True, capture_output=True)
    git(checkout, "config", "user.email", "codester@example.test")
    git(checkout, "config", "user.name", "Codester Test")
    (checkout / "README.md").write_text("first\n")
    git(checkout, "add", "README.md")
    git(checkout, "commit", "-m", "first")
    git(checkout, "remote", "add", "origin", str(remote))
    git(checkout, "push", "-u", "origin", "HEAD")
    (checkout / "README.md").write_text("second\n")
    git(checkout, "add", "README.md")
    git(checkout, "commit", "-m", "second")

    store = Store(tmp_path / "data")
    settings = copy.deepcopy(DEFAULTS)
    settings["github"]["repositories"] = [
        {
            "id": "1234567890abcdef",
            "repo": "taskerrr/codester",
            "path": str(checkout),
            "deploy_command": "git status --short",
        }
    ]
    store.save(settings)
    manager = RepositoryManager(store)

    status = manager.snapshot()["repositories"][0]
    assert status["ahead"] == 1
    assert status["needs_push"] is True
    assert status["deploy_state"] == "unknown"

    manager.start("1234567890abcdef", "deploy")
    wait_for_action(manager, "success")
    assert manager.snapshot()["repositories"][0]["deploy_state"] == "current"

    manager.start("1234567890abcdef", "push")
    wait_for_action(manager, "success")
    assert manager.snapshot()["repositories"][0]["ahead"] == 0

    (checkout / "README.md").write_text("dirty\n")
    manager.invalidate()
    dirty = manager.snapshot()["repositories"][0]
    assert dirty["changes"] == 1
    assert dirty["deploy_state"] == "needed"


def wait_for_action(manager, expected):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        manager.invalidate()
        action = manager.snapshot()["repositories"][0]["action"]
        if action["state"] != "running":
            assert action["state"] == expected
            return
        time.sleep(0.02)
    raise AssertionError("Repository action did not finish")
