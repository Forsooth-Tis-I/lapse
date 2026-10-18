# Verify the documentation claims

Run the checker against FalkorDB on the configured host and port. It does not need inbox credentials or an LLM call.

```sh
uv sync --extra browser
uv run python scripts/verify_claims.py
uv run python scripts/verify_claims.py --write
uv run python scripts/verify_claims.py --uid demo
```

By default, the checker loads the public fixture and current researched policies into a uniquely named disposable user graph. It calls the public scenario, planner, closure, and statistics functions. It deletes that graph afterward. It does not reload `lapse:u:demo` or `lapse:policy`.

`--uid` copies an existing user's graph before calculating results. The source graph's contacts, plans, and scenarios stay unchanged. That graph must contain the fixture root IDs used by this registry. Planning and copying can contend with other work on the same database.

The default file set is `README.md` plus every Markdown file under `docs/`. Pass explicit paths to limit it. Only marked claims are checked; an unmarked sentence is not automatically verified. Keep all new numerical demo claims inside markers.

A marker has the form `&lt;!-- claim:takeover_phone_old.full --&gt;value&lt;!-- /claim --&gt;`. Use the exact opening and closing syntax with ordinary angle brackets in the Markdown source. Repeated keys let the README, blog, and recording script share a fact. Unknown keys, nested or malformed markers, and mismatches exit nonzero. `--write` validates all files before replacing marked values.

## Registry

| Key | Current value | Source |
| --- | --- | --- |
| `takeover_phone_old.direct` | <!-- claim:takeover_phone_old.direct -->5<!-- /claim --> | Takeover result, direct account IDs. |
| `takeover_phone_old.full` | <!-- claim:takeover_phone_old.full -->10<!-- /claim --> | Takeover result, affected accounts. |
| `takeover_phone_old.unknown` | <!-- claim:takeover_phone_old.unknown -->1<!-- /claim --> | Takeover result, unknown accounts. |
| `lockout_email_college.full` | <!-- claim:lockout_email_college.full -->5<!-- /claim --> | College lockout result, affected accounts. |
| `lockout_email_college.lost_now` | <!-- claim:lockout_email_college.lost_now -->1<!-- /claim --> | Explicit immediate-loss tier, or legacy fresh-sign-in loss. |
| `lockout_email_college.recovery_lost` | <!-- claim:lockout_email_college.recovery_lost -->4<!-- /claim --> | Explicit recovery-loss tier; unavailable on older contracts. |
| `compound_lockout.full` | <!-- claim:compound_lockout.full -->15<!-- /claim --> | Lockout after losing both `phone_old` and `email_college`. |
| `compound_lockout.lost_now` | <!-- claim:compound_lockout.lost_now -->6<!-- /claim --> | Compound immediate-loss tier, or legacy fresh-sign-in loss. |
| `compound_lockout.recovery_lost` | <!-- claim:compound_lockout.recovery_lost -->14<!-- /claim --> | Compound recovery-loss tier; unavailable on older contracts. |
| `plan_phone_old.before` | <!-- claim:plan_phone_old.before -->11<!-- /claim --> | Plan exposure before replacing `phone_old` with `phone_new`. |
| `plan_phone_old.after` | <!-- claim:plan_phone_old.after -->0<!-- /claim --> | Projected exposure after the complete plan. |
| `plan_phone_old.steps` | <!-- claim:plan_phone_old.steps -->7<!-- /claim --> | Number of proposed changes, grouped by account. |
| `closure.ms` | <!-- claim:closure.ms -->0-20<!-- /claim --> ms | Median local closure time and its accepted range. |
| `queries.count` | <!-- claim:queries.count -->113<!-- /claim --> | Named files under `lapse/graph/queries/`. |
| `tools.count` | <!-- claim:tools.count -->14<!-- /claim --> | Registered MCP tools. |

The script also prints `graph.nodes`, `graph.edges`, `graph.accounts`, `graph.roots`, and `graph.methods` from `stats`, before it persists scenarios or a plan. Those totals depend on existing analytical history when using `--uid`; they are not published as stable demo claims. Optional test-count claims are not implemented. Test execution reports are the evidence for suite results.

The college adapter prefers explicit `lost_now_accounts` or `lost_now` and `recovery_lost_accounts` or `recovery_lost`. A missing recovery result renders `not reported`. It never substitutes zero or derives that number from the number of `USES` edges.

## Timing tolerance

`closure.ms` measures only the phone takeover closure, excluding fixture loading, plan generation, and scenario persistence. The checker takes the median of five runs. `--write` writes a range from zero to twice that median rounded up to a multiple of ten milliseconds, with a minimum upper bound of ten milliseconds. Check mode requires the measured median to fall inside the recorded range. It also accepts an existing scalar with 50% relative or one millisecond absolute tolerance.

The range absorbs local database scheduling noise. It is not a claim that every request meets that latency, and it is not a scale benchmark. Investigate a timing failure before widening the range.

## Query inventory

The checker regenerates the README table between its query-inventory markers. It sorts the actual `.cypher` filenames and joins them with `docs/query-descriptions.json`. Missing or extra descriptions fail the check, including in write mode. Add a reviewed description when a query is added, then run `--write`.

The inventory proves that the named files and descriptions correspond by name. It does not prove that every file is called on a particular user request. The `closure_round` and explain-path discussion identifies the main reasoning path.

## Integration pass

After merging the parallel lockout, LLM-client, worker, and demo-runner work, run `--write`, inspect the changed prose, and run the checker again. Update screenshot captures separately if their visible values change. Claim markers cannot rewrite numbers embedded in PNGs. The existing screenshot provenance is in [web verification](../web/docs/verification.md).
