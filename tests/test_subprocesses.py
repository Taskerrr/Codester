from codester import subprocesses


def test_background_processes_are_hidden_on_windows(monkeypatch):
    monkeypatch.setattr(subprocesses.sys, "platform", "win32")

    assert (
        subprocesses.hidden_subprocess_creation_flags()
        == subprocesses.WINDOWS_CREATE_NO_WINDOW
    )


def test_background_processes_need_no_options_elsewhere(monkeypatch):
    monkeypatch.setattr(subprocesses.sys, "platform", "darwin")

    assert subprocesses.hidden_subprocess_creation_flags() == 0
