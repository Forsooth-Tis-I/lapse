# Web API boundary

`index.ts` owns all fetch/EventSource calls and endpoint paths. `contracts.ts` mirrors the shared Pydantic contracts with Zod schemas and inferred types. `fixtures.ts` and `mock.ts` implement a session in memory; reload resets the demo. Set `VITE_USE_MOCK=false` to use REST; `VITE_API_URL` defaults to `http://localhost:8000`.

The singleton `api` implements `LapseApi`. Every REST response and SSE envelope/payload is parsed at the boundary. No credentials, OTPs, full email bodies, or backend error response bodies are logged or retained by the client module.

| Request | Body / response |
| --- | --- |
| GET `/api/roots` | `Root[]` |
| GET `/api/graph?scenario={id}` | `GraphData` below |
| POST `/api/scenarios` | `{kind:'takeover'\|'lockout',root_ids:string[]}` → `ScenarioResult` |
| GET `/api/scenarios/{id}` | `ScenarioResult` |
| GET `/api/scenarios/{id}/explain/{account_id}` | `Explanation` |
| POST `/api/plans` | `{old_root,new_root?,deadline?}` → `Plan` |
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

Extra transport shapes pending backend agreement:

```ts
type GraphData = {
  nodes: {id:string; label:string; node_type:'Root'|'Account'; root?:Root; account?:Account}[];
  edges: {id:string; source:string; target:string; label:string; confirmed:boolean; method_id?:string}[];
};
```

Edges point along dependency/derivation direction for display. Include `google → email_primary` to show the hosted-mailbox bridge. Full method nodes and multi-input constraints remain available in explanations; the graph labels Dropbox/GitHub AND requirements.

`subscribe(onEvent,onError?)` returns an unsubscribe function. The module accepts unnamed or named SSE messages containing the whole `GraphEvent` envelope. `decodeEvent` produces `{kind,data}`: scenario → ScenarioResult; plan → Plan; exec → ExecStep; trace → ToolCallRecord; ingest → `{emails_scanned,accounts_found,edges_inferred,edges_confirmed,status:'idle'|'running'|'done'}`; signal → Signal. A graph envelope with stats data produces `kind:'stats'`; other graph/chat payloads produce `kind:'other'` and preserve the envelope. Re-fetch graph after graph/stats events. A malformed payload reports a generic error without echoing data.

Mock scenarios emit partial `affected_accounts` round by round; `rounds` describes the final closure. The POST response and GET scenario always return the full result. Count Account nodes only: five direct and ten affected accounts; Gmail is an additional reached Root. The stated persona lists ten affected accounts, not twelve. GitHub is blocked by its TOTP requirement and Splitwise stays unknown.

Mock approval simulates T1 completion, T2 OTP waiting, T3 a deep link followed by simulated confirmation, and T4 a permanently pending manual visit. T1 is demonstrated in the college email plan. A six-digit OTP simulates success and is discarded. Only verified completion rewires a dependency and updates stored scenarios. A college account moved to Gmail remains exposed to takeover until Gmail’s recovery number is fixed; its explanation follows the updated dependency. Recreating a plan preserves each service’s tier while omitting completed changes. The screenshot is an SVG labelled SIMULATED EXECUTOR, not a real browser capture. Ingestion, evidence headers, query names/timings, deadlines, Telegram code and executor capabilities are demo data. The Telegram URL is a generic placeholder; backend must return a real bot deep link and code. Credentials are discarded in mock mode.
