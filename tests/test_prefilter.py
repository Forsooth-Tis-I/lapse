import pytest

from lapse.ingest.prefilter import load_services, prefilter, service_for_domain


@pytest.mark.parametrize(
    "keyword",
    [
        "welcome",
        "verify",
        "verification code",
        "OTP",
        "one-time",
        "sign-in",
        "new device",
        "security alert",
        "password",
        "two-factor",
        "2-step",
        "phone number",
        "recovery",
        "deactivated",
        "will be closed",
        "expire",
    ],
)
def test_keywords(raw, keyword):
    assert prefilter(raw(keyword, subject="Notice", sender="it@example.edu")) == (True, "security_keyword")


def test_known_service_and_irrelevant(raw):
    assert prefilter(raw("Your order is ready", subject="Receipt")) == (True, "known_service")
    assert prefilter(raw("A gardening digest", subject="News", sender="news@example.com")) == (
        False,
        "no_service_or_keyword",
    )


def test_domain_boundaries():
    assert service_for_domain("evilgoogle.com", {"google": ["google.com"]}) is None
    assert service_for_domain("google.com.attacker.test", {"google": ["google.com"]}) is None
    assert service_for_domain("accounts.google.com", {"google": ["google.com"]}) == "google"


def test_load_yaml_and_fallback(tmp_path):
    path = tmp_path / "services.yaml"
    assert "google" in load_services(path)
    path.write_text("services:\n  - service:\n      id: college\n      domains: [EXAMPLE.EDU]\n")
    assert load_services(path) == {"college": ["example.edu"]}
