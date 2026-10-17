# Agent instructions (read before changing anything)

Use `$fettle-mode` for all work in this repo.

## What this is
Lapse: an agent that finds accounts still tied to phone numbers, emails, or domains the user no longer controls (old SIM that will be reissued, college email being closed, expiring domain), explains the risk as graph paths, plans fixes in the right order, executes them with approval, and keeps watching. FalkorDB is the core: if the graph is removed, nothing works.

The full plan is `docs/BUILD_PLAN.md`. The **Decisions** section at its end overrides anything earlier in it.

## Ground rules
- `lapse/contracts.py` is the shared contract. Do not change it from a work-package branch; if you need a change, say so in your final report and work around it locally.
- The LLM never writes Cypher. Every query lives in `lapse/graph/queries/<name>.cypher` and is run by name through `lapse/graph/db.py`, which times it and records row counts for the trace panel.
- AND/OR semantics: a node is controlled if it is a seed, or if ANY method granting it has ALL of its needs controlled. Methods with `needs_password=true` only count for actors who know passwords (the user, never a stranger). Methods with zero needs must have `needs_password=true`.
- Say "under the methods we model". Unmodelled services are "unknown, not safe", never "safe".
- Never store or log secrets, account passwords, OTP codes, or full email bodies. Evidence keeps message id, headers, and a snippet of at most 300 chars.
- Never read or print `.env` or `persona.local.yaml`. Code loads them at runtime via `lapse/config.py`.
- FalkorDB runs from `docker compose` pinned to `falkordb/falkordb:v4.22.1` on localhost:6380 (6379 is taken on this machine). Browser on :3001.
- Python 3.12 via `uv`. Tests with `pytest`; tests that need FalkorDB are marked `@pytest.mark.db`. Lint with `ruff`.
- Graph names: `lapse:policy` (shared) and `lapse:u:<uid>` (per user). No cross-graph queries; compile policy into each user graph.
- Stay inside your work package's directories. If you must touch a shared file (pyproject.toml, docker-compose.yml, Makefile), keep the edit minimal and mention it in your report.
- Commit on your branch with clear messages. Do not push; the lead merges and pushes.
- No personal names in README or docs. Do not submit anything to the hackathon.
