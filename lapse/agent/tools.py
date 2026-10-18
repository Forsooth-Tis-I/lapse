from __future__ import annotations

import importlib
import inspect
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model
from redis.exceptions import RedisError

from lapse import trace as tracing
from lapse.contracts import ChangeStatus, ScenarioRequest
from lapse.graph import db


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    arguments: type[BaseModel]
    handler: Any
    outcome: str
    ids: dict[str, str]

    @property
    def schema(self):
        return self.arguments.model_json_schema()

    def openai(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.schema,
            },
        }


REGISTRY: dict[str, Tool] = {}


def register(name, description, outcome="memory", ids=None, **fields):
    def decorate(handler):
        model = create_model(f"{name}Arguments", __base__=Arguments, **fields)
        REGISTRY[name] = Tool(name, description, model, handler, outcome, ids or {})
        return handler

    return decorate


def plain(value):
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [plain(item) for item in value]
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    return value


def graph_call(module, function, *args, trace=None, **kwargs):
    fn = getattr(importlib.import_module(f"lapse.graph.{module}"), function)
    if "trace" in inspect.signature(fn).parameters:
        kwargs["trace"] = trace
    return fn(*args, **kwargs)


def entity(uid, entity_id, kind, trace=None):
    rows = db.run(db.user_graph(uid), "wp4_entity", {"id": entity_id, "kind": kind}, trace=trace).rows
    return rows[0] if rows else None


def failure(outcome, message):
    return {"outcome": outcome, "message": message}


def dispatch(uid: str, name: str, args: dict) -> Any:
    with tracing.tool_call(uid, name, args) as trace:
        tool = REGISTRY.get(name)
        if tool is None:
            trace.outcome = "error"
            return failure("error", "Unknown tool. Use one of the listed fixed tools.")
        try:
            if isinstance(args.get("depth"), bool):
                raise TypeError("Depth must be 1 or full")
            validated = tool.arguments.model_validate(args).model_dump()
        except (ValidationError, ValueError, TypeError):
            trace.outcome = "error"
            return failure("error", "Invalid tool arguments. Use the tool's JSON schema.")
        try:
            if any(
                isinstance(validated.get(field), str)
                and tracing.safe_text(validated[field]) == "[redacted sensitive input]"
                for field in ("hint", "text")
            ):
                trace.outcome = "error"
                return failure("error", "Do not send credentials to graph tools.")
            for field, kind in tool.ids.items():
                value = validated.get(field)
                if value is None:
                    continue
                found = entity(uid, value, kind, trace)
                if found is None:
                    trace.outcome = "unknown_root" if kind == "Root" else "not_in_graph"
                    return failure(
                        trace.outcome, f"That {kind.lower()} is not in the graph; unknown, not safe."
                    )
                if kind == "Account" and (
                    found["entity"].get("modelled") is False
                    or (found.get("service") or {}).get("modelled") is False
                ):
                    trace.outcome = "not_in_graph"
                    return {
                        **failure("not_in_graph", "This account is unmodelled; unknown, not safe."),
                        "account": found["entity"],
                        "service": found.get("service"),
                    }
            result = plain(tool.handler(uid, trace=trace, **validated))
            result_outcome = result.get("outcome") if isinstance(result, dict) else None
            trace.outcome = (
                result_outcome
                if result_outcome in {"path", "memory", "not_in_graph", "unknown_root", "ok", "error"}
                else tool.outcome
            )
            if result_outcome == "not_affected":
                trace.outcome = "memory"
            return result
        except (ValueError, TypeError, KeyError, ImportError, RuntimeError, OSError, RedisError):
            trace.outcome = "error"
            return failure("error", "This operation is unavailable. No safety conclusion can be drawn.")


@register("list_roots", "List your known roots, status, and deadlines.")
def list_roots(uid, *, trace=None):
    return graph_call("views", "list_roots", uid, trace=trace)


@register("list_entities", "List known root and account IDs, labels, and type cues for tool selection.")
def list_entities(uid, *, trace=None):
    roots = plain(list_roots(uid, trace=trace))
    catalog_roots = []
    for root in roots:
        item = {key: root[key] for key in ("id", "label", "kind", "status")}
        for key in ("email_kind", "device_kind"):
            if root.get(key) is not None:
                item[key] = root[key]
        item["replacement_ids"] = [
            other["id"]
            for other in roots
            if other["id"] != root["id"] and other["kind"] == root["kind"] and other["status"] == "active"
        ]
        catalog_roots.append(item)
    accounts = []
    for row in db.run(db.user_graph(uid), "wp4_accounts", trace=trace).rows:
        account, service = row["account"], row.get("service") or {}
        item = {
            "id": account["id"],
            "label": account["display"],
            "modelled": account.get("modelled") is not False and service.get("modelled") is not False,
        }
        if service.get("name"):
            item["service"] = service["name"]
        accounts.append(item)
    return {"roots": catalog_roots, "accounts": accounts}


