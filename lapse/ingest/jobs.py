from itertools import islice
from pathlib import Path

from lapse.config import ROOT_DIR
from lapse.worker import handler


@handler("ingest_run")
def handle_ingest_run(uid: str, payload: dict) -> dict:
    from lapse.ingest.pipeline import iter_events
    from lapse.ingest.writer import write_events
    from lapse.onboarding import load_persona_local

    limit = payload.get("limit")
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 0):
        raise ValueError("limit must be a nonnegative integer")
    persona_path = Path(payload.get("persona_path", ROOT_DIR / "persona.local.yaml"))
    if persona_path.is_file():
        load_persona_local(uid, persona_path)
    extraction_stats = {}
    events = iter_events(
        payload.get("inboxes", ["email_primary", "email_college"]),
        uid=uid,
        extraction_stats=extraction_stats,
        live=payload.get("live", not bool(payload.get("eml_dir"))),
        eml_dir=payload.get("eml_dir"),
        use_llm=not payload.get("no_llm", False),
    )
    try:
        for event in islice(events, limit):
            write_events(uid, [event])
    finally:
        events.close()
    counts = write_events(uid, [])
    counts["llm"] = extraction_stats
    return counts
