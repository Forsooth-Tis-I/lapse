from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

from falkordb.graph import Graph

from lapse.contracts import (
    HELD_STATUSES,
    Evidence,
    Explanation,
    PathStep,
    Root,
    RootKind,
    ScenarioKind,
    ScenarioRequest,
    ScenarioResult,
)
from lapse.graph import db
from lapse.graph.closure import ClosureResult, closure

user_graph = db.user_graph


@dataclass
class ScenarioEvaluation:
    result: ScenarioResult
    closure: ClosureResult
    baseline: ClosureResult | None
    seeds: list[str]


def evaluate_scenario(g: Graph, req: ScenarioRequest, *, trace=None) -> ScenarioEvaluation:
    start = perf_counter()
    roots = {
        row["root"]["id"]: Root.model_validate(row["root"])
        for row in db.run(g, "scenario_context", trace=trace).rows
    }
    requested = sorted(set(req.root_ids))
    if not requested or any(root_id not in roots for root_id in requested):
        raise ValueError("unknown_root")
    accounts = db.run(g, "scenario_accounts", trace=trace).rows
    baseline = None
    if req.kind == ScenarioKind.takeover:
        seeds = requested
        reached = closure(g, seeds, pw=False, trace=trace)
        affected = [node for node in reached.reached.values() if node.node_type == "Account"]
        direct = [node.node_id for node in affected if node.round == 1]
    else:
        held = sorted(
            root.id
            for root in roots.values()
            if root.kind in (RootKind.phone, RootKind.device) and root.status in HELD_STATUSES
        )
        seeds = [root_id for root_id in held if root_id not in requested]
        baseline = closure(g, held, pw=True, trace=trace)
        disabled = [
            row["id"]
            for row in db.run(
                g,
                "scenario_disabled",
                {"lost": requested},
                trace=trace,
            ).rows
        ]
        reached = closure(g, seeds, pw=True, disabled=disabled, trace=trace)
        affected = [
            node
            for node in baseline.reached.values()
            if node.node_type == "Account" and node.node_id not in reached.reached
        ]
        affected_ids = {node.node_id for node in affected}
        direct = [
            row["account"]["id"]
            for row in accounts
            if row["account"]["id"] in affected_ids and set(row["roots"]) & set(requested)
        ]
    touched = set(seeds) | set(requested)
    touched.update(
        node_id for node_id in reached.reached if node_id in roots and roots[node_id].kind == RootKind.email
    )
    unknown = [
        row["account"]["id"]
        for row in accounts
        if not row["account"].get("modelled", True) and set(row["roots"]) & touched
    ]
    result = ScenarioResult(
        id=uuid4().hex,
        kind=req.kind,
        root_ids=requested,
        actor="stranger" if req.kind == ScenarioKind.takeover else "user",
        rounds=reached.rounds,
        affected_accounts=sorted(affected, key=lambda node: (node.round, node.node_id)),
        direct_accounts=sorted(direct),
        unknown_accounts=sorted(unknown),
        total_accounts=len(accounts),
        ms=(perf_counter() - start) * 1000,
    )
    return ScenarioEvaluation(result, reached, baseline, seeds)


def run_scenario(uid, req: ScenarioRequest, *, trace=None) -> ScenarioResult:
    start = perf_counter()
    g = user_graph(uid)
    evaluation = evaluate_scenario(g, req, trace=trace)
    result = evaluation.result
    db.run(
        g,
        "write_scenario",
        {
            "props": {
                "id": result.id,
                "kind": result.kind.value,
                "actor": result.actor,
                "root_ids": result.root_ids,
                "created_at": datetime.now(UTC).isoformat(),
                "reached_count": len(evaluation.closure.reached),
                "result_json": result.model_dump_json(),
            },
            "seeds": evaluation.seeds,
        },
        write=True,
        trace=trace,
    )
    db.run(
        g,
        "write_reached",
        {
            "sid": result.id,
            "reached": [node.model_dump(mode="json") for node in evaluation.closure.reached.values()],
        },
        write=True,
        trace=trace,
    )
    derivations = [("reached", evaluation.closure)]
    if evaluation.baseline is not None:
        derivations.append(("baseline", evaluation.baseline))
    for basis, derivation in derivations:
        edges = [
            {
                "target": target,
                "need": need,
                "method": derivation.reached[target].via_method,
                "method_label": derivation.method_labels[derivation.reached[target].via_method],
                "round": derivation.reached[target].round,
            }
            for target, needs in derivation.needs.items()
            for need in needs
        ]
        db.run(
            g, "write_derivation", {"sid": result.id, "basis": basis, "edges": edges}, write=True, trace=trace
        )
    old_ids = [row["id"] for row in db.run(g, "scenario_old", trace=trace).rows]
    if old_ids:
        db.run(g, "scenario_prune_derivations", {"ids": old_ids}, write=True, trace=trace)
        db.run(g, "scenario_prune", {"ids": old_ids}, write=True, trace=trace)
    result.ms = (perf_counter() - start) * 1000
    db.run(
        g,
        "scenario_timing",
        {
            "sid": result.id,
            "ms": result.ms,
            "result_json": result.model_dump_json(),
        },
        write=True,
        trace=trace,
    )
    return result


