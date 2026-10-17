# Lapse: build plan

**Pitch:** Lapse finds every account still tied to a phone number, email, or domain you no longer control, before its new owner does. It fixes those accounts with your approval and keeps watching.

**Tracks:**
- **Track 1 (primary): Agents That Act on Connected Data.** Multi-hop reasoning, graph queries and algorithms as tools via MCP, actions chosen by the graph, explainable paths.
- **Track 2: Agent Memory & Coordination.** A persistent per-user graph, evidence and plan state that survive restarts, a shared policy graph, and per-tenant isolation.

**Hard rule:** if FalkorDB is removed, nothing works. The account map, the takeover and lockout computation, the fix order, and the agent's memory all live in and come from the graph.

---

## 1. User experience

### 1.1 Surfaces
- **Telegram bot.** One ongoing thread, like Muse.
  - You talk to it in natural language.
  - It messages you first when it finds something.
  - Inline buttons handle approvals; you type OTP codes when a site texts you.
- **Web app** (the agent's window):
  - account graph, with scenario toggles and depth contrast;
  - plan board;
  - agent trace (every tool call, its Cypher, timing, row count);
  - agent screen (live screenshots from its browser);
  - onboarding.
- **MCP server.** The same fixed tools, usable from Claude, ChatGPT or any MCP client. The Telegram agent also uses them through MCP.

### 1.2 Flows
1. **Onboard.**
   - In the web app, connect your inbox (IMAP app password) and list your phone numbers, current and old, with carrier and country.
   - Telegram `/start` links the chat to the user.
2. **Discover.**
   - The worker scans the inbox and the graph builds live in the UI.
   - Edges the agent inferred show dashed. The agent asks in Telegram to confirm the ambiguous ones ("Is ••4321 your old Vi number?").
3. **Alert.** Detectors fire on:
   - a number marked inactive, giving a reissue countdown from the carrier rule;
   - deactivation or closure notices;
   - domain expiry (RDAP);
   - a stale number that still receives codes;
   - a new device.

   Example: *"Your old number ••4321 can be reissued to a stranger from 12 Jan. 6 accounts use it directly. Through Gmail, 11 more."*
4. **Explain.** "Show me" → the web graph shows the depth contrast:
   - depth 1: the accounts using the number directly;
   - depth N: the full takeover closure, with the derivation path for any account clicked.
5. **Plan.** An ordered fix plan:
   - the change that removes the most stranger reach goes first;
   - changes that need a code on the old SIM are scheduled before the deadline;
   - each step carries an automation tier.
6. **Act.** You approve in Telegram (approve all safe steps, or step by step). The executor runs each tier:
   - **T1 automatic:** API, or a confirmation code arriving by email that the agent reads itself.
   - **T2 agent-driven:** its browser does the change and pauses for the SMS code you relay.
   - **T3 assisted:** a deep link to the exact settings page; you do it, the agent auto-verifies.
   - **T4 offline:** reminder plus checklist plus drafted letter, e.g. bank branch or Aadhaar centre.
7. **Verify.** A confirmation email or relayed SMS marks the step done and moves the graph edge from the old root to the new one.
8. **Watch.** Any later email that still references the old root means a missed account, and it is added to the plan. New accounts keep being discovered.

---

## 2. Architecture

```
            ┌──────────────┐   IMAP poll/IDLE   ┌──────────────────────────────┐
  Inbox ───▶│ ingest worker│──────────────────▶│ FalkorDB (pinned v4.22.1)     │
            │ prefilter →  │   MERGE evidence,  │  lapse:policy   (shared)      │
            │ regex → LLM  │   accounts, roots  │  lapse:u:<uid>  (per user)    │
            └──────────────┘                    │  + Redis pub/sub / streams    │
                                                └──────────────┬───────────────┘
  Telegram ⇄ bot ⇄ agent (LLM, tool-calling) ⇄ MCP server (fixed Cypher tools)
                                   │                           │
                     executor worker (T1 API · T2 Playwright · T3 deep link · T4 offline)
                                   │
  Browser ⇄ web app (React + Cytoscape) ⇄ FastAPI (REST + SSE) ⇄ FalkorDB
  Scheduler: detectors (reissue countdown, closure notices, RDAP, stale root, missed account, policy events)
```

- **Event bus and job queue:** Redis pub/sub and streams on the FalkorDB container (it is a Redis server), so no extra infrastructure.
- **Python 3.12 services:**
  - `api`, `worker`, `bot`, `mcp`;
  - one package, `lapse`, with different entry points.
- **Libraries:**
  - `falkordb` 1.8;
  - `fastapi`, `uvicorn`, `sse-starlette`;
  - `python-telegram-bot` 21 (long polling);
  - `mcp` (FastMCP);
  - `litellm`, so any LLM provider works;
  - `playwright`, `imapclient`, `pydantic`, `apscheduler`, `cryptography` (Fernet for stored credentials).
- **Web:** Vite + React + TypeScript + Tailwind + Cytoscape.js (dashed edges, path highlight, cascade animation).
- **Deploy:** docker compose (falkordb, api, worker, bot, mcp, web, caddy) on one VPS with 2 vCPU and 4 GB, enough for Playwright.

### Repo layout
```
lapse/
  docker-compose.yml  docker-compose.prod.yml  Caddyfile  Makefile  pyproject.toml
  lapse/
    contracts.py            # pydantic models shared by all packages
    graph/  db.py schema.cypher queries/*.cypher closure.py scenarios.py planner.py fanout.py
    policy/ services.yaml carriers.yaml compile.py
    ingest/ imap.py prefilter.py parsers.py extract.py writer.py eval/
    agent/  mcp_server.py agent.py guard.py prompts/
    exec/   base.py t1_github.py t2_browser.py recipes/*.py t3_assisted.py t4_offline.py verify.py
    signals/ detectors.py rdap.py scheduler.py policy_events.py
    api/    main.py routes/*.py sse.py auth.py
    bot/    main.py flows/*.py
  web/      (Vite app)
  fixtures/ persona.json    # hand-built persona graph used by every package before ingestion works
  scripts/  load_fixture.py verify_claims.py synth_tenants.py
  tests/
  docs/     api.md tools.md data-model.md explainer.md
```

---

## 3. Graph model

### 3.1 Graphs (FalkorDB multigraph)
- **`lapse:policy` (shared):** how each service logs in, recovers and changes contacts, plus carrier reissue rules. Maintained once and used by everyone.
- **`lapse:u:<uid>` (one per user):** that user's roots, accounts, methods, evidence, scenarios, plans, actions and trace.
  - Policy is compiled into each user graph, because FalkorDB has no cross-graph queries.

### 3.2 User graph, nodes

| Label | Key properties |
|---|---|
| `User` | `uid, name, tz, telegram_chat_id` |
| `Root:Phone` | `id, last4, e164?, country, carrier, status(active\|retiring\|inactive\|unknown), inactive_since?, reissue_after?` |
| `Root:Email` | `id, address, provider, kind(personal\|edu\|work\|custom), status(active\|closing\|closed), closes_at?` |
| `Root:Domain` | `id, name, registrar?, expires_at?, status` |
| `Root:Device` | `id, name, kind(phone\|laptop\|key), status(active\|sold\|lost)` |
| `Service` | `id, name, domains[], category, modelled` |
| `Account` | `id, service_id, display, identifier, modelled, first_seen, last_seen` |
| `Method` | `id, account_id, kind(login\|reset\|recover\|mailbox\|mx), label, needs_password, source(policy\|observed), confidence, doc_url` |
| `Evidence` | `id, msg_id, date, sender, subject, snippet(≤300 chars), event` |
| `Signal` | `id, kind, at, detail, status` |
| `Scenario` | `id, kind(takeover\|lockout), actor(stranger\|user), root_id, created_at, reached_count` |
| `Plan` | `id, old_root, new_root, deadline, status, exposure_before, exposure_after` |
| `Change` | `id, account_id, from_root, to_root, tier(1-4), requires_old_root, status(proposed\|approved\|running\|awaiting_otp\|awaiting_user\|done\|failed\|skipped), exposure_removed` |
| `Action` | `id, at, kind, result, detail, screenshot_url` |
| `ToolCall` | `id, at, tool, args_json, query_name, ms, rows, outcome` (episodic memory and trace) |
| `Turn` | `id, at, role, text` (conversation history, linked to entities mentioned) |

### 3.3 User graph, relationships

| Relationship | Meaning |
|---|---|
| `(Account)-[:OF]->(Service)` | |
| `(Account)-[:USES {role, confirmed, confidence, evidence_ids}]->(Root)` | `role` is one of `login_email`, `recovery_email`, `login_phone`, `recovery_phone`, `sms_2fa`, `totp_device` |
| `(Method)-[:GRANTS]->(Account\|Email\|Domain)` | Methods are compiled from `USES` plus service templates |
| `(Method)-[:NEEDS {as}]->(Root\|Account)` | **AND**: every need is required |
| `(Root\|Account)-[:ENABLES]->(Account\|Email)` | Materialized only from single-need methods ("x alone suffices"), for BFS fan-out |
| `(Evidence)-[:SUPPORTS]->(Account)`, `(Evidence)-[:MENTIONS]->(Root)`, `(Signal)-[:ABOUT]->(Root)` | |
| `(Scenario)-[:SEED]->(Root)` | |
| `(Scenario)-[:REACHED {round, via}]->(Account\|Email\|Domain)` | |
| `(X)-[:DERIVED {scenario, method, round}]->(Need)` | The derivation trail; explanations walk it |
| `(Plan)-[:HAS_STEP {order}]->(Change)`, `(Change)-[:BEFORE]->(Change)`, `(Change)-[:FOR]->(Account)`, `(Change)-[:LOGGED]->(Action)` | |
| `(Turn)-[:ABOUT]->(Account\|Root)`, `(ToolCall)-[:IN]->(Turn)` | |

### 3.4 Policy graph

| Node | Key properties |
|---|---|
| `Service` | `id, name, domains[], doc_url, verified_at` |
| `MethodTemplate` | `id, service_id, kind, label, needs_roles[], needs_password, doc_url` |
| `ChangeProcedure` | `service_id, root_kind(phone\|email), tier, requires[](password\|old_otp\|new_otp\|email_otp), settings_url, api?, confirmation_patterns[]` |
| `Carrier` | `id, name, country, reissue_after_days, source_url` |
| `PolicyEvent` | `id, at, service_id, description, diff` (e.g. a replay of Twitter's SMS-2FA removal on 2023-03-20) |

Carrier rules with sources:
- **India** (Jio, Airtel, Vi, BSNL): reissued after at least 90 days, per TRAI's statement in *Rajeswari v. Union of India*, 30 Oct 2023.
- **US carriers:** about 45 days, per Princeton's 2021 number-recycling study.

### 3.5 Indexes
```
CREATE INDEX FOR (a:Account) ON (a.id)
CREATE INDEX FOR (r:Root) ON (r.id)
CREATE INDEX FOR (p:Phone) ON (p.last4)
CREATE INDEX FOR (e:Email) ON (e.address)
CREATE INDEX FOR (s:Service) ON (s.id)
CREATE INDEX FOR (v:Evidence) ON (v.msg_id)
CALL db.idx.fulltext.createNodeIndex('Evidence', 'subject', 'snippet')
```

---

## 4. Core semantics: AND/OR closure

**Rules:**
- A node is controlled by an actor if it is a seed, **or** if any one method that grants it has all of its needs controlled (OR across methods, AND within a method).
- Methods with `needs_password=true` count only for actors who know the passwords (the user, not a stranger).
- Every method has at least one need. Zero-need methods do not exist; things like "re-register an expired domain" enter as scenario seeds.

**Scenarios:**
- **Takeover of root R:** actor is a stranger, seeds are `{R}`, no passwords. Answers "what can whoever gets R reach?"
- **Lockout of root R:** actor is the user, seeds are every active root and device except R, with passwords. Accounts **not** reached are the ones you'd be locked out of.
- Wording is always "under the methods we model". Unmodelled services report **unknown, not safe**.

**One closure round** (the app loops until nothing new is gained, then writes the derivation):
```cypher
MATCH (m:Method)-[:GRANTS]->(t)
WHERE NOT t.id IN $have AND (NOT m.needs_password OR $pw)
WITH m, t, [(m)-[:NEEDS]->(n) | n.id] AS needs
WHERE size(needs) > 0 AND all(x IN needs WHERE x IN $have)
RETURN t.id AS gained, collect(m.id)[0] AS via, needs
```

**Explain one account** (the depth-N path shown in the UI):
```cypher
MATCH p = (a {id:$account})-[:DERIVED*1..8]->(seed)
WHERE all(e IN relationships(p) WHERE e.scenario = $sid) AND seed.id IN $seeds
RETURN p ORDER BY length(p) ASC LIMIT 1
```

**Depth-1 view** (looks like a join, by design):
```cypher
MATCH (r:Root {id:$root})<-[:NEEDS]-(m:Method)-[:GRANTS]->(a:Account)
WHERE NOT m.needs_password
RETURN DISTINCT a.display
```

**Guaranteed fan-out:** `CALL algo.BFS(root, 0, 'ENABLES')` over single-need edges. It is a sound lower bound, used for quick UI counts. The closure is the source of truth.

### 4.1 Planner
Input: retiring root R, replacement R′ (optional), deadline D (from carrier rule or signal).
1. Affected accounts are those with any method that NEEDS R. For each, create a `Change(R→R′)` with tier and `requires_old_root` from `ChangeProcedure`.
2. Order the changes greedily, using the closure as the oracle:
   - At each step, pick the change that removes the most stranger reach under hypothetical application.
   - Break ties by `requires_old_root` first, then the lower tier.
   - Exhaustive evaluation is fine at personal scale.
3. Schedule every `requires_old_root` step before `D - buffer`. Flag the plan as **infeasible** if it can't fit, e.g. the old SIM is already gone.
4. Write `Plan`, `HAS_STEP {order}` and `BEFORE` edges. Store `exposure_before`, `exposure_after` and each step's `exposure_removed`. Every number on screen comes from these.

---

## 5. MCP tools (the LLM never writes Cypher)

All arguments are resolved against the graph first, so unknown ids get an honest "unknown". Every call is logged as a `ToolCall` and streamed to the trace panel.

| Tool | What it does |
|---|---|
| `list_roots()` | Roots with status, deadlines and confirmed flag |
| `resolve(hint)` | Maps "my old number" or "college email" to root or account ids, or asks to disambiguate |
| `dependents(root_id, depth)` | `depth=1` gives direct users; `depth="full"` gives the closure summary |
| `takeover_if_reassigned(root_id)` | Creates and runs the scenario; returns reached accounts and counts |
| `lockout_if_lost(root_id)` | Same, for the lockout direction |
| `explain(account_id, scenario_id)` | Derivation path with evidence emails |
| `account_info(account_id)` | Methods, uses and evidence, or "not modelled" |
| `search_evidence(text)` | Full-text search over evidence |
| `plan_retirement(old_root_id, new_root_id?, deadline?)` | Builds the ordered plan |
| `plan_status(plan_id)` | |
| `execute_change(change_id, approval_token)` | Only callable with a token minted by a Telegram button press |

**Answer outcomes**, in the style of the reference example: answered with a path; answered from memory; not in the graph; unknown root.

**Reply guard:** every service or account the LLM names must appear in that turn's tool results. Otherwise the reply is regenerated.

---

## 6. Ingestion

1. **Fetch.** IMAP over SSL with an app password, all mail, newest first, then incremental by UID.
   - Store only the `msg_id`, headers and a snippet of at most 300 characters.
2. **Prefilter** (cheap, deterministic): match on the sender domain list from the policy graph, or on keywords:
   - welcome, verify, verification code, OTP, sign-in, new device;
   - security, password, two-factor, 2-step;
   - phone number, recovery, deactivat, closure, expire.
3. **Deterministic parsers:**
   - The `To:` address gives the login email.
   - Masked phones: `ending in 4321`, `••••4321`, `*******21`, `+91 XXXXX X4321`.
   - Device names in sign-in alerts.
   - Domains in custom-domain addresses.
4. **LLM extraction:** a cheap model, batches of about 20 emails, JSON output in this shape:
```json
{"service_guess":"", "sender_domain":"", "account_identifier":"",
 "event":"signup|verify_email|otp_sms_notice|otp_email|login_alert|new_device|twofa_enabled|twofa_disabled|contact_changed|password_reset|deactivation_notice|domain_expiry|other",
 "phone_last4":[], "emails_mentioned":[], "device":null,
 "contact_change":{"kind":null,"old_last4":null,"new_last4":null},
 "deadline":null, "confidence":0.0}
```
5. **Writer.** `MERGE` Account, Root, USES and Evidence. Confidence comes from the evidence count and type.
   - `confirmed=false` until the user confirms or the evidence is decisive, e.g. a "phone number changed to ••4321" email.
   - A `last4` is matched to the user's declared numbers; ambiguous matches become a confirmation question.
6. **Compile methods.** For each account, the service's `MethodTemplate`s are instantiated with the account's `USES` roles. Single-need methods are materialized as `ENABLES` edges.
7. **Eval.** Label about 60 persona emails and report precision for service, identifier and last4 in the README, honestly.

---

## 7. Policy research (shared graph)

Around 20 services, each method backed by a link to the official help page and a verification date:
- **Identity and mail:** Google, Microsoft, Apple (policy only), GitHub.
- **Shopping and payments:** Amazon (.in and .com), PayPal.
- **Social:** LinkedIn, X, Instagram, Facebook, Discord, Reddit.
- **Productivity:** Dropbox, Notion, Figma, Canva, Slack.
- **Media:** Spotify, Netflix.
- **India, phone-first:** Swiggy, Zomato, Paytm.
- **Bank:** a generic Indian bank template (T4).

For each service, record:
- login methods;
- reset and recovery methods;
- what a contact change requires;
- tier;
- the settings deep link;
- confirmation-email patterns.

Unknown services are created with `modelled=false` and stay "unknown, not safe".

---

## 8. Executors

Shared interface:
```
Executor.can_run(change) -> bool
Executor.run(change, ctx) -> AsyncIterator[Step]
```
Each `Step` is one of `progress`, `screenshot`, `need_otp(channel)`, `need_user(link, instructions)`, `done(evidence?)` or `failed(reason)`.

- **T1 GitHub (email root):**
  - `POST /user/emails` adds the new address, using the persona's fine-grained token.
  - The verification email arrives in the inbox the agent watches. The agent opens the link in its logged-in browser profile.
  - It switches the primary address in the browser, then `DELETE /user/emails` removes the old one.
  - The confirmation email marks the step done.
  - **Spike early:** check whether GitHub's sudo mode re-prompts.
- **T2 Playwright recipes:**
  - One persistent, encrypted browser profile per user per site.
  - Recipes are Python step lists: `goto`, `fill`, `click`, `await_otp(new_phone)`, `expect`.
  - A screenshot after every step goes to the agent screen.
  - Domains are allow-listed per recipe.
  - **Spike candidates:** Microsoft account security info, Dropbox, LinkedIn, Discord, X, Amazon.in. Keep the one or two that work reliably; the rest fall back to T3.
- **T3 assisted:** exact deep link plus short instructions, then status `awaiting_user`. The verify watcher closes it from the confirmation email. Example: Google recovery phone at `myaccount.google.com/signinoptions/rescuephone`, confirmed by Google's "recovery phone changed" alert.
- **T4 offline:** checklist (documents needed), drafted request letter, reminder schedule. Closed when the user taps "done" or relays a confirmation SMS.
- **Verify watcher:** on new evidence, match `confirmation_patterns`. When matched:
  - mark the `Change` done;
  - repoint the `USES` edge from the old root to the new one, with evidence;
  - recompute exposure;
  - push a Telegram and SSE update.

---

## 9. Detectors (proactive behaviour)

| Detector | Fires when | Message |
|---|---|---|
| `reissue_countdown` | A phone is marked inactive, or a carrier deactivation email arrives | "Can be reissued from <date>; N accounts still use it" |
| `closing_email` | Closure or deactivation notice for an edu or work mailbox | Deadline plus plan offer |
| `domain_expiry` | A custom-domain address is seen; RDAP (`rdap.org/domain/<name>`) gives `expires_at` | Countdown plus takeover reach |
| `stale_root` | A number the user calls inactive still receives codes, or an "active" number hasn't been seen in 6+ months | "Do you still have ••4321?" |
| `new_device` | Sign-in alerts mention a new phone | "Did you move your authenticator app?" (lockout scenario on the old device) |
| `missed_account` | Evidence references a retired root after its plan completed | Account added to the plan |
| `policy_event` | A policy changes, or a replay is triggered | Recompile affected tenants, recompute exposure, notify only users whose outcome changed; show tenant count and latency |

`scripts/synth_tenants.py` generates N synthetic tenant graphs, labelled synthetic, to demonstrate the policy-event fan-out at scale. The real persona is never mixed with synthetic data.

---

## 10. Telegram flows

- `/start <link-code>` binds the chat to the user.
- **Proactive card:**
  - finding plus counts;
  - buttons: `Show risk` (web deep link), `Plan the fix`, `Not mine`.
- **Free text** to the agent, e.g. "I'm switching to +91 98…", "what happens if I lose my phone?", "why is Dropbox at risk?"
- **Plan card:**
  - steps with tier badges;
  - buttons: `Approve all T1–T3`, `Review steps`, `Not now`.
  - Each approval mints a single-use signed token.
- **OTP relay:** "Dropbox sent a code to ••7788. Reply with it (5 min)." The code is passed to the waiting executor and never stored.
- **Edge confirmations:** "Is ••4321 your old Vi number?" with `Yes` / `No` / `Not sure`.
- **Progress and done summaries.** Restarts resume the plan from the graph.

---

## 11. Web app

- **Onboarding:** IMAP credentials (stored encrypted), phone numbers, Telegram link code.
- **Graph:**
  - Cytoscape view of roots, accounts and services. Root status sets the colour; unconfirmed edges are dashed.
  - **Scenario bar:** "Stranger gets ••4321", "I lose my phone", "Domain expires".
  - **Depth control:** depth 1, then full closure.
  - Clicking an account shows its derivation path, with evidence emails.
- **Plan board:** ordered steps, `exposure_removed` bars, live status, the same approve buttons as Telegram.
- **Agent panel:**
  - trace: tool, arguments, Cypher query name, milliseconds, rows, outcome;
  - live screenshots from the executor;
  - graph stats: node and edge counts, last query latencies.
- **Public demo mode:** a read-only persona that judges can explore without connecting an inbox.

### 11.1 API contract (FastAPI)
| Method and path | Purpose |
|---|---|
| `GET /api/graph?scenario=` | Nodes and edges for the visualization, with status |
| `GET /api/roots` | |
| `POST /api/scenarios` `{kind, root_id}` | |
| `GET /api/scenarios/{id}` | |
| `GET /api/scenarios/{id}/explain/{account_id}` | |
| `POST /api/plans` `{old_root, new_root?, deadline?}` | |
| `GET /api/plans/{id}` | |
| `POST /api/changes/{id}/approve` | |
| `POST /api/changes/{id}/otp` `{code}` | |
| `GET /api/trace?since=` | |
| `GET /api/agent/screen` | |
| `GET /api/events` (SSE) | Ingest progress, scenario results, executor steps, signals |
| `POST /api/ingest/run` | |
| `POST /api/onboarding` | |
| `GET /api/stats` | |

---

## 12. Security and privacy

- **What is stored:**
  - **Never:** account passwords, OTP codes, full email bodies.
  - **Only:** evidence snippets and message ids.
- **Encrypted at rest (Fernet):** IMAP app password and browser profiles.
- **Approvals:** every write action needs a single-use approval token from a human tap. The browser executor is limited to allow-listed domains per recipe. Every action is logged as an `Action` node.
- **Access:**
  - Per-user graphs with FalkorDB per-graph ACL (`%R~lapse:u:<uid>*`);
  - API auth via Telegram-linked session;
  - self-host option documented.
- **The README states plainly that this graph is a takeover map.** It lists what is stored and why, and the threat model.

---

## 13. Testing and evaluation

- **Closure unit tests:**
  1. simple OR;
  2. AND gate blocks a stranger;
  3. a cycle without a seed stays locked;
  4. correlated device loss;
  5. a password-needed method blocked for a stranger;
  6. custom-domain MX path;
  7. two alternatives;
  8. a lockout complement.
- **Planner tests:** hub first; `requires_old_root` before deadline; infeasible flag; exposure numbers consistent.
- **Extraction eval:** about 60 labelled persona emails; precision reported.
- **`scripts/verify_claims.py`:** re-derives every number in the README, blog and demo from the live graph, and exits non-zero on any mismatch. Runs in CI.
- **E2E:** fixture persona → API → scenario → plan → mocked executor → verify → edge repointed.

---

## 14. Demo persona (real accounts, real emails)

A fresh test identity is created once and signed up to real services. The signups are designed so the graph has depth, AND gates, and a hub:

| Account | Setup |
|---|---|
| **Gmail G** | Recovery phone is the OLD number. This is the hub. |
| **Outlook O** | Recovery email is G |
| **Amazon.in, Swiggy, Zomato** | Login phone is OLD (depth 1) |
| **Notion, Figma, Canva, Spotify, X** | Email G, login via magic link or email reset (depth 2 through G) |
| **PayPal** | Email G plus SMS to OLD (AND gate, satisfied at depth 2) |
| **Dropbox** | Email O plus SMS 2FA to OLD (AND gate, satisfied at depth 3) |
| **Discord** | Email O, phone OLD |
| **GitHub** | Email O, TOTP 2FA on the user's phone. The AND gate blocks the stranger, so GitHub stays safe: the "2FA saved you" moment. Also the T1 executor demo. |
| **LinkedIn** | Email G, phone NEW (shows a correctly migrated account) |

Expected story: the old number reaches only about 3 accounts at depth 1, but most of the graph at full depth, all through the Gmail hub. Real counts come from the graph; nothing is hard-coded.

---

## 15. Demo video (about 2:30)

| Time | Beat |
|---|---|
| 0:00 | Hook: "66% of recycled phone numbers in a Princeton sample were still tied to someone's accounts." Lapse's proactive Telegram message about ••4321. |
| 0:20 | Web graph. Depth 1: 3 accounts, looks like a lookup. Full depth: the cascade through Gmail. Click Dropbox to see the AND-gate derivation path with the actual emails as evidence. |
| 0:55 | GitHub stays green: TOTP blocks the stranger. "Not in the graph": a service Lapse can't model is shown as unknown, not safe. |
| 1:10 | "Plan the fix": Gmail first, because it removes N accounts of stranger reach; old-SIM steps flagged before the deadline. Approve in Telegram. |
| 1:30 | Agent screen. T1: GitHub swaps the email automatically. T2: a site asks for the SMS code, typed into Telegram. T3: Google deep link, then auto-verified from the confirmation email. The graph edges flip. |
| 2:00 | Trace panel showing the Cypher, timings and row counts. Restart the agent; the plan resumes. Policy-event replay re-checks N tenants in X ms and notifies only those affected. |
| 2:20 | Close: what's stored, what's not, the link. |

---

## 16. Submission checklist (rules page)
- [ ] Public repo
- [ ] README with setup and the graph data model (diagram plus tables)
- [ ] The Cypher queries and algorithms the product depends on: `lapse/graph/queries/*.cypher` listed and explained
- [ ] Demo video
- [ ] Live deployment, plus public read-only demo mode
- [ ] Tracks named: Track 1 and Track 2
- [ ] AI assistance disclosed (Rule 11)
- [ ] `docs/explainer.md`, so the team can explain the model, queries and architecture (Rule 12)
- [ ] dev.to blog (#graphhacks #falkordb) for the side prize
- [ ] Submitted at wemakedevs.org/hackathons/falkordb/submit

---

## 17. Work packages for parallel agents

**WP0 goes first.** Every other package builds against its contracts and the fixture graph, so they can run in parallel without waiting on ingestion.

| WP | Scope | Depends on | Owner | Done when |
|---|---|---|---|---|
| **WP0 Foundation** | Repo scaffold, uv project, compose with pinned FalkorDB and `FALKORDB_ARGS`, `contracts.py`, `schema.cypher`, `fixtures/persona.json` plus loader, `docs/api.md`, `docs/tools.md`, Makefile, CI skeleton | none | Claude (lead) | `make up && make fixture` loads the persona; tests run |
| **WP1 Graph core** | Closure engine, scenarios plus derivation writes, explain, depth-1 view, BFS fan-out, planner | WP0 | Codex | 8 closure tests and planner tests pass on the fixture |
| **WP2 Policy** | Research about 20 services from official docs; `services.yaml`, `carriers.yaml`; compiler into user graphs | WP0 | Codex (web research) | Every method has a doc URL; fixture compiles; unknown services handled |
| **WP3 Ingestion** | IMAP, prefilter, parsers, LLM extraction, writer, incremental sync, eval harness | WP0, WP2 schema | Codex | Persona inbox becomes a graph; eval report |
| **WP4 Agent and MCP** | FastMCP tools wrapping WP1, agent loop (litellm), reply guard, ToolCall trace, answer outcomes | WP1 interface (stub first) | Codex | A scripted conversation hits all tools; trace persisted |
| **WP5 API** | FastAPI routes per contract, SSE over Redis pub/sub, auth, demo mode | WP0 | Codex | Contract endpoints serve fixture data |
| **WP6 Web** | Onboarding, graph (scenarios, depth control, path highlight, dashed edges), plan board, trace, agent screen, stats | WP5 contract (mock first) | Codex | Full UI against the fixture; cascade animation |
| **WP7 Telegram bot** | Flows in §10, approval tokens, OTP relay, proactive-message consumer | WP4, WP5 | Codex | End-to-end chat on the fixture with a mocked executor |
| **WP8 Executors** | Framework, T1 GitHub, T2 recipes (site spikes), T3, T4, verify watcher | WP0; persona accounts for spikes | Codex plus you (OTPs) | GitHub T1 live; at least one T2 site live; T3 auto-verify works |
| **WP9 Detectors** | §9 detectors, RDAP, scheduler, policy-event replay, `synth_tenants.py` | WP1, WP3 | Codex | Each detector fires on a fixture or persona and messages Telegram |
| **WP10 Deploy** | Prod Dockerfiles, compose, Caddy TLS, VPS setup script, GitHub Actions (tests plus `verify_claims`), backups | WP0 | Codex | Public URL serves demo mode; bot online |
| **WP11 Docs and story** | README, data-model diagram, Cypher listing, explainer, blog draft, demo script, `verify_claims.py` | All (iterative) | Claude | `verify_claims` green; README complete |
| **WP12 Persona** | Signup checklist (§14), browser profile logins, eval labels | none | You plus Claude | Persona inbox has real evidence for every row in §14 |

**Merge order:** WP0 → (WP1, WP2, WP5, WP6, WP10 in parallel) → (WP3, WP4) → (WP7, WP8, WP9) → WP11 → demo.

Each package runs in its own worktree via `delegate_task` with `isolation: worktree`. The lead reviews and integrates. Heavy coding goes to Codex to protect the Claude plan's usage limits.

---

## 18. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Wrong AND/OR result on camera | Closure tests before any UI; every number from `verify_claims` |
| LLM extraction errors | Deterministic parsers first; evidence-backed edges; dashed until confirmed |
| Bot detection on real sites | Spike T2 sites early; anything flaky drops to T3 (deep link plus auto-verify) |
| Inferred policy is wrong | Doc URL and verified date per method; "under modelled methods" wording; unknown is not safe |
| "Tiny graph, why a DB?" | Per-tenant multigraph, shared policy compiled per tenant, persistent evidence, plans, trace and conversation memory, policy-event fan-out across tenants with measured latency |
| FalkorDB defaults | Pin `v4.22.1`; `FALKORDB_ARGS="TIMEOUT_MAX 30000 TIMEOUT_DEFAULT 10000 RESULTSET_SIZE 100000 MAX_QUEUED_QUERIES 200"`; never the free cloud tier |
| Privacy concern from judges | Threat model in the README; no secrets stored; approvals; audit log; self-host |

---

## Decisions (override the plan above)
1. **Deployment is local**: docker compose on the developer machine. The Telegram bot uses long polling, so nothing needs to be exposed. Optionally a free Cloudflare quick tunnel gives a temporary public URL for recording. No VPS. README ships complete local setup instructions.
2. **Ports**: FalkorDB on localhost:6380, FalkorDB Browser on :3001 (6379 and 3000 are taken).
3. **LLM**: OpenCode Zen, OpenAI-compatible, `LLM_BASE_URL=https://opencode.ai/zen/v1`, `LLM_MODEL=deepseek-v4.1-flash-free`, used through the `openai` SDK. No paid keys. Keep LLM calls few: deterministic parsers first, batch extraction, cache results by message id.
4. **Two flagship scenarios**:
   - **Old number** (takeover): the SIM is being dropped on a date; the carrier can reissue it after 90 days (India, TRAI) to a stranger who can reset everything still tied to it.
   - **College email** (lockout): the college mailbox closes on a date; accounts that only log in or recover through it become unreachable. A *staged* closure email is sent to the stand-in college inbox for the demo, and the README says it is staged.
   - Compound scenarios with several roots at once are supported (`root_ids` is a list).
5. **No GitHub persona.** Tier 1 (fully automatic) is "email change confirmed by a code or link sent to the new address", which the agent reads from the inbox it already watches. Candidate services are those registered with the college email: Figma, Canva, Notion, Coursera. The agent drives its own browser profile and needs no human step.
6. **Demo identity**: a fresh test identity, with a primary Gmail plus a second Gmail standing in for the college address. Two real phone numbers play "old" and "new".
7. **Lockout semantics are fresh sign-in**: seeds are the possession roots the user still holds (phones, devices) plus password knowledge. Email inboxes are reached through their mailbox host account's methods, not assumed. A closed mailbox's hosting method is disabled.
8. **No personal names** anywhere in README or docs. **Do not submit** to the hackathon; the human does that.
