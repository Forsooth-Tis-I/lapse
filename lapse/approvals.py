import hashlib
import hmac
import json
import secrets

from lapse import jobs
from lapse.config import settings

TTL_SECONDS = 900


def _signature(uid: str, nonce: str) -> str:
    key = settings().approval_signing_key
    if not key:
        raise RuntimeError("APPROVAL_SIGNING_KEY must be configured")
    message = json.dumps([uid, nonce], separators=(",", ":")).encode()
    return hmac.new(key.encode(), message, hashlib.sha256).hexdigest()


def mint(uid: str, change_ids: list[str]) -> str:
    nonce = secrets.token_urlsafe(24)
    signature = _signature(uid, nonce)
    jobs.client().set(f"lapse:approval:{nonce}", json.dumps(change_ids), ex=TTL_SECONDS)
    return f"{nonce}.{signature}"


def consume(uid: str, token: str) -> list[str]:
    try:
        nonce, signature = token.split(".")
    except ValueError:
        raise ValueError("Invalid approval token") from None
    if not hmac.compare_digest(signature.encode(), _signature(uid, nonce).encode()):
        raise ValueError("Invalid approval token")
    value = jobs.client().getdel(f"lapse:approval:{nonce}")
    if value is None:
        raise ValueError("Approval expired or already used")
    return json.loads(value)
