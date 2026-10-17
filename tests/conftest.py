import socket
from datetime import UTC, datetime

import pytest

from lapse.ingest.imap import RawEmail


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Tests must not access the network")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


@pytest.fixture
def raw():
    def make(
        body="",
        subject="Security alert",
        sender="Notice <notice@accounts.google.com>",
        to="Demo <demo@example.com>",
        msg_id="<test@example.com>",
        inbox="email_primary",
    ):
        return RawEmail(msg_id, inbox, datetime(2026, 10, 17, tzinfo=UTC), sender, to, subject, body)

    return make
