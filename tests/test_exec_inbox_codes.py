from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime

import pytest
from imapclient.exceptions import IMAPClientError

from lapse.exec import inbox_codes
from lapse.ingest.settings import InboxSettings

SINCE = datetime(2026, 10, 17, 12, 30, tzinfo=UTC)


def mail(body, *, sender="Notion <notify@notion.so>", subject="Verify your email", html=False):
    message = EmailMessage()
    message["From"] = sender
    message["Subject"] = subject
    message["Date"] = format_datetime(SINCE + timedelta(seconds=1))
    message.set_content(body, subtype="html" if html else "plain")
    return message.as_bytes()


@pytest.mark.parametrize(
    ("body", "html", "expected"),
    [
        ("Your verification code is 123456.", False, "123456"),
        ("Your code is 012345.", False, "012345"),
        ("<p>Use <b>987654</b> to confirm.</p>", True, "987654"),
        ("Confirm: https://notion.so/verify?token=abc.", False, "https://notion.so/verify?token=abc"),
        (
            '<a href="https://notion.so/settings?k=abc&amp;flow=email"><b>Verify email</b></a>',
            True,
            "https://notion.so/settings?k=abc&flow=email",
        ),
        (
            '<a href="https://notion.so/confirm?token=123456">Confirm email</a>',
            True,
            "https://notion.so/confirm?token=123456",
        ),
        ("Your account number is 1234567.", False, None),
        ("Welcome! https://notion.so/help", False, None),
        ('<a href="http://notion.so/verify">Verify email</a>', True, None),
        ('<a href="https://[broken/verify">Verify email</a>', True, None),
        ("<script>123456</script><style>.x {color: #654321}</style>", True, None),
    ],
)
def test_extract_verification(body, html, expected):
    assert inbox_codes.extract_verification(mail(body, html=html)) == expected


def test_code_in_subject():
    assert (
        inbox_codes.extract_verification(mail("Enter the code.", subject="123456 is your code")) == "123456"
    )


def test_multipart_html_link_and_ignored_attachment():
    message = EmailMessage()
    message.set_content("Use the confirmation link in this email.")
    message.add_alternative('<a href="https://canva.com/verify?token=xyz">Confirm</a>', subtype="html")
    message.add_attachment("Unrelated number 654321", subtype="plain", filename="attachment.txt")
    assert inbox_codes.extract_verification(message.as_bytes()) == "https://canva.com/verify?token=xyz"


class FakeIMAP:
    def __init__(self, batches, *, gmail=True):
        self.batches = batches
        self.gmail = gmail
        self.selected = []
        self.searches = []
        self.fetches = []
        self.connections = []
        self.exits = 0

    def __call__(self, host, **kwargs):
        self.connections.append((host, kwargs))
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.exits += 1

    def login(self, user, password):
        assert (user, password) == ("test-user", "test-password")

    def select_folder(self, folder, *, readonly):
        self.selected.append((folder, readonly))
        if folder != "INBOX" and not self.gmail:
            raise IMAPClientError("No such mailbox")
        return {}

    def search(self, criteria):
        self.searches.append(criteria)
        self.records = self.batches[min(len(self.searches) - 1, len(self.batches) - 1)]
        return list(self.records)

    def fetch(self, uids, fields):
        self.fetches.append((uids, fields))
        return {uid: self.records[uid] for uid in uids}


def connect(monkeypatch, batches, *, gmail=True):
    client = FakeIMAP(batches, gmail=gmail)
    monkeypatch.setattr(inbox_codes, "IMAPClient", client)

    def settings(inbox):
        assert inbox == "email_primary"
        return InboxSettings("imap.example.test", "test-user", "test-password")

    monkeypatch.setattr(inbox_codes, "inbox_settings", settings)
    return client


def record(body, *, arrived=SINCE + timedelta(seconds=1), **kwargs):
    return {b"BODY[]": mail(body, **kwargs), b"INTERNALDATE": arrived}


async def test_readonly_poll_rejects_stale_sender_and_subject(monkeypatch):
    client = connect(
        monkeypatch,
        [
            {
                5: record("111111", arrived=SINCE - timedelta(seconds=1)),
                4: record("222222", arrived=SINCE - timedelta(seconds=2)),
                3: record("333333", sender='"notify@notion.so" <other@example.test>'),
                2: record("444444", subject="Your monthly bill"),
                1: record("555555"),
            }
        ],
        gmail=False,
    )
    result = await inbox_codes.await_inbox_code(
        "email_primary",
        r"@notion\.so$",
        r"verify your email",
        SINCE,
    )
    assert result == "555555"
    assert client.selected == [("[Gmail]/All Mail", True), ("INBOX", True)]
    assert client.searches == [["SINCE", (SINCE - timedelta(days=1)).date()]]
    assert all(fields == ["BODY.PEEK[]", "INTERNALDATE"] for _, fields in client.fetches)
    assert client.connections == [("imap.example.test", {"ssl": True, "timeout": 30})]
    assert client.exits == 1


