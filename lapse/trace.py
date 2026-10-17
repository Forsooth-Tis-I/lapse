from __future__ import annotations

import importlib
import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Literal
from uuid import uuid4

from lapse.contracts import ToolCallRecord
from lapse.graph import db

current_turn: ContextVar[str | None] = ContextVar("lapse_current_turn", default=None)
Outcome = Literal["path", "memory", "not_in_graph", "unknown_root", "ok", "error"]


def safe_text(text: str) -> str:
    if re.search(r"(?i)\b(?:password|otp|approval[ _]token|api[ _]key|secret|code)\b", text):
        return "[redacted sensitive input]"
    if re.fullmatch(r"\s*\d{4,8}\s*", text):
        return "[redacted]"
    return text


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[redacted]"
            if any(
                part in key.casefold() for part in ("token", "password", "otp", "code", "secret", "api_key")
            )
            else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return safe_text(value)
    return value


@dataclass
class ToolTrace:
    id: str
    at: datetime
    tool: str
    args: dict[str, Any]
    outcome: Outcome = "ok"
    queries: list[dict[str, Any]] = field(default_factory=list)
    ms: float = 0

    def __call__(self, query_name: str, params: dict[str, Any], ms: float, rows: int) -> None:
        self.queries.append({"query_name": query_name, "ms": ms, "rows": rows})

    @property
    def records(self) -> list[ToolCallRecord]:
        queries = self.queries or [{"query_name": None, "ms": self.ms, "rows": 0}]
        return [
            ToolCallRecord(
                id=f"{self.id}:{index}",
                at=self.at,
                tool=self.tool,
                args=self.args,
                outcome=self.outcome,
                **query,
            )
            for index, query in enumerate(queries)
        ]


@contextmanager
def tool_call(uid: str, tool: str, args: dict[str, Any]) -> Iterator[ToolTrace]:
    call = ToolTrace(f"tool_{uuid4().hex}", datetime.now(UTC), tool, redact(args))
    turn_id = current_turn.get()
    started = perf_counter()
    try:
        yield call
    except BaseException:
        call.outcome = "error"
        raise
    finally:
        call.ms = (perf_counter() - started) * 1000
        db.run(
            db.user_graph(uid),
            "wp4_trace_write",
            {
                "id": call.id,
                "at": call.at.isoformat(),
                "tool": call.tool,
                "args": json.dumps(call.args),
                "queries": json.dumps(call.queries),
                "ms": call.ms,
                "rows": sum(query["rows"] for query in call.queries),
                "query_name": call.queries[0]["query_name"] if len(call.queries) == 1 else None,
                "outcome": call.outcome,
                "turn_id": turn_id,
            },
            write=True,
        )
        try:
            events = importlib.import_module("lapse.events")
        except ModuleNotFoundError as exc:
            if exc.name != "lapse.events":
                raise
        else:
            for record in call.records:
                events.publish(uid, "trace", record.model_dump(mode="json"))


def list_trace(uid: str, since: datetime | str | None = None) -> list[ToolCallRecord]:
    if isinstance(since, str):
        since = datetime.fromisoformat(since)
    if since is not None:
        since = since.replace(tzinfo=UTC) if since.tzinfo is None else since.astimezone(UTC)
    rows = db.run(
        db.user_graph(uid),
        "wp4_trace_list",
        {"since": since.isoformat() if since is not None else None},
    ).rows
    records = []
    for row in rows:
        node = row["call"]
        call = ToolTrace(
            id=node["id"],
            at=datetime.fromisoformat(node["at"]),
            tool=node["tool"],
            args=json.loads(node["args_json"]),
            outcome=node["outcome"],
            queries=json.loads(node["queries_json"]),
            ms=node["ms"],
        )
        records.extend(call.records)
    return records
