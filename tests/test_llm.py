import json
from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError, OpenAI

from lapse import llm


@pytest.fixture
def configuration(monkeypatch):
    config = SimpleNamespace(
        llm_base_url="https://opencode.ai/zen/go/v1", llm_api_key="test", llm_model="primary"
    )
    monkeypatch.setattr(llm, "settings", lambda: config)
    monkeypatch.setenv("LLM_FALLBACK_MODELS", " fallback-one, fallback-two,primary ")
    return config


def test_session_header_is_stable_and_only_sent_to_opencode(monkeypatch, configuration):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]})

    def build(**kwargs):
        return OpenAI(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(respond)))

    monkeypatch.setattr(llm, "OpenAI", build)
    for _ in range(2):
        with llm.client() as connection:
            llm.complete(connection, messages=[{"role": "user", "content": "test"}])
    configuration.llm_base_url = "https://example.org/v1"
    with llm.client() as connection:
        assert connection.timeout == 30
        assert connection.max_retries == 1
        llm.complete(connection, messages=[{"role": "user", "content": "test"}])
    session = requests[0].headers["x-opencode-session"]
    assert session.startswith("lapse-")
    assert requests[1].headers["x-opencode-session"] == session
    assert "x-opencode-session" not in requests[2].headers


def test_models_fail_over_in_order_without_duplicate_primary(monkeypatch, configuration):
    attempts = []

    def respond(request):
        model = json.loads(request.content)["model"]
        attempts.append(model)
        if model != "fallback-two":
            return httpx.Response(400, json={"error": {"message": "provider rejection"}})
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]})

    diagnostics = {}
    with OpenAI(
        api_key="test", http_client=httpx.Client(transport=httpx.MockTransport(respond))
    ) as connection:
        response = llm.complete(connection, messages=[], diagnostics=diagnostics)
    assert response.choices[0].message.content == "ok"
    assert attempts == ["primary", "fallback-one", "fallback-two"]
    assert diagnostics == {"llm_attempts": 3, "model_fallback_used": True}


async def test_async_failover_and_exhaustion(configuration):
    attempts = []

    async def create(**kwargs):
        attempts.append(kwargs["model"])
        raise APIConnectionError(request=httpx.Request("POST", "https://example.org"))

    connection = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with pytest.raises(APIConnectionError):
        await llm.acomplete(connection, messages=[])
    assert attempts == ["primary", "fallback-one", "fallback-two"]


def test_doctor_uses_chat_completion(monkeypatch):
    from scripts import doctor

    class Connection:
        def __init__(self, **kwargs):
            assert kwargs == {"base_url": "configured", "api_key": "configured"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    calls = []
    monkeypatch.setattr(llm, "client", Connection)

    def complete(connection, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[object()])

    monkeypatch.setattr(llm, "complete", complete)
    assert doctor.check_llm(dict.fromkeys(["LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"], "configured")).ok
    assert calls == [
        {
            "messages": [{"role": "user", "content": "Reply OK."}],
            "max_tokens": 1,
            "model": "configured",
            "fallback_models": "",
        }
    ]


def test_mcp_respects_container_bind(monkeypatch):
    from lapse.agent.mcp_server import create_server

    monkeypatch.setenv("FASTMCP_HOST", "0.0.0.0")
    monkeypatch.setenv("FASTMCP_PORT", "8766")
    server = create_server()
    assert server.settings.host == "0.0.0.0"
    assert server.settings.port == 8766


def test_mixed_depth_enum_has_explicit_json_types():
    from lapse.agent.tools import REGISTRY

    depth = REGISTRY["dependents"].schema["properties"]["depth"]
    assert {option["type"] for option in depth["anyOf"]} == {"integer", "string"}


def test_doctor_probes_selected_configuration(monkeypatch, configuration):
    from scripts import doctor

    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]})

    monkeypatch.setattr(
        llm,
        "OpenAI",
        lambda **kwargs: OpenAI(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(respond))),
    )
    assert doctor.check_llm(
        {
            "LLM_BASE_URL": "https://selected.invalid/v1",
            "LLM_API_KEY": "selected-key",
            "LLM_MODEL": "selected-model",
        }
    ).ok
    assert requests[0].url.host == "selected.invalid"
    assert requests[0].headers["authorization"] == "Bearer selected-key"
    assert json.loads(requests[0].content)["model"] == "selected-model"
    assert "x-opencode-session" not in requests[0].headers
