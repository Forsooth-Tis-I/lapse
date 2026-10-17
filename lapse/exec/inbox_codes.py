import asyncio
import re
from datetime import UTC, datetime, timedelta
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit

from imapclient import IMAPClient
from imapclient.exceptions import IMAPClientError

from lapse.ingest.settings import inbox_settings

_URL = re.compile(r"https://[^\s<>\"']+", re.IGNORECASE)
_CODE = re.compile(r"(?<![A-Za-z0-9])[0-9]{6}(?![A-Za-z0-9])")
_VERIFICATION = re.compile(r"verif|confirm|activat|token|magic|auth|code=", re.IGNORECASE)


class _HTMLVerification(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text: list[str] = []
        self.links: list[list[str]] = []
        self.anchor: int | None = None
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag == "a" and not self.hidden:
            self.links.append([dict(attrs).get("href") or "", ""])
            self.anchor = len(self.links) - 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        if tag == "a":
            self.anchor = None

    def handle_data(self, data):
        if not self.hidden:
            self.text.append(data)
            if self.anchor is not None:
                self.links[self.anchor][1] += data


def extract_verification(payload: bytes, *, code_pattern: str | None = None) -> str | None:
    """Extract a code or HTTPS verification link without storing message content."""
    message = BytesParser(policy=policy.default).parsebytes(payload)
    texts = [str(message.get("Subject", ""))]
    links: list[tuple[str, str]] = []
    for part in message.walk():
        if part.get_content_disposition() == "attachment":
            continue
        if part.get_content_type() not in {"text/plain", "text/html"}:
            continue
        try:
            body = part.get_content(errors="replace")
        except LookupError:
            body = (part.get_payload(decode=True) or b"").decode("utf-8", errors="replace")
        if part.get_content_type() == "text/html":
            parser = _HTMLVerification()
            parser.feed(body)
            texts.append(" ".join(parser.text))
            links.extend((url, label) for url, label in parser.links)
        else:
            texts.append(body)
    text = "\n".join(texts)
    pattern = re.compile(code_pattern) if code_pattern is not None else _CODE
    code = pattern.search(_URL.sub("", text))
    if code:
        return code.group()
    links.extend((url.rstrip(".,);]"), "") for url in _URL.findall(text))
    for url, label in links:
        try:
            parsed = urlsplit(url)
        except ValueError:
            continue
        if (
            parsed.scheme.lower() == "https"
            and parsed.hostname
            and not parsed.username
            and _VERIFICATION.search(f"{parsed.path}?{parsed.query} {label}")
        ):
            return url
    return None


def _scan(
    inbox: str,
    sender: re.Pattern,
    subject: re.Pattern,
    since: datetime,
    timeout_s: float,
    code_pattern: str | None = None,
):
    config = inbox_settings(inbox)
    with IMAPClient(config.host, ssl=True, timeout=min(timeout_s, 30)) as client:
        client.login(config.user, config.password)
        try:
            client.select_folder("[Gmail]/All Mail", readonly=True)
        except IMAPClientError:
            client.select_folder("INBOX", readonly=True)
        # IMAP SINCE is day-granular and the server may use a different timezone.
        uids = client.search(["SINCE", (since - timedelta(days=1)).date()])
        for uid in sorted(uids, reverse=True):
            record = client.fetch([uid], ["BODY.PEEK[]", "INTERNALDATE"])[uid]
            payload = record[b"BODY[]"]
            message = BytesParser(policy=policy.default).parsebytes(payload)
            arrived = record.get(b"INTERNALDATE")
            if arrived is None:
                try:
                    arrived = parsedate_to_datetime(str(message.get("Date", "")))
                except (ValueError, TypeError, OverflowError):
                    continue
            if arrived.tzinfo is None:
                arrived = arrived.replace(tzinfo=UTC)
            if arrived < since.replace(microsecond=0):
                continue
            if not sender.search(parseaddr(str(message.get("From", "")))[1]):
                continue
            if not subject.search(str(message.get("Subject", ""))):
                continue
            result = extract_verification(payload, code_pattern=code_pattern)
            if result:
                return result
    return None


async def await_inbox_code(
    inbox: str,
    sender_pattern: str,
    subject_pattern: str,
    since: datetime,
    *,
    timeout_s: float = 120,
    poll_s: float = 2,
    code_pattern: str | None = None,
) -> str:
    """Wait for verification mail, including the request's whole second.

    IMAP dates have second precision, admitting less than one second of
    pre-request mail when ``since`` includes microseconds.
    """
    if since.tzinfo is None:
        raise ValueError("since must include a timezone")
    if timeout_s <= 0 or poll_s <= 0:
        raise ValueError("timeout_s and poll_s must be positive")
    sender = re.compile(sender_pattern, re.IGNORECASE)
    subject = re.compile(subject_pattern, re.IGNORECASE)
    try:
        async with asyncio.timeout(timeout_s):
            while True:
                result = await asyncio.to_thread(
                    _scan, inbox, sender, subject, since, timeout_s, code_pattern
                )
                if result:
                    return result
                await asyncio.sleep(poll_s)
    except IMAPClientError:
        raise RuntimeError("Inbox verification unavailable") from None
    except TimeoutError:
        raise TimeoutError("Timed out waiting for the service's verification email") from None
