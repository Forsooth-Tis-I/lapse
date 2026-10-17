# Lapse web

The live account map, fix plans, chat, agent trace, executor screen, and connections form. React, TypeScript, Vite, and Cytoscape. Fonts ship locally.

## Run against the API

From the repository root, load the shared demo fixture once and start the API:

```sh
uv sync
make fixture
LAPSE_UID=demo uv run uvicorn lapse.api.main:app --port 8020
```

In another terminal:

```sh
cd web
npm ci
VITE_USE_MOCK=false VITE_API_URL=http://localhost:8020 npm run dev
```

Open http://localhost:5173. If that port belongs to another worktree, append `-- --port 5174`. The API permits both local origins. Never open `.env`; application code loads its configuration.

For nginx or another same-origin proxy, leave `VITE_API_URL` unset or set it to `/api`. REST, SSE, and executor image paths then use the relative API base. Offline development remains available with `VITE_USE_MOCK=true npm run dev`.

## Verify

```sh
npm run typecheck
npm test
npm run build
npx playwright install chromium
WEB_URL=http://localhost:5174 API_URL=http://localhost:8020 node scripts/verify-live.mjs
```

The headless check uses the real demo API, creates plans, approves pending T1–T3 steps, sends a chat question, saves fixture persona metadata, and captures every page at 1920×1080. It does not connect an inbox. Use only the demo workspace. `make fixture` replaces the shared demo graph; coordinate its use with other workers.

`node scripts/verify-execution.mjs` separately stages a labelled `awaiting_otp` change, checks OTP relay and live SSE, then restores the original change. It does not run an executor. See [verification and remaining gaps](docs/verification.md).

## Demo sequence

1. Compare Direct only and Full chain. The current fixture returns 5 direct and 10 full-chain accounts. The mailbox bridge appears in round 2.
2. Inspect Dropbox for both prerequisites and the evidence subject, sender, and date. Inspect Splitwise for unknown methods.
3. Switch College email closes and Both. Counts always come from the backend. The current compiled policy returns zero college lockouts because other sign-in methods remain; the earlier offline mock returns four.
4. Plan from the selected scenario or a root. Approve one step or all T1–T3. The API queues execution; completion requires the worker and evidence.
5. Ask chat `show risk for 4321`. Follow its buttons and tool links to the query trace. The agent panel places tool, Cypher name, milliseconds, and rows above the executor screen and stats.
6. Save phones and persona in Connections, or supply write-only inbox credentials to queue discovery.

The claim applies **under the methods we model**. Unknown services are **unknown, not safe**. The college-closure scenario is staged. See [the API boundary](src/api/README.md) for transport details.
