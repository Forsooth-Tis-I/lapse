from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from lapse.graph import db
from lapse.trace import safe_text


def history(uid):
    rows = db.run(db.user_graph(uid), "wp4_turn_history").rows
    return [
        {**row["turn"], "context": json.loads(row["turn"].get("context_json", "{}"))}
        for row in reversed(rows)
    ]


def save_turn(uid, role, text, channel, entity_ids=(), context=None):
    turn_id = f"turn_{uuid4().hex}"
    db.run(
        db.user_graph(uid),
        "wp4_turn_write",
        {
            "id": turn_id,
            "role": role,
            "text": safe_text(text),
            "channel": channel,
            "at": datetime.now(UTC).isoformat(),
            "context": json.dumps(context or {}),
        },
        write=True,
    )
    link_turn(uid, turn_id, entity_ids)
    return turn_id


def link_turn(uid, turn_id, entity_ids):
    if entity_ids:
        db.run(
            db.user_graph(uid), "wp4_turn_about", {"id": turn_id, "entities": list(entity_ids)}, write=True
        )
