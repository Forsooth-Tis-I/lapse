from __future__ import annotations

import json
import os
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypedDict
from urllib.parse import quote

from httpx import HTTPError
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from openai import APIError
from redis.exceptions import RedisError

from lapse import llm
from lapse.agent import guard, memory
from lapse.agent.tools import REGISTRY, dispatch
from lapse.config import settings
from lapse.trace import current_turn, tool_call

MAX_TOOL_STEPS = 6
SYSTEM = Path(__file__).with_name("prompts").joinpath("system.md").read_text()


class AgentReply(TypedDict):
    text: str
    buttons: list[dict]
    tool_calls: list[str]
    diagnostics: dict


@dataclass
class TurnTools:
    uid: str
    turn_id: str
    session: Any = None
    definitions: list[dict] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    results: list[Any] = field(default_factory=list)
    llm_requests: int = 0
    llm_diagnostics: dict = field(default_factory=dict)

    async def call(self, name, arguments):
        if len(self.calls) >= MAX_TOOL_STEPS:
            raise ValueError("Tool step limit reached")
        self.calls.append(name)
        if name == "execute_change":
            with tool_call(self.uid, name, arguments) as trace:
                trace.outcome = "error"
            raise ValueError("Use a human approval action to execute changes")
        if self.session is None:
            result = dispatch(self.uid, name, arguments)
        else:
            reply = await self.session.call_tool(
                name,
                arguments,
                meta={
                    "lapse/uid": self.uid,
                    "lapse/turn_id": self.turn_id,
                },
            )
            if reply.isError:
                raise ValueError("MCP tool failed")
            result = json.loads("".join(item.text for item in reply.content if item.type == "text"))
        self.results.append(result)
        return result


@asynccontextmanager
async def tool_transport(uid, turn_id):
    definitions = [tool.openai() for tool in REGISTRY.values() if tool.name != "execute_change"]
    transport = os.getenv("AGENT_TOOL_TRANSPORT", "inprocess")
    if transport == "inprocess":
        yield TurnTools(uid, turn_id, definitions=definitions)
    elif transport == "mcp":
        url = os.getenv("MCP_URL", f"http://127.0.0.1:{os.getenv('MCP_PORT', '8766')}/mcp")
        async with (
            streamable_http_client(url) as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            listed = await session.list_tools()
            definitions = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.inputSchema,
                    },
                }
                for tool in listed.tools
                if tool.name in REGISTRY and tool.name != "execute_change"
            ]
            yield TurnTools(uid, turn_id, session=session, definitions=definitions)
    else:
        raise ValueError("AGENT_TOOL_TRANSPORT must be inprocess or mcp")


def create_llm():
    config = settings()
    if not config.llm_api_key:
        return None
    return llm.client(asynchronous=True)


async def model_answer(client, messages, tools):
    while len(tools.calls) < MAX_TOOL_STEPS:
        tools.llm_requests += 1
        response = await llm.acomplete(
            client, diagnostics=tools.llm_diagnostics,
            messages=messages,
            tools=tools.definitions,
            parallel_tool_calls=False,
        )
        message = response.choices[0].message
        if not message.tool_calls:
            if not message.content or not tools.results:
                raise ValueError("No grounded model answer")
            return message.content
        if len(message.tool_calls) > MAX_TOOL_STEPS - len(tools.calls):
            raise ValueError("Too many tool calls")
        messages.append(message.model_dump(exclude_none=True))
        for call in message.tool_calls:
            name = call.function.name
            try:
                args = json.loads(call.function.arguments)
                if not isinstance(args, dict):
                    raise TypeError("Tool arguments must be an object")
            except (TypeError, ValueError):
                tools.calls.append(name)
                with tool_call(tools.uid, name, {"malformed_arguments": True}) as trace:
                    trace.outcome = "error"
                raise ValueError("Malformed tool arguments") from None
            result = await tools.call(name, args)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)})
            if isinstance(result, dict) and result.get("outcome") == "error":
                raise ValueError("Invalid or unavailable tool call")
    return guard.templated(tools.results)


def latest_context(history):
    context = {}
    for turn in history:
        context.update(turn.get("context", {}))
    return context


