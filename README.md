<p align="center">
  <img src="docs/assets/lapse-logo-light.png" alt="Lapse: three strokes beside the lapse. wordmark" width="240">
</p>

# Lapse

**Know what you could lose. Fix the dependencies before you lose it.**

An old number can recover a mailbox. That mailbox can recover other accounts. **Lapse finds the whole chain**, explains the risk in Telegram, and plans fixes before you give up a number, inbox, or domain.

[![CI](https://github.com/tejas-raskar/lapse/actions/workflows/ci.yml/badge.svg)](https://github.com/tejas-raskar/lapse/actions/workflows/ci.yml)

## What it does

- **Discover dependencies** from inbox evidence and explicitly declared contact/factor relationships.
- **Reason across multiple hops** about stranger takeover, immediate lockout, and lost recovery routes.
- **Explain each result** with the access methods, prerequisites, and evidence behind it.
- **Plan before acting:** simulate repairs in FalkorDB graph copies and order changes while old contacts still work.
- **Execute with approval:** supported browser actions, code relay, or guided manual steps; then keep watching for new risks.

**Telegram is the conversation interface.** Ask *“What happens if someone gets my old number?”*, open **Show me** to inspect the graph, then ask *“What should I fix first?”* The web workspace provides the account map, plans, connections, and agent browser view.

![Lapse account map showing a synthetic old-number scenario and its multi-hop account dependencies](docs/assets/account-map.png)

*Light-mode app preview with synthetic frontend data, not live accounts or verified backend measurements.*

## What is in the graph?

**Example control flow:** old phone → Google host account → primary mailbox → Notion account.

These are control transitions, not literal stored edge directions. The host `Account` and its mailbox `Root:Email` are separate: signing into the host opens the inbox that downstream accounts use.

| Entity group | Nodes | What they represent |
| --- | --- | --- |
| Possession | `Root`: `Phone`, `Email`, `Domain`, `Device` | Numbers, mailboxes, domains, and devices you might lose. |
| Access | `Account`, `Method`, `Service` | An account, one way to access it, and the service policy behind it. |
| Evidence and monitoring | `Evidence`, `Signal`, `PolicyEvent` | Supporting message metadata, detected risks, and policy changes. |
| Reasoning and repair | `Scenario`, `Plan`, `Change` | A what-if result, a proposed repair plan, and its individual steps. |
| Agent context | `User`, `Turn`, `ToolCall` | User metadata, conversation history, and tool/query records. |
| Shared policy | `Service`, `MethodTemplate`, `ChangeProcedure`, `Carrier` | Service rules, access templates, change procedures, and reassignment rules. |

Shared policies live in `lapse:policy`; each user's compiled model and history live in `lapse:u:<uid>`. Queries never cross graph boundaries. Policy events can also record per-user notification state.

### How the nodes connect

Arrows below show **actual stored relationship directions**. `Root/Account` means either node type.

| Purpose | Relationships |
| --- | --- |
| Access requirements | `Method -NEEDS-> Root/Account`; `Method -GRANTS-> Account/Root` |
| Contacts and services | `Account -USES-> Root`; `Account -OF-> Service` |
| Evidence | `Evidence -SUPPORTS-> Account`; `Evidence -MENTIONS-> Root` |
| Monitoring | `Signal -ABOUT-> Root` |
| Scenario state | `Scenario -SEED-> Root`; `Scenario -REACHED-> Account/Root` |
| Explanations | `Account/Root -DERIVED-> prerequisite Account/Root` |
| Single-factor shortcuts | `Root/Account -ENABLES-> Account/Root` |
| Repair order | `Plan -HAS_STEP-> Change`; `Change -BEFORE-> Change`; `Change -FOR-> Account` |
| Agent memory | `Turn -ABOUT-> Account/Root`; `ToolCall -IN-> Turn` |
| Policy | `Service -HAS_METHOD-> MethodTemplate`; `Service -HAS_CHANGE-> ChangeProcedure` |

**OR between methods; AND within a method.** Any eligible method can grant access, but **all** its `NEEDS` must be controlled. An email-plus-device method cannot succeed with email alone. The user knows passwords; a stranger does not. A method with no possession prerequisites still requires a password. `USES` records a contact dependency, not proof of access.

A mailbox method **needs the host Account** and **grants the Email Root**. Standalone metadata records need no artificial edges. The tables cover implemented entities and relationships; planned `Action`/`LOGGED` records are not included. [Full schema and semantics →](docs/data-model.md)

### See it in FalkorDB

> **Screenshot placeholder · Demo access graph**
>
> Add `docs/assets/falkordb-demo-graph.png`: a small synthetic phone → host account → mailbox → downstream account graph, with Method nodes and labelled `NEEDS`/`GRANTS` edges.

> **Screenshot placeholder · Multi-hop explanation**
>
> Add `docs/assets/falkordb-multihop.png`: one saved scenario's `REACHED`/`DERIVED` graph, showing the prerequisite chain and an AND branch.

[Capture instructions and replacement image Markdown →](web/docs/verification.md#falkordb-screenshots)

## What traversals does Lapse use?

| Question | Graph operation | Why it matters |
| --- | --- | --- |
| **What can a stranger reach?** | Repeated [`NEEDS`/`GRANTS` closure](lapse/graph/queries/closure_round.cypher). | Checks complete prerequisite sets, not just connected nodes; advances until no new target is controlled. |
| **What if I lose this contact?** | [Before/after closure comparisons](lapse/graph/scenarios.py), with and without password knowledge. | Separates accounts lost now from accounts losing password-free recovery. |
| **Why is this account affected?** | Follow [`DERIVED`](lapse/graph/queries/explain.cypher) from target to prerequisites; retrieve `SUPPORTS`/`MENTIONS` evidence. | Preserves every prerequisite branch, including AND methods. |
| **What is the shortest route?** | [`algo.SPpaths`](lapse/graph/queries/algo_shortest_path.cypher) over `ENABLES`. | Finds shortest password-free, single-factor routes. |
| **Which dependency is a hub?** | [`algo.betweenness`](lapse/graph/queries/algo_keystones.cypher) plus bounded upstream/downstream traversals over `ENABLES`. | Estimates centrality; ranks by upstream-source × downstream-account counts. |
| **What should I fix first?** | [`GRAPH.COPY` simulations](lapse/graph/planner.py), contact changes, recompilation, and exposure reevaluation. | Tests repairs before proposing ordered steps, rather than guessing from an account list. |

`ENABLES` exists only for password-free methods with exactly one prerequisite. Its algorithms are **lower bounds**, not substitutes for AND/OR closure. No single-factor route does **not** mean safe.

The LLM selects fixed tools; **it never writes Cypher**. Named queries perform the reasoning in FalkorDB. Without the graph, Lapse cannot compute risk, explain dependencies, or simulate and resume repairs.

### Reproducible demo results

Synthetic backend fixture results, **under the methods we model**:

| Scenario | Verified result |
| --- | --- |
| Stranger gets the old number | <!-- claim:takeover_phone_old.direct -->5<!-- /claim --> accounts directly reachable → <!-- claim:takeover_phone_old.full -->10<!-- /claim --> across the full chain; <!-- claim:takeover_phone_old.unknown -->1<!-- /claim --> unknown. |
| College inbox closes | <!-- claim:lockout_email_college.lost_now -->1<!-- /claim --> account lost immediately; <!-- claim:lockout_email_college.recovery_lost -->4<!-- /claim --> lose recovery. |
| Simulate replacing the old number | <!-- claim:plan_phone_old.before -->11<!-- /claim --> distinct affected accounts → <!-- claim:plan_phone_old.after -->0<!-- /claim --> projected, across <!-- claim:plan_phone_old.steps -->7<!-- /claim --> proposed steps. |

The plan counts the union of takeover and lockout exposure, hence 11 rather than 10. Projection is not execution or a guarantee about unknown methods. [Reproduce the claims →](docs/claims.md)

## Run locally

Requires **Docker Compose v2**, **Python 3.12 + [uv](https://docs.astral.sh/uv/)**, a Telegram bot token, an OpenAI-compatible LLM key, and IMAP inbox access.

```sh
git clone https://github.com/tejas-raskar/lapse.git
cd lapse
uv sync --extra browser
cp -n .env.example .env
cp -n persona.local.example.yaml persona.local.yaml
make keys
# Edit both local files: generated keys, Telegram, LLM, inboxes, and matching roots.
# Keep LAPSE_UID=demo for the commands below.
make up
uv run python -m lapse.onboarding --uid demo
make demo
```

Open the **[workspace](http://localhost:8080)** → **Connections** to discover inbox accounts and link Telegram. Loading roots is not inbox discovery. Inspect the database in **[FalkorDB Browser](http://localhost:3001)**. [Detailed configuration, linking, browser execution, and troubleshooting →](docs/deploy.md)

## Tests and references

With dependencies installed and FalkorDB running:

```sh
make lint && make test && make test-db
uv run python scripts/verify_claims.py
(cd web && npm ci && npm test && npm run build)
```

[CI](.github/workflows/ci.yml) runs Python lint, unit/database tests, and claim checks; frontend checks run separately. Coverage includes AND/OR reasoning, multi-hop scenarios, repair simulations, ingestion, approvals, and UI state.

[Setup](docs/deploy.md) · [Graph model](docs/data-model.md) · [Named queries](lapse/graph/queries) · [Tools and MCP](docs/tools.md) · [Execution support](docs/exec-notes.md) · [Contributing](AGENTS.md)

**Scope:** experimental and policy-dependent. Unmodelled services are **unknown, not safe**. SSO/synced authentication is not modelled. Only the documented personal, unmanaged Notion flow has live browser-recipe validation; other flows may require manual action. The college-closure demo is staged. [Assumptions and policy limits](docs/policy-notes.md).

*Built with AI coding assistance; implementation and claims remain subject to review and verification.*
