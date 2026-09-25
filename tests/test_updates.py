import re
import subprocess
from pathlib import Path

import pytest

from codester.app import create_app
from codester.store import ConfigurationError
from codester.updates import SourceUpdater


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=Update Test", "-c", "user.email=test@example.invalid", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    remote = tmp_path / "remote"
    remote.mkdir()
    git(remote, "init", "-b", "main")
    (remote / ".gitignore").write_text(".data/\n.venv/\n.env\n", encoding="utf-8")
    (remote / "app.txt").write_text("old", encoding="utf-8")
    git(remote, "add", ".")
    git(remote, "commit", "-m", "initial")
    local = tmp_path / "local"
    git(tmp_path, "clone", str(remote), str(local))
    data = local / ".data"
    data.mkdir()
    (data / "settings.sqlite").write_bytes(b"preserve settings and credential references")
    (local / ".env").write_text("preserve environment", encoding="utf-8")
    monkeypatch.setenv("CODESTER_NATIVE", "1")
    return SourceUpdater(local, data), remote


def publish(remote: Path, name: str = "app.txt", content: str = "new") -> None:
    path = remote / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    git(remote, "add", "-f", name)
    git(remote, "commit", "-m", "update")


def test_fast_forward_preserves_settings(checkout):
    updater, remote = checkout
    assert updater.status()["supported"]
    assert updater.pull()["updated"] is False
    publish(remote)
    assert updater.pull()["updated"] is True
    assert (updater.root / "app.txt").read_text(encoding="utf-8") == "new"
    assert (
        updater.data_dir / "settings.sqlite"
    ).read_bytes() == b"preserve settings and credential references"
    assert (updater.root / ".env").read_text(encoding="utf-8") == "preserve environment"


@pytest.mark.parametrize("staged", [False, True])
def test_dirty_checkout_never_overwritten(checkout, staged):
    updater, remote = checkout
    publish(remote)
    (updater.root / "app.txt").write_text("local edits", encoding="utf-8")
    if staged:
        git(updater.root, "add", "app.txt")
    assert updater.status()["supported"] is False
    with pytest.raises(ConfigurationError, match="Local changes"):
        updater.pull()
    assert (updater.root / "app.txt").read_text(encoding="utf-8") == "local edits"


def test_untracked_files_block_update(checkout):
    updater, _ = checkout
    (updater.root / "notes.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="Local changes"):
        updater.pull()


def test_diverged_branch_is_not_reset(checkout):
    updater, remote = checkout
    publish(updater.root, "local.txt", "local commit")
    before = git(updater.root, "rev-parse", "HEAD")
    publish(remote)
    with pytest.raises(ConfigurationError, match="own commits"):
        updater.pull()
    assert git(updater.root, "rev-parse", "HEAD") == before


@pytest.mark.parametrize(
    "name",
    [".data/settings.sqlite", ".env", ".venv/test.txt", ".data.before-native-123/settings.sqlite"],
)
def test_incoming_data_paths_are_rejected(checkout, name):
    updater, remote = checkout
    publish(remote, name, "do not install")
    before = git(updater.root, "rev-parse", "HEAD")
    with pytest.raises(ConfigurationError, match="protected"):
        updater.pull()
    assert git(updater.root, "rev-parse", "HEAD") == before
    assert (
        updater.data_dir / "settings.sqlite"
    ).read_bytes() == b"preserve settings and credential references"


def test_tracked_data_deletion_is_rejected(checkout):
    updater, remote = checkout
    publish(remote, ".data/tracked.txt", "protected")
    git(updater.root, "pull", "--ff-only")
    git(remote, "rm", "-f", ".data/tracked.txt")
    git(remote, "commit", "-m", "remove data")
    with pytest.raises(ConfigurationError, match="protected"):
        updater.pull()
    assert (updater.data_dir / "tracked.txt").is_file()


def test_dependency_update_explains_install_step(checkout):
    updater, remote = checkout
    publish(remote, "pyproject.toml", "# dependencies changed")
    assert "installer" in updater.pull()["message"]


def test_concurrent_update_is_rejected(checkout):
    updater, _ = checkout
    with updater.lock:
        with pytest.raises(ConfigurationError, match="already running"):
            updater.pull()


def test_non_native_update_is_rejected(checkout, monkeypatch):
    updater, _ = checkout
    monkeypatch.delenv("CODESTER_NATIVE")
    assert updater.status()["supported"] is False
    with pytest.raises(ConfigurationError, match="native Git checkout"):
        updater.pull()


def test_update_api_requires_csrf_and_rejects_demo(tmp_path, monkeypatch):
    client = create_app(tmp_path, start_poller=False).test_client()
    assert client.post("/api/updates/pull").status_code == 403
    token = re.search(r'name="csrf-token" content="([^"]+)"', client.get("/").text)[1]
    headers = {"X-Codester-CSRF": token}
    assert (
        client.post(
            "/api/updates/pull", headers={**headers, "Origin": "https://other.invalid"}
        ).status_code
        == 403
    )
    monkeypatch.setattr(SourceUpdater, "pull", lambda self: {"updated": False, "message": "test"})
    assert client.post("/api/updates/pull", headers=headers).status_code == 400
