from collections.abc import AsyncIterator
from datetime import UTC, datetime

from redis.asyncio import Redis

from lapse import jobs
from lapse.config import settings
from lapse.contracts import GraphEvent


def async_client() -> Redis:
    config = settings()
    return Redis(host=config.falkordb_host, port=config.falkordb_port, decode_responses=True)


def publish(uid: str, type: str, data: dict) -> None:
    event = GraphEvent(type=type, uid=uid, at=datetime.now(UTC), data=data)
    jobs.client().publish(f"lapse:events:{uid}", event.model_dump_json())


async def subscribe(uid: str) -> AsyncIterator[GraphEvent]:
    redis = async_client()
    try:
        async with redis.pubsub() as pubsub:
            await pubsub.subscribe(f"lapse:events:{uid}")
            try:
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        yield GraphEvent.model_validate_json(message["data"])
            finally:
                await pubsub.unsubscribe(f"lapse:events:{uid}")
    finally:
        await redis.aclose()
