import json
import sys
from contextlib import contextmanager
from datetime import UTC, date, datetime
from types import ModuleType, SimpleNamespace

import fakeredis
import pytest
import yaml
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError

from lapse import events, jobs
from lapse.api import main
from lapse.contracts import (
    Change,
    ChangeStatus,
    Explanation,
    GraphEvent,
    Plan,
    Root,
    ScenarioResult,
    ToolCallRecord,
)

NOW = datetime(2026, 10, 17, 10, tzinfo=UTC)


@pytest.fixture
def api(monkeypatch, tmp_path):
    redis = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(jobs, "client", lambda: redis)
    config = SimpleNamespace(uid="demo", demo_mode=False, secret_key=Fernet.generate_key().decode())
    monkeypatch.setattr(main, "settings", lambda: config)
    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    monkeypatch.delenv("TELEGRAM_BOT_USERNAME", raising=False)
    calls = []
    traces = []
    trace_callback = lambda *args: None
    active = []
    root = Root(id="phone_old", kind="phone", label="Old number", status="retiring")
    change = Change(
        id="change_1",
        plan_id="plan_1",
        order=1,
        account_id="google",
        account_label="Google",
        role="recovery_phone",
        from_root="phone_old",
        to_root="phone_new",
        tier=2,
        requires_old_root=True,
    )
    plan = Plan(
        id="plan_1",
        kind="takeover",
        old_root="phone_old",
        new_root="phone_new",
        deadline=None,
        feasible=True,
        exposure_before=1,
        exposure_after=0,
        steps=[change],
        created_at=NOW,
    )
    scenario = ScenarioResult(
        id="scenario_1",
        kind="takeover",
        root_ids=["phone_old"],
        actor="stranger",
        rounds=1,
        affected_accounts=[],
        direct_accounts=[],
        unknown_accounts=[],
        total_accounts=1,
        ms=1.5,
    )
    graph = {
        "nodes": [
            {
                "id": "phone_old",
                "label": "Old number",
                "node_type": "Root",
                "root": root.model_dump(mode="json"),
            }
        ],
        "edges": [],
    }
    record = ToolCallRecord(
        id="trace_1",
        at=NOW,
        tool="list_roots",
        args={},
        query_name="list_roots",
        ms=1.5,
        rows=1,
        outcome="ok",
    )

    def module(name, **functions):
        value = ModuleType(name)
        value.__dict__.update(functions)
        monkeypatch.setitem(sys.modules, name, value)
        return value

    def call(name, uid, *args, **kwargs):
        assert active, f"{name} was not traced"
        calls.append((name, uid, args, kwargs))

    def list_roots(uid):
        call("list_roots", uid)
        return [root, Root(id="phone_new", kind="phone", label="New number")]

    def graph_view(uid, scenario_id=None):
        call("graph_view", uid, scenario_id)
        return graph

    def stats(uid):
        call("stats", uid)
        return {"nodes": 1, "edges": 0, "last_query_ms": 1.5, "by_label": {"Root": 1}}

    def run_scenario(uid, req, *, trace=None):
        assert trace is trace_callback
        call("run_scenario", uid, req)
        return scenario

    def get_scenario(uid, id):
        call("get_scenario", uid, id)
        return scenario if id == scenario.id else None

    def explain(uid, id, account_id, *, trace=None):
        assert trace is trace_callback
        call("explain", uid, id, account_id)
        return Explanation(
            scenario_id=id,
            account_id=account_id,
            outcome="not_affected" if account_id == "google" else "not_in_graph",
        )

    def plan_for_root(uid, old_root, new_root=None, deadline=None, *, trace=None):
        assert trace is trace_callback
        call("plan_for_root", uid, old_root, new_root, deadline)
        return plan

    def get_plan(uid, id):
        call("get_plan", uid, id)
        return plan if id == plan.id else None

    def list_plans(uid):
        call("list_plans", uid)
        return [plan]

    def update_change(uid, id, *, status, note=None):
        call("update_change", uid, id, status=status)
        change.status = status
        return change

    def list_trace(uid, since=None):
        call("list_trace", uid, since)
        return [record]

    @contextmanager
    def tool_call(uid, name, args):
        traces.append((uid, name, args))
        active.append(name)
        try:
            yield trace_callback
        finally:
            active.pop()

    def load_persona_local(uid, path="persona.local.yaml"):
        call("load_persona_local", uid, yaml.safe_load(main.Path(path).read_text()))
        return {"roots": 1}

    async def respond(uid, text, *, channel="telegram"):
        call("respond", uid, text, channel=channel)
        return {"text": "I can explain your plan.", "buttons": [], "tool_calls": []}

    modules = {
        "views": module("lapse.graph.views", list_roots=list_roots, graph_view=graph_view, stats=stats),
        "scenarios": module(
            "lapse.graph.scenarios", run_scenario=run_scenario, get_scenario=get_scenario, explain=explain
        ),
        "planner": module(
            "lapse.graph.planner",
            plan_for_root=plan_for_root,
            get_plan=get_plan,
            list_plans=list_plans,
            update_change=update_change,
        ),
        "trace": module("lapse.trace", tool_call=tool_call, list_trace=list_trace),
        "onboarding": module("lapse.onboarding", load_persona_local=load_persona_local),
        "agent": module("lapse.agent.agent", respond=respond),
    }
    with TestClient(main.app) as client:
        yield SimpleNamespace(
            client=client,
            redis=redis,
            config=config,
            calls=calls,
            traces=traces,
            change=change,
            plan=plan,
            scenario=scenario,
            graph=graph,
            modules=modules,
            directory=tmp_path,
        )
    redis.close()


