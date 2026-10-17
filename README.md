# Lapse

Lapse finds every account still tied to a phone number, email, or domain you no longer control, before its new owner does. Then it fixes them with your approval and keeps watching.

> Built for Graph Hacks (WeMakeDevs × FalkorDB). Tracks: 1 (Agents That Act on Connected Data) and 2 (Agent Memory & Coordination).

Work in progress. See `docs/BUILD_PLAN.md`.

## Quick start (local)

```bash
cp .env.example .env            # fill in values locally; never commit
make up                         # FalkorDB on :6380, Browser on :3001
uv sync
make fixture                    # load the demo persona graph
make test
```
