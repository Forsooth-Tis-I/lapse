# REST and SSE contract

`lapse.api.main:app` serves the API under `/api`. Run it with `uv run uvicorn lapse.api.main:app --port 8000`.
The web boundary in [web/src/api/README.md](../web/src/api/README.md) defines the response shapes.
Shared graph models come from [lapse/contracts.py](../lapse/contracts.py).

Dates use `YYYY-MM-DD`. Datetimes use ISO 8601 with a timezone. Enums use lowercase strings.
The default user is `settings().uid`, configured with `LAPSE_UID`. `X-Lapse-Uid` overrides it per request.
This header selects a tenant for local demos; it is not authentication. The current web client uses the default user,
including its EventSource connection. CORS permits `http://localhost:5173` and `http://localhost:5174`, GET and POST, and the
`Content-Type` and `X-Lapse-Uid` headers.

## Routes

Successful requests return HTTP 200. Unknown IDs return 404 with a `detail` message. Invalid requests return 422.
Validation errors omit submitted values, including OTPs and inbox credentials. Missing graph, agent, onboarding,
or trace implementations return 503. Missing tracing alone does not prevent other graph routes from running.
Redis connection failures return 503.

| Route | Request | Response |
| --- | --- | --- |
| `GET /api/roots` | None | `Root[]` |
| `GET /api/graph?scenario=<id>` | Optional stored scenario ID | `GraphData` |
| `POST /api/scenarios` | `{kind, root_ids}`; kind is `takeover` or `lockout`, with at least one root | `ScenarioResult` |
| `GET /api/scenarios/{id}` | Scenario ID | `ScenarioResult` |
| `GET /api/scenarios/{id}/explain/{account_id}` | Scenario and account IDs | `Explanation`; absent accounts return 404 |
| `POST /api/plans` | `{old_root, new_root?, deadline?}` | `Plan`; graph planner infers the scenario kind |
| `GET /api/plans` | None | `Plan[]` |
| `GET /api/plans/{id}` | Plan ID | `Plan` |
| `POST /api/changes/{id}/approve` | `{}` | `Change`; marks it approved and queues `execute_change` with `{change_id}` |
| `POST /api/changes/{id}/otp` | `{code}`; nonempty string, at most 128 characters | Current `Change`; stores code transiently without changing status |
| `GET /api/trace?since=<timestamp>` | Optional ISO datetime | `ToolCallRecord[]` |
| `GET /api/agent/screen` | None | `{url: string|null, caption: string, mock: false}` |
| `GET /api/screens/{uid}/{name}` | Tenant and screenshot basename | Image from the selected tenant’s `data/screens/{uid}` directory; PNG, JPEG, WebP, or GIF |
| `GET /api/screens/{name}` | Legacy screenshot basename | Same selected-tenant restriction |
| `GET /api/stats` | None | `{nodes: integer, edges: integer, last_query_ms: number}` |
| `POST /api/onboarding` | Inbox and persona fields below | `{telegram_code, telegram_url}` |
| `POST /api/ingest/run` | `{}` or `{inboxes: string[]}` of Email root IDs | `{started: true}` after queuing `ingest_run` |
| `POST /api/chat` | `{text}`; nonempty string | Agent reply `{text, buttons, tool_calls, diagnostics}` with channel `web` |
| `GET /api/events` | None | SSE stream of complete `GraphEvent` envelopes |

`LAPSE_DEMO_MODE=true` rejects approval, OTP, onboarding, ingestion, and chat with HTTP 403 and a friendly
read-only message. Scenario and plan computation remain available for exploration. Those graph operations may
persist their results; demo mode prevents account and ingestion actions, not analytical result storage.

Every API graph invocation runs inside `lapse.trace.tool_call` when available. The API forwards the trace callback
to functions that declare a `trace` parameter. Trace arguments omit OTPs, inbox credentials, and chat text.

## Graph and risk results

```ts
type GraphData = {
  nodes: {
    id: string;
    label: string;
    node_type: 'Root' | 'Account';
    root?: Root;
    account?: Account;
  }[];
  edges: {
    id: string;
    source: string;
    target: string;
    label: string;
    confirmed: boolean;
    method_id?: string;
  }[];
};
```

This replaces the earlier proposed `labels` and `data` graph envelope. Graph methods own dependency direction,
mailbox bridges, and scenario filtering. The API does not recompute graph semantics.

`ScenarioRequest.root_ids` supports compound scenarios. Takeover reports accounts the stranger can control.
Lockout reports loss of fresh sign-in or password-free recovery. These conclusions hold **under the methods
we model**. Unmodelled services remain **unknown, not safe**.

