# Web verification

## README assets

The root README uses `docs/assets/account-map.png`, captured from the UI with
`VITE_USE_MOCK=true` in Newsprint/light. This is a synthetic frontend preview,
not a live graph result or completed account change. The capture uses a
1600 x 1100 viewport, device scale factor 2, and reduced motion.

The README uses only the light logo, exported from the app's existing `.brand`
symbol and wordmark and backed by a light background for readability. The older
dark logo and dark Fix plan image remain as unused assets. No personal graph,
real inbox, or authenticated external browser was used for these assets.

### FalkorDB screenshots

The two README blockquotes are intentional placeholders for **user-supplied**
FalkorDB Browser screenshots. Do not replace them with the frontend mock map:
they should show actual synthetic nodes and edges stored in FalkorDB.

#### Prepare an isolated synthetic graph

With FalkorDB running, the following creates a fresh, uniquely named screenshot
graph from the public fixture and saves one old-phone takeover scenario.
It uses existing named queries, does not reset shared policy or demo graphs,
and makes no LLM, inbox, Telegram, or browser-execution calls.

```sh
uv run python - <<'PY'
from uuid import uuid4
from lapse.config import ROOT_DIR
from lapse.contracts import ScenarioRequest
from lapse.graph import db
from lapse.graph.scenarios import run_scenario
from lapse.policy.loader import load_policy_file
from scripts.load_fixture import load_persona

uid = f"readme-capture-{uuid4().hex}"
policies, _ = load_policy_file(ROOT_DIR / "lapse/policy/services.yaml")
_, carriers = load_policy_file(ROOT_DIR / "lapse/policy/carriers.yaml")
g = db.user_graph(uid)
load_persona(g, policies, carriers)
result = run_scenario(uid, ScenarioRequest(kind="takeover", root_ids=["phone_old"]))
print(f"Browser graph: {g.name}")
print(f"Scenario ID: {result.id}")
PY
```

Keep the printed graph name and scenario ID. Open
<http://localhost:3001>, connect to the local FalkorDB service, and select that
exact graph. **Do not use `make fixture`**: it replaces `lapse:u:demo` and
`lapse:policy`. The capture graph persists so you can arrange and retake images;
delete only that exact graph after you no longer need it.

#### Screenshot 1: demo access graph

1. Open the existing [`wp4_entity.cypher`](../../lapse/graph/queries/wp4_entity.cypher)
   in the Browser query editor. For this manual read-only lookup, replace `$id`
   with `'phone_old'` and `$kind` with `'Root'`, then run it in the capture graph.
2. Switch to graph visualization and use its node-expansion controls to reveal
   incoming `NEEDS` methods and their `GRANTS` targets. Follow the Google account,
   its mailbox method, `email_primary`, and the Notion account methods. Use the
   same lookup with `$id = 'google'`, `'email_primary'`, or `'notion'` and the
   appropriate `'Account'`/`'Root'` kind if you need to start a focused view.
3. Keep the central chain small: `phone_old`, Google Account, `email_primary`,
   Notion Account, and the corresponding Method nodes. Include selected `USES`
   and `OF` edges only if they remain legible; hide unrelated neighbours rather
   than deleting database records. Hide scenario/history edges for this image.
4. Arrange prerequisites left, methods between their prerequisites and targets,
   and downstream accounts right. **Keep arrows in their stored directions:**
   Method → NEEDS → prerequisite; Method → GRANTS → target.
5. Use `label` for Root/Method captions, `display` for Account, and `name` for
   Service. If the Browser version offers only one caption property, use `id`
   consistently. Show relationship names. Use a light background and distinct
   node-label colors.

Save as **`docs/assets/falkordb-demo-graph.png`**. Replace the first README
placeholder blockquote with:

```markdown
![Synthetic FalkorDB access graph linking an old phone, Google host account, primary mailbox, and Notion through explicit access methods](docs/assets/falkordb-demo-graph.png)

*Actual synthetic FalkorDB nodes and stored NEEDS/GRANTS relationships; USES records contacts, not access.*
```

#### Screenshot 2: multi-hop explanation

1. In the same capture graph, use `wp4_entity.cypher` with the printed scenario
   ID substituted for `$id` and `'Scenario'` for `$kind`. Expand its `SEED`
   and `REACHED` neighbours. Keep only the central phone/mailbox chain and the
   Dropbox branch visible, not every reached account.
2. Expand the selected accounts' outgoing `DERIVED` relationships. This graph
   has only one saved scenario, so historical derivations cannot mix in.
   [`explain.cypher`](../../lapse/graph/queries/explain.cypher), with `$sid`
   replaced by the printed scenario ID, gives a read-only table of its
   prerequisites and method labels to check against the visual.
3. Include both Dropbox prerequisites: `email_primary` and `phone_old`.
   Both DERIVED edges share a method ID; together they explain the AND step.
   Keep `DERIVED` arrows pointing from target to prerequisite. Do not redraw
   them as forward control-flow arrows.
4. Caption the Scenario by `id`, Account by `display`, and Root by `label`
   (or use `id` for all). Show `SEED`, `REACHED`, and `DERIVED` labels, keeping
   unrelated `USES`/`ENABLES`/policy edges out of this image.

Save as **`docs/assets/falkordb-multihop.png`**. Replace the second README
placeholder blockquote with:

```markdown
![Saved synthetic takeover scenario showing reached accounts and a multi-hop derivation, including both prerequisites for Dropbox](docs/assets/falkordb-multihop.png)

*DERIVED points back to prerequisites. Dropbox requires both the mailbox and phone under the modelled method.*
```

Before saving either image, spread nodes until no label or edge crosses another
label. Crop unnecessary browser chrome and keep text readable at roughly
900 pixels wide in the README. Use synthetic IDs only; exclude personal
identifiers, evidence snippets, credentials, and unrelated history. Screenshots
show modelled graph state, not proof of a successful vendor account takeover.

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
