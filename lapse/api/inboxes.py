import fcntl
import json
import os
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

from lapse.api.models import InboxInput


def store(uid: str, inboxes: list[InboxInput], directory: Path, cipher: Fernet) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "inboxes.enc"
    with (directory / ".inboxes.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        records = json.loads(cipher.decrypt(path.read_bytes())) if path.exists() else {}
        records[uid] = [
            {
                "host": inbox.host,
                "username": inbox.username,
                "app_password": inbox.app_password.get_secret_value(),
            }
            for inbox in inboxes
        ]
        encrypted = cipher.encrypt(json.dumps(records).encode())
        fd, temporary = tempfile.mkstemp(dir=directory, prefix=".inboxes.")
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(encrypted)
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
