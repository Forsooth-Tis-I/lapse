# Lapse web

WP6: the account map, ordered fix plan, agent trace/screen, and connections flow. React + TypeScript + Vite, Tailwind, Cytoscape with dagre ordering. Fonts ship locally. Dark appearance is the default; the sidebar switches to light.

## Run

Use Node 22.12+ and npm. From the repository root:

```sh
cd web
npm ci
npm run dev
```

Open http://localhost:5173. The dev server uses port 5173 with `strictPort`; it fails rather than silently switching ports. Mock mode is on by default and resets on browser reload.

```sh
npm run typecheck
npm test
npm run build
```

To use the parallel backend without creating a secrets file:

```sh
VITE_USE_MOCK=false VITE_API_URL=http://localhost:8000 npm run dev
```

The API must allow CORS from http://localhost:5173. All HTTP/SSE paths, request bodies, response parsing, and demo transport live in `src/api/`. See [the complete API handoff](src/api/README.md) for every endpoint and transport shape awaiting backend agreement.

## Structure

- `src/api/contracts.ts`: Zod schemas and inferred TypeScript models mirroring `lapse/contracts.py`.
- `src/api/index.ts`: REST/SSE boundary and environment selection.
- `src/api/fixtures.ts`, `mock.ts`: in-memory demo persona and simulated events.
- `src/App.tsx`: navigation, scenario selection, live state, counts, deadlines.
- `src/components/`: graph, explanation/evidence panel, plan board, agent panel, onboarding.
- `src/styles.css`: responsive layout, themes, and reduced-motion styles.
- `src/**/*.test.tsx`, `src/api/api.test.ts`: behavior and contract checks.
- `docs/screenshots/`: browser captures; `docs/verification.md`: verification record and replay recipe.

## Demo sequence

1. Account map starts at Direct only: five accounts use the old number. Switch to Full chain to reveal Google, its Gmail mailbox, and five more accounts by derivation round.
2. Inspect Dropbox to show both email and SMS prerequisites. Scroll its details to see evidence headers. Inspect GitHub for its missing authenticator factor; Splitwise is explicitly unknown, not safe.
3. Select College email closes: four accounts lose fresh sign-in access while Google retains another route. Both overlays independent takeover and lockout results, because the shared request permits only one scenario kind.
4. Open Fix plan, build it, and approve a step or all T1–T3. Google pauses for an OTP; any six digits simulate success. T1 college-email replacements complete automatically. T3 opens settings and simulates confirmation after six seconds. T4 remains pending. Verified fixes update graph edges and scenario counts.
5. Agent activity shows named query traces, timings, rows, and a clearly labelled simulated executor image. Connections accepts fictional IMAP/phone details, clears the password on submission, and streams discovery progress plus a placeholder Telegram code.

The explicit requested fixture yields **10 affected accounts plus the Gmail Root**, not 12 accounts. Counts come from scenario results. GitHub is only a blocked graph example; it is not the T1 executor persona. Moving a college account to Gmail while Gmail remains exposed does not make it safe. The mock preserves that risk until the hub is fixed.

## Backend work still needed

Real inbox ingestion and evidence, graph computations and explanations, persisted plans/approvals, OTP relay, executor screenshots and verification, named-query traces, stats, Telegram linking, and SSE must replace the mock. Mock service tiers and deadlines are illustrative, not verified policy. The college-closure story is staged. The frontend does not infer real-world safety from mock data.

The graph focuses on the selected scenario and includes blocked prerequisites. The account selector remains available for all discovered accounts. Unknown services are never green. Reduced motion reveals the final cascade immediately and retains opacity feedback without movement.
