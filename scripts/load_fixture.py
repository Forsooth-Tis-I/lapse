from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path

import yaml
from falkordb.graph import Graph
from redis.exceptions import ResponseError

from lapse.config import ROOT_DIR
from lapse.contracts import Account, CarrierRule, Evidence, Root, RootKind, ServicePolicy, Uses
from lapse.graph.db import ensure_schema, policy_graph, run, user_graph
from lapse.policy.compile import compile_user_graph, write_policy_graph
from lapse.policy.loader import load_policy_file


def load_persona(
    g: Graph,
    policies: list[ServicePolicy],
    carriers: list[CarrierRule],
    path: str | Path = ROOT_DIR / "fixtures/persona.yaml",
) -> None:
    data = yaml.safe_load(Path(path).read_text())
    rules = {carrier.id: carrier for carrier in carriers}
    roots = [Root.model_validate(root) for root in data["roots"]]
    for root in roots:
        if root.kind == RootKind.phone and root.drop_at is not None:
            root.reissue_after = root.drop_at + timedelta(days=rules[root.carrier].reissue_after_days)
    accounts = [Account.model_validate(account) for account in data["accounts"]]
    uses = [Uses.model_validate(use) for use in data["uses"]]
    evidence = [Evidence.model_validate(item["evidence"]) for item in data["evidence"]]
    if any(len(item.snippet) > 300 for item in evidence):
        raise ValueError("Evidence snippets must be at most 300 characters")
    ensure_schema(g)
    run(g, "fixture_user", {"props": {**data["user"], "uid": g.name.removeprefix("lapse:u:")}}, write=True)
    for kind in RootKind:
        run(
            g,
            f"fixture_roots_{kind}",
            {
                "roots": [
                    root.model_dump(mode="json", exclude_none=True) for root in roots if root.kind == kind
                ]
            },
            write=True,
        )
    run(
        g,
        "policy_service",
        {"services": [policy.service.model_dump(mode="json", exclude_none=True) for policy in policies]},
        write=True,
    )
    run(
        g,
        "fixture_accounts",
        {"accounts": [account.model_dump(mode="json", exclude_none=True) for account in accounts]},
        write=True,
    )
    run(g, "fixture_uses", {"uses": [use.model_dump(mode="json") for use in uses]}, write=True)
    for item, record in zip(evidence, data["evidence"], strict=True):
        run(
            g,
            "fixture_evidence",
            {
                "props": item.model_dump(mode="json"),
                "account_id": record["account_id"],
                "root_ids": record["root_ids"],
            },
            write=True,
        )
    compile_user_graph(g, policies)


def _drop(g: Graph) -> None:
    try:
        g.delete()
    except ResponseError as exc:
        if "Invalid graph operation on empty key" not in str(exc):
            raise


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replace the demo policy and user graphs with fake fixture data."
    )
    parser.add_argument("--uid", default="demo")
    args = parser.parse_args()
    policies, carriers = load_policy_file(ROOT_DIR / "fixtures/policy.yaml")
    shared = policy_graph()
    g = user_graph(args.uid)
    _drop(shared)
    _drop(g)
    write_policy_graph(policies, carriers)
    load_persona(g, policies, carriers)
    for loaded in (shared, g):
        nodes = run(loaded, "graph_node_count").rows[0]["count"]
        edges = run(loaded, "graph_edge_count").rows[0]["count"]
        print(f"{loaded.name}: {nodes} nodes, {edges} edges")


if __name__ == "__main__":
    main()
