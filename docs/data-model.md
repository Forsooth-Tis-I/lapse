# Graph data model

This reference follows [the shared contracts](../lapse/contracts.py) and the final Decisions in [the build plan](BUILD_PLAN.md). Foundation writes policy, roots, accounts, methods, and fixture evidence. Graph core persists scenarios, derivations, plans, and changes. Execution, signal, and conversation records below describe other consumers of that foundation.

## Graphs and storage

`lapse:policy` holds shared service policies and carrier rules. `lapse:u:<uid>` holds one user's data. Policy compilation copies the information needed for reasoning into the user graph. Queries never cross graph boundaries.

Dates are ISO `YYYY-MM-DD` strings in FalkorDB. Datetimes use ISO 8601 strings. Lists contain scalar values. Optional properties may be absent. API models use Python dates, datetimes, and enums and serialize them as JSON strings. Internal FalkorDB node IDs are not application IDs.

`Root.kind` identifies `phone`, `email`, `domain`, or `device`. Email classification is `email_kind`; device classification is `device_kind`. Neither overwrites `kind`.

## User graph nodes

A question mark marks an optional property. Fields on later work-package records are the target contract, not a claim that foundation persists them.

| Labels | Properties |
| --- | --- |
| `User` | `uid`, `name?`, `tz?`, `telegram_chat_id?`. No shared Pydantic model yet. |
| `Root` | `id`, `kind`, `label`, `status`, `confirmed`. Every root also has its kind label below. |
| `Root:Phone` | `last4?`, `e164?`, `country?`, `carrier?`, `drop_at?`, `inactive_since?`, `reissue_after?`. Carrier is the carrier rule ID. |
| `Root:Email` | `address?`, `email_kind?` = `personal`, `edu`, `work`, or `custom`; `hosted_by_service?`, `closes_at?`. |
| `Root:Domain` | `name?`, `registrar?`, `expires_at?`. |
| `Root:Device` | `name?`, `device_kind?` = `phone`, `laptop`, or `key`. |
| `Service` | `id`, `name`, `domains`, `category?`, `modelled`, `doc_url?`. |
| `Account` | `id`, `service_id`, `display`, `identifier?`, `status` = `active` or `closed`, `modelled`, `first_seen?`, `last_seen?`. |
| `Method` | `id`, `account_id`, `kind`, `label`, `needs_password`, `source`, `doc_url?`; observed methods may add `confidence`. No shared instance model yet. |
| `Evidence` | `id`, `msg_id`, `inbox`, `date`, `sender`, `subject`, `snippet`, `event`. |
| `Signal` | `id`, `kind`, `root_id?`, `at`, `title`, `detail`, `deadline?`, `status` = `open`, `acted`, or `dismissed`. |
| `Scenario` | `id`, `kind`, `actor`, `root_ids`, `created_at`, `reached_count`, `ms`, `result_json`. The JSON string preserves the shared `ScenarioResult` summary. |
| `Plan` | `id`, `kind`, `old_root`, `new_root?`, `deadline?`, `feasible`, `exposure_before`, `exposure_after`, `created_at`. Steps are relationships. The plan's earlier `status` field is not in the shared model. |
| `Change` | `id`, `plan_id`, `order`, `account_id`, `account_label`, `role`, `from_root`, `to_root?`, `tier`, `requires_old_root`, `due?`, `exposure_removed`, `status`, `settings_url?`, `note?`. |
| `Action` | Planned `id`, `at`, `kind`, `result`, `detail`, `screenshot_url?`. No shared persistence model yet. |
| `ToolCall` | `id`, `at`, `tool`, `args_json`, `query_name?`, `ms`, `rows`, `outcome`. `args_json` stores the JSON encoding of `ToolCallRecord.args`. |
| `Turn` | Planned `id`, `at`, `role`, `text`. No shared model yet. |

Account `display` is `<Service> · <identifier>` when an identifier exists, otherwise the service name. Views, plan titles, and explanation paths use this label to distinguish accounts of the same service.

`RootStatus` permits `active`, `retiring`, `inactive`, `closing`, `closed`, `expired`, `sold`, `lost`, and `unknown`. Held statuses are `active`, `retiring`, and `closing`. A phone's `reissue_after` is its `drop_at` plus the carrier's `reissue_after_days`; the fixture's Vi date is 2027-01-29.

`Method.kind` is `login`, `reset`, `recover`, `mailbox`, or the planned domain `mx` method. Foundation emits `source='policy'`. The fixture compiler emits account methods and mailbox methods; it does not implement domain MX methods.

`Evidence.event` uses `EventKind`: `signup`, `verify_email`, `otp_sms_notice`, `otp_email`, `login_alert`, `new_device`, `twofa_enabled`, `twofa_disabled`, `contact_changed`, `password_reset`, `deactivation_notice`, `domain_expiry`, or `other`. Evidence retains message metadata and a snippet of at most 300 characters. It never retains full bodies, passwords, or OTP values.

