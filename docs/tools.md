# MCP tool contract

These are the planned fixed tools from build-plan section 5. WP1 supplies graph reasoning, WP4 exposes tools, and executors handle approved actions. Foundation supplies the named-query runner. The graph functions and query files below exist; WP4 supplies the MCP handlers.

Arguments are resolved against the current user's graph before work starts. A missing root returns `unknown_root`; an absent account or an unmodelled account cannot produce a claim of safety. Service and account names in a generated answer must appear in that turn's tool results. Risk claims use "under the methods we model".

## Tools and query files

Every query filename in this table exists under `lapse/graph/queries/`. A tool may use several queries. Return models refer to [contracts.py](../lapse/contracts.py); descriptions marked proposed have no shared response model.

| Tool and arguments | Return | Query files |
| --- | --- | --- |
| `list_roots()` | `list[Root]`, including status, confirmed flag, and available deadline fields. | `view_roots.cypher` |
| `resolve(hint: str)` | Proposed matching root or account IDs and labels, with candidates for disambiguation when several match. | WP4 handler pending; no query registered. |
| `dependents(root_id: str, depth: 1 or "full")` | Proposed direct account IDs for depth 1, or a full takeover summary. Direct means a root alone suffices, not every account with a USES edge. | `scenario_context.cypher`, `scenario_accounts.cypher`, `closure_seeds.cypher`, `closure_round.cypher`; full depth also persists the scenario. |
| `takeover_if_reassigned(root_id: str)` | `ScenarioResult` for a stranger with that root and no password knowledge. | `scenario_context.cypher`, `scenario_accounts.cypher`, `scenario_disabled.cypher`, `closure_seeds.cypher`, `closure_round.cypher`, `write_scenario.cypher`, `write_reached.cypher`, `write_derivation.cypher` |
| `lockout_if_lost(root_id: str)` | `ScenarioResult` with `lost_now_accounts` for immediate loss and `recovery_lost_accounts` for loss of password-free recovery; `affected_accounts` is their union. Each tier excludes accounts already unreachable before the loss. | `scenario_context.cypher`, `scenario_accounts.cypher`, `scenario_disabled.cypher`, `closure_seeds.cypher`, `closure_round.cypher`, `write_scenario.cypher`, `write_reached.cypher`, `write_derivation.cypher` |
| `explain(account_id: str, scenario_id: str)` | `Explanation` with all required method branches and supporting evidence. Outcomes are `path` for takeover, `lost_now` for immediate lockout, and `recovery_lost` for recovery-only loss; `not_affected` and `not_in_graph` remain unchanged. | `get_scenario.cypher`, `scenario_account.cypher`, `explain.cypher`, `account_evidence.cypher` |
| `account_info(account_id: str)` | Proposed account, USES relationships, methods, and Evidence records, or an explicit unmodelled result. | `view_accounts.cypher`, `view_uses.cypher`, `view_methods.cypher`, `view_evidence.cypher` |
| `search_evidence(text: str)` | Proposed `list[Evidence]` with full-text matches from subjects and snippets. | `view_search_evidence.cypher` |
| `plan_retirement(old_root_id: str, new_root_id: str or null = null, deadline: date or null = null)` | `Plan` ordered by exposure removed, old-root requirement, and tier. | `planner_roots.cypher`, `planner_candidates.cypher`, `closure_round.cypher`, `planner_save_plan.cypher`, `planner_save_steps.cypher`, `planner_step_order.cypher` |
| `plan_status(plan_id: str)` | `Plan`, including current Change statuses. | `planner_get_plan.cypher`, `planner_list_plans.cypher` |
| `execute_change(change_id: str, approval_token: str)` | Proposed stream of `ExecStep` events. Requires a valid human-issued, single-use approval token. | `planner_get_change.cypher`, `planner_update_change.cypher`, `planner_repoint_use.cypher`, `planner_drop_use.cypher`; execution and action logging remain WP8-owned. |

Scenario reads use `get_scenario.cypher`. Persistence records timing through `scenario_timing.cypher` and retains the latest 20 scenarios through `scenario_old.cypher`, `scenario_prune_derivations.cypher`, and `scenario_prune.cypher`.

