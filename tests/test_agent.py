import copy
import json
import shutil
import sys
from contextlib import asynccontextmanager, contextmanager
from types import ModuleType, SimpleNamespace
from uuid import uuid4

import anyio
import pytest
from mcp.shared.memory import create_client_server_memory_streams
from openai.types.chat import ChatCompletionMessage
from redis.exceptions import ResponseError

from lapse import trace
from lapse.agent import agent, guard, mcp_server, memory
from lapse.agent import tools as registry_tools
from lapse.graph import db
from lapse.trace import current_turn


def message(text=None, calls=()):
    return ChatCompletionMessage.model_validate(
        {
            "role": "assistant",
            "content": text,
            "tool_calls": [
                {
                    "id": f"call-{index}",
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": args if isinstance(args, str) else json.dumps(args),
                    },
                }
                for index, (name, args) in enumerate(calls)
            ]
            or None,
        }
    )


class FakeLLM:
    def __init__(self, *script):
        self.script = list(script)
        self.requests = []
        self.closed = False
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        response = self.script.pop(0)
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(choices=[SimpleNamespace(message=response)])

    async def close(self):
        self.closed = True


@pytest.fixture
def world(monkeypatch):
    monkeypatch.delenv("AGENT_TOOL_TRANSPORT", raising=False)
    state = SimpleNamespace(calls=[], minted=[], saved=[], linked=[], prior=[], llm=None, traced=[])
    state.root = {"id": "phone-old", "label": "••4321", "kind": "root"}
    state.scenario = {
        "id": "scenario-1",
        "kind": "takeover",
        "root_ids": ["phone-old"],
        "affected_accounts": [
            {"node_id": "gmail", "label": "Gmail"},
            {"node_id": "dropbox", "label": "Dropbox"},
        ],
        "direct_accounts": ["gmail"],
        "unknown_accounts": [],
    }
    state.plan = {
        "id": "plan-1",
        "old_root": "phone-old",
        "exposure_before": 2,
        "exposure_after": 0,
        "feasible": True,
        "steps": [
            {
                "id": f"change-{index}",
                "order": index,
                "account_id": "dropbox",
                "account_label": "Dropbox",
                "tier": tier,
                "status": status,
            }
            for index, (tier, status) in enumerate(
                [(1, "proposed"), (2, "proposed"), (3, "proposed"), (4, "proposed"), (1, "done")], 1
            )
        ],
    }

    def dispatch(uid, name, args):
        state.calls.append((uid, name, copy.deepcopy(args), current_turn.get()))
        if name == "resolve":
            candidate = (
                {"id": "dropbox", "label": "Dropbox", "kind": "account"}
                if "dropbox" in args["hint"].lower()
                else state.root
            )
            return {"candidates": [candidate], "ambiguous": False}
        if name == "list_roots":
            return [state.root]
        if name in {"takeover_if_reassigned", "lockout_if_lost"}:
            return {**state.scenario, "kind": "lockout" if name == "lockout_if_lost" else "takeover"}
        if name in {"plan_retirement", "plan_status"}:
            return copy.deepcopy(state.plan)
        if name == "explain":
            return {
                "outcome": "path",
                "account_id": "dropbox",
                "steps": [
                    {
                        "from_id": "gmail",
                        "from_label": "Gmail",
                        "to_id": "dropbox",
                        "to_label": "Dropbox",
                        "method_label": "email recovery",
                    },
                ],
            }
        if name == "account_info":
            return {"account": {"id": "dropbox", "display": "Dropbox"}}
        raise AssertionError(f"Unexpected tool: {name}")

    def mint(uid, changes):
        state.minted.append((uid, list(changes)))
        return "private-approval-token"

    @contextmanager
    def trace_call(uid, name, args):
        record = SimpleNamespace(uid=uid, name=name, args=trace.redact(args), outcome="ok")
        state.traced.append(record)
        yield record

    state.trace_call = trace_call

    approvals = ModuleType("lapse.approvals")
    approvals.mint = mint
    monkeypatch.setitem(sys.modules, "lapse.approvals", approvals)
    monkeypatch.setattr(agent, "dispatch", dispatch)
    monkeypatch.setattr(mcp_server, "dispatch", dispatch)
    monkeypatch.setattr(agent, "create_llm", lambda: state.llm)
    monkeypatch.setattr(agent, "tool_call", trace_call)
    return state


