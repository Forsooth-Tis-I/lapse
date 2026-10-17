import os
from dataclasses import dataclass, field

from cryptography.fernet import Fernet, InvalidToken

from lapse.api.inboxes import load
from lapse.config import ROOT_DIR
from lapse.config import settings as app_settings
from lapse.graph.views import list_roots

DATA_DIR = ROOT_DIR / "data"


@dataclass(frozen=True)
class InboxSettings:
    host: str
    user: str
    password: str = field(repr=False)


def inbox_settings(inbox: str, *, uid: str | None = None) -> InboxSettings:
    if (DATA_DIR / "inboxes.enc").exists():
        config = app_settings()
        uid = uid or config.uid
        try:
            saved = load(uid, DATA_DIR, Fernet(config.secret_key.encode()))
        except (InvalidToken, ValueError) as exc:
            raise ValueError("Stored inboxes could not be decrypted. Check LAPSE_SECRET_KEY.") from exc
        if saved:
            address = next((root.address for root in list_roots(uid) if root.id == inbox), None)
            for record in saved:
                if address and record.username.strip().lower() == address.strip().lower():
                    return InboxSettings(record.host, record.username, record.app_password.get_secret_value())
    prefixes = {"email_primary": "PRIMARY", "email_college": "COLLEGE"}
    if inbox not in prefixes:
        raise ValueError(f"Unknown inbox: {inbox}")
    prefix = prefixes[inbox]
    values = [os.environ.get(f"{prefix}_IMAP_{key}", "") for key in ("HOST", "USER", "PASSWORD")]
    if not all(values):
        raise ValueError(f"Missing {prefix}_IMAP_HOST, USER or PASSWORD configuration")
    return InboxSettings(*values)
