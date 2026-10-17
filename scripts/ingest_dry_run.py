import argparse
import json
import sys
from pathlib import Path

from lapse.ingest.pipeline import PrefilterStats, iter_events


def main() -> None:
    parser = argparse.ArgumentParser(description="Print extracted inbox events as JSONL.")
    parser.add_argument("--live", action="store_true", help="Read configured IMAP inboxes")
    parser.add_argument("--no-llm", action="store_true", help="Use deterministic parsing only")
    parser.add_argument("--eml-dir", type=Path, help="Directory of synthetic .eml fixtures")
    parser.add_argument("--inboxes", nargs="+", default=["email_primary", "email_college"])
    args = parser.parse_args()
    stats = PrefilterStats()
    for event in iter_events(
        args.inboxes, live=args.live, eml_dir=args.eml_dir, use_llm=not args.no_llm, stats=stats
    ):
        print(event.model_dump_json())
    print(json.dumps(vars(stats)), file=sys.stderr)


if __name__ == "__main__":
    main()