@pytest.fixture
def offline(world, monkeypatch):
    def save(uid, role, text, channel, entity_ids=(), context=None):
        turn_id = f"turn-{len(world.saved)}"
        world.saved.append(
            {
                "id": turn_id,
                "uid": uid,
                "role": role,
                "text": text,
                "channel": channel,
                "entities": set(entity_ids),
                "context": context or {},
            }
        )
        return turn_id

    monkeypatch.setattr(memory, "history", lambda uid: world.prior)
    monkeypatch.setattr(memory, "save_turn", save)
    monkeypatch.setattr(
        memory, "link_turn", lambda uid, turn_id, ids: world.linked.append((uid, turn_id, set(ids)))
    )
    return world


async def test_scripted_model_resolves_runs_scenario_and_returns_buttons(offline):
    text = "Under the methods we model, Gmail and Dropbox are at risk. Plan the fix."
    offline.llm = FakeLLM(
        message(calls=[("resolve", {"hint": "my old number"})]),
        message(calls=[("takeover_if_reassigned", {"root_id": "phone-old"})]),
        message(text),
    )
    reply = await agent.respond("alice", "risk of my old number", channel="web")
    assert reply["text"] == text
    assert reply["tool_calls"] == ["resolve", "takeover_if_reassigned"]
    assert reply["buttons"] == [
        {"label": "Plan the fix", "action": "plan_root", "payload": {"root_id": "phone-old"}},
        {"label": "Show risk", "action": "open_web", "payload": {"path": "/graph?scenario=scenario-1"}},
    ]
    assert all(call[0] == "alice" and call[3] == "turn-0" for call in offline.calls)
    assert offline.saved[-1]["context"] == {
        "scenario_id": "scenario-1",
        "root_id": "phone-old",
        "scenario_kind": "takeover",
    }
    assert offline.saved[-1]["channel"] == "web"
    assert offline.saved[-1]["entities"] >= {"phone-old", "gmail", "dropbox"}
    assert offline.llm.closed
    assert current_turn.get() is None


@pytest.mark.parametrize(
    "prompt, expected, context",
    [
        ("risk of my old number", ["resolve", "takeover_if_reassigned"], {}),
        ("what if I lose my old number", ["resolve", "lockout_if_lost"], {}),
        ("plan the fix for my old number", ["resolve", "plan_retirement"], {}),
        ("why is Dropbox at risk", ["resolve", "explain"], {"scenario_id": "scenario-1"}),
        ("why is Dropbox at risk", ["resolve", "account_info"], {}),
        ("status", ["plan_status"], {"plan_id": "plan-1"}),
        ("approve", ["plan_status"], {"plan_id": "plan-1"}),
    ],
)
@pytest.mark.parametrize("failure", ["unavailable", "malformed"])
async def test_broken_model_falls_back_to_intents(offline, prompt, expected, context, failure):
    offline.prior = [{"role": "assistant", "text": "Previous result", "context": context}]
    offline.llm = FakeLLM(
        RuntimeError("rate limited")
        if failure == "unavailable"
        else message(calls=[("resolve", "{broken-json")])
    )
    reply = await agent.respond("alice", prompt)
    assert reply["tool_calls"] == (["resolve"] if failure == "malformed" else []) + expected
    if failure == "malformed":
        (rejected,) = offline.traced
        assert rejected.name == "resolve"
        assert rejected.args == {"malformed_arguments": True}
        assert rejected.outcome == "error"
    assert "under the methods we model" in reply["text"].lower()
    assert "execute_change" not in reply["tool_calls"]
    assert offline.llm.closed


