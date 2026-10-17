# Lapse

Lapse finds every account still tied to a phone number, email, or domain you no longer control, before its new owner does. Then it fixes them with your approval and keeps watching.

> Built for Graph Hacks (WeMakeDevs × FalkorDB). Tracks: 1 (Agents That Act on Connected Data) and 2 (Agent Memory & Coordination).

Work in progress. See `docs/BUILD_PLAN.md`.

## Run locally

```bash
cp .env.example .env             # fill in credentials locally
uv sync
make keys                       # put the generated keys in .env
# Create persona.local.yaml using docs/persona-setup.md.
make doctor
make demo                       # build and start the local Docker stack
make fixture
```

Open <http://localhost:8080>. FalkorDB uses port 6380, with its Browser on 3001.
The bot uses long polling. `make tunnel` optionally prints a temporary public URL;
use demo data and read-only demo mode for recordings. `make demo-down` stops the
stack and keeps local data.

For host services, headed browser login, configuration and troubleshooting, see
[local deployment](docs/deploy.md). Use `make api`, `make worker`, and `make bot`
in separate terminals after `make up`; headed browser login requires a host worker.
