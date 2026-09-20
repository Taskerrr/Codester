import os
from pathlib import Path

import pytest

from codester import codex


@pytest.mark.parametrize(
    ("platform", "folder", "name"),
    [
        ("win32", "windows-x86_64", "codex.exe"),
        ("linux", "linux-x86_64", "codex"),
        ("darwin", "darwin-aarch64", "codex"),
    ],
)
def test_extension_discovery_ignores_newer_foreign_binary(
    tmp_path, monkeypatch, platform, folder, name
):
    monkeypatch.delenv("CODESTER_CODEX_BIN", raising=False)
    monkeypatch.setattr(codex.shutil, "which", lambda _: None)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(codex.sys, "platform", platform)
    root = tmp_path / ".vscode/extensions/openai.chatgpt-test/bin"
    expected = root / folder / name
    expected.parent.mkdir(parents=True)
    expected.touch()
    os.utime(expected, (100, 100))
    foreign = root / ("linux-x86_64" if platform == "win32" else "windows-x86_64")
    foreign.mkdir()
    (foreign / ("codex" if platform == "win32" else "codex.exe")).touch()

    assert codex.executable() == str(expected)