async def test_no_model_key_uses_fallback_and_mints_only_eligible_steps(offline):
    reply = await agent.respond("alice", "plan the fix for my old number")
    assert reply["tool_calls"] == ["resolve", "plan_retirement"]
    assert offline.minted == [("alice", ["change-1", "change-2", "change-3"])]
    assert reply["buttons"] == [
        {
            "label": "Approve all T1–T3",
            "action": "approve_changes",
            "payload": {
                "change_ids": ["change-1", "change-2", "change-3"],
                "approval_token": "private-approval-token",
            },
        },
        {"label": "Review in web", "action": "open_web", "payload": {"path": "/plans/plan-1"}},
    ]
    assert "private-approval-token" not in reply["text"]
    assert all("private-approval-token" not in turn["text"] for turn in offline.saved)


async def test_plan_token_never_enters_model_context(offline):
    offline.llm = FakeLLM(
        message(calls=[("plan_retirement", {"old_root_id": "phone-old"})]),
        message("Under the methods we model, review the plan before approval."),
    )
    reply = await agent.respond("alice", "plan the fix")
    assert offline.minted == [("alice", ["change-1", "change-2", "change-3"])]
    assert "private-approval-token" not in json.dumps(offline.llm.requests)
    assert reply["buttons"][0]["payload"]["approval_token"] == "private-approval-token"


async def test_six_tool_calls_is_total_limit(offline):
    offline.llm = FakeLLM(*[message(calls=[("list_roots", {})]) for _ in range(6)])
    reply = await agent.respond("alice", "risk of my old number")
    assert reply["tool_calls"] == ["list_roots"] * 6
    assert len(offline.calls) == 6
    assert len(offline.llm.requests) == 6
    assert "••4321" in reply["text"]


async def test_fallback_respects_tool_budget_already_spent(offline):
    offline.llm = FakeLLM(*[message(calls=[("list_roots", {})]) for _ in range(5)], RuntimeError("offline"))
    reply = await agent.respond("alice", "risk of my old number")
    assert reply["tool_calls"] == ["list_roots"] * 5 + ["resolve"]
    assert len(offline.calls) == 6


async def test_last_eight_history_turns_are_in_model_context(offline):
    offline.prior = [
        {"role": "user" if index % 2 == 0 else "assistant", "text": f"history-{index}"} for index in range(8)
    ]
    offline.llm = FakeLLM(RuntimeError("offline"))
    await agent.respond("alice", "risk of my old number")
    messages = offline.llm.requests[0]["messages"]
    assert messages[0]["role"] == "system"
    assert [item["content"] for item in messages[1:9]] == [f"history-{index}" for index in range(8)]
    assert [item["role"] for item in messages[1:9]] == ["user", "assistant"] * 4
    assert messages[-1] == {"role": "user", "content": "risk of my old number"}


@pytest.mark.parametrize(
    "revision, expected",
    [
        ("Under the methods we model, Dropbox is at risk. Plan the fix.", "model"),
        ("Under the methods we model, Spotify is at risk. Plan the fix.", "template"),
    ],
)
async def test_unsupported_names_regenerate_once_then_use_results(offline, revision, expected):
    offline.llm = FakeLLM(
        message(calls=[("takeover_if_reassigned", {"root_id": "phone-old"})]),
        message("Under the methods we model, Spotify is at risk. Plan the fix."),
        message(revision),
    )
    reply = await agent.respond("alice", "risk of my old number")
    assert len(offline.llm.requests) == 3
    assert "Spotify" not in reply["text"]
    if expected == "model":
        assert reply["text"] == revision
    else:
        assert "directly: 1" in reply["text"]
        assert "Gmail, Dropbox" in reply["text"]
    assert reply["tool_calls"] == ["takeover_if_reassigned"]


async def test_approval_execution_is_never_an_llm_tool(offline):
    offline.llm = FakeLLM(
        message(calls=[("execute_change", {"change_id": "change-1", "approval_token": "secret"})])
    )
    reply = await agent.respond("alice", "approve")
    names = {tool["function"]["name"] for tool in offline.llm.requests[0]["tools"]}
    assert "execute_change" not in names
    assert reply["tool_calls"] == ["execute_change"]
    assert offline.calls == []
    (rejected,) = offline.traced
    assert rejected.outcome == "error"
    assert rejected.args["approval_token"] == "[redacted]"


