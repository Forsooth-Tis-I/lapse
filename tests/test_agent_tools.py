import json
import sys
from contextlib import contextmanager
from datetime import UTC, date, datetime
from types import ModuleType, SimpleNamespace

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from lapse import trace
from lapse.agent import mcp_server, tools
from lapse.contracts import Root
from lapse.graph import db


@pytest.fixture
def fake_tools(monkeypatch):
    state = SimpleNamespace(
        roots=[
            Root(
                id="phone-old",
                kind="phone",
                label="••4321 (Vi)",
                last4="4321",
                carrier="Vi",
                status="retiring",
            ),
            Root(id="phone-new", kind="phone", label="••7788 (Jio)", last4="7788", carrier="Jio"),
            Root(
                id="email-college",
                kind="email",
                label="student@college.example",
                email_kind="edu",
                status="closing",
            ),
        ],
        accounts=[
            {
                "account": {"id": "dropbox-personal", "display": "Personal Dropbox", "service_id": "dropbox"},
                "service": {"name": "Dropbox", "modelled": True},
            },
            {
                "account": {"id": "dropbox-work", "display": "Work Dropbox", "service_id": "dropbox"},
                "service": {"name": "Dropbox", "modelled": True},
            },
        ],
        calls=[],
        queries=[],
        traces=[],
        authorized=["change-1"],
        consume_error=None,
        explanation_outcome="path",
    )
    entities = {
        "Root": {root.id: {"entity": root.model_dump()} for root in state.roots},
        "Account": {
            row["account"]["id"]: {"entity": row["account"], "service": row["service"]}
            for row in state.accounts
        },
        "Scenario": {"scenario-1": {"entity": {"id": "scenario-1"}}},
        "Plan": {"plan-1": {"entity": {"id": "plan-1"}}},
        "Change": {"change-1": {"entity": {"id": "change-1", "status": "proposed"}}},
    }
    state.entities = entities

    @contextmanager
    def traced(uid, name, args):
        call = trace.ToolTrace("test-call", datetime.now(UTC), name, trace.redact(args))
        state.traces.append((uid, trace.current_turn.get(), call))
        yield call

    def query(graph, name, params=None, *, trace=None, **kwargs):
        state.queries.append((graph, name, params))
        if name == "wp4_entity":
            found = entities[params["kind"]].get(params["id"])
            rows = [found] if found else []
        elif name == "wp4_accounts":
            rows = state.accounts
        else:
            raise AssertionError(f"Unexpected query: {name}")
        if trace:
            trace(name, params or {}, 1.25, len(rows))
        return db.QueryOutcome(rows, len(rows), 1.25, name)

    def list_roots(uid):
        state.calls.append(("list_roots", uid))
        return state.roots

    def account_detail(uid, account_id):
        state.calls.append(("account_detail", uid, account_id))
        return {"account": entities["Account"][account_id]["entity"], "methods": []}

    def search_evidence(uid, text):
        state.calls.append(("search_evidence", uid, text))
        return [{"id": "evidence-1", "subject": "Contact changed"}]

    def run_scenario(uid, request, *, trace=None):
        state.calls.append(("run_scenario", uid, request))
        trace("scenario_context", {}, 3.0, 1)
        return {"id": "scenario-1", "kind": request.kind.value, "root_ids": request.root_ids}

    def direct_dependents(uid, root_id, *, trace=None):
        state.calls.append(("direct_dependents", uid, root_id))
        return ["dropbox-personal"]

    def explain(uid, scenario_id, account_id, *, trace=None):
        state.calls.append(("explain", uid, scenario_id, account_id))
        return {"scenario_id": scenario_id, "account_id": account_id, "outcome": state.explanation_outcome}

    def plan_for_root(uid, old_root, new_root=None, deadline=None, *, trace=None):
        state.calls.append(("plan_for_root", uid, old_root, new_root, deadline))
        return {"id": "plan-1", "old_root": old_root, "steps": []}

    def get_plan(uid, plan_id):
        state.calls.append(("get_plan", uid, plan_id))
        return {"id": plan_id, "steps": []}

    def consume(uid, token):
        state.calls.append(("consume", uid, token))
        if state.consume_error:
            raise ValueError(state.consume_error)
        return state.authorized

    def enqueue(uid, kind, payload):
        state.calls.append(("enqueue", uid, kind, payload))
        return "job-1"

    def update_change(uid, change_id, *, status, trace=None):
        state.calls.append(("update_change", uid, change_id, status.value))
        entities["Change"][change_id]["entity"]["status"] = status.value

    modules = {
        "lapse.graph.views": {
            "list_roots": list_roots,
            "account_detail": account_detail,
            "search_evidence": search_evidence,
        },
        "lapse.graph.scenarios": {
            "run_scenario": run_scenario,
            "direct_dependents": direct_dependents,
            "explain": explain,
        },
        "lapse.graph.planner": {
            "plan_for_root": plan_for_root,
            "get_plan": get_plan,
            "update_change": update_change,
        },
        "lapse.approvals": {"consume": consume},
        "lapse.jobs": {"enqueue": enqueue},
    }
    for name, attributes in modules.items():
        module = ModuleType(name)
        module.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(trace, "tool_call", traced)
    monkeypatch.setattr(db, "user_graph", lambda uid: f"fake:{uid}")
    monkeypatch.setattr(db, "run", query)
    return state


