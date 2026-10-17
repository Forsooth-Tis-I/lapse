from __future__ import annotations

from typing import Any

from lapse.contracts import Account, Evidence, Root, ScenarioResult, Uses
from lapse.graph.db import Trace, run, user_graph


def list_roots(uid: str, *, trace: Trace | None = None) -> list[Root]:
    return [Root.model_validate(row["root"]) for row in run(user_graph(uid), "view_roots", trace=trace).rows]


def graph_view(uid: str, scenario_id: str | None = None, *, trace: Trace | None = None) -> dict:
    g = user_graph(uid)
    roots = [Root.model_validate(row["root"]) for row in run(g, "view_roots", trace=trace).rows]
    accounts = [
        Account.model_validate(row["account"])
        for row in run(g, "view_accounts", {"account_id": ""}, trace=trace).rows
    ]
    uses = run(g, "view_uses", {"account_id": ""}, trace=trace).rows
    methods = run(g, "view_methods", {"account_id": ""}, trace=trace).rows
    affected: dict[str, int] = {}
    rounds: dict[str, int] = {}
    unknown: set[str] = set()
    if scenario_id is not None:
        saved = run(g, "view_scenario", {"scenario_id": scenario_id}, trace=trace).rows
        if saved:
            scenario = ScenarioResult.model_validate_json(saved[0]["result_json"])
            affected = {item.node_id: item.round for item in scenario.affected_accounts}
            rounds = {item["id"]: item["round"] for item in saved[0]["reached"] if item["id"]}
            unknown = set(scenario.unknown_accounts)

    nodes = []
    for item in [*roots, *accounts]:
        is_root = isinstance(item, Root)
        nodes.append(
            {
                "id": item.id,
                "label": item.label if is_root else item.display,
                "node_type": "Root" if is_root else "Account",
                "root" if is_root else "account": item.model_dump(mode="json"),
                "status": item.status.value if is_root else item.status,
                "round": affected.get(item.id, rounds.get(item.id)),
                "affected": item.id in affected,
                "unknown": item.id in unknown or (not is_root and not item.modelled),
            }
        )

    constraints: dict[tuple[str, str], set[str]] = {}
    edges: list[dict[str, Any]] = []
    method_labels = {}
    for row in methods:
        method = row["method"]
        needs = [need for need in row["needs"] if need["id"]]
        label = method["label"]
        if len(needs) > 1:
            label += " (AND: " + " + ".join(need["label"] or need["id"] for need in needs) + ")"
            for need in needs:
                constraints.setdefault((row["target_id"], need["id"]), set()).add(label)
        method_labels[method["id"]] = label
        if method["kind"] == "mailbox":
            for need in needs:
                edges.append(
                    {
                        "id": f"method:{method['id']}:{need['id']}",
                        "source": need["id"],
                        "target": row["target_id"],
                        "label": label,
                        "confirmed": False,
                        "derived": False,
                        "method_id": method["id"],
                    }
                )
    for use in uses:
        labels = sorted(constraints.get((use["account_id"], use["root_id"]), set()))
        edges.append(
            {
                "id": f"uses:{use['account_id']}:{use['root_id']}:{use['role']}",
                "source": use["root_id"],
                "target": use["account_id"],
                "label": "; ".join([use["role"], *labels]),
                "confirmed": use["confirmed"],
                "derived": False,
            }
        )
    if scenario_id is not None:
        for edge in run(g, "view_derived", {"scenario_id": scenario_id}, trace=trace).rows:
            edges.append(
                {
                    "id": f"derived:{scenario_id}:{edge['method_id']}:{edge['need_id']}:{edge['target_id']}",
                    "source": edge["need_id"],
                    "target": edge["target_id"],
                    "label": method_labels.get(edge["method_id"], edge["method_label"] or edge["method_id"]),
                    "confirmed": False,
                    "derived": True,
                    "method_id": edge["method_id"],
                    "round": edge["round"],
                }
            )
    return {"nodes": nodes, "edges": edges}


def account_detail(uid: str, account_id: str, *, trace: Trace | None = None) -> dict:
    g = user_graph(uid)
    params = {"account_id": account_id}
    rows = run(g, "view_accounts", params, trace=trace).rows
    if not rows:
        return {"account": None, "uses": [], "methods": [], "evidence": []}
    account = Account.model_validate(rows[0]["account"]).model_dump(mode="json")
    uses = [
        Uses.model_validate(row).model_dump(mode="json")
        for row in run(g, "view_uses", params, trace=trace).rows
    ]
    methods = []
    for row in run(g, "view_methods", params, trace=trace).rows:
        method = {key: value for key, value in row["method"].items() if key != "_labels"}
        methods.append({**method, "needs": [need for need in row["needs"] if need["id"]]})
    evidence = [
        Evidence.model_validate(row["evidence"]).model_dump(mode="json")
        for row in run(g, "view_evidence", params, trace=trace).rows
    ]
    return {"account": account, "uses": uses, "methods": methods, "evidence": evidence}


def search_evidence(uid: str, text: str, limit: int = 10, *, trace: Trace | None = None) -> list[Evidence]:
    if not text.strip() or limit <= 0:
        return []
    return [
        Evidence.model_validate(row["evidence"])
        for row in run(
            user_graph(uid), "view_search_evidence", {"text": text, "limit": limit}, trace=trace
        ).rows
    ]


def stats(uid: str, *, trace: Trace | None = None) -> dict:
    g = user_graph(uid)
    nodes = run(g, "graph_node_count", trace=trace)
    edges = run(g, "graph_edge_count", trace=trace)
    labels = run(g, "view_label_counts", trace=trace)
    return {
        "nodes": nodes.rows[0]["count"] if nodes.rows else 0,
        "edges": edges.rows[0]["count"] if edges.rows else 0,
        "by_label": {row["label"]: row["count"] for row in labels.rows},
        "last_query_ms": labels.ms,
    }
