# Internal Python interfaces (cross-package contract)

Work packages build in parallel against these signatures.
- Implement only the module you own.
- For anything owned by someone else, import it and fake it in your tests (monkeypatch). Do not create placeholder copies of another package's module; that causes merge conflicts.
- Types come from `lapse/contracts.py`.
- `uid` is the user id. Graph name is `lapse:u:<uid>`:
  - The fixture persona is `demo`.
  - Real ingestion writes `settings().uid`.
- Every function that runs Cypher accepts `trace=None` and passes it to `db.run(..., trace=trace)`.

## Graph core: `lapse/graph/` (WP1)

```python
# scenarios.py
run_scenario(uid, req: ScenarioRequest, *, trace=None) -> ScenarioResult
    # Persists (:Scenario), (:Scenario)-[:SEED]->(root), (:Scenario)-[:REACHED {round, via}]->(x), (x)-[:DERIVED {scenario, method, round}]->(need)
get_scenario(uid, scenario_id) -> ScenarioResult | None
explain(uid, scenario_id, account_id, *, trace=None) -> Explanation
direct_dependents(uid, root_id, *, trace=None) -> list[str]  # account ids; the depth-1 view

# planner.py
plan_for_root(uid, old_root, new_root=None, deadline=None, *, trace=None) -> Plan
    # kind: lockout if old_root is an email being closed or a device being lost; otherwise takeover
    # (phone being dropped, domain expiring). Phone exposure includes takeover union lockout.
    # deadline defaults to drop_at / closes_at / expires_at.
get_plan(uid, plan_id) -> Plan | None
list_plans(uid) -> list[Plan]
update_change(uid, change_id, *, status: ChangeStatus, note=None) -> Change
apply_change_done(uid, change_id, evidence_id=None, *, trace=None) -> Change
    # Repoints all listed roles old->new for that account, recompiles its policy methods, marks done.

# views.py
list_roots(uid) -> list[Root]
graph_view(uid, scenario_id=None) -> dict  # payload shape defined in web/src/api/README.md (GraphData)
account_detail(uid, account_id) -> dict  # {account, uses, methods, evidence}
search_evidence(uid, text, limit=10) -> list[Evidence]  # full-text index
stats(uid) -> dict  # {nodes, edges, by_label, last_query_ms}
```

## Policy and compile: `lapse/policy/` (WP0, extended in WP2r2)
```python
compile_user_graph(g, policies, account_ids=None, *, trace=None)  # honours MethodTemplate.requires_absent_roles
```

## Events, approvals, jobs, OTP: `lapse/events.py`, `lapse/approvals.py`, `lapse/jobs.py`, `lapse/otp.py` (WP5)
All four use Redis on the FalkorDB container (same host and port as the graph).

```python
events.publish(uid, type, data) -> None  # PUBLISH lapse:events:<uid> <GraphEvent json>
events.subscribe(uid) -> AsyncIterator[GraphEvent]
approvals.mint(uid, change_ids: list[str]) -> str  # single use, TTL 15 min, HMAC with APPROVAL_SIGNING_KEY
approvals.consume(uid, token) -> list[str]  # raises if invalid, expired or reused
jobs.enqueue(uid, kind: str, payload: dict) -> str  # XADD lapse:jobs; kinds: execute_change, ingest_run, run_detectors
jobs.consume(group="workers") -> Iterator[Job]
otp.submit(uid, change_id, code) -> None  # SET lapse:otp:<uid>:<change_id> EX 300; never persisted to the graph or logs
otp.wait(uid, change_id, timeout_s=300) -> str | None
```

## Worker: `lapse/worker.py` (WP5 creates the skeleton)
```python
@handler("execute_change")  # registered by lapse/exec (WP8)
@handler("ingest_run")      # registered by lapse/ingest (WP3b)
@handler("run_detectors")   # registered by lapse/signals (WP9)
run()  # imports the handler modules listed in HANDLER_MODULES and consumes jobs; also starts the scheduler
```

## Notifications: `lapse/notify.py` (WP5 creates it; the Telegram bot consumes it)
```python
notify(uid, text, buttons: list[dict] = []) -> None  # PUBLISH lapse:notify:<uid>
# button: {"label": str, "action": str, "payload": dict}
```

## Trace and agent: `lapse/trace.py`, `lapse/agent/` (WP4)
```python
trace.tool_call(uid, tool, args) -> contextmanager yielding a db trace callback
    # On exit: writes a (:ToolCall) node and publishes a "trace" event.
trace.list_trace(uid, since=None) -> list[ToolCallRecord]
agent.respond(uid, text, *, channel="telegram") -> AgentReply
    # AgentReply = {text: str, buttons: list[button], tool_calls: list[str]}
agent_actions = {
  "approve_changes": {"change_ids": [...]},
  "plan_root": {"root_id"},
  "open_web": {"path"},
  "confirm_use": {"account_id", "root_id", "role", "value": bool},
  "dismiss_signal": {"signal_id"},
}
mcp_server.run()  # FastMCP exposing the tools in docs/tools.md
```

## Ingest writer and onboarding: `lapse/ingest/writer.py`, `lapse/onboarding.py` (WP3b)
```python
writer.write_events(uid, events: list[ExtractedEvent], *, trace=None) -> dict  # counts
onboarding.load_persona_local(uid, path="persona.local.yaml") -> dict  # writes User + roots; computes reissue_after
```

## Executors: `lapse/exec/` (WP8)
The `execute_change` handler runs the right tier and emits `ExecStep` events via `events.publish(uid, "exec", ...)`.

## Detectors: `lapse/signals/` (WP9)
`run_detectors(uid) -> list[Signal]`. It is registered as a job and scheduled in the worker.
