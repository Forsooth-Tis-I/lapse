from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from importlib import import_module
from math import ceil
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import yaml
from pydantic import BaseModel, ConfigDict, Field

from lapse.contracts import ScenarioKind, ScenarioRequest, ServicePolicy, UseRole
from lapse.graph import db
from lapse.graph.scenarios import evaluate_scenario
from lapse.policy.compile import compile_user_graph
from lapse.policy.loader import default_policy_paths, load_policy_file
from lapse.signals.tenants import tenant_uids


class PolicyDiff(BaseModel):
    model_config = ConfigDict(extra="forbid")
    disable_needs_roles: list[UseRole] = Field(min_length=1)
    exempt_account_property: str


class PolicyEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    at: date
    service_id: str
    description: str
    source_url: str
    coverage_url: str
    diff: PolicyDiff


@dataclass(frozen=True)
class Outcome:
    affected: frozenset[str]
    direct: frozenset[str]
    unknown: frozenset[str]
    reachable: frozenset[str]
    baseline: frozenset[str]


def load_event(event_id: str) -> PolicyEvent:
    data = yaml.safe_load(Path(__file__).with_suffix(".yaml").read_text())
    for item in data["events"]:
        event = PolicyEvent.model_validate(item)
        if event.id == event_id:
            return event
    raise ValueError(f"Unknown policy event: {event_id}")


def event_policies(event: PolicyEvent) -> list[ServicePolicy]:
    policies = [policy for path in default_policy_paths() for policy in load_policy_file(path)[0]]
    if not any(policy.service.id == event.service_id for policy in policies):
        raise ValueError(f"Unknown service: {event.service_id}")
    disabled = set(event.diff.disable_needs_roles)
    return [
        policy.model_copy(
            update={
                "methods": [
                    method for method in policy.methods if not disabled.intersection(method.needs_roles)
                ]
            }
        )
        if policy.service.id == event.service_id
        else policy
        for policy in policies
    ]


def _snapshot(g, roots: list[str], *, trace=None) -> dict[tuple[str, ScenarioKind], Outcome]:
    outcomes = {}
    for root_id in roots:
        for kind in ScenarioKind:
            evaluation = evaluate_scenario(g, ScenarioRequest(kind=kind, root_ids=[root_id]), trace=trace)
            result = evaluation.result
            outcomes[root_id, kind] = Outcome(
                frozenset(node.node_id for node in result.affected_accounts),
                frozenset(result.direct_accounts),
                frozenset(result.unknown_accounts),
                frozenset(
                    node.node_id
                    for node in evaluation.closure.reached.values()
                    if node.node_type == "Account"
                ),
                frozenset(
                    node.node_id
                    for node in evaluation.baseline.reached.values()
                    if node.node_type == "Account"
                )
                if evaluation.baseline
                else frozenset(),
            )
    return outcomes


def _notification_text(event, before, after):
    changed_roots = sorted({root for root, kind in before if before[root, kind] != after[root, kind]})
    return (
        f"{event.description} Outcomes changed for {len(changed_roots)} watched roots "
        "under the methods we model. Review sign-in access and recovery risk."
    )


def _notify_change(uid, text):
    try:
        notifier = import_module("lapse.notify")
    except ModuleNotFoundError as exc:
        if exc.name != "lapse.notify":
            raise
        return False
    notifier.notify(uid, text, [{"label": "Show risk", "action": "open_web", "payload": {"path": "/"}}])
    return True


def apply_policy_event(event_id: str, *, dry_run: bool = False, trace=None) -> dict:
    started = perf_counter()
    event = load_event(event_id)
    policies = event_policies(event)
    if not dry_run:
        db.run(
            db.policy_graph(),
            "signals_policy_event",
            {
                "props": {
                    **event.model_dump(mode="json", exclude={"diff"}),
                    "diff": event.diff.model_dump_json(),
                }
            },
            write=True,
            trace=trace,
        )
    timings, changed_uids = [], []
    notifications_unavailable = 0
    for uid in tenant_uids():
        tenant_started = perf_counter()
        g = db.user_graph(uid)
        accounts = db.run(
            g,
            "signals_policy_accounts",
            {"service_id": event.service_id, "exempt_property": event.diff.exempt_account_property},
            trace=trace,
        ).rows
        if accounts:
            roots = [
                row["root"]["id"]
                for row in db.run(g, "view_roots", trace=trace).rows
                if row["root"].get("status") in {"retiring", "closing"}
            ]
            before = _snapshot(g, roots, trace=trace)
            working = g.copy(f"lapse:sandbox:policy:{uuid4().hex}") if dry_run else g
            try:
                compile_user_graph(working, policies, account_ids=[row["id"] for row in accounts])
                after = _snapshot(working, roots, trace=trace)
            finally:
                if dry_run:
                    working.delete()
            if before != after:
                changed_uids.append(uid)
                if not dry_run:
                    db.run(
                        g,
                        "signals_policy_event",
                        {
                            "props": {
                                "id": event.id,
                                "notification_text": _notification_text(event, before, after),
                                "notification_pending": True,
                            }
                        },
                        write=True,
                        trace=trace,
                    )
        if not dry_run:
            pending = db.run(g, "signals_policy_pending", {"id": event.id}, trace=trace).rows
            if pending:
                if _notify_change(uid, pending[0]["text"]):
                    db.run(
                        g,
                        "signals_policy_event",
                        {"props": {"id": event.id, "notification_pending": False}},
                        write=True,
                        trace=trace,
                    )
                else:
                    notifications_unavailable += 1
        timings.append((perf_counter() - tenant_started) * 1000)
    return {
        "event_id": event.id,
        "dry_run": dry_run,
        "tenants_scanned": len(timings),
        "tenants_changed": len(changed_uids),
        "total_ms": (perf_counter() - started) * 1000,
        "p95_tenant_ms": sorted(timings)[ceil(len(timings) * 0.95) - 1] if timings else 0.0,
        "changed_uids": changed_uids,
        "notifications_unavailable": notifications_unavailable,
    }