Lockout `ScenarioResult` adds `lost_now_accounts: Reached[]` and `recovery_lost_accounts: Reached[]`, both
optional on older stored results and defaulting to `[]`. The first lists accounts lost even with passwords;
the second lists accounts whose password-free recovery route disappears. Before and after comparisons use
inboxes accessible in the corresponding password-aware closure as recovery channels. Accounts already
unreachable in a tier are excluded. `affected_accounts` is the union, not the sum, and `direct_accounts`
contains affected accounts directly attached to a lost root. Takeover leaves both tier lists empty.

`Explanation` includes `scenario_id`, `account_id`, `outcome`, and ordered `steps`. Lockout paths use outcome
`lost_now` or `recovery_lost`; if both apply, `lost_now` wins. Takeover retains `path`. Other outcomes remain
`not_affected` and `not_in_graph`. Each `PathStep` can include
evidence. `Plan.steps` contains `Change` objects in execution order. A plan has no `status` field.
Approval retries can enqueue an already-approved change after a queue failure. Running, waiting, completed, and
skipped changes are returned unchanged. Queue delivery is at least once.

Phone plans count the union of stranger-reachable accounts and both user lockout tiers after dropping the
phone. Email and device plans measure the union of both lockout tiers; domain plans measure takeover. `kind` remains the primary
scenario for compatibility. `exposure_before` and `exposure_after` count distinct accounts, so overlapping
components must not be added. Both original lockout baselines stay fixed across all hypothetical changes.
For an inactive phone, that baseline includes possession of the old phone before it was lost.

Additive plan fields are `takeover_before`, `takeover_after`, `lockout_before`, `lockout_after`,
`remaining_accounts`, `unknown_accounts`, and `note`. Component counts default to zero when reading older plans
that did not record them. `note` names any residual exposure; unknown services remain unknown even at zero
modelled exposure. `Change.roles` groups every role on the account's old root into one step. `role` remains the
primary role for compatibility, and `title` describes the grouped action. Older stored changes without `roles`
retain their original single-role scope. Missing procedures produce tier-3 manual steps and a settings/help link
when known. Unmodelled services produce tier-3 steps marked "unknown, not safe". Policy
`ChangeProcedure.settings_note` supplies manual instructions through `Change.note`.

Chat diagnostics contain `llm_tool_calls`, `llm_requests`, `fallback_used`, `guard_regenerated`, and optional
`fallback_reason`. Shared provider diagnostics add `llm_attempts` and `model_fallback_used`;
the latter records ordered model failover separately from deterministic agent fallback. The reason is an exception class, never a provider response body or credential. `tool_calls`
includes both model and fallback calls. `guard_regenerated` records an attempted single grounding rewrite.
Chat awaits the agent inside the API trace context. Saying "approve" retrieves the plan and offers a human
approval button; it does not enqueue execution.

Change statuses are `proposed`, `approved`, `running`, `awaiting_otp`, `awaiting_user`, `done`, `failed`, and `skipped`.

## Onboarding and inbox storage

The existing web request is accepted unchanged:

```json
{
  "inboxes": [{"host": "imap.example.com", "username": "demo@example.com", "app_password": "example-only"}],
  "phones": [{"number": "+910000004321", "carrier": "Vi", "status": "retiring", "drop_at": "2026-10-31"}]
}
```

Both lists default to empty. The API also accepts `display_name`, `emails`, and `devices` in the shape of
[persona.local.example.yaml](../persona.local.example.yaml). Phone entries can include `id` and `country`.
Phone `number` becomes `e164`; omitted IDs are stable hashes of the number. `country` defaults to `IN`.
Email fields are `id`, `address`, `kind?`, `hosted_by?`, `status?`, and `closes_at?`.
Device fields are `id`, `name`, `kind`, and `status?`.

The API passes a temporary, credential-free persona YAML file to `lapse.onboarding.load_persona_local` and deletes
it after the call. It does not infer college status, a closure date, or a hosted mailbox service from inbox order.

When inboxes are supplied, `LAPSE_SECRET_KEY` must be a valid Fernet key. The entire JSON object
`{uid: [{host, username, app_password}]}` is Fernet-encrypted into `data/inboxes.enc`, with file mode 0600.
Updates preserve other users, use a file lock, and replace the ciphertext atomically. An empty inbox list leaves
stored credentials unchanged. Credentials never appear in responses or trace arguments.
Ingestion reads this encrypted store first, scoped to the job's user. It matches the requested Email root's
address to a stored inbox username, ignoring case and surrounding spaces. No matching stored inbox falls back
to environment settings. Invalid ciphertext or an invalid key fails explicitly. The job handler is registered
as `ingest_run` and passes its user ID through pipeline and IMAP settings.