async def test_unknown_model_tool_is_traced_and_falls_back(offline, monkeypatch):
    monkeypatch.setattr(agent, "dispatch", registry_tools.dispatch)
    monkeypatch.setattr(trace, "tool_call", offline.trace_call)
    offline.llm = FakeLLM(message(calls=[("invented_tool", {})]))
    reply = await agent.respond("alice", "approve")
    assert reply["tool_calls"] == ["invented_tool"]
    (rejected,) = offline.traced
    assert rejected.name == "invented_tool"
    assert rejected.outcome == "error"
    assert offline.llm.closed


async def test_college_risk_and_followup_preserve_lockout_kind(offline):
    offline.root = {"id": "email-college", "label": "College email", "kind": "root", "root_kind": "email"}
    offline.scenario["root_ids"] = ["email-college"]
    reply = await agent.respond("alice", "risk of college email")
    assert reply["tool_calls"] == ["resolve", "lockout_if_lost"]
    assert offline.saved[-1]["context"] == {
        "scenario_id": "scenario-1",
        "root_id": "email-college",
        "scenario_kind": "lockout",
    }
    offline.prior = [offline.saved[-1]]
    reply = await agent.respond("alice", "show risk")
    assert reply["tool_calls"] == ["lockout_if_lost"]


@pytest.mark.parametrize(
    "sensitive",
    [
        "The OTP for this login is 123456.",
        "My OTP code is 123456",
        "My password is a long private phrase",
    ],
)
async def test_sensitive_user_input_never_reaches_memory_or_model(offline, sensitive):
    assert memory.safe_text(sensitive) == "[redacted sensitive input]"
    offline.llm = FakeLLM(RuntimeError("offline"))
    await agent.respond("alice", sensitive)
    assert offline.saved[0]["text"] == "[redacted sensitive input]"
    assert offline.llm.requests[0]["messages"][-1]["content"] == "[redacted sensitive input]"


@pytest.mark.parametrize("field", ["text", "hint"])
def test_trace_redacts_credentials_in_free_text_arguments(monkeypatch, field):
    writes = []
    monkeypatch.setattr(db, "user_graph", lambda uid: None)
    monkeypatch.setattr(db, "run", lambda graph, name, params, **kwargs: writes.append(params))
    monkeypatch.setitem(sys.modules, "lapse.events", None)
    with trace.tool_call("alice", "resolve", {field: "The OTP for this login is 123456."}):
        pass
    assert json.loads(writes[0]["args"]) == {field: "[redacted sensitive input]"}
    assert "123456" not in json.dumps(writes)


@pytest.mark.parametrize(
    "text",
    [
        "Under the methods we model, Spotify is at risk.",
        "Under the methods we model, spotify is at risk.",
        "Under the methods we model, ••4321 is at risk.",
        "Under the methods we model, 4321 is at risk.",
        "Dropbox is at risk.",
    ],
)
def test_guard_rejects_unseen_names_numbers_and_missing_scope(world, text):
    assert guard.grounded(text, [world.scenario]) is False


def test_guard_accepts_known_entities_and_requires_unknown_wording(world):
    assert guard.grounded("Under the methods we model, Gmail and Dropbox are at risk.", [world.scenario])
    result = {"outcome": "not_in_graph", "message": "Account absent."}
    assert not guard.grounded("Under the methods we model, this account is safe.", [result])
    assert guard.grounded("Under the methods we model, this account is unknown, not safe.", [result])


async def test_mcp_transport_uses_real_client_session(offline, monkeypatch):
    server = mcp_server.create_server()._mcp_server

    @asynccontextmanager
    async def in_memory_http(url):
        assert url == "http://127.0.0.1:8766/mcp"
        async with (
            create_client_server_memory_streams() as (client_streams, server_streams),
            anyio.create_task_group() as group,
        ):
            group.start_soon(server.run, *server_streams, server.create_initialization_options())
            try:
                yield (*client_streams, lambda: None)
            finally:
                group.cancel_scope.cancel()

    monkeypatch.setenv("AGENT_TOOL_TRANSPORT", "mcp")
    monkeypatch.setenv("MCP_URL", "http://127.0.0.1:8766/mcp")
    monkeypatch.setattr(agent, "streamable_http_client", in_memory_http)
    reply = await agent.respond("alice", "risk of my old number")
    assert reply["tool_calls"] == ["resolve", "takeover_if_reassigned"]
    assert all(call[0] == "alice" and call[3] == "turn-0" for call in offline.calls)
    assert "Gmail, Dropbox" in reply["text"]


