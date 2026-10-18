"""FalkorDB graph algorithms over single-factor ENABLES edges.

Keystones come from algo.betweenness, which FalkorDB samples, so its score is an estimate. Ranking uses
the exact count of chains through each node (upstream sources x downstream accounts).

ENABLES holds only password-free methods with one need, so these results are a lower bound:
an account reached only through an AND method needs closure (scenarios) to be found.
"""

from __future__ import annotations

from lapse.graph.db import Trace, run, user_graph


def keystones(uid: str, limit: int = 3, *, trace: Trace | None = None) -> dict:
    rows = run(user_graph(uid), "algo_keystones", {"limit": limit}, trace=trace).rows
    return {
        "outcome": "keystones",
        "algorithm": "betweenness",
        "keystones": [
            {
                "id": row["id"],
                "label": row["label"],
                "node_type": row["node_type"],
                "score": float(row["score"]),
                "chains": row["chains"],
                "upstream": row["upstream"],
                "downstream": row["downstream"],
                "downstream_labels": sorted(row["downstream_labels"]),
            }
            for row in rows
        ],
    }


def _known(uid: str, node_id: str, trace: Trace | None) -> bool:
    return any(
        run(user_graph(uid), "wp4_entity", {"id": node_id, "kind": kind}, trace=trace).rows
        for kind in ("Root", "Account")
    )


def shortest_path(uid: str, from_id: str, to_id: str, *, trace: Trace | None = None) -> dict:
    for node_id in (from_id, to_id):
        if not _known(uid, node_id, trace):
            raise KeyError(node_id)
    rows = run(user_graph(uid), "algo_shortest_path", {"from_id": from_id, "to_id": to_id}, trace=trace).rows
    if not rows:
        return {"outcome": "no_single_route", "from_id": from_id, "to_id": to_id}
    row = rows[0]
    return {
        "outcome": "route",
        "algorithm": "SPpaths",
        "hops": row["hops"],
        "route": [{"id": i, "label": label} for i, label in zip(row["ids"], row["labels"], strict=True)],
    }
