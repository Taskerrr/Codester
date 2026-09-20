import sqlite3

import pytest

from codester.app import create_app
from codester.credentials import PREFIX, CredentialStoreError
from codester.poller import Poller
from codester.store import ConfigurationError, Store


def save_token(store, token):
    settings = store.read()
    settings["github"]["token"] = token
    store.save(settings)


def rows(directory):
    with sqlite3.connect(directory / "settings.sqlite") as db:
        return db.execute("SELECT name, value FROM secrets").fetchall()


def test_native_save_replace_delete_and_restart(tmp_path, credential_backend):
    store = Store(tmp_path)
    save_token(store, "first-token")
    assert not (tmp_path / "secret.key").exists()
    assert rows(tmp_path)[0][1].startswith(PREFIX)
    assert Store(tmp_path).secret("github") == "first-token"
    save_token(store, "second-token")
    assert list(credential_backend.values.values()) == ["second-token"]
    settings = store.read()
    settings["github"]["clear_token"] = True
    store.save(settings)
    assert credential_backend.values == {}
    assert Store(tmp_path).secret("github") == ""


def test_failed_save_preserves_existing_secret_and_settings(tmp_path, credential_backend):
    store = Store(tmp_path)
    save_token(store, "original")
    credential_backend.fail_write = True
    settings = store.read()
    settings["github"].update(token="replacement", organization="changed")
    with pytest.raises(CredentialStoreError, match="existing settings were preserved"):
        store.save(settings)
    assert store.secret("github") == "original"
    assert store.read()["github"]["organization"] == ""


def test_failed_migration_preserves_legacy_then_retries(tmp_path, monkeypatch, credential_backend):
    monkeypatch.setenv("CODESTER_SECRET_STORAGE", "file")
    save_token(Store(tmp_path), "legacy-secret")
    original = rows(tmp_path)
    monkeypatch.setenv("CODESTER_SECRET_STORAGE", "native")
    credential_backend.fail_write = True
    with pytest.raises(CredentialStoreError):
        Store(tmp_path)
    assert rows(tmp_path) == original
    assert (tmp_path / "secret.key").exists()
    credential_backend.fail_write = False
    migrated = Store(tmp_path)
    assert migrated.secret("github") == "legacy-secret"
    assert not (tmp_path / "secret.key").exists()
    assert rows(tmp_path)[0][1].startswith(PREFIX)


def test_deleted_credentials_cleanup_retries(tmp_path, credential_backend):
    store = Store(tmp_path)
    save_token(store, "remove-me")
    credential_backend.fail_delete = True
    settings = store.read()
    settings["github"]["clear_token"] = True
    with pytest.raises(CredentialStoreError, match="cleanup is pending"):
        store.save(settings)
    assert store.secret("github") == ""
    credential_backend.fail_delete = False
    Store(tmp_path)
    assert credential_backend.values == {}


def test_missing_native_secret_does_not_return_empty(tmp_path, credential_backend):
    store = Store(tmp_path)
    save_token(store, "original")
    credential_backend.values.clear()
    with pytest.raises(CredentialStoreError, match="missing"):
        store.secret("github")


def test_file_mode_cannot_read_native_references(tmp_path, monkeypatch):
    save_token(Store(tmp_path), "original")
    monkeypatch.setenv("CODESTER_SECRET_STORAGE", "file")
    with pytest.raises(CredentialStoreError, match="cannot be downgraded"):
        Store(tmp_path)


def test_unverified_write_does_not_migrate(tmp_path, monkeypatch, credential_backend):
    monkeypatch.setenv("CODESTER_SECRET_STORAGE", "file")
    save_token(Store(tmp_path), "original")
    original = rows(tmp_path)
    monkeypatch.setenv("CODESTER_SECRET_STORAGE", "native")
    monkeypatch.setattr(credential_backend, "set_password", lambda *args: None)
    with pytest.raises(CredentialStoreError):
        Store(tmp_path)
    assert rows(tmp_path) == original
    assert (tmp_path / "secret.key").exists()