def normalize(text):
    return " ".join(re.findall(r"\w+", text.casefold()))


@register(
    "resolve",
    "Resolve an ambiguous phrase to root or account IDs. Known IDs can be used directly. "
    "Ask the user when there are multiple candidates.",
    hint=(str, Field(min_length=1, max_length=500)),
)
def resolve(uid, hint, *, trace=None):
    roots = plain(list_roots(uid, trace=trace))
    accounts = db.run(db.user_graph(uid), "wp4_accounts", trace=trace).rows
    candidates = []
    needle = normalize(hint)
    words = set(needle.split()) - {"my", "the", "one", "a", "an"}
    for root in roots:
        aliases = [root.get(key) for key in ("id", "label", "last4", "carrier", "address", "name")]
        alias_words = set(normalize(" ".join(str(x) for x in aliases if x)).split())
        semantic = {
            "number": root["kind"] == "phone",
            "sim": root["kind"] == "phone",
            "phone": root["kind"] == "phone" or root.get("device_kind") == "phone",
            "email": root["kind"] == "email",
            "mailbox": root["kind"] == "email",
            "device": root["kind"] == "device",
            "old": root["status"] in {"retiring", "inactive", "closing", "closed", "expired", "sold", "lost"},
            "new": root["status"] == "active",
        }
        for word in ("college", "university", "edu"):
            semantic[word] = root["kind"] == "email" and root.get("email_kind") == "edu"
        matched = any(normalize(str(alias)) == needle for alias in aliases if alias) or (
            bool(words) and all(semantic.get(word, word in alias_words) for word in words)
        )
        if matched:
            candidates.append(
                {
                    "id": root["id"],
                    "label": root["label"],
                    "kind": "root",
                    "root_kind": root["kind"],
                    "replacement_ids": [
                        other["id"]
                        for other in roots
                        if other["id"] != root["id"]
                        and other["kind"] == root["kind"]
                        and other["status"] == "active"
                    ],
                }
            )
    for row in accounts:
        account, service = row["account"], row.get("service") or {}
        aliases = [account.get(key) for key in ("id", "display", "identifier", "service_id")]
        aliases += [service.get("name")]
        if any(needle == normalize(str(alias)) for alias in aliases if alias) or (
            words and any(words == set(normalize(str(alias)).split()) for alias in aliases if alias)
        ):
            candidates.append({"id": account["id"], "label": account["display"], "kind": "account"})
    if not candidates:
        return {
            **failure("not_in_graph", "No matching root or account is in the graph; unknown, not safe."),
            "candidates": [],
        }
    return {"candidates": candidates, "ambiguous": len(candidates) > 1}


@register(
    "dependents",
    "Direct accounts opened by a root alone, or the full takeover closure.",
    "path",
    ids={"root_id": "Root"},
    root_id=(str, ...),
    depth=(Literal[1] | Literal["full"], "full"),  # noqa: PYI030 - provider requires typed enum branches.
)
def dependents(uid, root_id, depth="full", *, trace=None):
    if depth == 1:
        return graph_call("scenarios", "direct_dependents", uid, root_id, trace=trace)
    return takeover_if_reassigned(uid, root_id, trace=trace)


@register(
    "takeover_if_reassigned",
    "What happens if someone gets an old number: stranger takeover without passwords. "
    "Use a known root ID or resolve an ambiguous phrase. Returns direct and indirect counts, with mailbox paths.",
    "path",
    ids={"root_id": "Root"},
    root_id=(str, ...),
)
def takeover_if_reassigned(uid, root_id, *, trace=None):
    result = plain(
        graph_call(
            "scenarios",
            "run_scenario",
            uid,
            ScenarioRequest(kind="takeover", root_ids=[root_id]),
            trace=trace,
        )
    )
    indirect = {a["node_id"] for a in result.get("affected_accounts", [])} - set(
        result.get("direct_accounts", [])
    )
    if indirect:
        result["via_accounts"] = db.run(
            db.user_graph(uid),
            "wp4_mailbox_paths",
            {"sid": result["id"], "accounts": sorted(indirect)},
            trace=trace,
        ).rows
    return result


