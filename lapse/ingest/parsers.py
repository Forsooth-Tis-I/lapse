import re
from datetime import datetime
from email.utils import getaddresses

import tldextract

from lapse.contracts import ContactChange, EventKind, ExtractedEvent
from lapse.ingest.imap import RawEmail
from lapse.ingest.prefilter import load_services, sender_host, service_for_domain

_DOMAIN = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)
_PHONE = re.compile(
    r"(?:ending\s+(?:in\s+)?|last\s+(?:two|four|2|4)\s+digits?\s*[: ]\s*|"
    r"[•*xX●]{2,}[\s()\-•*xX●]*)(\d{2,4})(?!\d)",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"[\w.!#$%&'*+/=?^`{|}~-]+@[\w-]+(?:\.[\w-]+)+")
_SENSITIVE = re.compile(
    r"\b(?:otp|code|pin|passcode|passphrase|password|token|secret)\b|one[ -]time", re.IGNORECASE
)
_DEVICE = re.compile(
    r"(?:new sign[ -]?in on|new device\s*[:\-]|new sign[ -]?in (?:from|using))\s*"
    r"([^.!?;\n]{1,80})",
    re.IGNORECASE,
)
_CHANGE = re.compile(r"\b(changed?|updated?|added|replaced)\b", re.IGNORECASE)
_RULES = [
    (EventKind.deactivation_notice, r"deactivat|will be closed|mailbox.{0,30}clos"),
    (EventKind.domain_expiry, r"domain.{0,50}expir"),
    (EventKind.twofa_disabled, r"(?:two[ -]factor|2[ -]step|2fa).{0,40}(?:disabled|turned off|removed)"),
    (EventKind.twofa_enabled, r"(?:two[ -]factor|2[ -]step|2fa).{0,40}(?:enabled|turned on|activated)"),
    (EventKind.password_reset, r"password.{0,30}(?:reset|changed)|reset.{0,30}password"),
    (EventKind.new_device, r"new device|new sign[ -]?in on"),
    (EventKind.verify_email, r"verif(?:y|ication).{0,30}email|email.{0,30}verif"),
    (EventKind.otp_email, r"\botp\b|one[ -]time|(?:verification|login|sign[ -]?in) code"),
    (EventKind.login_alert, r"sign[ -]?in|new login|logged in"),
    (EventKind.signup, r"welcome|account.{0,20}created"),
]


def phone_last4(text: str) -> list[str]:
    return list(dict.fromkeys(match.group(1) for match in _PHONE.finditer(text)))


def emails_mentioned(text: str) -> list[str]:
    text = re.sub(r"https?://\S+", "", text)
    return list(dict.fromkeys(match.group(0).lower() for match in _EMAIL.finditer(text)))


def contact_change(text: str) -> ContactChange | None:
    sentences = re.split(r"(?<=[.!?])\s+|\n", text)
    best = None
    for index, sentence in enumerate(sentences):
        if not _CHANGE.search(sentence):
            continue
        if re.search(r"\bphone\b|\bmobile\b", sentence, re.IGNORECASE):
            kind, extract_values = "phone", phone_last4
        elif re.search(r"\bemail\b|e-mail", sentence, re.IGNORECASE):
            kind, extract_values = "email", emails_mentioned
        else:
            continue
        for following in sentences[index + 1 : index + 3]:
            if re.match(r"\s*(?:old|new)\b", following, re.IGNORECASE):
                sentence += " " + following
            else:
                break
        old = new = None
        parts = re.split(r"\b(from|to|old|new)\b(?=\s|:)", sentence, flags=re.IGNORECASE)
        for role, segment in zip(parts[1::2], parts[2::2], strict=True):
            values = extract_values(segment)
            if values:
                if role.lower() in {"from", "old"}:
                    old = values[0]
                else:
                    new = values[0]
        if new is None and re.search(r"\badded\b", sentence, re.IGNORECASE):
            values = extract_values(sentence)
            new = values[0] if values else None
        candidate = (
            ContactChange(kind=kind, old_last4=old, new_last4=new)
            if kind == "phone"
            else ContactChange(kind=kind, old_email=old, new_email=new)
        )
        if best is None or len(candidate.model_dump(exclude_none=True)) > len(
            best.model_dump(exclude_none=True)
        ):
            best = candidate
    return best


def deadline_date(text: str):
    pattern = (
        r"\b(?:deactivat\w*|clos(?:e[ds]?|ing|ure)|expir\w*)\b[^.!?\n]*?"
        r"\b(?:on|by|before)\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4}|"
        r"\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})\b"
    )
    for match in re.finditer(pattern, text, re.IGNORECASE):
        for format in ("%d %B %Y", "%d %b %Y", "%d/%m/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(match[1], format).date()
            except ValueError:
                pass
    return None


def event_kind(text: str, change: ContactChange | None = None) -> EventKind:
    for kind, pattern in _RULES:
        if re.search(pattern, text, re.IGNORECASE):
            if kind == EventKind.otp_email and re.search(
                r"\bsms\b|sent.{0,50}(?:phone|mobile)", text, re.IGNORECASE
            ):
                return EventKind.otp_sms_notice
            if change and kind not in {EventKind.deactivation_notice, EventKind.domain_expiry}:
                return EventKind.contact_changed
            return kind
    return EventKind.contact_changed if change else EventKind.other


def safe_text(text: str, *, context: str = "") -> str:
    if _SENSITIVE.search(text + " " + context):
        return "[Security content omitted]"
    return re.sub(r"https?://\S+", "[link omitted]", text)


def parse(email: RawEmail, services: dict[str, list[str]] | None = None) -> ExtractedEvent:
    if services is None:
        services = load_services()
    text = email.subject + ". " + email.body_text
    change = contact_change(text)
    kind = event_kind(text, change)
    host = sender_host(email.sender)
    domain = _DOMAIN(host).top_domain_under_public_suffix or host
    recipients = [address for _, address in getaddresses([email.to]) if "@" in address]
    device = _DEVICE.search(text)
    return ExtractedEvent(
        msg_id=email.msg_id,
        inbox=email.inbox,
        date=email.date,
        sender=email.sender,
        sender_domain=domain,
        subject=safe_text(email.subject, context=email.body_text),
        snippet=safe_text(email.body_text, context=email.subject)[:300],
        service_id=service_for_domain(host, services),
        account_identifier=recipients[0].lower() if recipients else None,
        event=kind,
        phone_last4=phone_last4(text),
        emails_mentioned=emails_mentioned(email.body_text),
        device=device[1].strip() if device and not _SENSITIVE.search(device[1]) else None,
        contact_change=change,
        deadline=deadline_date(text)
        if kind in {EventKind.deactivation_notice, EventKind.domain_expiry}
        else None,
        confidence=0.8 if kind != EventKind.other else 0.35,
    )
