from __future__ import annotations

import argparse

from lapse.signals.policy_events import apply_policy_event


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay a policy event across all tenant graphs.")
    parser.add_argument("--replay", required=True)
    parser.add_argument(
        "--dry-run", action="store_true", help="Evaluate isolated copies; do not write or notify."
    )
    args = parser.parse_args()
    stats = apply_policy_event(args.replay, dry_run=args.dry_run)
    print(f"Event: {stats['event_id']} | dry run: {stats['dry_run']}")
    print("Tenants scanned | Tenants changed | Total ms | p95 per tenant ms")
    print(
        f"{stats['tenants_scanned']:15d} | {stats['tenants_changed']:15d} | "
        f"{stats['total_ms']:8.2f} | {stats['p95_tenant_ms']:17.2f}"
    )
    if stats["notifications_unavailable"]:
        print(
            f"Notifications unavailable: {stats['notifications_unavailable']} (lapse.notify is not installed)"
        )


if __name__ == "__main__":
    main()
