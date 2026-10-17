# Web API boundary

`index.ts` owns all fetch/EventSource calls and endpoint paths. `contracts.ts` mirrors the shared Pydantic contracts with Zod schemas and inferred types. `fixtures.ts` and `mock.ts` implement a session in memory; reload resets the demo. REST is the default. Set `VITE_USE_MOCK=true` for offline development. `VITE_API_URL` defaults to relative `/api` for a same-origin proxy; an origin such as `http://localhost:8020` is also accepted. Both forms use exactly one `/api` prefix for REST and SSE.

The singleton `api` implements `LapseApi`. Every REST response and SSE envelope/payload is parsed at the boundary. No credentials, OTPs, full email bodies, or backend error response bodies are logged or retained by the client module.

| Request | Body / response |
| --- | --- |
| GET `/api/roots` | `Root[]` |
| GET `/api/graph?scenario={id}` | `GraphData` below |
| POST `/api/scenarios` | `{kind:'takeover'\|'lockout',root_ids:string[]}` → `ScenarioResult` |
| GET `/api/scenarios/{id}` | `ScenarioResult` |
| GET `/api/scenarios/{id}/explain/{account_id}` | `Explanation` |
| POST `/api/plans` | `{old_root,new_root?,deadline?}` → `Plan` |
| GET `/api/plans` | `Plan[]`, restored on load and reconnect |
| POST `/api/chat` | `{text}` → `{text, buttons, tool_calls: string[]}` |
| GET `/api/plans/{id}` | `Plan` |
| POST `/api/changes/{id}/approve` | `{}` → `Change` |
| POST `/api/changes/{id}/otp` | `{code}` → `Change` |
| GET `/api/trace?since={ISO timestamp}` | `ToolCallRecord[]` |
| GET `/api/agent/screen` | `{url:string\|null,caption:string,mock:boolean}` |
| GET `/api/stats` | `{nodes:number,edges:number,last_query_ms:number}` |
| POST `/api/onboarding` | `{inboxes:[{host,username,app_password}],phones:[{number,carrier,status:'retiring'\|'active',drop_at?}]}` → `{telegram_code,telegram_url}` |
| POST `/api/ingest/run` | `{}` → `{started:boolean}` |
| GET `/api/events` | SSE `GraphEvent` envelopes |

`root_ids` follows `ScenarioRequest` and the final Decisions, overriding the earlier singular `root_id` API table. A compound UI view runs takeover and lockout separately because their actor semantics differ; each request also supports multiple roots of the same kind.

Implemented transport shapes:

```ts
type GraphData = {
  nodes: {id:string; label:string; node_type:'Root'|'Account'; root?:Root; account?:Account}[];
  edges: {id:string; source:string; target:string; label:string; confirmed:boolean; method_id?:string}[];
};
```

Edges point along dependency/derivation direction for display. Include `google → email_primary` to show the hosted-mailbox bridge. Full method nodes and multi-input constraints remain available in explanations; the graph labels Dropbox/GitHub AND requirements.

`subscribe(onEvent,onError?)` returns an unsubscribe function. The module accepts unnamed or named SSE messages containing the whole `GraphEvent` envelope. `decodeEvent` produces `{kind,data}`: scenario → ScenarioResult; plan → Plan; exec → ExecStep; trace → ToolCallRecord; ingest → `{emails_scanned,accounts_found,edges_inferred,edges_confirmed,status:'idle'|'running'|'done'}`; signal → Signal. A graph envelope with stats data produces `kind:'stats'`; other graph/chat payloads produce `kind:'other'` and preserve the envelope. Re-fetch graph and recompute scenarios after graph/stats events. Re-fetch plans on executor events and restore state after SSE reconnects. A malformed payload reports a generic error without echoing data.

Mock scenarios emit partial `affected_accounts` round by round; `rounds` describes the final closure. The POST response and GET scenario always return the full result. Count Account nodes only: five direct and ten affected accounts; Gmail is an additional reached Root. The stated persona lists ten affected accounts, not twelve. GitHub is blocked by its TOTP requirement and Splitwise stays unknown.

Mock approval simulates T1 completion, T2 OTP waiting, T3 a deep link followed by simulated confirmation, and T4 a permanently pending manual visit. T1 is demonstrated in the college email plan. A six-digit OTP simulates success and is discarded. Only verified completion rewires a dependency and updates stored scenarios. A college account moved to Gmail remains exposed to takeover until Gmail’s recovery number is fixed; its explanation follows the updated dependency. Recreating a plan preserves each service’s tier while omitting completed changes. The screenshot is an SVG labelled SIMULATED EXECUTOR, not a real browser capture. Ingestion, evidence headers, query names/timings, deadlines, Telegram code and executor capabilities are demo data. The Telegram URL is a generic placeholder; backend must return a real bot deep link and code. Credentials are discarded in mock mode.


## Live integration details

The current plan for each root is the newest by `created_at`. Reopening an unfinished matching plan reuses it, so repeated planning does not duplicate bulk approvals. Extra plan and change fields survive parsing and appear under **Additional planner details**. T4 always remains outside bulk approval.

The agent returns `tool_calls` as names, not trace records. Chat captures matching query-record IDs when each reply arrives, preserving links when later replies reuse a tool. The API does not return a turn/call identifier, so correlation with simultaneous Telegram calls remains approximate. The trace retains the newest 150 rows.

Chat buttons use `open_web {path}`, `plan_root {root_id}`, or `approve_changes {change_ids, approval_token?}`. Explicit approval clicks call the existing per-change approval endpoint. That endpoint does not consume the Telegram approval token.

Unknown accounts, such as Splitwise, are identified by `account.modelled=false`; their methods are not in the model. The web shows **unknown, not safe** without treating the explanation endpoint's 404 as a failed path lookup. Root mailbox bridges are displayed at the host account's next round, but never counted as affected accounts.

Onboarding accepts `display_name`, email metadata, optional phone `id` and `country`, and devices in addition to inboxes/phones. The form permits persona-only submission, clears inbox credentials, and queues ingestion only when an inbox was supplied. No inbox credentials are fetched or persisted in browser storage.
