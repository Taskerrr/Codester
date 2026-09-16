"""Explicit OS credential backends; never select plaintext third-party keyrings."""

import sys
import uuid
from functools import cached_property

PREFIX = b"codester-keyring-v1:"
SERVICE = "Codester"


class CredentialStoreError(RuntimeError):
    """Sanitized credential-store failure, safe for the settings screen."""


def native_backend():
    try:
        if sys.platform == "win32":
            from keyring.backends.Windows import WinVaultKeyring

            backend = WinVaultKeyring()
            backend.persist = "local machine"
            return backend
        if sys.platform == "darwin":
            from keyring.backends.macOS import Keyring

            return Keyring()
        from keyring.backends.SecretService import Keyring

        return Keyring()
    except Exception:
        raise CredentialStoreError(
            "OS credential storage is unavailable. Enable or unlock your system keyring "
            "and restart Codester. No file-storage fallback was used."
        ) from None


class NativeCredentials:
    def __init__(self):
        self.created: list[bytes] = []

    @cached_property
    def backend(self):
        return native_backend()

    def encrypt(self, value: bytes) -> bytes:
        reference = PREFIX + uuid.uuid4().hex.encode()
        self.created.append(reference)
        try:
            self.backend.set_password(f"{SERVICE}/{reference.decode()}", "credential", value.decode())
            if self.decrypt(reference) != value:
                raise CredentialStoreError("Credential verification failed.")
        except Exception:
            raise CredentialStoreError(
                "Could not save and verify the credential in your OS credential store. "
                "Unlock it and try again; the existing settings were preserved."
            ) from None
        return reference

    def decrypt(self, reference: bytes) -> bytes:
        if not reference.startswith(PREFIX):
            raise CredentialStoreError("This credential needs migration from local storage.")
        try:
            value = self.backend.get_password(f"{SERVICE}/{reference.decode()}", "credential")
        except Exception:
            raise CredentialStoreError(
                "Could not read your OS credential store. Unlock it and try again."
            ) from None
        if value is None:
            raise CredentialStoreError(
                "A saved credential is missing from this OS account. Re-enter it in Settings."
            )
        return value.encode()

    def delete(self, reference: bytes) -> None:
        try:
            service = f"{SERVICE}/{reference.decode()}"
            if self.backend.get_password(service, "credential") is not None:
                self.backend.delete_password(service, "credential")
        except Exception:
            raise CredentialStoreError(
                "Credential cleanup is pending. Unlock your OS credential store and "
                "save Settings again to retry."
            ) from None