def get_scenario(uid, scenario_id, *, trace=None) -> ScenarioResult | None:
    rows = db.run(user_graph(uid), "get_scenario", {"sid": scenario_id}, trace=trace).rows
    return ScenarioResult.model_validate_json(rows[0]["result_json"]) if rows else None


def direct_dependents(uid, root_id, *, trace=None) -> list[str]:
    evaluation = evaluate_scenario(
        user_graph(uid),
        ScenarioRequest(kind=ScenarioKind.takeover, root_ids=[root_id]),
        trace=trace,
    )
    return evaluation.result.direct_accounts


def explain(uid, scenario_id, account_id, *, trace=None) -> Explanation:
    g = user_graph(uid)
    rows = db.run(g, "scenario_account", {"account": account_id}, trace=trace).rows
    if not rows or not rows[0]["account"].get("modelled", True):
        return Explanation(scenario_id=scenario_id, account_id=account_id, outcome="not_in_graph")
    result = get_scenario(uid, scenario_id, trace=trace)
    if result is None:
        raise ValueError("unknown_scenario")
    if account_id not in {node.node_id for node in result.affected_accounts}:
        return Explanation(scenario_id=scenario_id, account_id=account_id, outcome="not_affected")
    by_target = defaultdict(list)
    for row in db.run(g, "explain", {"sid": scenario_id}, trace=trace).rows:
        by_target[row["target"]].append(row)
    pending, seen, path = [account_id], set(), []
    while pending:
        target = pending.pop()
        if target in seen:
            continue
        seen.add(target)
        for row in by_target[target]:
            path.append(row)
            pending.append(row["need"])
    steps = []
    for row in sorted(path, key=lambda edge: (edge["round"], edge["target"], edge["need"])):
        evidence = [
            Evidence.model_validate(item["evidence"])
            for item in db.run(
                g,
                "account_evidence",
                {"ids": [row["need"], row["target"]]},
                trace=trace,
            ).rows
        ]
        steps.append(
            PathStep(
                from_id=row["need"],
                from_label=row["need_label"],
                to_id=row["target"],
                to_label=row["target_label"],
                method_id=row["method"],
                method_label=row["method_label"] or row["method"],
                round=row["round"],
                evidence=evidence,
            )
        )
    return Explanation(scenario_id=scenario_id, account_id=account_id, outcome="path", steps=steps)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a takeover under the methods we model.")
    parser.add_argument("--uid", default="demo")
    parser.add_argument("--takeover", required=True, nargs="+")
    args = parser.parse_args()
    result = run_scenario(args.uid, ScenarioRequest(kind="takeover", root_ids=args.takeover))
    print(
        f"Under the methods we model: direct={len(result.direct_accounts)}, "
        f"full={len(result.affected_accounts)}, rounds={result.rounds}, ms={result.ms:.2f}"
    )
    print("Direct: " + ", ".join(result.direct_accounts))
    print("Full: " + ", ".join(node.node_id for node in result.affected_accounts))
    print("Unknown, not safe: " + ", ".join(result.unknown_accounts))
    explanation = explain(args.uid, result.id, "dropbox")
    print(f"Dropbox: {explanation.outcome}")
    for step in explanation.steps:
        print(f"  {step.from_id} -> {step.to_id} via {step.method_label} (round {step.round})")


if __name__ == "__main__":
    main()