def test_reads_match_web_shapes_and_tenant(api):
    c = api.client
    assert c.get("/api/roots").json()[0]["id"] == "phone_old"
    graph = c.get("/api/graph?scenario=scenario_1").json()
    assert graph["nodes"][0]["node_type"] == "Root"
    assert "account" not in graph["nodes"][0]
    assert graph["edges"] == []
    assert c.get("/api/scenarios/scenario_1").json() == api.scenario.model_dump(mode="json")
    assert c.get("/api/scenarios/scenario_1/explain/google").json() == {
        "scenario_id": "scenario_1",
        "account_id": "google",
        "outcome": "not_affected",
        "steps": [],
    }
    assert c.get("/api/plans/plan_1").json() == api.plan.model_dump(mode="json")
    assert c.get("/api/plans").json() == [api.plan.model_dump(mode="json")]
    assert c.get("/api/stats").json() == {"nodes": 1, "edges": 0, "last_query_ms": 1.5}
    assert c.get("/api/trace?since=2026-10-17T10:00:00Z").json()[0]["id"] == "trace_1"
    assert api.calls[-1][2] == (NOW,)
    c.get("/api/roots", headers={"X-Lapse-Uid": "second"})
    assert api.calls[-1][1] == "second"
    assert api.traces[-1][:2] == ("second", "list_roots")


def test_scenario_and_plan_creation_forward_typed_inputs(api):
    response = api.client.post("/api/scenarios", json={"kind": "takeover", "root_ids": ["phone_old"]})
    assert response.status_code == 200
    assert response.json() == api.scenario.model_dump(mode="json")
    assert api.calls[-1][2][0].root_ids == ["phone_old"]
    response = api.client.post(
        "/api/plans", json={"old_root": "phone_old", "new_root": "phone_new", "deadline": "2026-10-31"}
    )
    assert response.status_code == 200
    assert response.json() == api.plan.model_dump(mode="json")
    assert api.calls[-1][2] == ("phone_old", "phone_new", date(2026, 10, 31))


