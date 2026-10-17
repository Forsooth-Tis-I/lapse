from datetime import date

import pytest

from lapse.contracts import EventKind
from lapse.ingest.parsers import contact_change, deadline_date, parse, phone_last4


@pytest.mark.parametrize(
    "text,expected",
    [
        ("ending in 4321", ["4321"]),
        ("••••4321", ["4321"]),
        ("******21", ["21"]),
        ("+91 XXXXX X4321", ["4321"]),
        ("xxx-xxx-4321", ["4321"]),
        ("+1 (•••) •••-••21", ["21"]),
        ("Your OTP is 4321", []),
        ("ending in 4321 and ••••4321", ["4321"]),
        ("ending in 432123", []),
    ],
)
def test_masked_phones(text, expected):
    assert phone_last4(text) == expected


def test_addresses_service_and_domain(raw):
    event = parse(
        raw("Recovery email: old@example.edu", sender="Amazon <n@notify.amazon.co.uk>"),
        {"amazon": ["amazon.co.uk"]},
    )
    assert event.account_identifier == "demo@example.com"
    assert event.sender_domain == "amazon.co.uk"
    assert event.service_id == "amazon"
    assert event.emails_mentioned == ["old@example.edu"]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("New sign-in on Pixel 9", "Pixel 9"),
        ("We noticed a new device: iPhone 17.", "iPhone 17"),
    ],
)
def test_device(raw, text, expected):
    event = parse(raw(text))
    assert event.device == expected
    assert event.event == EventKind.new_device


def test_phone_change():
    change = contact_change("Your recovery phone number changed from ••••4321 to ••••7788.")
    assert change.model_dump(exclude_none=True) == {"kind": "phone", "old_last4": "4321", "new_last4": "7788"}
    change = contact_change("Your phone number was changed to ******21.")
    assert change.old_last4 is None
    assert change.new_last4 == "21"


def test_email_change():
    change = contact_change("Your email address changed from old@example.edu to new@example.com.")
    assert change.model_dump(exclude_none=True) == {
        "kind": "email",
        "old_email": "old@example.edu",
        "new_email": "new@example.com",
    }


@pytest.mark.parametrize("text", ["will be deactivated on 15 November 2026", "will be closed by 15/11/2026"])
def test_deadline(raw, text):
    assert parse(raw(text)).deadline == date(2026, 11, 15)


def test_invalid_deadline():
    assert deadline_date("will be closed by 31/02/2026") is None


@pytest.mark.parametrize(
    "text,kind",
    [
        ("Welcome to Coursera", "signup"),
        ("Verify your email address", "verify_email"),
        ("Your OTP is 918273", "otp_email"),
        ("Verification code sent by SMS to phone ending in 4321", "otp_sms_notice"),
        ("New login to X", "login_alert"),
        ("2-Step Verification enabled", "twofa_enabled"),
        ("Two-factor authentication disabled", "twofa_disabled"),
        ("Reset your password", "password_reset"),
        ("Your domain will expire on 20 November 2026", "domain_expiry"),
        ("A phone number ending in 4321 was added", "contact_changed"),
        ("Thanks for your order", "other"),
    ],
)
def test_kinds(raw, text, kind):
    assert parse(raw(text)).event == kind


def test_otp_and_links_not_in_evidence(raw):
    event = parse(raw("Use maple-river-forest as your login code.", subject="Your OTP 918273"))
    assert "918273" not in event.model_dump_json()
    assert "maple-river-forest" not in event.model_dump_json()
    event = parse(raw("Visit https://example.com/auth?token=secret for details."))
    assert "https://" not in event.snippet


@pytest.mark.parametrize(
    "text",
    [
        "Recovery phone changed. Your phone number changed from ending in 4321 to ending in 7788.",
        "Your phone number changed to ending in 7788 from ending in 4321.",
        "Your phone number changed. Old phone: ••••4321. New phone: ••••7788.",
    ],
)
def test_contact_change_roles_across_subject_and_body(text):
    change = contact_change(text)
    assert change.old_last4 == "4321"
    assert change.new_last4 == "7788"


@pytest.mark.parametrize(
    "subject,body",
    [
        ("Your verification code", "918273"),
        ("918273", "Here is your login code."),
        ("Security alert", "New sign-in on Pixel 9 using code 918273."),
    ],
)
def test_secret_context_covers_subject_body_and_device(raw, subject, body):
    assert "918273" not in parse(raw(body, subject=subject)).model_dump_json()


def test_url_tokens_do_not_become_email_evidence(raw):
    event = parse(
        raw(
            "Click https://example.com/verify?token=SUPERSECRET&email=demo@example.com "
            "to verify your email. Contact help@example.com."
        )
    )
    assert event.emails_mentioned == ["help@example.com"]
    assert "supersecret" not in event.model_dump_json().lower()


def test_signin_pin_is_not_persisted(raw):
    event = parse(raw("Your sign-in PIN is 918273.", subject="New sign-in"))
    assert "918273" not in event.model_dump_json()


def test_deadline_belongs_to_deactivation_clause(raw):
    event = parse(
        raw(
            "On 1 November 2026 we announced the closure. Your email will be deactivated on 15 November 2026."
        )
    )
    assert event.deadline == date(2026, 11, 15)