async def fallback(text, tools, previous):
    if len(tools.calls) >= MAX_TOOL_STEPS:
        return guard.templated(tools.results)
    lower = text.casefold().strip().rstrip("?.!")
    if re.search(r"\b(approve|status)\b", lower):
        plan_id = previous.get("plan_id")
        if plan_id:
            await tools.call("plan_status", {"plan_id": plan_id})
            if "approve" in lower:
                return "Review the plan to approve changes under the methods we model."
        return guard.templated(tools.results)
    why = re.search(r"why\s+is\s+(.+?)\s+at\s+risk", text, re.IGNORECASE)
    loss = re.search(
        r"(?:what\s+(?:happens\s+)?if\s+i\s+lose|(?:if\s+i\s+)?lose|lost)\s+(.+)", text, re.IGNORECASE
    )
    plan = re.search(r"(?:plan\s+(?:the\s+)?fix|fix|retire)(?:\s+for)?\s+(.+)", text, re.IGNORECASE)
    risk = re.search(r"(?:risk\s+(?:of|for)|show\s+(?:the\s+)?risk\s+(?:of|for))\s+(.+)", text, re.IGNORECASE)
    closing = re.search(r"what\s+do\s+i\s+lose\s+when\s+(.+?)\s+closes", text, re.IGNORECASE)
    reassigned = re.search(r"(?:someone|a stranger)\s+(?:gets|takes|has)\s+(.+)", text, re.IGNORECASE)
    safety = re.search(r"^is\s+(.+?)\s+safe[?.!]*$", text, re.IGNORECASE)
    loss = closing or loss
    match = why or loss or plan or risk or reassigned or safety
    if not match:
        if re.fullmatch(r"(?:plan\s+the\s+fix|show\s+risk)", lower) and previous.get("root_id"):
            match_id = previous["root_id"]
            tool = (
                "plan_retirement"
                if lower.startswith("plan")
                else (
                    "lockout_if_lost"
                    if previous.get("scenario_kind") == "lockout"
                    else "takeover_if_reassigned"
                )
            )
            await tools.call(tool, {"old_root_id" if tool == "plan_retirement" else "root_id": match_id})
        else:
            await tools.call("list_roots", {})
        return guard.templated(tools.results)
    resolved = await tools.call("resolve", {"hint": match.group(1).strip().rstrip("?.!")})
    candidates = resolved.get("candidates", [])
    if len(candidates) != 1 or len(tools.calls) >= MAX_TOOL_STEPS:
        return guard.templated(tools.results)
    candidate = candidates[0]
    if why and candidate["kind"] == "account":
        if previous.get("scenario_id"):
            explanation = await tools.call(
                "explain", {"account_id": candidate["id"], "scenario_id": previous["scenario_id"]}
            )
            if (
                explanation.get("outcome") == "not_affected"
                and previous.get("scenario_kind") == "takeover"
                and previous.get("root_id")
                and len(tools.calls) <= MAX_TOOL_STEPS - 2
            ):
                scenario = await tools.call("lockout_if_lost", {"root_id": previous["root_id"]})
                if scenario.get("id"):
                    await tools.call(
                        "explain", {"account_id": candidate["id"], "scenario_id": scenario["id"]}
                    )
        else:
            await tools.call("account_info", {"account_id": candidate["id"]})
    elif candidate["kind"] == "root":
        tool = (
            "plan_retirement"
            if plan
            else (
                "lockout_if_lost"
                if loss or candidate.get("root_kind") in {"email", "device"}
                else "takeover_if_reassigned"
            )
        )
        arguments = {"old_root_id" if plan else "root_id": candidate["id"]}
        replacements = candidate.get("replacement_ids", [])
        if plan and len(replacements) == 1:
            arguments["new_root_id"] = replacements[0]
        await tools.call(tool, arguments)
    else:
        await tools.call("account_info", {"account_id": candidate["id"]})
    return guard.templated(tools.results)