def test_approval_enqueues_and_otp_returns_change_without_echoing_code(api):
    response = api.client.post("/api/changes/change_1/approve", json={})
    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    message = api.redis.xrange("lapse:jobs")[0][1]
    assert message["uid"] == "demo"
    assert message["kind"] == "execute_change"
    assert json.loads(message["payload"]) == {"change_id": "change_1"}
    response = api.client.post("/api/changes/change_1/otp", json={"code": "073992"})
    assert response.status_code == 200
    assert response.json() == api.change.model_dump(mode="json")
    assert api.redis.get("lapse:otp:demo:change_1") == "073992"
    assert 299 <= api.redis.ttl("lapse:otp:demo:change_1") <= 300
    assert "073992" not in response.text + repr(api.traces)


def test_ingest_and_chat(api):
    assert api.client.post("/api/ingest/run", json={}).json() == {"started": True}
    fields = api.redis.xrange("lapse:jobs")[0][1]
    assert fields["kind"] == "ingest_run"
    assert json.loads(fields["payload"]) == {}
    response = api.client.post("/api/chat", json={"text": "Explain this plan"})
    assert response.json() == {"text": "I can explain your plan.", "buttons": [], "tool_calls": []}
    assert api.calls[-1] == ("respond", "demo", ("Explain this plan",), {"channel": "web"})


def test_screen_absolute_url_file_and_path_escape(api):
    assert api.client.get("/api/agent/screen").json() == {
        "url": None,
        "caption": "No screenshot yet.",
        "mock": False,
    }
    directory = api.directory / "screens"
    directory.mkdir()
    image = b"\x89PNG\r\n\x1a\n"
    (directory / "step.png").write_bytes(image)
    api.redis.set("lapse:screen:second", "data/screens/step.png")
    response = api.client.get("/api/agent/screen", headers={"X-Lapse-Uid": "second"})
    assert response.json() == {
        "url": "http://testserver/api/screens/step.png",
        "caption": "Latest executor screenshot",
        "mock": False,
    }
    response = api.client.get(response.json()["url"])
    assert response.content == image
    assert response.headers["content-type"] == "image/png"
    outside = api.directory / "private.png"
    outside.write_bytes(b"private")
    (directory / "escape.png").symlink_to(outside)
    assert api.client.get("/api/screens/escape.png").status_code == 404
    assert api.client.get("/api/screens/missing.png").status_code == 404
    (directory / "secret.txt").write_text("secret")
    assert api.client.get("/api/screens/secret.txt").status_code == 404


def test_onboarding_encrypts_tenant_inboxes_and_translates_persona(api, monkeypatch):
    payload = {
        "inboxes": [
            {"host": "imap.example.com", "username": "mail@example.com", "app_password": "app-secret-value"}
        ],
        "phones": [
            {"number": "+910000004321", "carrier": "Vi", "status": "retiring", "drop_at": "2026-10-31"}
        ],
        "display_name": "Demo user",
        "emails": [{"id": "email_primary", "address": "mail@example.com"}],
    }
    response = api.client.post("/api/onboarding", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["telegram_url"] == f"https://t.me/LapseAlfredBot?start={data['telegram_code']}"
    assert api.redis.get(f"lapse:tglink:{data['telegram_code']}") == "demo"
    assert "app-secret-value" not in response.text + repr(api.traces) + repr(api.calls)
    persona = api.calls[-1][2][0]
    assert persona["phones"][0]["e164"] == "+910000004321"
    assert persona["phones"][0]["drop_at"] == "2026-10-31"
    assert persona["emails"][0]["id"] == "email_primary"
    assert "inboxes" not in persona
    encrypted = (api.directory / "inboxes.enc").read_bytes()
    assert b"app-secret-value" not in encrypted
    assert (api.directory / "inboxes.enc").stat().st_mode & 0o777 == 0o600
    cipher = Fernet(api.config.secret_key.encode())
    records = json.loads(cipher.decrypt(encrypted))
    assert records == {"demo": payload["inboxes"]}
    assert not list(api.directory.glob("*.yaml"))
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "@OtherBot")
    response = api.client.post("/api/onboarding", json=payload, headers={"X-Lapse-Uid": "second"})
    assert response.json()["telegram_url"].startswith("https://t.me/OtherBot?start=")
    records = json.loads(cipher.decrypt((api.directory / "inboxes.enc").read_bytes()))
    assert set(records) == {"demo", "second"}