`Signal.kind` is `reissue_countdown`, `closing_email`, `domain_expiry`, `stale_root`, `new_device`, `missed_account`, or `policy_event`. `Change.status` is `proposed`, `approved`, `running`, `awaiting_otp`, `awaiting_user`, `done`, `failed`, or `skipped`.

## User graph relationships

| Relationship | Properties and meaning |
| --- | --- |
| `(Account)-[:OF]->(Service)` | Associates an account with its service. |
| `(Account)-[:USES]->(Root)` | `role`, `confirmed`, `confidence`, `evidence_ids`. The fixture sets `confirmed=true`. |
| `(Method)-[:GRANTS]->(Account or Root)` | The target controlled after the method succeeds. Mailbox methods grant an Email root. Domain targets are planned. |
| `(Method)-[:NEEDS]->(Root or Account)` | `as` names the role. All need targets are required. A mailbox method needs its host account. |
| `(Root or Account)-[:ENABLES]->(Account or Root)` | Materialized only when a method has exactly one need and `needs_password=false`. |
| `(Evidence)-[:SUPPORTS]->(Account)` | Associates evidence with an account. |
| `(Evidence)-[:MENTIONS]->(Root)` | Associates evidence with a root. |
| `(Signal)-[:ABOUT]->(Root)` | The signal's affected root. |
| `(Scenario)-[:SEED]->(Root)` | Roots initially controlled by the actor. |
| `(Scenario)-[:REACHED]->(Account or Root)` | `round`, `via`; records the method that established control. |
| `(target)-[:DERIVED]->(need)` | `scenario`, `basis`, `method`, `method_label`, `round`; retains each prerequisite for an explanation. `basis` distinguishes actual `reached` derivations from lockout `baseline` and `recovery_baseline` derivations. |
| `(Plan)-[:HAS_STEP]->(Change)` | `order`; the ordered repair steps. |
| `(Change)-[:BEFORE]->(Change)` | Execution ordering. |
| `(Change)-[:FOR]->(Account)` | The account being changed. |
| `(Change)-[:LOGGED]->(Action)` | Execution audit records. |
| `(Turn)-[:ABOUT]->(Account or Root)` | Entities discussed in a turn. |
| `(ToolCall)-[:IN]->(Turn)` | The turn that invoked the tool. |

Persona YAML can declare dependencies that emails never reveal in `declared_uses`. Each entry names the `service`, an `account` email root, the dependency `role`, and the target `root`. After each ingest run, `onboarding.apply_declared_uses` matches the discovered service account by that email root's address. It writes the edge with `confirmed=true`, `confidence=1.0`, and `source='declared'`, then recompiles touched accounts. Undiscovered accounts are skipped until a later ingest run. Declarations do not create accounts.

`USES.role` is `login_email`, `recovery_email`, `login_phone`, `recovery_phone`, `sms_2fa`, or `totp_device`. `NEEDS.as` carries the corresponding role for a compiled account method.

## Policy graph

| Label | Properties |
| --- | --- |
| `Service` | All `Service` fields above, plus `verified_at?` from `ServicePolicy`. |
| `MethodTemplate` | `id` = `<service_id>:<template_id>`, `template_id` = the service-local YAML ID, `service_id`, `kind`, `label`, `needs_roles`, `needs_password`, `doc_url?`. |
| `ChangeProcedure` | `id` = `<service_id>:<root_kind>:<index>`, `service_id`, `root_kind`, `tier`, `requires`, `settings_url?`, `recipe?`, `confirmation_patterns`, `doc_url?`. |
| `Carrier` | `id`, `name`, `country`, `reissue_after_days`, `source_url`. |
| `PolicyEvent` | Planned `id`, `at`, `service_id`, `description`, `diff`. No shared model or foundation writer yet. |

`(Service)-[:HAS_METHOD]->(MethodTemplate)` and `(Service)-[:HAS_CHANGE]->(ChangeProcedure)` connect policy records. Carrier rules are independent nodes.

`ChangeProcedure.requires` permits `password`, `old_otp`, `new_otp`, `email_otp_old`, `email_otp_new`, and `in_person`. Tiers are 1 for automatic, 2 for browser execution with an OTP relay, 3 for an assisted settings link, and 4 for offline action. `recipe` replaces the earlier build-plan `api` field.

Policy YAML has top-level `services` and `carriers` lists. Each service entry has `service`, `methods`, `change`, and optional `verified_at`, matching `ServicePolicy`. Each carrier entry matches `CarrierRule`. Dates may be YAML dates or ISO strings. `load_policy_file(path)` returns `(list[ServicePolicy], list[CarrierRule])`.

`default_policy_paths()` selects the full `lapse/policy/services.yaml` and `lapse/policy/carriers.yaml` files when present, with `fixtures/policy.yaml` as the fallback. The fixture policy is a conservative demo subset, not the full policy research.

## Compilation and control semantics

`write_policy_graph(policies, carriers)` writes `lapse:policy`. `compile_user_graph(g, policies)` rebuilds Method nodes and ENABLES edges idempotently. Only active, modelled accounts receive service methods. A template with a missing role produces no method. Multiple roots for a role produce one method per combination of resolved roots.