@pytest.mark.parametrize(
    "hint, expected",
    [
        ("my old number", "phone-old"),
        ("college email", "email-college"),
        ("••4321", "phone-old"),
        ("the Jio one", "phone-new"),
        ("Personal Dropbox", "dropbox-personal"),
    ],
)
def test_resolve_phrases(fake_tools, hint, expected):
    result = tools.dispatch("alice", "resolve", {"hint": hint})
    assert [candidate["id"] for candidate in result["candidates"]] == [expected]
    assert result["ambiguous"] is False
    assert fake_tools.traces[-1][2].outcome == "memory"


def test_resolve_ambiguous_service_and_missing_name(fake_tools):
    result = tools.dispatch("alice", "resolve", {"hint": "Dropbox"})
    assert result == {
        "candidates": [
            {"id": "dropbox-personal", "label": "Personal Dropbox", "kind": "account"},
            {"id": "dropbox-work", "label": "Work Dropbox", "kind": "account"},
        ],
        "ambiguous": True,
    }
    result = tools.dispatch("alice", "resolve", {"hint": "Imaginary service"})
    assert result["candidates"] == []
    assert result["outcome"] == "not_in_graph"
    assert "unknown, not safe" in result["message"]
    assert fake_tools.traces[-1][2].outcome == "not_in_graph"


@pytest.mark.parametrize(
    "name, args, outcome",
    [
        ("dependents", {"root_id": "absent"}, "unknown_root"),
        ("takeover_if_reassigned", {"root_id": "absent"}, "unknown_root"),
        ("lockout_if_lost", {"root_id": "absent"}, "unknown_root"),
        ("account_info", {"account_id": "absent"}, "not_in_graph"),
        ("explain", {"account_id": "dropbox-personal", "scenario_id": "absent"}, "not_in_graph"),
        ("plan_retirement", {"old_root_id": "phone-old", "new_root_id": "absent"}, "unknown_root"),
        ("plan_status", {"plan_id": "absent"}, "not_in_graph"),
        ("execute_change", {"change_id": "absent", "approval_token": "private-token"}, "not_in_graph"),
    ],
)
def test_unknown_ids_do_not_call_handlers_or_enqueue(fake_tools, name, args, outcome):
    result = tools.dispatch("alice", name, args)
    assert result["outcome"] == outcome
    assert "unknown, not safe" in result["message"]
    assert fake_tools.calls == []
    assert fake_tools.traces[-1][2].outcome == outcome
    assert all(graph == "fake:alice" for graph, _, _ in fake_tools.queries)