def test_onboarding_without_credentials_does_not_require_encryption_key(api):
    api.config.secret_key = ""
    assert api.client.post("/api/onboarding", json={"phones": [], "inboxes": []}).status_code == 200
    assert not (api.directory / "inboxes.enc").exists()


def test_onboarding_refuses_missing_key_before_side_effects(api):
    api.config.secret_key = ""
    response = api.client.post(
        "/api/onboarding",
        json={
            "phones": [],
            "inboxes": [{"host": "imap.example.com", "username": "u", "app_password": "secret"}],
        },
    )
    assert response.status_code == 503
    assert not api.calls
    assert not list(api.directory.iterdir())


@pytest.mark.parametrize(
    "path,payload",
    [
        ("/api/changes/change_1/approve", {}),
        ("/api/changes/change_1/otp", {"code": "123456"}),
        ("/api/onboarding", {"inboxes": [], "phones": []}),
        ("/api/ingest/run", {}),
        ("/api/chat", {"text": "hello"}),
    ],
)
def test_demo_mode_blocks_writes_without_effects(api, path, payload):
    api.config.demo_mode = True
    response = api.client.post(path, json=payload)
    assert response.status_code == 403
    assert "read-only" in response.json()["detail"]
    assert not api.calls
    assert not api.redis.keys("*")
    assert not list(api.directory.iterdir())


def test_demo_still_allows_graph_analysis(api):
    api.config.demo_mode = True
    assert api.client.get("/api/roots").status_code == 200
    assert (
        api.client.post("/api/scenarios", json={"kind": "takeover", "root_ids": ["phone_old"]}).status_code
        == 200
    )
    assert api.client.post("/api/plans", json={"old_root": "phone_old"}).status_code == 200


@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("GET", "/api/scenarios/unknown", None),
        ("GET", "/api/plans/unknown", None),
        ("GET", "/api/graph?scenario=unknown", None),
        ("GET", "/api/scenarios/unknown/explain/google", None),
        ("GET", "/api/scenarios/scenario_1/explain/unknown", None),
        ("POST", "/api/changes/unknown/approve", {}),
        ("POST", "/api/changes/unknown/otp", {"code": "123456"}),
    ],
)
def test_unknown_ids_are_404(api, method, path, payload):
    response = api.client.request(method, path, json=payload)
    assert response.status_code == 404
    assert "detail" in response.json()
    assert not api.redis.keys("*")


@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("POST", "/api/scenarios", {"kind": "takeover", "root_ids": []}),
        ("POST", "/api/scenarios", {"kind": "wrong", "root_ids": ["phone_old"]}),
        ("POST", "/api/plans", {"old_root": "phone_old", "deadline": "wrong"}),
        ("POST", "/api/changes/change_1/otp", {"code": {"secret": "hidden-code"}}),
        ("POST", "/api/onboarding", {"inboxes": [{"app_password": "hidden-code"}]}),
        ("POST", "/api/chat", {"text": ""}),
        ("GET", "/api/trace?since=wrong", None),
    ],
)
def test_validation_422_never_echoes_input(api, method, path, payload):
    response = api.client.request(method, path, json=payload)
    assert response.status_code == 422
    assert "hidden-code" not in response.text
    assert "input" not in response.text
    assert not api.calls


