# Web verification

## README assets

The current root README uses `docs/assets/account-map.png` and
`docs/assets/fix-plan.png`, captured from the current UI with
`VITE_USE_MOCK=true`. These are synthetic frontend previews, not live graph
results or completed external account changes. The map uses Newsprint and the
plan uses Risograph. Captures use a 1600 x 1100 viewport, device scale factor 2,
and reduced motion.

The light and dark logo PNGs export the app's existing `.brand` symbol and
wordmark with transparent backgrounds. No personal graph, real inbox, or
authenticated external browser was used for these four assets.

## Historical WP6 round 2 verification

The results below describe the earlier integration checkpoint, not the current
UI or present test counts. The web chat and trace panels were subsequently
removed, and the API now returns both lockout tiers.

Verified 2026-10-17 on `wp6r2-web`, after merging `main` at `c7504a6`. The inherited checkpoint is `c0f71ee`; the merge is `53d1bf2`. This report replaces the earlier mock-only verification.

## Results

- `uv sync`, `make fixture`, and `npm ci` completed. API ran with `LAPSE_UID=demo` on port 8020 against shared FalkorDB on 6380. No environment file or private persona file was opened.
- `npm run typecheck`, `npm test`, and `npm run build` passed. Frontend has 35 tests. Build retains a large graph bundle warning and third-party Zod annotation warnings.
- `uv run --extra browser pytest -q`: 607 passed, including database tests. The browser extra is required by the merged executor tests. `tests/test_api.py` has 39 passing tests; together with `tests/test_wave2_api.py`, 40 pass.
- Ruff passed for the changed Python files, and `git diff --check` passed.
- `scripts/verify-live.mjs` passed against Vite on 5174 with `VITE_USE_MOCK=false`, then against the production build behind nginx 1.28 on 8082. The nginx check used the deployment proxy directives with the upstream changed to local port 8020. REST and SSE used relative `/api`; the final browser request origins are in [live-checks.json](live-checks.json).
- Screenshots use 1920×1080, except `connections-mobile.png` at 390×844. No browser exceptions were observed. Native reduced-motion emulation showed the final cascade round immediately. Light appearance and narrow Connections layout passed the overflow check.

## Real behavior checked

The graph loads roots and returns 5 direct and 10 full-chain accounts for the old phone. The cascade visibly advances through rounds 1, 2, and 3 without moving the map frame. Dropbox shows its evidence subject and sender. Splitwise says it is not in the graph of modelled methods and remains unknown, not safe.

College closure returns zero fresh-sign-in lockouts with the current researched policy. The summary shows `0 lost now` and `Recovery loss not reported`. Password knowledge still permits sign-in under the methods we model. Unit tests cover future `lost_now_accounts` and `recovery_lost_accounts`, including separate counts, account labels, duplicate results, and exclusion of Root nodes. These optional tiers were not fabricated in live screenshots.

The phone plan reports 10 → 0 distinct affected accounts, with separate takeover and lockout counts, remaining and unknown accounts, grouped roles, titles, and notes. Swiggy and Zomato have visible T3 manual instructions. The first live pass exercised per-step approval and bulk approval. Repeated runs reuse unfinished plans and skip approvals already completed. No worker was started to carry out external account changes.

Chat POSTs to the real agent, shows `Working…`, renders the returned text and buttons, opens the risk graph and plan, and links a tool to its highlighted trace row. The trace shows tool, named Cypher query, milliseconds, rows, and outcome. Stats and the empty executor screen use real API responses.

Connections saved explicit fixture email metadata through the real API and returned a Telegram link. No Telegram message was sent. Browser storage remained empty. Tests verify credential clearing, reuse of a matching email root, automatic personal-root creation for supplied credentials, and forwarding only that root ID to ingestion. Live inbox ingestion was not attempted without test mailbox credentials.

`scripts/verify-execution.mjs` stages an explicitly labelled OTP wait, submits a generated test code through the UI, consumes it once from Redis, and checks that it is absent from trace data. Exec and trace SSE updates reach the page. The script also captures a local test page through the real `StepEmitter.screenshot`, serves its nested image through the API, and verifies browser image decoding. The original change and screenshot pointer are restored. This verifies transport, not an external service change.

## Integration fixes

Web changes complete live chat, trace links, scenario refresh, planner details, truthful lockout summaries, optional recovery tiers, OTP relay, and onboarding. Mock mode defaults to off; nginx requests use relative `/api`.

Small API changes keep the inherited port-5174 CORS allowance, accept the executor's JSON screenshot pointer and nested image paths, and forward optional ingestion root IDs to the existing worker. Screenshot path containment and extension checks remain in place. The API regression tests were run failing before these fixes and passing afterward. Main's async chat fix is preserved. Shared graph contracts and graph semantics were not changed on this branch.

Independent review found the screenshot and onboarding mismatches, then a fresh review checked the fixes and found no source blockers. Its checks included typecheck, 35 frontend tests, production build, and 39 API tests. Comment review found no actionable added comments. Review used the same provider; it was independent context, not cross-provider review.

## Screenshot index

All files below are in [screenshots](screenshots/). Older mock screenshots were removed to avoid mixing evidence.

| View | Files |
| --- | --- |
| Account map | `graph-direct.png`, `graph-full.png`, `graph-college.png`, `graph-both.png` |
| Explanation | `explanation-evidence.png`, `unknown-splitwise.png` |
| Plan | `plans.png`, `plans-phone.png`, `plans-manual-steps.png`, `plans-approved.png` |
| Staged OTP | `plan-awaiting-otp.png` |
| Chat (removed from the web app; Telegram only) | `chat-working.png`, `chat.png` |
| Trace and stats (removed from the web app; `GET /api/trace` remains) | `agent-trace.png` |
| Agent screen | `agent-screen-staged.png` |
| Connections | `connections.png`, `connections-saved.png`, `connections-mobile.png` |
| Appearance and motion | `graph-light-reduced-motion.png` |

## Remaining limits

The API does not yet return the two lockout tiers. Chat exposes tool names without a turn/call ID, so simultaneous Telegram activity can make trace correlation approximate. Redis SSE has no event replay; the UI refetches state on reconnect. External inbox discovery and live account execution require configured test accounts and were not claimed as verified here.

See [web setup](../README.md) for replay commands. Fixture loading replaces the shared demo graph; coordinate with other work before reloading it. The live script approves demo steps and saves persona metadata. The execution script additionally requires `uv sync --extra browser` and installed Playwright Chromium.
