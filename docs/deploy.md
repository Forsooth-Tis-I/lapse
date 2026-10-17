# Run locally

Lapse runs on your machine. The Telegram bot uses long polling; no public host,
webhook, or VPS is needed. Use Python 3.12 with uv and Docker Compose v2 or newer.
Node 22 is needed only for host web development.

## Configure

1. Copy `.env.example` to `.env` and fill in the LLM key, Telegram token and inbox
   credentials. Run `make keys` locally and put both generated keys in `.env`.
   Keep the host database port at 6380; 6379 and 3000 are already occupied.
2. Follow [persona setup](persona-setup.md) to create `persona.local.yaml`.
   Replace placeholder values locally. Never commit either private file.
3. Run `uv sync --extra browser`, start FalkorDB with `make up`, then inspect
   `make doctor`. Doctor exits nonzero for failed checks, prints fix hints, and
   never prints credentials or persona contents. Its database check needs the
   running server, but its port check currently flags that server's bound ports.
   Resolve other failures; those expected reports do not require stopping FalkorDB.
   Empty optional inboxes are skipped; partially configured inboxes fail.

Doctor checks host dependencies. A Docker-only worker does not require host
Chromium; an already running stack will correctly report its published ports as
occupied. Stop only the services you intend to replace.

## Docker stack

```sh
make demo                 # build, then start all default services
make fixture              # load the fixture graph through localhost:6380
make logs s=worker        # Ctrl-C stops log following, not the service
make demo-down            # stop containers; retain ./data and ./browser_profiles
```

Open the app at <http://localhost:8080> and FalkorDB Browser at
<http://localhost:3001>. API is on localhost:8000 and MCP on localhost:8766.
Containers reach FalkorDB at `falkordb:6379`; Compose overrides the host settings
from `.env`. Existing FalkorDB configuration and the `lapse-falkordb` container
name are retained. Do not start another checkout's stack against that container.

The Python Dockerfile has `api`, `worker`, `worker-browser`, `bot`, and `mcp`
targets. Compose selects `worker-browser` for Chromium and its Linux libraries.
Data and browser profiles are bind-mounted, and survive container replacement.
The local persona file is mounted read-only for onboarding and ingestion.
The web image builds the real API client and serves it with nginx on 8080;
`/api/` is proxied without buffering so SSE events arrive as they happen.

The API, worker, bot and MCP entrypoint implementations must be present before
starting the stack. The MCP image selects streamable HTTP transport and honors `FASTMCP_HOST=0.0.0.0` and
`FASTMCP_PORT=8766`. Host CLI use still defaults to stdio. Image builds alone do not verify service interfaces.

## Host services and browser login

```sh
make up
uv sync --extra browser
uv run playwright install --with-deps chromium
make doctor
make fixture
```

Run `make api`, `make worker`, `make bot`, and `make mcp` in separate terminals.
For the web development server, run `cd web && npm ci`, then
`VITE_USE_MOCK=false npm run dev` and open <http://localhost:5173>.
The host web client defaults to the API on localhost:8000.

Run the worker on the host for headed browser login. Use the executor's login
workflow with the local desktop and `browser_profiles/`; the container has no
desktop display. Stop the Docker worker with `docker compose stop worker` before
starting the host worker. Do not run two bots with the same token.

## Optional recording tunnel

Start the local stack, then run `make tunnel`. This starts the `tunnel` profile,
waits up to 60 seconds, and prints its temporary `https://…trycloudflare.com` URL.
The URL changes when the tunnel restarts. Requests go through web's nginx proxy,
including SSE. No Cloudflare account or token is needed.

The tunnel makes the web app and its proxied API public. Use demo data and enable
`LAPSE_DEMO_MODE=true` before starting the API for a public recording. The API
implementation must enforce read-only demo mode. Stop exposure with
`docker compose --profile tunnel stop tunnel`, or stop everything with
`make demo-down`. Telegram does not need this tunnel.

## Troubleshooting

- **Missing config:** fill in the variable names reported by `make doctor`. Do
  not paste credentials, `.env`, or persona contents into logs or bug reports.
- **Port occupied:** stop the owning local process or stack. The reserved ports
  6379 and 3000 are not used as host bindings by this Compose file.
- **Database unavailable:** run `make up` and inspect `make logs s=falkordb`.
  Doctor expects the graph module version `42201`, provided by v4.22.1.
- **LLM completion fails:** verify `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL`. Doctor sends a
  one-token chat completion through the same client as the agent and extractor. OpenCode Go uses
  `https://opencode.ai/zen/go/v1`; the client supplies its required process-stable session header.
  `LLM_FALLBACK_MODELS` is an ordered comma-separated list, defaulting to
  `glm-5.3-flash,qwen3.8-flash`. Set it empty to disable model failover. Requests have a
  30-second timeout and one SDK retry before trying the next model.
- **IMAP login fails:** enable IMAP and use an app password where required.
  Doctor only logs in and out; it never fetches messages.
- **Browser missing:** install the browser extra and Chromium using the commands
  above, or rebuild `docker compose build worker` for the container worker.
- **API unavailable or missing module:** integrate the API/worker/bot/MCP work
  packages, rebuild, and inspect that service's logs. nginx waits for API health.
- **No tunnel URL:** inspect `make logs s=tunnel`; outbound Cloudflare access may
  be blocked. The local app and long-polling bot remain usable.

## WP11 integration checkpoint

The current `make mcp` command uses the MCP server's default stdio transport. For
host HTTP clients, run
`uv run python -m lapse.agent.mcp_server --transport streamable-http`.
The server binds loopback and reads `MCP_PORT`;
the Docker settings currently advertise `FASTMCP_HOST` and `FASTMCP_PORT`. Align
that entrypoint and binding before treating the container MCP health check as
working. The agent's default in-process tool transport does not require HTTP MCP.

The separately integrated LLM client targets OpenCode Go at
`https://opencode.ai/zen/go/v1`, model `kimi-k2.7-code`, with an
`x-opencode-session` header. This supersedes the earlier free-tier target for the
integrated build. Verify that client and worker handler registration after merging
before recording live execution. The final smoke command is
`uv run python scripts/demo_e2e.py` once that parallel work lands.