Account method IDs are `m:<account_id>:<template_id>`, with a numeric suffix when combinations require separate IDs. Each method grants its account and needs the resolved roots. An Email root with `hosted_by_service` receives `m:mailbox:<email_id>` when its active host account has the same service ID and an identifier equal to its address. Closed email roots receive no mailbox method. The mailbox method needs the host Account, grants the Email root, and does not need a password itself.

Control is an OR across methods and an AND within each method. A node is controlled when it is a seed, or when at least one eligible granting method has every need controlled. Password methods are eligible for the user, who knows passwords, and never for a stranger. A method with zero needs must require a password. This permits the college host's password-only login without creating an unauthenticated entry point. An unseeded cycle alone cannot grant control.

A takeover scenario seeds the roots acquired by a stranger and gives that actor no passwords. Lockout means fresh sign-in after the user loses the requested roots. Its seeds are held possession roots, phones and devices, excluding those lost. The user knows passwords. Email roots are not implicit seeds: mailbox access must follow from the host account's methods. Loss of an Email root models closure of the whole hosting account: it disables the mailbox method and every method granting its host Account, including password-only login and alternate recovery methods. Compound scenarios use a list of root IDs.

`ENABLES` supports a sound lower bound for password-free reachability. It cannot represent an AND gate and does not replace closure. GitHub's fixture reset requires both `email_primary` and `device_phone`; email alone creates no ENABLES shortcut to GitHub.

Scenario claims are always qualified as "under the methods we model". Accounts with `modelled=false`, such as fixture Splitwise, have no compiled methods and are "unknown, not safe". In lockout results, `lost_now_accounts` contains accounts unreachable even with passwords. `recovery_lost_accounts` contains accounts that lose their password-free recovery route. Each list compares its own no-loss baseline with access after the loss, excluding accounts already unreachable in that tier. `affected_accounts` is their union, and `direct_accounts` is the subset attached directly to a lost root. The two tier lists can overlap and default to empty when reading older scenarios.

## How the closure works

`closure.py` repeatedly runs `closure_round.cypher` with the IDs already controlled, password knowledge, and disabled method IDs. FalkorDB checks every method's complete NEEDS set. A method succeeds only when all its needs were controlled before this round. Any eligible method may grant a target; zero-need methods require password knowledge.

Each round adds new targets until no target is gained. Methods sort by ID, so competing methods in the same earliest round produce one deterministic derivation. The result retains the target's round, selected method, and every need. An unseeded cycle never starts. The Python loop does not substitute ordinary graph reachability for the database's AND check.

Takeover seeds the acquired roots without passwords. For immediate lockout, compare closures with password knowledge before and after losing the requested roots. Mailbox methods granting a lost Email root and all methods granting its hosting Account are disabled after the loss. For recovery loss, run password-free closures from the possession roots and mailboxes available in each corresponding password-aware closure. This models forgetting an account password while retaining access to other inboxes. A password-only college mailbox therefore remains a recovery channel before closure; an inbox indirectly lost through a missing phone or second factor is unavailable afterward. Each tier reports only the difference between its before and after account sets.

SEED and REACHED describe the actor's actual closure. DERIVED edges with `basis='reached'` preserve its earliest derivations. Lockout also stores `basis='baseline'` and `basis='recovery_baseline'` derivations. `explain` uses the immediate-loss baseline for `outcome='lost_now'` or the recovery baseline for `outcome='recovery_lost'`, retaining every AND branch. An account in both tiers receives the immediate-loss explanation. Takeover retains `outcome='path'`. Steps run from prerequisites to account, ordered by round. Graph views use actual reached derivations, so a surviving account shows the route it retains. Evidence comes from SUPPORTS and MENTIONS on the path's nodes. Pruning removes all derivation sets with scenarios older than the latest 20.

Planner exposure uses this same evaluator in `GRAPH.COPY` sandboxes, serialized with the Redis lock
`lapse:lock:graph-copy` and bounded retry for fork conflicts. Phone plans count the union of takeover and lockout;
email/device plans count the union of both lockout tiers and domain plans count takeover. Both original
lockout baseline account sets remain fixed across changes.

For an email closure plan, the hosting account cannot migrate and is excluded from fixable exposure and change steps. It stays in `remaining_accounts` with the note "closes with the mailbox: save anything you need from it". Moving every migratable account can therefore reach `exposure_after=0` while the host remains listed.

An inactive phone is restored to the before-loss possession baseline. Removing an
account's only sign-in method cannot make a plan appear to repair that account. Plans persist both component
counts, exact remaining account IDs, unknown account IDs, and a note. Each Change groups an account's roles
on the old root in `roles`, retaining `role` for older consumers and `title` for display. Recompilation uses
`compile_user_graph(..., account_ids=[...], trace=...)` and preserves observed methods.

## Indexes

`ensure_schema(g)` applies [schema.cypher](../lapse/graph/schema.cypher) idempotently. Existing-index errors are ignored. Indexes cover `Account.id`, `Root.id`, `Phone.last4`, `Email.address`, `Service.id`, and `Evidence.msg_id`. The Evidence full-text index covers `subject` and `snippet`.
