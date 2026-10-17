import os
from dataclasses import dataclass, field

from lapse.config import ROOT_DIR

DATA_DIR = ROOT_DIR / "data"


@dataclass(frozen=True)
class InboxSettings:
    host: str
    user: str
    password: str = field(repr=False)


def inbox_settings(inbox: str) -> InboxSettings:
    prefixes = {"email_primary": "PRIMARY", "email_college": "COLLEGE"}
    if inbox not in prefixes:
        raise ValueError(f"Unknown inbox: {inbox}")
    prefix = prefixes[inbox]
    values = [os.environ.get(f"{prefix}_IMAP_{key}", "") for key in ("HOST", "USER", "PASSWORD")]
    if not all(values):
        raise ValueError(f"Missing {prefix}_IMAP_HOST, USER or PASSWORD configuration")
    return InboxSettings(*values)
