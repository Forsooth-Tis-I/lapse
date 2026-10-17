from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from itertools import product
from uuid import uuid4

from falkordb.graph import Graph

from lapse.contracts import (
    HELD_STATUSES,
    Change,
    ChangeStatus,
    Plan,
    Root,
    RootKind,
    ScenarioKind,
    ScenarioRequest,
    ServicePolicy,
)
from lapse.graph import db
from lapse.graph.scenarios import evaluate_scenario
from lapse.policy import loader


def _policies() -> list[ServicePolicy]:
    return [policy for path in loader.default_policy_paths() for policy in loader.load_policy_file(path)[0]]


def _compile_account(g: Graph, account_id: str, policies: list[ServicePolicy], *, trace=None) -> None:
    rows = db.run(g, "planner_compile_account", {"account_id": account_id}, trace=trace).rows
    methods, needs = [], []
    if rows:
        account = rows[0]["account"]
        policy = next((p for p in policies if p.service.id == account["service_id"]), None)
        if policy and policy.service.modelled and account.get("modelled", True):
            roles = defaultdict(set)
            for use in rows[0]["uses"]:
                if use["root_id"] is not None:
                    roles[use["role"]].add(use["root_id"])
            for template in policy.methods:
                if any(roles[role] for role in template.requires_absent_roles):
                    continue
                if not template.needs_roles and not template.needs_password:
                    raise ValueError(f"Zero-need method {template.id} must need a password")
                choices = [sorted(roles[role]) for role in template.needs_roles]
                for index, roots in enumerate(product(*choices)):
                    method_id = f"m:{account_id}:{template.id}" + (f":{index}" if index else "")
                    methods.append(
                        {
                            "props": {
                                "id": method_id,
                                "account_id": account_id,
                                "kind": template.kind,
                                "label": template.label,
                                "needs_password": template.needs_password,
                                "source": "policy",
                                "doc_url": template.doc_url,
                            },
                            "target_id": account_id,
                        }
                    )
                    needs.extend(
                        {"method_id": method_id, "node_id": root, "role": role.value}
                        for role, root in zip(template.needs_roles, roots, strict=True)
                    )
    db.run(g, "planner_compile_clear_methods", {"account_id": account_id}, write=True, trace=trace)
    db.run(g, "planner_compile_clear_enables", {"account_id": account_id}, write=True, trace=trace)
    db.run(g, "compile_methods", {"methods": methods}, write=True, trace=trace)
    db.run(g, "compile_needs", {"needs": needs}, write=True, trace=trace)
    db.run(g, "planner_compile_enables", {"account_id": account_id}, write=True, trace=trace)


def _apply(g: Graph, change: Change, policies: list[ServicePolicy], *, trace=None) -> None:
    db.run(
        g,
        "planner_repoint_use" if change.to_root else "planner_drop_use",
        change.model_dump(mode="json"),
        write=True,
        trace=trace,
    )
    _compile_account(g, change.account_id, policies, trace=trace)


def _exposure(g: Graph, req: ScenarioRequest, baseline: set[str] | None, *, trace=None) -> int:
    evaluation = evaluate_scenario(g, req, trace=trace)
    if baseline is None:
        return len(evaluation.result.affected_accounts)
    return len(baseline - evaluation.closure.reached.keys())