@pytest.mark.db
async def test_turns_persist_with_about_links_and_last_eight_history(world, monkeypatch, tmp_path):
    graph = db.graph(f"lapse:test:wp4:agent:{uuid4().hex}")
    monkeypatch.setattr(db, "user_graph", lambda uid: graph)
    for path in db.QUERY_DIR.glob("wp4_turn_*.cypher"):
        shutil.copy(path, tmp_path / path.name)
    (tmp_path / "seed.cypher").write_text(
        "CREATE (:Root {id: 'phone-old'}), (:Account {id: 'gmail'}), (:Account {id: 'dropbox'})"
    )
    (tmp_path / "inspect.cypher").write_text(
        "MATCH (t:Turn) OPTIONAL MATCH (t)-[:ABOUT]->(n) "
        "RETURN t AS turn, collect(n.id) AS entities ORDER BY t.at"
    )
    monkeypatch.setattr(db, "QUERY_DIR", tmp_path)
    try:
        db.run(graph, "seed", write=True)
        for index in range(10):
            memory.save_turn("alice", "user", f"earlier {index}", "telegram")
        assert [turn["text"] for turn in memory.history("alice")] == [
            f"earlier {index}" for index in range(2, 10)
        ]
        reply = await agent.respond("alice", "risk of my old number")
        rows = db.run(graph, "inspect").rows
        assert len(rows) == 12
        user, assistant = rows[-2:]
        assert user["turn"]["role"] == "user"
        assert user["turn"]["text"] == "risk of my old number"
        assert assistant["turn"]["role"] == "assistant"
        assert assistant["turn"]["text"] == reply["text"]
        assert set(user["entities"]) == set(assistant["entities"]) == {"phone-old", "gmail", "dropbox"}
        assert memory.history("alice")[-1]["context"] == {
            "scenario_id": "scenario-1",
            "root_id": "phone-old",
            "scenario_kind": "takeover",
        }
    finally:
        try:
            graph.delete()
        except ResponseError as exc:
            if "Invalid graph operation on empty key" not in str(exc):
                raise


@pytest.mark.parametrize(
    "prompt, expected",
    [
        ("what happens if someone gets my old number?", ["resolve", "takeover_if_reassigned"]),
        ("what do I lose when my college email closes?", ["resolve", "lockout_if_lost"]),
        ("is dropbox safe?", ["resolve", "account_info"]),
    ],
)
async def test_demo_wording_routes_when_model_is_unavailable(offline, prompt, expected):
    offline.llm = FakeLLM(RuntimeError("provider unavailable"))
    reply = await agent.respond("alice", prompt)
    assert reply["tool_calls"] == expected
    assert reply["diagnostics"]["fallback_used"] is True
    assert reply["diagnostics"]["llm_tool_calls"] == []
    assert reply["diagnostics"]["guard_regenerated"] is False


def test_template_keeps_takeover_when_model_also_checks_lockout(world):
    takeover = world.scenario
    lockout = {**takeover, "kind": "lockout", "lost_now_accounts": [], "recovery_lost_accounts": []}
    answer = guard.templated([takeover, lockout])
    assert "takeover: directly: 1" in answer
    assert "lost outright: 0" in answer
    assert "no way back if you forget the password: 0" in answer


def test_focus_drops_replacement_root_scenarios_before_answer_and_memory(world):
    selected = {"candidates": [{"id": "email-college", "kind": "root", "replacement_ids": ["email-primary"]}]}
    college = {**world.scenario, "kind": "lockout", "root_ids": ["email-college"]}
    replacement = {**world.scenario, "kind": "lockout", "root_ids": ["email-primary"]}
    assert guard.focused_results([selected, college, replacement]) == [selected, college]
