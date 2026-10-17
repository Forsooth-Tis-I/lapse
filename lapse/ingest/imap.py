from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path

from imapclient import IMAPClient
from imapclient.exceptions import IMAPClientError

from lapse.ingest.settings import DATA_DIR, inbox_settings
from lapse.ingest.storage import read_json, write_json


@dataclass(frozen=True)
class RawEmail:
    msg_id: str
    inbox: str
    date: datetime
    sender: str
    to: str
    subject: str
    body_text: str = field(repr=False)


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"br", "p", "div", "li", "tr"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {"p", "div", "li", "tr"}:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def parse_email(payload: bytes, inbox: str, fallback_date: datetime | None = None) -> RawEmail:
    message = BytesParser(policy=policy.default).parsebytes(payload)
    part = message.get_body(preferencelist=("plain", "html"))
    body = ""
    if part is not None:
        try:
            body = part.get_content(errors="replace")
        except LookupError:
            body = part.get_payload(decode=True).decode("utf-8", errors="replace")
        if part.get_content_type() == "text/html":
            parser = _HTMLText()
            parser.feed(body)
            body = "".join(parser.parts)
    try:
        date = parsedate_to_datetime(str(message.get("Date", "")))
    except (ValueError, TypeError, OverflowError):
        date = fallback_date or datetime(1970, 1, 1, tzinfo=UTC)
    if date.tzinfo is None:
        date = date.replace(tzinfo=UTC)
    return RawEmail(
        msg_id=str(message.get("Message-ID") or f"<sha256-{sha256(payload).hexdigest()}@lapse.invalid>"),
        inbox=inbox,
        date=date,
        sender=str(message.get("From", "")),
        to=str(message.get("To", "")),
        subject=str(message.get("Subject", "")),
        body_text=" ".join(body.split())[:4000],
    )


@contextmanager
def fetch_emails(
    inbox: str,
    *,
    uid: str | None = None,
    state_path: Path = DATA_DIR / "ingest_state.json",
    client_factory=IMAPClient,
) -> Iterator[Iterator[RawEmail]]:
    """Checkpoint only when the complete scan and its consumer finish successfully."""
    config = inbox_settings(inbox, uid=uid)
    state = read_json(state_path)
    with client_factory(config.host, ssl=True, timeout=30) as client:
        client.login(config.user, config.password)
        mailbox = "[Gmail]/All Mail"
        try:
            selected = client.select_folder(mailbox, readonly=True)
        except IMAPClientError:
            mailbox = "INBOX"
            selected = client.select_folder(mailbox, readonly=True)
        identity = f"{config.host}/{config.user}/{mailbox}"
        validity = int(selected[b"UIDVALIDITY"])
        previous = state.get(inbox, {})
        watermark = (
            int(previous.get("uid", 0))
            if previous.get("identity") == identity and previous.get("uidvalidity") == validity
            else 0
        )
        uids = sorted(
            (int(uid) for uid in client.search(["UID", f"{watermark + 1}:*"]) if int(uid) > watermark),
            reverse=True,
        )
        consumed = False

        def messages():
            nonlocal consumed
            for message_uid in uids:
                response = client.fetch([message_uid], ["BODY.PEEK[]", "INTERNALDATE"])
                record = response[message_uid]
                yield parse_email(record[b"BODY[]"], inbox, record.get(b"INTERNALDATE"))
            consumed = True

        yield messages()
        if consumed:
            state[inbox] = {
                "identity": identity,
                "uidvalidity": validity,
                "uid": max(uids, default=watermark),
            }
            write_json(state_path, state)