@pytest.mark.parametrize("microsecond", [0, 750000])
async def test_poll_accepts_receipt_in_request_second(monkeypatch, microsecond):
    connect(
        monkeypatch,
        [
            {
                4: record("111111", arrived=SINCE - timedelta(seconds=1)),
                3: record("222222", arrived=SINCE, sender="other@example.test"),
                2: record("333333", arrived=SINCE, subject="Monthly bill"),
                1: record("444444", arrived=SINCE),
            }
        ],
    )
    assert (
        await inbox_codes.await_inbox_code(
            "email_primary",
            r"@notion\.so$",
            "verify",
            SINCE.replace(microsecond=microsecond),
            timeout_s=0.05,
            poll_s=0.001,
        )
        == "444444"
    )


async def test_poll_finds_message_on_later_scan(monkeypatch):
    client = connect(monkeypatch, [{}, {1: record("123456")}])
    assert (
        await inbox_codes.await_inbox_code(
            "email_primary",
            r"@notion\.so$",
            "verify",
            SINCE,
            poll_s=0.001,
        )
        == "123456"
    )
    assert len(client.searches) == 2
    assert client.exits == 2


async def test_poll_timeout(monkeypatch):
    client = connect(monkeypatch, [{}])
    with pytest.raises(TimeoutError, match="Timed out waiting"):
        await inbox_codes.await_inbox_code(
            "email_primary",
            r"@notion\.so$",
            "verify",
            SINCE,
            timeout_s=0.02,
            poll_s=0.001,
        )
    assert client.exits > 0


async def test_date_fallback_and_missing_date(monkeypatch):
    no_date = EmailMessage()
    no_date["From"] = "notify@notion.so"
    no_date["Subject"] = "Verify email"
    no_date.set_content("654321")
    connect(monkeypatch, [{2: {b"BODY[]": no_date.as_bytes()}, 1: {b"BODY[]": mail("123456")}}])
    assert (
        await inbox_codes.await_inbox_code(
            "email_primary",
            r"@notion\.so$",
            "verify",
            SINCE,
        )
        == "123456"
    )


async def test_reject_naive_start_time():
    with pytest.raises(ValueError, match="timezone"):
        await inbox_codes.await_inbox_code("email_primary", ".*", ".*", SINCE.replace(tzinfo=None))


@pytest.mark.parametrize(("timeout_s", "poll_s"), [(0, 1), (1, 0)])
async def test_reject_invalid_poll_limits(timeout_s, poll_s):
    with pytest.raises(ValueError, match="positive"):
        await inbox_codes.await_inbox_code(
            "email_primary", ".*", ".*", SINCE, timeout_s=timeout_s, poll_s=poll_s
        )


@pytest.mark.parametrize("code", ["Ab12Cd", "abcdef", "123456"])
def test_explicit_code_pattern_extracts_bare_line_before_verification_link(code):
    payload = mail(f"{code}\n\nConfirm: https://notion.so/verify?token=other")
    assert inbox_codes.extract_verification(payload, code_pattern=r"(?m)^[A-Za-z0-9]{6}$") == code


def test_alphanumeric_codes_do_not_change_default_extraction():
    assert inbox_codes.extract_verification(mail("Ab12Cd")) is None
    assert (
        inbox_codes.extract_verification(mail("Ab12Cd\nhttps://notion.so/verify?token=other"))
        == "https://notion.so/verify?token=other"
    )


async def test_inbox_poll_forwards_explicit_alphanumeric_pattern(monkeypatch):
    connect(monkeypatch, [{1: record("Ab12Cd")}])
    assert (
        await inbox_codes.await_inbox_code(
            "email_primary",
            r"@notion\.so$",
            "verify",
            SINCE,
            code_pattern=r"(?m)^[A-Za-z0-9]{6}$",
            timeout_s=0.1,
            poll_s=0.001,
        )
        == "Ab12Cd"
    )


def test_notion_code_pattern_accepts_crlf_plain_text():
    from lapse.exec.recipes.notion_change_email import CODE_PATTERN

    payload = mail("Ab12Cd").replace(b"\n", b"\r\n")
    assert inbox_codes.extract_verification(payload, code_pattern=CODE_PATTERN) == "Ab12Cd"
    assert inbox_codes.extract_verification(payload) is None
    assert inbox_codes.extract_verification(mail("123456").replace(b"\n", b"\r\n")) == "123456"
