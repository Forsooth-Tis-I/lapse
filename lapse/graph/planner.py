from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
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
from lapse.graph.closure import closure
from lapse.graph.scenarios import evaluate_scenario, recovery_closure
from lapse.policy import loader
from lapse.policy.compile import compile_user_graph


def _policies() -> list[ServicePolicy]:
    return [policy for path in loader.default_policy_paths() for policy in loader.load_policy_file(path)[0]]


def _apply(g: Graph, change: Change, policies: list[ServicePolicy], *, trace=None) -> None:
    db.run(
        g,
        "planner_repoint_use" if change.to_root else "planner_drop_use",
        {**change.model_dump(mode="json"), "roles": change.roles or [change.role]},
        write=True,
        trace=trace,
    )
    compile_user_graph(g, policies, account_ids=[change.account_id], trace=trace)


def _exposure(
    g: Graph, root: Root, baseline: tuple[set[str], set[str]] | None, *, trace=None
) -> tuple[set[str], set[str]]:
    taken, lost = set(), set()
    if root.kind in {RootKind.phone, RootKind.domain}:
        evaluation = evaluate_scenario(
            g, ScenarioRequest(kind=ScenarioKind.takeover, root_ids=[root.id]), trace=trace
        )
        taken = {node.node_id for node in evaluation.result.affected_accounts}
    if baseline is not None:
        evaluation = evaluate_scenario(
            g, ScenarioRequest(kind=ScenarioKind.lockout, root_ids=[root.id]), trace=trace
        )
        access_before, recovery_before = baseline
        lost = (access_before - evaluation.closure.reached.keys()) | (
            recovery_before - evaluation.recovery.reached.keys()
        )
    return taken, lost


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
    policies = _policies()
    by_service = {policy.service.id: policy for policy in policies}
    plan_id = f"plan:{uuid4().hex}"
    remaining = []
    unknown_accounts = set()
    for row in db.run(g, "planner_candidates", {"root_id": old_root}, trace=trace).rows:
        policy = by_service.get(row["service_id"])
        procedure = next((p for p in policy.change if p.root_kind == root.kind), None) if policy else None
        unknown = policy is None or not policy.service.modelled or not row["modelled"]
        note = procedure.settings_note if procedure else None
        if unknown:
            unknown_accounts.add(row["account_id"])
            note = "unknown, not safe: recovery methods are unmodelled; verify the change manually."
        elif procedure is None:
            note = "manual: no documented procedure for this root kind; verify every listed role in settings."
        requires_old_root = bool(procedure and {"old_otp", "email_otp_old"}.intersection(procedure.requires))
        roles = sorted(row["roles"])
        role_labels = {"recovery_phone": "recovery phone", "sms_2fa": "2-Step phone"}
        label = policy.service.name if policy else row["account_label"]
        title = f"Move {label}'s " + " and ".join(
            role_labels.get(role, role.replace("_", " ")) for role in roles
        )
        settings_url = (
            (procedure.settings_url if procedure else None)
            or (policy.service.doc_url if policy else None)
            or row["doc_url"]
        )
        remaining.append(
            Change(
                id=f"change:{uuid4().hex}",
                plan_id=plan_id,
                order=0,
                account_id=row["account_id"],
                account_label=row["account_label"],
                role=roles[0],
                roles=roles,
                title=title,
                from_root=old_root,
                to_root=new_root,
                tier=3 if unknown or procedure is None else procedure.tier,
                requires_old_root=requires_old_root,
                due=deadline - timedelta(days=1) if deadline else None,
                settings_url=settings_url,
                note=note,
            )
        )
    baseline = None
    if root.kind in {RootKind.phone, RootKind.email, RootKind.device}:
        original = evaluate_scenario(
            g, ScenarioRequest(kind=ScenarioKind.lockout, root_ids=[old_root]), trace=trace
        )
        held_before = original.baseline
        recovery_before = original.recovery_baseline
        if root.kind == RootKind.phone and root.status not in HELD_STATUSES:
            held_before = closure(g, [*original.seeds, old_root], pw=True, trace=trace)
            recovery_before = recovery_closure(g, held_before, trace=trace)
        baseline = tuple(
            {node.node_id for node in access.reached.values() if node.node_type == "Account"}
            for access in (held_before, recovery_before)
        )
    if root.kind in {RootKind.phone, RootKind.domain}:
        takeover = evaluate_scenario(
            g, ScenarioRequest(kind=ScenarioKind.takeover, root_ids=[old_root]), trace=trace
        )
        unknown_accounts.update(takeover.result.unknown_accounts)
    taken_before, lost_before = _exposure(g, root, baseline, trace=trace)
    exposure_before = len(taken_before | lost_before)
    exposure = exposure_before
    taken, lost = taken_before, lost_before
    steps = []
    feasible = not any(
        change.requires_old_root
        and (root.status not in HELD_STATUSES or (deadline is not None and deadline < date.today()))
        for change in remaining
    )
    if remaining:
        working = db.copy_graph(g, f"lapse:sandbox:{uid}:{plan_id}")
        try:
            while remaining:
                scored = []
                for change in remaining:
                    trial = db.copy_graph(working, f"{working.name}:{change.id}")
                    try:
                        _apply(trial, change, policies, trace=trace)
                        components = _exposure(trial, root, baseline, trace=trace)
                        scored.append((change, components))
                    finally:
                        trial.delete()
                winner, (taken, lost) = min(
                    scored,
                    key=lambda item: (
                        len(item[1][0] | item[1][1]),
                        not item[0].requires_old_root,
                        item[0].tier,
                        item[0].account_id,
                        item[0].role,
                    ),
                )
                after = len(taken | lost)
                winner.order = len(steps) + 1
                winner.exposure_removed = exposure - after
                _apply(working, winner, policies, trace=trace)
                steps.append(winner)
                remaining.remove(winner)
                exposure = after
        finally:
            working.delete()
    notes = ["Exposure counts distinct affected accounts under the methods we model."]
    if taken:
        notes.append("Remaining takeover: " + ", ".join(sorted(taken)) + ".")
    if lost:
        notes.append(
            "Remaining lockout: "
            + ", ".join(sorted(lost))
            + "; these changes do not restore sign-in or recovery."
        )
    if unknown_accounts:
        notes.append("Unknown, not safe: " + ", ".join(sorted(unknown_accounts)) + ".")
    plan = Plan(
        id=plan_id,
        kind=kind,
        old_root=old_root,
        new_root=new_root,
        deadline=deadline,
        feasible=feasible,
        exposure_before=exposure_before,
        exposure_after=exposure,
        takeover_before=len(taken_before),
        takeover_after=len(taken),
        lockout_before=len(lost_before),
        lockout_after=len(lost),
        remaining_accounts=sorted(taken | lost),
        unknown_accounts=sorted(unknown_accounts),
        note=" ".join(notes),
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
