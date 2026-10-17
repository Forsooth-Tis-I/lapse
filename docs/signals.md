# Signals and policy replay

`lapse.signals.detectors.run_detectors(uid, *, now=None)` evaluates one tenant.
`now` accepts a date or datetime for reproducible checks. The optional `rdap_client`
accepts an httpx-compatible client. Every application query has a named Cypher file.

Signals use `(kind, root_id, deadline)` as their identity and link to their root with
`ABOUT`. A missing deadline has an empty internal `deadline_key`. Existing ingestion
signals with the same identity are adopted. Repeated runs update the message without
resetting the original timestamp or reopening dismissed signals.

Each new open signal offers **Show risk**, **Plan the fix**, and **Not mine**.
Notification delivery remains pending until `lapse.notify.notify` succeeds. Pending
delivery is retried even when a follow-up plan has already removed the detector trigger.
Counts describe outcomes **under the methods we model**. Unmodelled accounts are
**unknown, not safe**.

## Detector reference

| Detector | Trigger | Message |
| --- | --- | --- |
| `reissue_countdown` | Retiring or inactive phone with `reissue_after`. | "••4321 can be reissued to a stranger from DATE. N accounts still use it (M through other accounts)." N is full takeover reach; M excludes direct reach. |
| `closing_email` | Closing Email with `closes_at`. | "ADDRESS closes on DATE; you'd lose N accounts." N comes from the lockout scenario. |
| `domain_expiry` | Email with `email_kind=custom` and an address whose domain has an RDAP expiration event. | "DOMAIN expires on DATE; N accounts could be reached." The detector writes `expires_at` on the Email root and evaluates takeover. |
| `stale_root` | Inactive phone mentioned within 30 days, or active phone whose last evidence is at least 180 days old. | "Do you still have LABEL?" The message explains the evidence mismatch. |
| `new_device` | `new_device` evidence supports an account that uses an old `totp_device`. | "Did you move your authenticator app from LABEL?" Show risk opens a lockout scenario for that old device. |
| `missed_account` | Evidence mentions a root with a completed Change, but its supported account has no Change for that root. | "N missed accounts were added to follow-up plan PLAN." Unsupported accounts require manual review. |

The stale-root detector ignores future evidence. For a phone with no evidence,
`first_seen` can establish the 180-day interval; an unknown age does not establish it.
The new-device detector excludes the device mentioned by the sign-in evidence from
the old-device candidates. Without an identified old authenticator, it cannot offer
a valid old-device lockout scenario.

RDAP requests use `https://rdap.org/domain/DOMAIN`, follow redirects, and have a
five-second timeout. Domain extraction uses the bundled public-suffix list without
a network update. The earliest valid `expiration` event supplies the date. Network
errors and malformed responses skip domain expiry without stopping other detectors.

The missed-account detector uses the existing planner and the completed plan's
replacement root. A follow-up plan covers the root's outstanding uses. An account
needs a modeled contact-change procedure and a `USES` role for automatic planning;
`MENTIONS` alone does not establish which role to change. The detector does not
execute or approve changes.

## Policy-event reference

`apply_policy_event("x_sms_2fa_2023", *, dry_run=False)` loads
`lapse/signals/policy_events.yaml` and records the event in `lapse:policy`.
The event replays Twitter/X's March 20, 2023 SMS 2FA removal for non-subscribers.
Sources are the [original announcement](https://blog.x.com/en_us/topics/product/2023/an-update-on-two-factor-authentication-using-sms-on-twitter)
and [February 2023 announcement coverage](https://www.bleepingcomputer.com/news/security/twitter-gets-rid-of-sms-2fa-for-non-blue-members-what-you-need-to-do/).

The diff removes X method templates that need `sms_2fa`. Accounts marked
`x_blue_subscriber=true` are exempt. A missing subscription flag is treated as
non-subscriber for this replay; ingestion does not infer subscription eligibility.
The replay preserves observed `USES` edges and other factor requirements. It does
not invent a password-only fallback or simulate the service's complete migration flow.

For each `lapse:u:*` graph, replay recompiles the affected accounts and compares
takeover and lockout outcomes for every retiring or closing root. Comparisons use
account identities, including direct reach, unknown accounts, baseline access, and
remaining access. Scenario IDs and timings do not affect the comparison. A drop in
the lockout count can reflect loss of baseline access, so the notification asks the
user to review changed outcomes rather than declaring the account safe.

Only changed tenants receive notifications. Each tenant keeps pending policy
notification text until delivery succeeds. Replaying an already-applied event does
not produce another notification, but it retries pending delivery. If WP5's notifier
is absent, statistics report `notifications_unavailable` and the CLI prints that gap.

Dry runs evaluate disposable graph copies and delete them afterward. They do not
change tenant methods, write the shared event, or notify. A graph-copy failure is
reported; replay does not fall back to mutating and restoring the original graph.

The returned statistics are `tenants_scanned`, `tenants_changed`, `total_ms`,
`p95_tenant_ms`, `changed_uids`, and `notifications_unavailable`. The p95 is the
nearest-rank percentile of elapsed time across all scanned tenants, including
tenants without an affected account.

## Demo commands

```sh
uv sync
uv run python scripts/synth_tenants.py 200
uv run python scripts/policy_event.py --replay x_sms_2fa_2023 --dry-run
uv run python scripts/policy_event.py --replay x_sms_2fa_2023
uv run python scripts/synth_tenants.py --drop
```

The generator writes `lapse:u:synth_<i>` with `User.synthetic=true`, varied persona
services, and X accounts with different factor and subscription combinations.
Rerunning it resets those synthetic graphs to their pre-event state. Drop checks
both the synthetic namespace and the User label before deleting a graph.
Replay scans all tenant graphs, so its scanned count can exceed the generated count.

## Lead integration

- Register the `run_detectors` job by calling
  `lapse.signals.jobs.register_handlers()` after the worker registry exists.
- Schedule `lapse.signals.jobs.run_all_detectors()` at the worker's chosen interval,
  and provide WP5's `lapse.notify.notify(uid, text, buttons)`.
- Policy replay updates existing methods. Ingestion and planner compilation still
  reload the original policy YAML; those callers must apply persisted policy events
  during future recompilation to keep the replayed policy in force. WP9 does not
  modify those packages.

```sh
uv run pytest -q tests/test_signal_detectors.py tests/test_signal_jobs.py \
  tests/test_signal_policy_events.py tests/test_signal_synthetic.py
uv run pytest -q -m 'not db'
uv run ruff check .
```
