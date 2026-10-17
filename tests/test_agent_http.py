import asyncio
import shutil
import socket
import sys
import threading
import time
from types import ModuleType
from uuid import uuid4

import pytest
import uvicorn

from lapse import trace
from lapse.agent import agent, mcp_server
from lapse.graph import db


@pytest.mark.db
async def test_respond_over_streamable_http_keeps_user_turn_and_query_trace(monkeypatch, tmp_path):
    graph = db.graph(f"lapse:test:wp4:http:{uuid4().hex}")
    monkeypatch.setattr(db, "user_graph", lambda uid: graph)
    for path in db.QUERY_DIR.glob("wp4_*.cypher"):
        shutil.copy(path, tmp_path / path.name)
    (tmp_path / "seed.cypher").write_text(
        "CREATE (:Root {id: 'phone-old', label: 'Old number', kind: 'phone', status: 'retiring'})"
    )
    (tmp_path / "roots.cypher").write_text("MATCH (r:Root) RETURN r AS root")
    (tmp_path / "linked.cypher").write_text(
        "MATCH (c:ToolCall)-[:IN]->(t:Turn) RETURN c.tool AS tool, t.role AS role, t.text AS text"
    )
    monkeypatch.setattr(db, "QUERY_DIR", tmp_path)
    views = ModuleType("lapse.graph.views")

    def list_roots(uid, *, trace=None):
        assert uid == "http-user"
        return [row["root"] for row in db.run(db.user_graph(uid), "roots", trace=trace).rows]

    views.list_roots = list_roots
    monkeypatch.setitem(sys.modules, "lapse.graph.views", views)
    monkeypatch.setattr(agent, "create_llm", lambda: None)
    app = mcp_server.create_server().streamable_http_app()
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="on"))
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    try:
        db.run(graph, "seed", write=True)
        thread.start()
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
        assert server.started
        monkeypatch.setenv("AGENT_TOOL_TRANSPORT", "mcp")
        monkeypatch.setenv("MCP_URL", f"http://127.0.0.1:{port}/mcp")
        reply = await agent.respond("http-user", "show roots")
        assert reply["tool_calls"] == ["list_roots"]
        assert "Old number" in reply["text"]
        assert [
            (record.tool, record.query_name, record.rows) for record in trace.list_trace("http-user")
        ] == [("list_roots", "roots", 1)]
        assert db.run(graph, "linked").rows == [{"tool": "list_roots", "role": "user", "text": "show roots"}]
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
        graph.delete()
    assert not thread.is_alive()
