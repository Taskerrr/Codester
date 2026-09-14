"""Minimal OpenSSH askpass bridge into Codester's encrypted local secret store."""

import os
from pathlib import Path

from codester.store import Store


def main() -> None:
    name = os.environ.get("CODESTER_SSH_SECRET", "")
    if not name.startswith("tunnel-password:"):
        raise SystemExit(1)
    password = Store(Path(os.environ.get("CODESTER_DATA_DIR", ".data"))).secret(name)
    if not password:
        raise SystemExit(1)
    print(password, flush=True)


if __name__ == "__main__":
    main()
