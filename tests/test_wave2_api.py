from fastapi.testclient import TestClient

from lapse.agent import agent
from lapse.api import main


def test_chat_awaits_real_agent_interface(monkeypatch):
    async def respond(uid, text, *, channel):
        return {'text': f'{uid}: {text}', 'buttons': [], 'tool_calls': []}

    monkeypatch.setattr(agent, 'respond', respond)
    monkeypatch.setattr(main, 'graph_call', lambda uid, module, name, *args, **kwargs: respond(uid, *args, **kwargs))
    main.app.dependency_overrides[main.writable] = lambda: None
    main.app.dependency_overrides[main.current_uid] = lambda: 'demo'
    try:
        with TestClient(main.app) as client:
            response = client.post('/api/chat', json={'text': 'hello'})
        assert response.status_code == 200
        assert response.json()['text'] == 'demo: hello'
    finally:
        main.app.dependency_overrides.clear()