def buttons_for(uid, results):
    for result in reversed(results):
        if not isinstance(result, dict):
            continue
        if "exposure_before" in result:
            buttons = [
                {
                    "label": "Review in web",
                    "action": "open_web",
                    "payload": {"path": f"/plans/{quote(result['id'], safe='')}"},
                }
            ]
            changes = [
                step["id"] for step in result["steps"] if step["tier"] <= 3 and step["status"] == "proposed"
            ]
            if changes:
                try:
                    from lapse.approvals import mint

                    token = mint(uid, changes)
                except (ImportError, ValueError, RuntimeError, RedisError):
                    return buttons
                buttons.insert(
                    0,
                    {
                        "label": "Approve all T1–T3",
                        "action": "approve_changes",
                        "payload": {"change_ids": changes, "approval_token": token},
                    },
                )
            return buttons
        if "affected_accounts" in result:
            return [
                {
                    "label": "Plan the fix",
                    "action": "plan_root",
                    "payload": {"root_id": result["root_ids"][0]},
                },
                {
                    "label": "Show risk",
                    "action": "open_web",
                    "payload": {"path": f"/graph?scenario={quote(result['id'], safe='')}"},
                },
            ]
    return []


async def respond(uid: str, text: str, *, channel="telegram") -> AgentReply:
    prior = memory.history(uid)
    clean_text = memory.safe_text(text)
    turn_id = memory.save_turn(uid, "user", clean_text, channel)
    turn_token = current_turn.set(turn_id)
    calls, results, buttons = [], [], []
    diagnostics = {
        "llm_tool_calls": [],
        "fallback_used": False,
        "guard_regenerated": False,
        "llm_requests": 0,
    }
    answer = "The graph tools are unavailable. Unknown, not safe under the methods we model. Try again."
    try:
        async with tool_transport(uid, turn_id) as tools:
            client = create_llm()
            context_ids = json.dumps(latest_context(prior))
            messages = [
                {"role": "system", "content": SYSTEM + "\nPrior context IDs to re-read: " + context_ids}
            ]
            messages += [{"role": turn["role"], "content": turn["text"]} for turn in prior]
            messages.append({"role": "user", "content": clean_text})
            try:
                if client is None:
                    raise ValueError("Model unavailable")
                answer = await model_answer(client, messages, tools)
                tools.results = guard.focused_results(tools.results)
                if not guard.grounded(answer, tools.results):
                    diagnostics["guard_regenerated"] = True
                    messages.extend(
                        [
                            {"role": "assistant", "content": answer},
                            {
                                "role": "user",
                                "content": "Rewrite once using only names and facts in this turn's tool "
                                "results. Say 'under the methods we model'. Missing models are 'unknown, not safe'.",
                            },
                        ]
                    )
                    tools.llm_requests += 1
                    response = await llm.acomplete(
                        client, diagnostics=tools.llm_diagnostics,
                        messages=messages,
                    )
                    revised = response.choices[0].message
                    answer = revised.content if not revised.tool_calls else ""
                    if not guard.grounded(answer, tools.results):
                        answer = guard.templated(tools.results)
            except (
                APIError,
                HTTPError,
                ValueError,
                TypeError,
                KeyError,
                AttributeError,
                RuntimeError,
                OSError,
            ) as exc:
                diagnostics["llm_tool_calls"] = list(tools.calls)
                diagnostics["fallback_used"] = True
                diagnostics["fallback_reason"] = type(exc).__name__
                answer = await fallback(clean_text, tools, latest_context(prior))
            finally:
                if client is not None:
                    await client.close()
                calls, results = tools.calls, tools.results
                if not diagnostics["fallback_used"]:
                    diagnostics["llm_tool_calls"] = list(calls)
                diagnostics["llm_requests"] = tools.llm_requests
                diagnostics.update(tools.llm_diagnostics)
            buttons = buttons_for(uid, results)
    except (HTTPError, ValueError, RuntimeError, OSError, RedisError, ExceptionGroup):
        if results:
            answer = guard.templated(results)
    finally:
        current_turn.reset(turn_token)
    context = {}
    for result in results:
        if isinstance(result, dict) and "affected_accounts" in result:
            context.update(
                scenario_id=result["id"], root_id=result["root_ids"][0], scenario_kind=result["kind"]
            )
        elif isinstance(result, dict) and "exposure_before" in result:
            context.update(plan_id=result["id"], root_id=result["old_root"])
            if result.get("kind"):
                context["scenario_kind"] = result["kind"]
    mentioned = guard.entities(results)
    memory.link_turn(uid, turn_id, mentioned)
    memory.save_turn(uid, "assistant", answer, channel, mentioned, context)
    return {"text": answer, "buttons": buttons, "tool_calls": calls, "diagnostics": diagnostics}