@pytest.mark.parametrize("unmodelled", ["entity", "service"])
def test_unmodelled_accounts_are_unknown(fake_tools, unmodelled):
    fake_tools.entities["Account"]["dropbox-personal"][unmodelled]["modelled"] = False
    result = tools.dispatch("alice", "account_info", {"account_id": "dropbox-personal"})
    assert result["outcome"] == "not_in_graph"
    assert "unknown, not safe" in result["message"]
    assert fake_tools.calls == []


@pytest.mark.parametrize(
    "name, args, expected, outcome",
    [
        ("dependents", {"root_id": "phone-old", "depth": 1}, ["dropbox-personal"], "path"),
        (
            "takeover_if_reassigned",
            {"root_id": "phone-old"},
            {"id": "scenario-1", "kind": "takeover", "root_ids": ["phone-old"]},
            "path",
        ),
        (
            "lockout_if_lost",
            {"root_id": "phone-old"},
            {"id": "scenario-1", "kind": "lockout", "root_ids": ["phone-old"]},
            "path",
        ),
        (
            "dependents",
            {"root_id": "phone-old", "depth": "full"},
            {"id": "scenario-1", "kind": "takeover", "root_ids": ["phone-old"]},
            "path",
        ),
        (
            "search_evidence",
            {"text": "contact"},
            [{"id": "evidence-1", "subject": "Contact changed"}],
            "memory",
        ),
        ("plan_status", {"plan_id": "plan-1"}, {"id": "plan-1", "steps": []}, "memory"),
    ],
)
def test_successful_tools_return_raw_results_and_classify_trace(fake_tools, name, args, expected, outcome):
    assert tools.dispatch("alice", name, args) == expected
    assert fake_tools.traces[-1][2].outcome == outcome


def test_planner_arguments_and_explanation_order(fake_tools):
    result = tools.dispatch(
        "alice",
        "plan_retirement",
        {
            "old_root_id": "phone-old",
            "new_root_id": "phone-new",
            "deadline": "2026-12-01",
        },
    )
    assert result == {"id": "plan-1", "old_root": "phone-old", "steps": []}
    assert fake_tools.calls[-1] == ("plan_for_root", "alice", "phone-old", "phone-new", date(2026, 12, 1))
    assert fake_tools.traces[-1][2].outcome == "path"
    fake_tools.explanation_outcome = "not_affected"
    result = tools.dispatch(
        "alice", "explain", {"account_id": "dropbox-personal", "scenario_id": "scenario-1"}
    )
    assert result["outcome"] == "not_affected"
    assert fake_tools.calls[-1] == ("explain", "alice", "scenario-1", "dropbox-personal")
    assert fake_tools.traces[-1][2].outcome == "memory"


@pytest.mark.parametrize("status", ["proposed", "failed", "approved"])
def test_approved_change_consumes_token_then_enqueues(fake_tools, status):
    fake_tools.entities["Change"]["change-1"]["entity"]["status"] = status
    result = tools.dispatch(
        "alice", "execute_change", {"change_id": "change-1", "approval_token": "approved"}
    )
    assert result == {"job_id": "job-1", "change_id": "change-1"}
    assert fake_tools.calls == [
        ("consume", "alice", "approved"),
        ("update_change", "alice", "change-1", "approved"),
        ("enqueue", "alice", "execute_change", {"change_id": "change-1"}),
    ]
    assert fake_tools.traces[-1][2].outcome == "ok"
    assert fake_tools.traces[-1][2].args["approval_token"] == "[redacted]"


@pytest.mark.parametrize("status", ["running", "awaiting_otp", "awaiting_user", "done", "skipped"])
def test_approval_does_not_reexecute_started_or_finished_change(fake_tools, status):
    fake_tools.entities["Change"]["change-1"]["entity"]["status"] = status
    result = tools.dispatch(
        "alice", "execute_change", {"change_id": "change-1", "approval_token": "approved"}
    )
    assert result == {"change_id": "change-1", "status": status}
    assert fake_tools.calls == [("consume", "alice", "approved")]


