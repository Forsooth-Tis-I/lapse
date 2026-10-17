import socket
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from redis.exceptions import ResponseError

from lapse.graph.db import graph
from lapse.ingest.imap import RawEmail


@pytest.fixture(autouse=True)
def no_network(request, monkeypatch):
    """Unit tests must stay offline. Tests marked `db` may reach the local FalkorDB."""
    if request.node.get_closest_marker("db"):
        return

    def blocked(*args, **kwargs):
        raise AssertionError("Tests must not access the network")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


@pytest.fixture
def isolated_graph():
    g = graph(f"lapse:test:{uuid4().hex}")
    try:
        yield g
    finally:
        try:
            g.delete()
        except ResponseError as exc:
            if "Invalid graph operation on empty key" not in str(exc):
                raise


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
