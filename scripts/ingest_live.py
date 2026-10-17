import argparse
from pathlib import Path

from lapse.config import ROOT_DIR, settings
from lapse.ingest.jobs import handle_ingest_run


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest inbox evidence into the user graph.")
    parser.add_argument("--uid", default=settings().uid)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--eml-dir", type=Path, help="Read synthetic .eml files offline")
    source.add_argument("--live", action="store_true", help="Read configured IMAP inboxes")
    parser.add_argument("--no-llm", action="store_true", help="Use deterministic extraction only")
    parser.add_argument("--persona", dest="persona_path", type=Path, help="Persona YAML path")
    parser.add_argument("--limit", type=int, help="Maximum events to write")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 0:
        parser.error("--limit must be nonnegative")
    if args.persona_path is None:
        args.persona_path = ROOT_DIR / (
            "tests/fixtures/persona.test.yaml" if args.eml_dir else "persona.local.yaml"
        )
    counts = handle_ingest_run(args.uid, vars(args))
    llm_stats = counts.get("llm", {})
    print(
        f"LLM batches: {llm_stats.get('batches_succeeded', 0)}/"
        f"{llm_stats.get('batches_attempted', 0)} succeeded; "
        f"JSON parsed: {llm_stats.get('json_parsed', 0)}; "
        f"model fallback: {llm_stats.get('model_fallback_used', False)}"
    )
    print(f"Accounts: {counts['accounts']}")
    print(
        f"USES: {counts['uses']} (confirmed: {counts['confirmed_uses']}, inferred: {counts['inferred_uses']})"
    )
    print(f"Signals: {counts['signals']}")
    print(f"Unknown services: {counts['unknown_services']}")
    print("Accounts per service:")
    for service_id, count in sorted(counts["per_service"].items()):
        print(f"  {service_id}: {count}")


if __name__ == "__main__":
    main()
