import json
from datetime import UTC, datetime
from email.message import EmailMessage

import pytest
from imapclient.exceptions import IMAPClientError

from lapse.ingest.imap import fetch_emails, parse_email


def email_bytes(subject="Welcome", body="Hello", *, html=False):
    message = EmailMessage()
    message["From"] = "notice@example.com"
    message["To"] = "demo@example.com"
    message["Subject"] = subject
    message["Date"] = "Sat, 17 Oct 2026 12:00:00 +0000"
    message["Message-ID"] = "<imap@example.com>"
    message.set_content(body, subtype="html" if html else "plain")
    return message.as_bytes()


class FakeIMAP:
    def __init__(self, *, uids=(1, 2, 3), validity=10, fallback=False):
        self.uids = uids
        self.validity = validity
        self.fallback = fallback
        self.folders = []
        self.queries = []
        self.fetched = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def login(self, user, password):
        assert user == "demo@example.com"
        assert password == "synthetic"

    def select_folder(self, folder, *, readonly):
        assert readonly is True
        self.folders.append(folder)
        if self.fallback and folder != "INBOX":
            raise IMAPClientError("No such folder")
        return {b"UIDVALIDITY": self.validity}

    def search(self, query):
        self.queries.append(query)
        return self.uids

    def fetch(self, uids, fields):
        assert fields == ["BODY.PEEK[]", "INTERNALDATE"]
        self.fetched.extend(uids)
        return {uids[0]: {b"BODY[]": email_bytes(subject=f"Welcome {uids[0]}")}}


@pytest.fixture
def configured(monkeypatch):
    for suffix, value in (
        ("HOST", "imap.example.com"),
        ("USER", "demo@example.com"),
        ("PASSWORD", "synthetic"),
    ):
        monkeypatch.setenv(f"PRIMARY_IMAP_{suffix}", value)


def factory(client):
    def make(host, *, ssl, timeout):
        assert host == "imap.example.com"
        assert ssl is True
        assert timeout == 30
        return client

    return make


def test_newest_first_incremental_and_fallback(configured, tmp_path):
    state = tmp_path / "state.json"
    client = FakeIMAP(fallback=True)
    with fetch_emails("email_primary", state_path=state, client_factory=factory(client)) as messages:
        assert [email.subject for email in messages] == ["Welcome 3", "Welcome 2", "Welcome 1"]
        assert not state.exists()
    assert json.loads(state.read_text())["email_primary"]["uid"] == 3
    assert client.folders == ["[Gmail]/All Mail", "INBOX"]
    client = FakeIMAP(uids=(3, 4), fallback=True)
    with fetch_emails("email_primary", state_path=state, client_factory=factory(client)) as messages:
        assert [email.subject for email in messages] == ["Welcome 4"]
    assert client.queries == [["UID", "4:*"]]
    assert client.fetched == [4]
    assert json.loads(state.read_text())["email_primary"]["uid"] == 4


def test_interrupted_or_failed_consumer_does_not_checkpoint(configured, tmp_path):
    state = tmp_path / "state.json"
    with fetch_emails("email_primary", state_path=state, client_factory=factory(FakeIMAP())) as messages:
        next(messages)
    assert not state.exists()
    with (
        pytest.raises(RuntimeError, match="consumer failure"),
        fetch_emails("email_primary", state_path=state, client_factory=factory(FakeIMAP())) as messages,
    ):
        list(messages)
        raise RuntimeError("consumer failure")
    assert not state.exists()


def test_uidvalidity_reset_and_reversed_uid_range(configured, tmp_path):
    state = tmp_path / "state.json"
    for client in (FakeIMAP(), FakeIMAP(uids=(3,))):
        with fetch_emails("email_primary", state_path=state, client_factory=factory(client)) as messages:
            list(messages)
    assert client.fetched == []
    reset = FakeIMAP(uids=(1,), validity=11)
    with fetch_emails("email_primary", state_path=state, client_factory=factory(reset)) as messages:
        assert len(list(messages)) == 1
    assert json.loads(state.read_text())["email_primary"]["uid"] == 1
    assert reset.queries == [["UID", "1:*"]]


def test_plain_preferred_html_stripped_truncated_and_repr_private():
    raw = parse_email(
        email_bytes(body="<p>Hello</p><script>hidden()</script><p>World</p>", html=True), "email_primary"
    )
    assert raw.body_text == "Hello World"
    assert raw.body_text not in repr(raw)
    message = EmailMessage()
    message.set_content("Plain body")
    message.add_alternative("<p>HTML body</p>", subtype="html")
    assert parse_email(message.as_bytes(), "email_primary").body_text == "Plain body"
    assert len(parse_email(email_bytes(body="a" * 5000), "email_primary").body_text) == 4000


def test_missing_headers_have_stable_id_and_date():
    first = parse_email(b"Subject: Hello\n\nExample", "email_primary")
    second = parse_email(b"Subject: Hello\n\nExample", "email_primary")
    assert first.msg_id == second.msg_id
    assert first.date == datetime(1970, 1, 1, tzinfo=UTC)
