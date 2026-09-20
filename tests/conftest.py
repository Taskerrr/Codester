import pytest

from codester import credentials


class MemoryKeyring:
    def __init__(self):
        self.values = {}
        self.fail_write = False
        self.fail_delete = False

    def get_password(self, service, username):
        return self.values.get((service, username))

    def set_password(self, service, username, password):
        if self.fail_write:
            raise RuntimeError("sensitive upstream error")
        self.values[service, username] = password

    def delete_password(self, service, username):
        if self.fail_delete:
            raise RuntimeError("sensitive upstream error")
        self.values.pop((service, username), None)


@pytest.fixture(autouse=True)
def credential_backend(monkeypatch):
    """Tests must never write into the developer's real OS credential store."""
    backend = MemoryKeyring()
    monkeypatch.setattr(credentials, "native_backend", lambda: backend)
    monkeypatch.delenv("CODESTER_SECRET_STORAGE", raising=False)
    return backend
