from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter, sleep
from typing import Any

from falkordb import FalkorDB
from falkordb.edge import Edge
from falkordb.graph import Graph
from falkordb.node import Node
from falkordb.path import Path as GraphPath
from redis.exceptions import ResponseError

from lapse.config import settings
from lapse.contracts import POLICY_GRAPH, user_graph_name

QUERY_DIR = Path(__file__).with_name("queries")
Trace = Callable[[str, dict[str, Any], float, int], None]


@dataclass(frozen=True)
class QueryOutcome:
    rows: list[dict[str, Any]]
    row_count: int
    ms: float
    query_name: str


def graph(name: str) -> Graph:
    config = settings()
    return FalkorDB(host=config.falkordb_host, port=config.falkordb_port).select_graph(name)


def copy_graph(g: Graph, name: str, *, timeout_s: float = 30) -> Graph:
    deadline = perf_counter() + timeout_s
    lock = g.client.connection.lock(
        "lapse:lock:graph-copy", timeout=timeout_s + 60, blocking_timeout=timeout_s, sleep=0.05
    )
    if not lock.acquire():
        raise TimeoutError("Timed out waiting for GRAPH.COPY")
    try:
        backoff = 0.05
        while True:
            try:
                return g.copy(name)
            except ResponseError as exc:
                if "fork" not in str(exc).lower():
                    raise
                remaining = deadline - perf_counter()
                if remaining <= 0:
                    raise TimeoutError("Timed out retrying GRAPH.COPY after a fork conflict") from exc
                sleep(min(backoff, remaining))
                backoff = min(backoff * 2, 0.5)
    finally:
        lock.release()


def user_graph(uid: str | None = None) -> Graph:
    return graph(user_graph_name(settings().uid if uid is None else uid))


def policy_graph() -> Graph:
    return graph(POLICY_GRAPH)


def _plain(value: Any) -> Any:
    if isinstance(value, Node):
        return {"_labels": list(value.labels), **_plain(value.properties)}
    if isinstance(value, Edge):
        return {"_type": value.relation, **_plain(value.properties)}
    if isinstance(value, GraphPath):
        return {"nodes": _plain(value.nodes()), "edges": _plain(value.edges())}
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def run(
    g: Graph,
    name: str,
    params: dict[str, Any] | None = None,
    *,
    write: bool = False,
    timeout_ms: int = 10000,
    trace: Trace | None = None,
) -> QueryOutcome:
    queries = {path.stem: path for path in QUERY_DIR.glob("*.cypher")}
    cypher = queries[name].read_text()
    parameters = {} if params is None else params
    start = perf_counter()
    rows = []
    try:
        result = (g.query if write else g.ro_query)(cypher, parameters, timeout=timeout_ms)
        columns = [column[1] for column in result.header]
        rows = [dict(zip(columns, _plain(row), strict=True)) for row in result.result_set]
    except ResponseError as exc:
        if write or "Invalid graph operation on empty key" not in str(exc):
            raise
    finally:
        ms = (perf_counter() - start) * 1000
        if trace is not None:
            trace(name, parameters, ms, len(rows))
    return QueryOutcome(rows=rows, row_count=len(rows), ms=ms, query_name=name)


def execute_admin(g: Graph, cypher: str) -> None:
    """Execute one schema statement; application queries belong in the registry."""
    statement = cypher.strip().rstrip(";").strip()
    if ";" in statement or not re.match(
        r"^(?:(?:CREATE|DROP) INDEX\b|CALL db\.idx\.fulltext\.(?:createNodeIndex|drop)\s*\()",
        statement,
        re.IGNORECASE,
    ):
        raise ValueError("execute_admin accepts only index schema statements")
    g.query(statement)


def ensure_schema(g: Graph) -> None:
    for statement in Path(__file__).with_name("schema.cypher").read_text().split(";"):
        if not statement.strip():
            continue
        try:
            execute_admin(g, statement)
        except ResponseError as exc:
            if "already indexed" not in str(exc).lower():
                raise
