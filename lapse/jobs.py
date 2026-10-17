"""Redis stream jobs. Delivery is at least once; handlers must tolerate retries."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import lru_cache
from uuid import uuid4

from redis import Redis
from redis.exceptions import ResponseError

from lapse.config import settings

STREAM = "lapse:jobs"
MAX_ATTEMPTS = 3
RECLAIM_AFTER_MS = 300_000
_RENEW_LEASE = """
local pending = redis.call('XPENDING', KEYS[1], ARGV[1], ARGV[2], ARGV[2], 1)
if #pending == 0 or pending[1][2] ~= ARGV[3] then return 0 end
local claimed = redis.call('XCLAIM', KEYS[1], ARGV[1], ARGV[3], 0, ARGV[2], 'JUSTID')
return #claimed
"""


@lru_cache
def client() -> Redis:
    config = settings()
    return Redis(host=config.falkordb_host, port=config.falkordb_port, decode_responses=True)


@dataclass(frozen=True)
class Job:
    id: str
    uid: str
    kind: str
    payload: dict
    attempts: int = 1
    group: str = field(default="workers", repr=False)
    consumer: str = field(default="", repr=False)

    def renew_lease(self) -> bool:
        return bool(client().eval(_RENEW_LEASE, 1, STREAM, self.group, self.id, self.consumer))

    def ack(self) -> None:
        ack(self)

    def retry(self) -> str | None:
        return retry(self)


def _fields(uid: str, kind: str, payload: dict, attempts: int = 1) -> dict:
    return {"uid": uid, "kind": kind, "payload": json.dumps(payload), "attempts": attempts}


def enqueue(uid: str, kind: str, payload: dict) -> str:
    return client().xadd(STREAM, _fields(uid, kind, payload))


def ack(job: Job) -> None:
    client().xack(STREAM, job.group, job.id)


def retry(job: Job) -> str | None:
    exhausted = job.attempts >= MAX_ATTEMPTS
    with client().pipeline(transaction=True) as pipe:
        pipe.xadd(
            f"{STREAM}:failed" if exhausted else STREAM,
            _fields(job.uid, job.kind, job.payload, job.attempts + (not exhausted)),
        )
        pipe.xack(STREAM, job.group, job.id)
        result = pipe.execute()
    return None if exhausted else result[0]


def consume(group: str = "workers") -> Iterator[Job]:
    redis = client()
    try:
        redis.xgroup_create(STREAM, group, id="0", mkstream=True)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise
    consumer = uuid4().hex
    cursor = "0-0"
    while True:
        claimed = redis.xautoclaim(STREAM, group, consumer, RECLAIM_AFTER_MS, cursor, count=1)
        cursor, messages = claimed[:2]
        if not messages:
            batches = redis.xreadgroup(group, consumer, {STREAM: ">"}, count=1, block=1000)
            messages = batches[0][1] if batches else []
        for message_id, fields in messages:
            yield Job(
                id=message_id,
                uid=fields["uid"],
                kind=fields["kind"],
                payload=json.loads(fields["payload"]),
                attempts=int(fields.get("attempts", 1)),
                group=group,
                consumer=consumer,
            )