def plan_for_root(uid, old_root, new_root=None, deadline=None, *, trace=None) -> Plan:
    g = db.user_graph(uid)
    rows = db.run(
        g, "planner_roots", {"ids": [old_root, new_root] if new_root else [old_root]}, trace=trace
    ).rows
    roots = {row["root"]["id"]: Root.model_validate(row["root"]) for row in rows}
    if old_root not in roots:
        raise ValueError(f"Unknown root: {old_root}")
    root = roots[old_root]
    if new_root is not None:
        if new_root not in roots:
            raise ValueError(f"Unknown replacement root: {new_root}")
        if new_root == old_root or roots[new_root].kind != root.kind:
            raise ValueError("Replacement must be a different root of the same kind")
    if deadline is None:
        deadline = root.drop_at or root.closes_at or root.expires_at
    elif isinstance(deadline, str):
        deadline = date.fromisoformat(deadline)
    kind = ScenarioKind.lockout if root.kind in {RootKind.email, RootKind.device} else ScenarioKind.takeover
    req = ScenarioRequest(kind=kind, root_ids=[old_root])
    policies = _policies()
    by_service = {policy.service.id: policy for policy in policies}
    plan_id = f"plan:{uuid4().hex}"
    remaining = []
    for row in db.run(g, "planner_candidates", {"root_id": old_root}, trace=trace).rows:
        policy = by_service.get(row["service_id"])
        procedure = next((p for p in policy.change if p.root_kind == root.kind), None) if policy else None
        if procedure is None:
            continue
        requires_old_root = bool({"old_otp", "email_otp_old"}.intersection(procedure.requires))
        remaining.append(
            Change(
                id=f"change:{uuid4().hex}",
                plan_id=plan_id,
                order=0,
                account_id=row["account_id"],
                account_label=row["account_label"],
                role=row["role"],
                from_root=old_root,
                to_root=new_root,
                tier=procedure.tier,
                requires_old_root=requires_old_root,
                due=deadline - timedelta(days=1) if deadline else None,
                settings_url=procedure.settings_url,
            )
        )
    original = evaluate_scenario(g, req, trace=trace)
    baseline = (
        {node_id for node_id, node in original.baseline.reached.items() if node.node_type == "Account"}
        if original.baseline is not None
        else None
    )
    exposure_before = len(original.result.affected_accounts)
    exposure = exposure_before
    steps = []
    feasible = not any(
        change.requires_old_root
        and (root.status not in HELD_STATUSES or (deadline is not None and deadline < date.today()))
        for change in remaining
    )
    if remaining:
        working = g.copy(f"lapse:sandbox:{uid}:{plan_id}")
        try:
            while remaining:
                scored = []
                for change in remaining:
                    trial = working.copy(f"{working.name}:{change.id}")
                    try:
                        _apply(trial, change, policies, trace=trace)
                        after = _exposure(trial, req, baseline, trace=trace)
                        scored.append((change, after))
                    finally:
                        trial.delete()
                winner, after = min(
                    scored,
                    key=lambda item: (
                        item[1],
                        not item[0].requires_old_root,
                        item[0].tier,
                        item[0].account_id,
                        item[0].role,
                    ),
                )
                winner.order = len(steps) + 1
                winner.exposure_removed = exposure - after
                _apply(working, winner, policies, trace=trace)
                steps.append(winner)
                remaining.remove(winner)
                exposure = after
        finally:
            working.delete()
    plan = Plan(
        id=plan_id,
        kind=kind,
        old_root=old_root,
        new_root=new_root,
        deadline=deadline,
        feasible=feasible,
        exposure_before=exposure_before,
        exposure_after=exposure,
        steps=steps,
        created_at=datetime.now(UTC),
    )
    db.run(
        g,
        "planner_save_plan",
        {"props": plan.model_dump(mode="json", exclude={"steps"}, exclude_none=True)},
        write=True,
        trace=trace,
    )
    db.run(
        g,
        "planner_save_steps",
        {"plan_id": plan.id, "steps": [step.model_dump(mode="json", exclude_none=True) for step in steps]},
        write=True,
        trace=trace,
    )
    db.run(g, "planner_step_order", {"plan_id": plan.id}, write=True, trace=trace)
    return plan


def _read_plan(row) -> Plan:
    return Plan.model_validate(
        {
            "new_root": None,
            "deadline": None,
            **row["plan"],
            "steps": [{"to_root": None, **step} for step in row["steps"]],
        }
    )


def get_plan(uid, plan_id, *, trace=None) -> Plan | None:
    rows = db.run(db.user_graph(uid), "planner_get_plan", {"plan_id": plan_id}, trace=trace).rows
    if not rows:
        return None
    return _read_plan(rows[0])


def list_plans(uid, *, trace=None) -> list[Plan]:
    return [_read_plan(row) for row in db.run(db.user_graph(uid), "planner_list_plans", trace=trace).rows]


def update_change(uid, change_id, *, status: ChangeStatus, note=None, trace=None) -> Change:
    rows = db.run(
        db.user_graph(uid),
        "planner_update_change",
        {"change_id": change_id, "status": ChangeStatus(status).value, "note": note},
        write=True,
        trace=trace,
    ).rows
    if not rows:
        raise ValueError(f"Unknown change: {change_id}")
    return Change.model_validate({"to_root": None, **rows[0]["change"]})


def apply_change_done(uid, change_id, evidence_id=None, *, trace=None) -> Change:
    g = db.user_graph(uid)
    rows = db.run(g, "planner_get_change", {"change_id": change_id}, trace=trace).rows
    if not rows:
        raise ValueError(f"Unknown change: {change_id}")
    change = Change.model_validate({"to_root": None, **rows[0]["change"]})
    if change.status == ChangeStatus.done:
        return change
    if (
        change.to_root is not None
        and not db.run(g, "planner_roots", {"ids": [change.to_root]}, trace=trace).rows
    ):
        raise ValueError(f"Unknown replacement root: {change.to_root}")
    _apply(g, change, _policies(), trace=trace)
    if evidence_id is not None:
        db.run(
            g,
            "planner_change_evidence",
            {"change_id": change_id, "evidence_id": evidence_id},
            write=True,
            trace=trace,
        )
    return update_change(uid, change_id, status=ChangeStatus.done, note=change.note, trace=trace)
