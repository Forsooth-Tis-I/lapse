import asyncio
import json
import shutil
import sys
from datetime import UTC, datetime, timedelta
from types import ModuleType
from uuid import uuid4

import pytest
from redis.exceptions import ResponseError

from lapse import trace
from lapse.graph import db


@pytest.fixture
def trace_graph(tmp_path, monkeypatch):
    graph = db.graph(f"lapse:test:wp4:trace:{uuid4().hex}")
    monkeypatch.setattr(db, "user_graph", lambda uid: graph)
    for path in db.QUERY_DIR.glob("wp4_trace_*.cypher"):
        shutil.copy(path, tmp_path / path.name)
    queries = {
        "seed": "CREATE (:Turn {id: $id, role: 'user', text: 'risk', at: '2026-10-17'})",
        "read": "MATCH (t:Turn) RETURN t.id AS id",
        "inspect": (
            "MATCH (c:ToolCall) OPTIONAL MATCH (c)-[:IN]->(t:Turn) "
            "RETURN c AS call, t.id AS turn_id ORDER BY c.at"
        ),
    }
    for name, query in queries.items():
        (tmp_path / f"{name}.cypher").write_text(query)
    monkeypatch.setattr(db, "QUERY_DIR", tmp_path)
    try:
        yield graph
    finally:
        try:
            graph.delete()
        except ResponseError as exc:
            if "Invalid graph operation on empty key" not in str(exc):
                raise


@pytest.fixture
def published(monkeypatch):
    published = []
    events = ModuleType("lapse.events")
    events.publish = lambda uid, kind, data: published.append((uid, kind, data))
    monkeypatch.setitem(sys.modules, "lapse.events", events)
    return published


@pytest.mark.db
def test_each_query_has_trace_and_one_invocation_node(trace_graph, published):
    db.run(trace_graph, "seed", {"id": "turn-1"}, write=True)
    token = trace.current_turn.set("turn-1")
    try:
        with trace.tool_call("demo", "dependents", {"root_id": "phone-old"}) as call:
            db.run(trace_graph, "read", trace=call)
            db.run(trace_graph, "read", trace=call)
            call.outcome = "path"
    finally:
        trace.current_turn.reset(token)

    records = trace.list_trace("demo")
    assert [record.query_name for record in records] == ["read", "read"]
    assert [record.rows for record in records] == [1, 1]
    assert [record.id for record in records] == [f"{call.id}:0", f"{call.id}:1"]
    assert all(record.outcome == "path" and record.ms >= 0 for record in records)
    assert records == call.records
    rows = db.run(trace_graph, "inspect").rows
    assert len(rows) == 1
    assert rows[0]["turn_id"] == "turn-1"
    assert rows[0]["call"]["rows"] == 2
    assert published == [("demo", "trace", record.model_dump(mode="json")) for record in records]


@pytest.mark.db
def test_zero_query_call_is_persisted_and_since_filters(trace_graph, published):
    before = datetime.now(UTC) - timedelta(seconds=1)
    with trace.tool_call("demo", "resolve", {"hint": "missing"}) as call:
        call.outcome = "unknown_root"
    (record,) = trace.list_trace("demo", since=before.isoformat())
    assert record.query_name is None
    assert record.rows == 0
    assert record.outcome == "unknown_root"
    assert record.ms >= 0
    assert trace.list_trace("demo", since=record.at) == []
    assert trace.list_trace("demo", since=before.replace(tzinfo=None)) == [record]
    assert db.run(trace_graph, "inspect").rows[0]["turn_id"] is None


@pytest.mark.db
def test_failed_query_keeps_error_trace_without_error_message(trace_graph, published):
    db.run(trace_graph, "seed", {"id": "turn-1"}, write=True)
    with pytest.raises(ResponseError), trace.tool_call("demo", "broken", {}) as call:
        db.run(trace_graph, "seed", {"id": "hidden-parameter"}, trace=call)
    (record,) = trace.list_trace("demo")
    assert record.outcome == "error"
    assert record.query_name == "seed"
    assert record.rows == 0
    assert "hidden-parameter" not in json.dumps(db.run(trace_graph, "inspect").rows)


@pytest.mark.db
def test_redacts_nested_secrets_and_does_not_mutate_arguments(trace_graph, published):
    arguments = {
        "approval_token": "token-private",
        "nested": [{"OTP": "123456", "password": "pw-private", "code": "code-private"}],
        "change_id": "change-1",
    }
    with (
        pytest.raises(ValueError, match="message-private"),
        trace.tool_call("demo", "execute_change", arguments),
    ):
        raise ValueError("message-private")
    (record,) = trace.list_trace("demo")
    assert record.args == {
        "approval_token": "[redacted]",
        "nested": [{"OTP": "[redacted]", "password": "[redacted]", "code": "[redacted]"}],
        "change_id": "change-1",
    }
    assert arguments["approval_token"] == "token-private"
    saved = json.dumps(db.run(trace_graph, "inspect").rows) + json.dumps(published)
    for secret in ("token-private", "123456", "pw-private", "code-private", "message-private"):
        assert secret not in saved


@pytest.mark.db
def test_missing_event_module_is_allowed(trace_graph, monkeypatch):
    monkeypatch.setitem(sys.modules, "lapse.events", None)
    with trace.tool_call("demo", "resolve", {}):
        pass
    assert len(trace.list_trace("demo")) == 1


async def test_current_turn_is_local_to_async_conversation():
    async def conversation(turn):
        token = trace.current_turn.set(turn)
        try:
            await asyncio.sleep(0)
            return trace.current_turn.get()
        finally:
            trace.current_turn.reset(token)

    assert await asyncio.gather(conversation("one"), conversation("two")) == ["one", "two"]
    assert trace.current_turn.get() is None