def test_missing_vault_entry_keeps_settings_accessible_and_poller_alive(
    tmp_path, credential_backend
):
    store = Store(tmp_path)
    data = store.read()
    data["demo"] = False
    data["github"].update(enabled=True, token="original")
    store.save(data)
    credential_backend.values.clear()
    app = create_app(tmp_path, start_poller=False)
    assert app.test_client().get("/api/settings").status_code == 200
    poller = Poller(store)
    assert poller.refresh("github") is False
    assert "missing" in poller.state["github"]["message"]
    save_token(store, "replacement")
    assert store.secret("github") == "replacement"


def test_multi_secret_migration_is_atomic(tmp_path, monkeypatch, credential_backend):
    monkeypatch.setenv("CODESTER_SECRET_STORAGE", "file")
    store = Store(tmp_path)
    settings = store.read()
    settings["github"]["token"] = "github-original"
    settings["signoz"]["api_key"] = "signoz-original"
    store.save(settings)
    original = rows(tmp_path)
    write = credential_backend.set_password

    def fail_second(service, username, password):
        if password == "github-original":
            raise RuntimeError("sensitive")
        write(service, username, password)

    monkeypatch.setenv("CODESTER_SECRET_STORAGE", "native")
    monkeypatch.setattr(credential_backend, "set_password", fail_second)
    with pytest.raises(CredentialStoreError):
        Store(tmp_path)
    assert rows(tmp_path) == original
    assert (tmp_path / "secret.key").exists()
    monkeypatch.setattr(credential_backend, "set_password", write)
    store = Store(tmp_path)
    assert store.secret("github") == "github-original"
    assert store.secret("signoz") == "signoz-original"
    assert len(credential_backend.values) == 2


def saved_tunnel(store):
    data = store.read()
    data["tunnels"] = [
        dict(
            id="1234567890abcdef", name="Original", ssh_host="server.internal",
            ssh_port=22, username="jack", auth="password", password="private-password",
            local_port=15432, remote_host="localhost", remote_port=5432,
        )
    ]
    store.save(data)
    return store.public()["tunnels"][0]


def test_copy_server_password_stays_private_and_survives_source_deletion(
    tmp_path, credential_backend
):
    store = Store(tmp_path)
    original = saved_tunnel(store)
    duplicate = dict(
        original, id="abcdef1234567890", name="Another service", local_port=13000,
        remote_port=3000, credential_source=original["id"], password="",
    )
    data = store.read()
    data["tunnels"].append(duplicate)
    store.save(data)
    assert store.secret("tunnel-password:abcdef1234567890") == "private-password"
    assert "private-password" not in str(store.public())
    assert "credential_source" not in str(store.public())
    assert len(credential_backend.values) == 2
    data = store.read()
    data["tunnels"] = [data["tunnels"][1]]
    store.save(data)
    assert store.secret("tunnel-password:abcdef1234567890") == "private-password"
    assert len(credential_backend.values) == 1


@pytest.mark.parametrize("changes", [
    {"ssh_host": "other.internal"}, {"username": "other"}, {"ssh_port": 2222},
    {"credential_source": "unknown"}, {"credential_source": []}, {"auth": "agent"},
])
def test_copy_password_rejects_changed_identity(tmp_path, changes):
    store = Store(tmp_path)
    original = saved_tunnel(store)
    duplicate = dict(
        original, id="abcdef1234567890", name="Other", local_port=13000,
        credential_source=original["id"], password="",
    )
    duplicate.update(changes)
    data = store.read()
    data["tunnels"].append(duplicate)
    with pytest.raises(ConfigurationError):
        store.save(data)
    assert len(store.read()["tunnels"]) == 1
    assert store.secret("tunnel-password:1234567890abcdef") == "private-password"
