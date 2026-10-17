# REST and SSE contract

This is the interface target for WP5, based on build-plan section 11.1. Foundation supplies [shared models](../lapse/contracts.py), not HTTP handlers. Model names below refer to that file. Envelopes marked proposed do not yet have shared models and must be agreed when WP5 implements them.

JSON dates use `YYYY-MM-DD`; datetimes use ISO 8601. Enum values are lowercase strings. User identity comes from the server session, not a request-supplied graph name. Demo mode is read-only. The plan calls for human approval before external account changes; OTP values are transient and must never enter logs, trace arguments, or graph properties.

## Routes

| Route | Request | Response |
| --- | --- | --- |
| `GET /api/graph?scenario=<id>` | Optional scenario filter. | Proposed graph envelope below. |
| `GET /api/roots` | None. | `list[Root]`. |
| `POST /api/scenarios` | `ScenarioRequest`. Uses `root_ids`, not the earlier plan's singular `root_id`. | `ScenarioResult`. |
| `GET /api/scenarios/{id}` | Scenario ID. | `ScenarioResult`. |
| `GET /api/scenarios/{id}/explain/{account_id}` | Scenario and account IDs. | `Explanation`. |
| `POST /api/plans` | Proposed `{old_root, new_root?, deadline?}`. | `Plan`. |
| `GET /api/plans/{id}` | Plan ID. | `Plan`. |
| `POST /api/changes/{id}/approve` | Human approval action; request model and session binding are unresolved. | Proposed `Change` after approval. |
| `POST /api/changes/{id}/otp` | Proposed `{code: string}`. | Proposed `{accepted: boolean}`. Never echoes the code. |
| `GET /api/trace?since=<timestamp>` | Optional ISO datetime cursor. | `list[ToolCallRecord]`; cursor and pagination semantics remain to be defined. |
| `GET /api/agent/screen` | None. | Proposed latest screenshot `ExecStep`, or `null`. |
| `GET /api/events` | SSE subscription for the current user. | `GraphEvent` frames described below. |
| `POST /api/ingest/run` | Proposed empty body. | Proposed `{accepted: boolean}`; progress arrives through SSE. |
| `POST /api/onboarding` | IMAP connection settings, declared roots, and Telegram linking details. No shared request model yet. | No shared response model yet. |
| `GET /api/stats` | None. | Proposed `{node_count, edge_count, last_query_ms}`. |

HTTP status codes, error envelopes, authentication details, approval-token transport, and onboarding credential fields remain WP5 decisions. This reference does not claim implemented behavior for them.

## Graph and roots

The proposed visualization envelope uses string application IDs and retains node properties in `data`. Edges carry their type, endpoints, and properties. Scenario styling is an API concern; no shared graph DTO exists yet.

```json
{
  "nodes": [
    {"id": "phone_old", "labels": ["Root", "Phone"], "data": {"kind": "phone", "label": "••4321 (Vi)", "status": "retiring"}},
    {"id": "google", "labels": ["Account"], "data": {"service_id": "google", "display": "Google", "modelled": true}}
  ],
  "edges": [
    {"source": "google", "target": "phone_old", "type": "USES", "data": {"role": "recovery_phone", "confirmed": true}}
  ]
}
```

A `Root` response can omit optional null fields. This example is valid as a `Root`:

```json
{
  "id": "phone_old",
  "kind": "phone",
  "label": "••4321 (Vi)",
  "status": "retiring",
  "confirmed": true,
  "last4": "4321",
  "country": "IN",
  "carrier": "vi_in",
  "drop_at": "2026-10-31",
  "reissue_after": "2027-01-29"
}
```

## Scenarios and explanations

`ScenarioRequest` supports one or more acquired or lost roots:

```json
{"kind": "takeover", "root_ids": ["phone_old"]}
```

The following `ScenarioResult` illustrates the response shape with a single-account graph. Its counts are not fixture acceptance values. Production counts come from graph computation.

```json
{
  "id": "scenario_example",
  "kind": "takeover",
  "root_ids": ["phone_old"],
  "actor": "stranger",
  "rounds": 1,
  "affected_accounts": [{"node_id": "google", "label": "Google", "node_type": "Account", "round": 1, "via_method": "m:google:reset_recovery_phone"}],
  "direct_accounts": ["google"],
  "unknown_accounts": [],
  "total_accounts": 1,
  "ms": 2.4
}
```