Planner simulations use FalkorDB `GRAPH.COPY` through the client graph-copy API. Each candidate changes a copy of the current sandbox and runs the same scenario evaluator. The planner deletes trial and working sandboxes, including when evaluation fails. `planner_compile_account.cypher`, `planner_compile_clear_methods.cypher`, `planner_compile_clear_enables.cypher`, and `planner_compile_enables.cypher` scope recompilation to one account. The helper reuses `compile_methods.cypher` and `compile_needs.cypher`, honors absent-role rules, and preserves observed methods. `planner_change_evidence.cypher` attaches completion evidence.

`graph_view` uses `view_roots.cypher`, `view_accounts.cypher`, `view_uses.cypher`, `view_methods.cypher`, `view_scenario.cypher`, and `view_derived.cypher`. It returns the web GraphData fields plus node `status`, `round`, `affected`, and `unknown`, and edge `derived` flags. Edges point from prerequisite to dependent. `stats` uses `graph_node_count.cypher`, `graph_edge_count.cypher`, and `view_label_counts.cypher`; `last_query_ms` is the final statistics query's elapsed time.

The scenario tools retain their section 5 single-root signatures. The underlying `ScenarioRequest` and REST API support compound `root_ids`. A future MCP extension for compound scenarios needs an explicit signature decision.

An execution token is minted by a human approval action, not by the LLM. The section 5 Telegram button is the original source; the web approval endpoint requires equivalent authorization. Tokens and OTP values must be removed from trace arguments. Invalid approval must prevent the external action.

## Outcomes

`ToolCallRecord.outcome` has these exact values:

| Value | Meaning |
| --- | --- |
| `path` | Answer backed by a graph derivation. |
| `memory` | Answer from previously stored graph evidence or state. |
| `not_in_graph` | The requested account is absent or its service has no model for the requested reasoning. Unknown is not safe. |
| `unknown_root` | No root matches the requested root ID. |
| `ok` | Successful operation without a path or memory answer. |
| `error` | The operation failed. |

There is no shared generic MCP response envelope yet. These are trace outcomes, not an invented `{outcome, data}` return type. `Explanation.outcome` separately permits `path`, `not_affected`, and `not_in_graph`; a valid but unaffected account must not be described as missing.

`ToolCallRecord` fields are `id`, `at`, `tool`, `args`, `query_name`, `ms`, `rows`, and `outcome`. The trace writer must decide how to associate multiple query records with one tool invocation; `query_name` is singular in the shared model.

## Foundation query interface

`graph(name)` selects a named graph using `settings()`. `user_graph(uid=None)` selects `lapse:u:<uid>` and defaults to the configured UID. `policy_graph()` selects `lapse:policy`. The local default connection is `localhost:6380`.

```python
run(g, name, params=None, *, write=False, timeout_ms=10000, trace=None) -> QueryOutcome
```

The runner loads `lapse/graph/queries/<name>.cypher` by file stem. Reads use `ro_query`; writes require `write=True`. Query text belongs in those files, never in LLM output. `execute_admin(g, cypher)` is reserved for schema and administrative statements. `ensure_schema(g)` applies the idempotent indexes.

`QueryOutcome` is a dataclass with `rows: list[dict]`, `row_count`, `ms`, and `query_name`. Column names become dictionary keys. Values become plain Python objects:

| FalkorDB value | Returned value |
| --- | --- |
| Node | `{"_labels": [...], **properties}` |
| Edge | `{"_type": relationship_type, **properties}` |
| Path | `{"nodes": [...], "edges": [...]}` using the same conversions |

A read on a never-written graph returns no rows when FalkorDB reports `Invalid graph operation on empty key`. This special case does not hide other query errors.

An optional `trace(query_name, params, ms, row_count)` callable receives metadata for every attempted query, including failures with zero returned rows. Query errors still propagate to the caller. This hook feeds the trace panel; the runner does not itself create `ToolCallRecord` IDs, tool names, or turn associations. Parameters must not contain secrets.

`ENABLES` queries are only a password-free lower bound on reachability. Full scenario answers use AND/OR closure, including password gating and mailbox methods. A query that follows each NEEDS edge independently cannot establish that a multi-need method succeeds.

Lockout recovery assumes the user can use inboxes that remain accessible with known passwords. It then tests
password-free methods for recovering other accounts. Losing a mailbox directly or through its host account
removes that recovery channel. Planner lockout exposure counts the union of both tiers against fixed before-loss
baselines, so deleting a recovery method cannot make a repair appear successful.
