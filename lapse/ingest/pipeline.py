from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from lapse.config import ROOT_DIR
from lapse.contracts import ExtractedEvent
from lapse.ingest.extract import BatchExtractor
from lapse.ingest.imap import RawEmail, fetch_emails, parse_email
from lapse.ingest.prefilter import load_services, prefilter
from lapse.ingest.settings import DATA_DIR


@dataclass
class PrefilterStats:
    fetched: int = 0
    kept: int = 0
    dropped_by_reason: Counter[str] = field(default_factory=Counter)


def iter_events(
    inboxes: Iterable[str],
    live: bool = True,
    eml_dir: Path | str | None = None,
    *,
    uid: str | None = None,
    use_llm: bool = True,
    client: Any = None,
    stats: PrefilterStats | None = None,
    extraction_stats: dict | None = None,
    cache_path: Path = DATA_DIR / "extract_cache.json",
    state_path: Path = DATA_DIR / "ingest_state.json",
) -> Iterator[ExtractedEvent]:
    """Yield extracted events; consume to exhaustion to acknowledge a live inbox scan."""
    inboxes = list(dict.fromkeys(inboxes))
    if not inboxes:
        return
    services = load_services()
    stats = stats if stats is not None else PrefilterStats()
    extractor = BatchExtractor(client=client, use_llm=use_llm, cache_path=cache_path, services=services)

    if extraction_stats is not None:
        extraction_stats.update(extractor.diagnostics)
        extractor.diagnostics = extraction_stats

    def kept(messages):
        for email in messages:
            stats.fetched += 1
            keep, reason = prefilter(email, services)
            if keep:
                stats.kept += 1
                yield email
            else:
                stats.dropped_by_reason[reason] += 1

    if live:
        for inbox in inboxes:
            with fetch_emails(inbox, uid=uid, state_path=state_path) as messages:
                yield from extractor.extract(kept(messages))
    else:
        directory = Path(eml_dir) if eml_dir is not None else ROOT_DIR / "tests/fixtures/emails"

        def messages() -> Iterator[RawEmail]:
            for path in sorted(directory.glob("*.eml")):
                email = parse_email(path.read_bytes(), inboxes[0])
                if "email_college" in inboxes and "@example.edu" in email.to.lower():
                    email = replace(email, inbox="email_college")
                yield email

        yield from extractor.extract(kept(messages()))
