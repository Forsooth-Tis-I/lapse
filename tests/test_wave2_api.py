from contextlib import contextmanager
from types import SimpleNamespace

from fastapi.testclient import TestClient

from lapse import trace
from lapse.api import main


def test_chat_awaits_real_agent_interface(monkeypatch):
    active = []

    @contextmanager
    def traced(*args):
        active.append(True)
        try:
            yield None
        finally:
            active.pop()

    async def respond(uid, text, *, channel):
        assert active
        return {"text": f"{uid}: {text}", "buttons": [], "tool_calls": []}

    monkeypatch.setattr(main, "load", lambda module: SimpleNamespace(respond=respond))
    monkeypatch.setattr(trace, "tool_call", traced)
    main.app.dependency_overrides[main.writable] = lambda: None
    main.app.dependency_overrides[main.current_uid] = lambda: "demo"
    try:
        with TestClient(main.app) as client:
            response = client.post("/api/chat", json={"text": "hello"})
        assert response.status_code == 200
        assert response.json()["text"] == "demo: hello"
    finally:
        main.app.dependency_overrides.clear()
