from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from falkordb.graph import Graph

from lapse.contracts import Reached
from lapse.graph import db


@dataclass
class ClosureResult:
    reached: dict[str, Reached]
    needs: dict[str, list[str]]
    method_labels: dict[str, str]
    rounds: int
    ms: float


def closure(
    g: Graph, seeds: list[str], *, pw: bool = False, disabled: list[str] | None = None, trace=None
) -> ClosureResult:
    start = perf_counter()
    reached = {}
    for row in db.run(g, "closure_seeds", {"seeds": seeds}, trace=trace).rows:
        reached[row["id"]] = Reached(
            node_id=row["id"],
            label=row["label"],
            node_type=row["node_type"],
            round=0,
        )
    needs, method_labels = {}, {}
    round_number = 0
    while True:
        rows = db.run(
            g,
            "closure_round",
            {
                "have": sorted(reached),
                "pw": pw,
                "disabled": disabled or [],
            },
            trace=trace,
        ).rows
        if not rows:
            break
        round_number += 1
        for row in rows:
            node_id = row["gained"]
            if node_id in reached:
                continue
            reached[node_id] = Reached(
                node_id=node_id,
                label=row["label"],
                node_type=row["node_type"],
                round=round_number,
                via_method=row["via"],
            )
            needs[node_id] = sorted(set(row["needs"]))
            method_labels[row["via"]] = row["method_label"]
    return ClosureResult(reached, needs, method_labels, round_number, (perf_counter() - start) * 1000)