@pytest.mark.parametrize("reason", ["wrong_member", "expired"])
def test_invalid_approval_never_enqueues_or_leaks_token(fake_tools, reason):
    if reason == "wrong_member":
        fake_tools.authorized = ["other-change"]
    else:
        fake_tools.consume_error = "approval expired: private-token"
    result = tools.dispatch(
        "alice", "execute_change", {"change_id": "change-1", "approval_token": "private-token"}
    )
    assert result["outcome"] == "error"
    assert fake_tools.calls == [("consume", "alice", "private-token")]
    assert "private-token" not in json.dumps(result)
    assert "private-token" not in json.dumps(fake_tools.traces[-1][2].args)


@pytest.mark.parametrize(
    "name, args",
    [
        ("arbitrary_cypher", {"approval_token": "private-token"}),
        ("execute_change", {"change_id": 99, "approval_token": "private-token"}),
        ("dependents", {"root_id": "phone-old", "depth": "1"}),
        ("dependents", {"root_id": "phone-old", "depth": True}),
        ("list_roots", {"password": "private-token"}),
        ("resolve", {"hint": ""}),
    ],
)
def test_malformed_arguments_fail_before_graph_work(fake_tools, name, args):
    result = tools.dispatch("alice", name, args)
    assert result["outcome"] == "error"
    assert "private-token" not in json.dumps(result)
    assert "private-token" not in json.dumps(fake_tools.traces[-1][2].args)
    assert fake_tools.calls == []
    assert fake_tools.queries == []


async def test_mcp_lists_same_schemas_and_forwards_uid_and_turn(fake_tools):
    server = mcp_server.create_server()
    async with create_connected_server_and_client_session(server) as client:
        listed = await client.list_tools()
        assert {tool.name: tool.inputSchema for tool in listed.tools} == {
            name: tool.schema for name, tool in tools.REGISTRY.items()
        }
        result = await client.call_tool(
            "list_roots", {}, meta={"lapse/uid": "alice", "lapse/turn_id": "turn-7"}
        )
        assert result.isError is False
        assert [root["id"] for root in json.loads(result.content[0].text)] == [
            "phone-old",
            "phone-new",
            "email-college",
        ]
        assert fake_tools.traces[-1][:2] == ("alice", "turn-7")
        assert trace.current_turn.get() is None
        await client.call_tool("list_roots", {}, meta={"lapse/uid": "bob"})
        assert fake_tools.traces[-1][:2] == ("bob", None)


def test_resolve_does_not_ignore_conflicting_carrier(fake_tools):
    result = tools.dispatch("alice", "resolve", {"hint": "my old Jio number"})
    assert result["candidates"] == []
    assert result["outcome"] == "not_in_graph"


def test_credential_prose_never_reaches_graph_handler(fake_tools):
    result = tools.dispatch("alice", "search_evidence", {"text": "My OTP code is 123456"})
    assert result["outcome"] == "error"
    assert fake_tools.calls == []
    assert fake_tools.queries == []
    assert "123456" not in json.dumps(fake_tools.traces[-1][2].args)


@pytest.mark.db
def test_real_takeover_returns_proven_mailbox_depth(monkeypatch, isolated_graph):
    from lapse.config import ROOT_DIR
    from lapse.policy.loader import load_policy_file
    from scripts.load_fixture import load_persona

    policies, _ = load_policy_file(ROOT_DIR / "lapse/policy/services.yaml")
    _, carriers = load_policy_file(ROOT_DIR / "lapse/policy/carriers.yaml")
    load_persona(isolated_graph, policies, carriers)
    monkeypatch.setattr(db, "user_graph", lambda uid: isolated_graph)
    from lapse.graph import scenarios

    monkeypatch.setattr(scenarios, "user_graph", lambda uid: isolated_graph)
    result = tools.takeover_if_reassigned("test", "phone_old")
    assert result["direct_accounts"] == ["amazon_in", "google", "swiggy", "x", "zomato"]
    assert len(result["affected_accounts"]) == 10
    assert len(result["via_accounts"]) == 1
    hub = result["via_accounts"][0]
    assert hub["label"] == "Gmail"
    assert set(hub["accounts"]) == {"dropbox", "linkedin", "notion", "paypal", "spotify"}