Inbox credentials alone do not create Email roots. For the example above, also provide
`"emails": [{"id": "email_primary", "address": "demo@example.com", "kind": "personal"}]`, or create that root
before ingestion. The default job scans `email_primary` and `email_college`; configure roots and credentials
for both or POST an explicit nonempty `inboxes` list of Email root IDs to `/api/ingest/run`. The web form
reuses matching email metadata or creates a personal Email root for supplied credentials, then queues that
root ID. Inbox order does not assign primary or college semantics.

The response uses `https://t.me/<bot>?start=<code>`. `TELEGRAM_BOT_USERNAME` defaults to `LapseAlfredBot`.
The code is stored in `lapse:tglink:<code>` for one hour. Binding consumes it once and maintains both user-to-chat
and chat-to-user mappings, removing stale links when rebinding.

## Events and screenshots

Redis publishes JSON on `lapse:events:<uid>`. Each SSE frame names the type and includes the **whole envelope**:

```text
event: graph
data: {"type":"graph","uid":"demo","at":"2026-10-17T10:00:00Z","data":{"nodes":42,"edges":63,"last_query_ms":1.2}}

```

The event types are `ingest`, `graph`, `scenario`, `plan`, `exec`, `signal`, `trace`, and `chat`.
Payloads follow the web decoder:

- `scenario`: `ScenarioResult`.
- `plan`: `Plan`.
- `exec`: `ExecStep`.
- `signal`: `Signal`.
- `trace`: `ToolCallRecord`.
- `ingest`: `{emails_scanned, accounts_found, edges_inferred, edges_confirmed, status}`, with status `idle`, `running`, or `done`.
- `graph`: graph stats when present, otherwise a graph-change notification.
- `chat`: agent-specific data, preserved by the web decoder.

SSE emits heartbeat comments through `sse-starlette`. Redis pub/sub has no replay or event cursor; clients must
re-fetch current state after reconnecting. Disconnect closes the subscription and Redis connection.

`GET /api/agent/screen` reads the latest image path from `lapse:screen:<uid>` and returns an absolute API URL, so
images resolve from the frontend origin. Without a path, `url` is null. Screenshot serving rejects path escapes,
symlinks outside the selected user’s directory, missing files, and unsupported extensions. Both screenshot
routes confine files to `data/screens/<selected uid>`. A URL’s uid must match the selected uid. The local tenant
header remains a selector, not authentication.

## Platform interfaces

All Redis connections use the FalkorDB host and port from settings, defaulting to `localhost:6380`.
All platform keys and channels begin with `lapse:`.

- `approvals.mint(uid, change_ids)` signs a random nonce with HMAC-SHA256 and `APPROVAL_SIGNING_KEY`.
  `consume(uid, token)` verifies the signature and tenant, then atomically consumes the stored change IDs.
  Tokens expire after 900 seconds and cannot be reused.
- `otp.submit(uid, change_id, code)` stores `lapse:otp:<uid>:<change_id>` for 300 seconds.
  `otp.wait` atomically consumes the code or returns null after its timeout. Codes are never logged or sent to graph storage.
- `notify.notify(uid, text, buttons)` publishes `{text, buttons}` on `lapse:notify:<uid>`.
  Each button contains `label`, `action`, and `payload`.
- `jobs.enqueue(uid, kind, payload)` appends to `lapse:jobs`. `jobs.consume(group="workers")` yields
  `Job(id, uid, kind, payload, attempts)` with `ack()` and `retry()`.
  Failed attempts atomically enqueue a retry and acknowledge the original. After three handled attempts, the job is
  retained in `lapse:jobs:failed`. Pending jobs idle for five minutes are reclaimed after a worker stops.
  Active handlers renew their leases every 100 seconds, with an atomic ownership check.
  Crash redelivery preserves the handled-attempt counter. Delivery is at least once; handlers must tolerate retry.

`python -m lapse.worker` loads `lapse.exec.jobs`, `lapse.ingest.jobs`, and `lapse.signals.jobs` by default.
`HANDLER_MODULES` can override this with a comma-separated module list. Missing modules produce warnings.
A missing dependency inside an installed handler module remains an error. Register handlers with
`@lapse.worker.handler(kind)`; callbacks accept `(uid, payload)`.
Callbacks may be synchronous or asynchronous; the worker awaits asynchronous handlers before acknowledging jobs.
After every successful `ingest_run`, it verifies pending changes. APScheduler queues `run_detectors` and
`verify_pending` for every tenant every five minutes and checks T4 reminders every minute.