@register(
    "lockout_if_lost",
    "What do I lose when an email closes or a SIM is dropped: immediate sign-in loss and password-free recovery loss. "
    "Use for the user losing access, not for a stranger getting a number. SMS 2FA may block the user even when a stranger cannot sign in.",
    "path",
    ids={"root_id": "Root"},
    root_id=(str, ...),
)
def lockout_if_lost(uid, root_id, *, trace=None):
    return graph_call(
        "scenarios", "run_scenario", uid, ScenarioRequest(kind="lockout", root_ids=[root_id]), trace=trace
    )


@register(
    "explain",
    "Explain all required method branches for an account in a scenario.",
    "path",
    ids={"account_id": "Account", "scenario_id": "Scenario"},
    account_id=(str, ...),
    scenario_id=(str, ...),
)
def explain(uid, account_id, scenario_id, *, trace=None):
    return graph_call("scenarios", "explain", uid, scenario_id, account_id, trace=trace)


@register(
    "keystones",
    "What to fix first: the accounts or mailboxes that the most single-factor chains pass through "
    "(betweenness centrality), with the accounts reachable downstream of each.",
    limit=(int, 3),
)
def keystones(uid, limit=3, *, trace=None):
    return graph_call("algorithms", "keystones", uid, max(1, min(limit, 10)), trace=trace)


@register(
    "path_between",
    "How a root or account connects to another account: the shortest single-factor route (algo.SPpaths). "
    "No route does not mean safe; AND methods need explain.",
    "path",
    from_id=(str, ...),
    to_id=(str, ...),
)
def path_between(uid, from_id, to_id, *, trace=None):
    try:
        return graph_call("algorithms", "shortest_path", uid, from_id, to_id, trace=trace)
    except KeyError:
        return failure("not_in_graph", "That root or account is not in the graph; unknown, not safe.")


@register(
    "account_info",
    "Read an account's methods, uses and evidence.",
    ids={"account_id": "Account"},
    account_id=(str, ...),
)
def account_info(uid, account_id, *, trace=None):
    return graph_call("views", "account_detail", uid, account_id, trace=trace)


@register("search_evidence", "Search stored evidence subjects and snippets.", text=(str, ...))
def search_evidence(uid, text, *, trace=None):
    return graph_call("views", "search_evidence", uid, text, trace=trace)


@register(
    "plan_retirement",
    "Plan fixes for a retiring root. Use known root IDs or resolve ambiguous phrases; use the unique "
    "replacement_ids candidate when available. Omitting new_root_id means removing the dependency "
    "and may leave lockout unresolved. Phone exposure combines takeover and lockout.",
    "path",
    ids={"old_root_id": "Root", "new_root_id": "Root"},
    old_root_id=(str, ...),
    new_root_id=(str | None, None),
    deadline=(str | None, None),
)
def plan_retirement(uid, old_root_id, new_root_id=None, deadline=None, *, trace=None):
    return graph_call(
        "planner",
        "plan_for_root",
        uid,
        old_root_id,
        new_root_id,
        date.fromisoformat(deadline) if deadline else None,
        trace=trace,
    )


@register(
    "plan_status",
    "Read a stored plan and its current change statuses. Omit plan_id for the latest plan with proposed steps.",
    ids={"plan_id": "Plan"},
    plan_id=(str | None, None),
)
def plan_status(uid, plan_id=None, *, trace=None):
    if plan_id is not None:
        return graph_call("planner", "get_plan", uid, plan_id, trace=trace)
    for plan in plain(graph_call("planner", "list_plans", uid, trace=trace)):
        if any(step["status"] == "proposed" for step in plan["steps"]):
            return plan
    return failure("memory", "No stored plan has proposed steps. No changes were executed.")


@register(
    "execute_change",
    "Enqueue one change with a human-issued, single-use approval token.",
    "ok",
    ids={"change_id": "Change"},
    change_id=(str, ...),
    approval_token=(str, Field(min_length=1)),
)
def execute_change(uid, change_id, approval_token, *, trace=None):
    approvals = importlib.import_module("lapse.approvals")
    jobs = importlib.import_module("lapse.jobs")
    authorized = approvals.consume(uid, approval_token)
    if change_id not in authorized:
        return failure("error", "Approval does not authorize this change.")
    change = entity(uid, change_id, "Change", trace)["entity"]
    if change["status"] not in (ChangeStatus.proposed, ChangeStatus.failed, ChangeStatus.approved):
        return {"change_id": change_id, "status": change["status"]}
    graph_call("planner", "update_change", uid, change_id, status=ChangeStatus.approved, trace=trace)
    return {"job_id": jobs.enqueue(uid, "execute_change", {"change_id": change_id}), "change_id": change_id}