For takeover, `affected_accounts` contains accounts the stranger can control. For lockout, it contains accounts the user cannot reach through fresh sign-in. Lockout seeds held phones and devices except the lost roots, with password knowledge. Mailboxes must be reached through host-account methods. Unknown accounts are "unknown, not safe"; every risk statement is "under the methods we model".

An `Explanation` with a path contains ordered `PathStep` records. Each step may include `Evidence` records. All prerequisites of an AND method must remain visible in the explanation.

```json
{
  "scenario_id": "scenario_example",
  "account_id": "google",
  "outcome": "path",
  "steps": [{"from_id": "phone_old", "from_label": "••4321 (Vi)", "to_id": "google", "to_label": "Google", "method_id": "m:google:reset_recovery_phone", "method_label": "Reset with recovery phone", "round": 1, "evidence": []}]
}
```

`Explanation.outcome` is `path`, `not_affected`, or `not_in_graph`. It is distinct from the trace outcome enum.

## Plans and execution

The proposed plan request uses the field names from section 11.1:

```json
{"old_root": "phone_old", "new_root": "phone_new", "deadline": "2026-10-31"}
```

A valid `Plan` response contains `Change` objects in execution order. This illustrative one-step plan does not assert fixture exposure counts:

```json
{
  "id": "plan_example",
  "kind": "takeover",
  "old_root": "phone_old",
  "new_root": "phone_new",
  "deadline": "2026-10-31",
  "feasible": true,
  "exposure_before": 1,
  "exposure_after": 0,
  "created_at": "2026-10-17T10:00:00Z",
  "steps": [{"id": "change_example", "plan_id": "plan_example", "order": 1, "account_id": "google", "account_label": "Google", "role": "recovery_phone", "from_root": "phone_old", "to_root": "phone_new", "tier": 3, "requires_old_root": false, "due": "2026-10-31", "exposure_removed": 1, "status": "proposed", "settings_url": "https://myaccount.google.com/signinoptions/rescuephone", "note": null}]
}
```

The shared `Plan` does not have a `status` field. `Change.status` is `proposed`, `approved`, `running`, `awaiting_otp`, `awaiting_user`, `done`, `failed`, or `skipped`. Progress uses `ExecStep.kind`: `progress`, `screenshot`, `need_otp`, `need_user`, `done`, or `failed`.

The plan request lacks a `kind` field although `Plan` requires one. WP5 and WP1 must agree whether to infer it or add a shared request model; foundation does not change `contracts.py`.

## Trace and SSE

A `ToolCallRecord` captures query timing and row count:

```json
{"id": "trace_example", "at": "2026-10-17T10:00:00Z", "tool": "list_roots", "args": {}, "query_name": "list_roots", "ms": 1.2, "rows": 5, "outcome": "ok"}
```

`GET /api/events` streams events published on Redis channel `lapse:events:<uid>`. The shared envelope is `GraphEvent`, with `type`, `uid`, `at`, and a `data` object. Event types are `ingest`, `graph`, `scenario`, `plan`, `exec`, `signal`, `trace`, and `chat`. The proposed SSE framing uses `event: <type>` and one JSON `GraphEvent` in `data:`:

```text
event: exec
data: {"type":"exec","uid":"demo","at":"2026-10-17T10:00:00Z","data":{"change_id":"change_example","kind":"need_user","message":"Update the recovery phone in settings.","channel":null,"url":"https://myaccount.google.com/signinoptions/rescuephone","at":"2026-10-17T10:00:00Z"}}

```

The proposed event payload mapping is `scenario` → `ScenarioResult`, `plan` → `Plan`, `exec` → `ExecStep`, `signal` → `Signal`, and `trace` → `ToolCallRecord`. `GraphEvent.data` is currently an unconstrained dictionary, so this mapping is not enforced by the shared model. `ingest`, `graph`, and `chat` payloads, reconnect replay, event IDs, and heartbeat behavior remain unspecified.