def test_missing_modules_return_503_and_missing_trace_is_noop(api, monkeypatch):
    monkeypatch.setitem(sys.modules, "lapse.graph.views", None)
    assert api.client.get("/api/roots").status_code == 503
    monkeypatch.setitem(sys.modules, "lapse.graph.views", api.modules["views"])
    monkeypatch.setitem(sys.modules, "lapse.agent.agent", None)
    assert api.client.post("/api/chat", json={"text": "hello"}).status_code == 503
    monkeypatch.setitem(sys.modules, "lapse.trace", None)
    monkeypatch.setattr(api.modules["views"], "list_roots", lambda uid: [])
    assert api.client.get("/api/roots").json() == []
    assert api.client.get("/api/trace").status_code == 503


def test_backend_errors_are_honest_and_do_not_echo_values(api, monkeypatch):
    def unknown(uid):
        raise KeyError("private identifier")

    monkeypatch.setattr(api.modules["views"], "list_roots", unknown)
    response = api.client.get("/api/roots")
    assert response.status_code == 404
    assert "private identifier" not in response.text

    def invalid(uid):
        raise ValueError("private input")

    monkeypatch.setattr(api.modules["views"], "list_roots", invalid)
    response = api.client.get("/api/roots")
    assert response.status_code == 422
    assert "private input" not in response.text
    monkeypatch.setattr(api.redis, "get", lambda key: (_ for _ in ()).throw(ConnectionError("secret")))
    response = api.client.get("/api/agent/screen")
    assert response.status_code == 503
    assert "secret" not in response.text


def test_sse_frames_full_graph_event_envelope(api, monkeypatch):
    event = GraphEvent(
        type="graph", uid="second", at=NOW, data={"nodes": 1, "edges": 0, "last_query_ms": 1.5}
    )
    closed = []

    async def subscribe(uid):
        assert uid == "second"
        try:
            yield event
        finally:
            closed.append(True)

    monkeypatch.setattr(events, "subscribe", subscribe)
    response = api.client.get("/api/events", headers={"X-Lapse-Uid": "second"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text.replace("\r\n", "\n") == f"event: graph\ndata: {event.model_dump_json()}\n\n"
    assert closed == [True]


def test_cors(api):
    response = api.client.options(
        "/api/changes/change_1/approve",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type,X-Lapse-Uid",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    response = api.client.options(
        "/api/roots", headers={"Origin": "https://other.example", "Access-Control-Request-Method": "GET"}
    )
    assert response.status_code == 400


def test_approval_retries_queue_after_redis_failure(api, monkeypatch):
    xadd = api.redis.xadd

    def unavailable(*args, **kwargs):
        raise ConnectionError("queue unavailable")

    monkeypatch.setattr(api.redis, "xadd", unavailable)
    assert api.client.post("/api/changes/change_1/approve", json={}).status_code == 503
    assert api.change.status == "approved"
    monkeypatch.setattr(api.redis, "xadd", xadd)
    response = api.client.post("/api/changes/change_1/approve", json={})
    assert response.status_code == 200
    assert api.redis.xlen("lapse:jobs") == 1
    assert json.loads(api.redis.xrange("lapse:jobs")[0][1]["payload"]) == {"change_id": "change_1"}


def test_approval_does_not_reexecute_running_or_completed_change(api):
    for status in ("running", "awaiting_otp", "awaiting_user", "done", "skipped"):
        api.change.status = ChangeStatus(status)
        response = api.client.post("/api/changes/change_1/approve", json={})
        assert response.json()["status"] == status
    assert api.redis.xlen("lapse:jobs") == 0


@pytest.mark.parametrize(
    "path,body",
    [
        ("/api/scenarios", {"kind": "takeover", "root_ids": ["unknown"]}),
        ("/api/plans", {"old_root": "unknown"}),
        ("/api/plans", {"old_root": "phone_old", "new_root": "unknown"}),
    ],
)
def test_unknown_roots_are_404_before_computing(api, path, body):
    response = api.client.post(path, json=body)
    assert response.status_code == 404
    assert "root" in response.json()["detail"]
    assert [call[0] for call in api.calls] == ["list_roots"]
