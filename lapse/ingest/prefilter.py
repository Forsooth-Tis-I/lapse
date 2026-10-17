import re
from email.utils import parseaddr
from pathlib import Path

import yaml

from lapse.config import ROOT_DIR
from lapse.ingest.imap import RawEmail

BUILTIN_SERVICES = {
    "google": ["google.com", "accounts.google.com"],
    "amazon": ["amazon.in", "amazon.com"],
    "paypal": ["paypal.com"],
    "dropbox": ["dropbox.com"],
    "github": ["github.com"],
    "notion": ["notion.so", "makenotion.com"],
    "figma": ["figma.com"],
    "coursera": ["coursera.org"],
    "swiggy": ["swiggy.in", "swiggy.com"],
    "zomato": ["zomato.com"],
    "microsoft": ["microsoft.com", "accountprotection.microsoft.com"],
    "x": ["x.com", "twitter.com"],
}
KEYWORDS = re.compile(
    r"welcome|verif(?:y|ication)|\botp\b|one[ -]time|sign[ -]?in|new device|new login|"
    r"security|password|two[ -]factor|2[ -]step|\b2fa\b|phone number|recovery|"
    r"deactivat|will be closed|closure|expir|login code",
    re.IGNORECASE,
)


def load_services(path: Path = ROOT_DIR / "lapse/policy/services.yaml") -> dict[str, list[str]]:
    if not path.exists():
        return BUILTIN_SERVICES.copy()
    document = yaml.safe_load(path.read_text())
    return {
        row["service"]["id"]: [domain.lower().rstrip(".") for domain in row["service"]["domains"]]
        for row in document["services"]
    }


def sender_host(sender: str) -> str:
    return parseaddr(sender)[1].rpartition("@")[2].lower().rstrip(".")


def service_for_domain(domain: str, services: dict[str, list[str]]) -> str | None:
    matches = [
        (len(known), service)
        for service, domains in services.items()
        for known in domains
        if domain == known or domain.endswith("." + known)
    ]
    return max(matches)[1] if matches else None


def prefilter(email: RawEmail, services: dict[str, list[str]] | None = None) -> tuple[bool, str]:
    if services is None:
        services = load_services()
    if service_for_domain(sender_host(email.sender), services):
        return True, "known_service"
    match = KEYWORDS.search(email.subject + " " + email.body_text)
    if match:
        return True, "security_keyword"
    return False, "no_service_or_keyword"
