.PHONY: up down fixture test test-db lint keys api worker bot mcp web fmt

up:            ## start FalkorDB (graph on :6380, browser on :3001)
	docker compose up -d falkordb

down:
	docker compose down

fixture:       ## load policy graph + demo persona graph (lapse:u:demo)
	uv run python scripts/load_fixture.py

test:          ## unit tests (no DB)
	uv run pytest -m "not db" -q

test-db:       ## tests that need FalkorDB (make up first)
	uv run pytest -m db -q

lint:
	uv run ruff check lapse scripts tests

fmt:
	uv run ruff format lapse scripts tests

keys:          ## print fresh local secrets for .env
	@uv run python -c "from cryptography.fernet import Fernet; import secrets; print('LAPSE_SECRET_KEY=' + Fernet.generate_key().decode()); print('APPROVAL_SIGNING_KEY=' + secrets.token_urlsafe(32))"

api:
	uv run uvicorn lapse.api.main:app --reload --port 8000

worker:
	uv run python -m lapse.worker

bot:
	uv run python -m lapse.bot.main

mcp:
	uv run python -m lapse.agent.mcp_server

web:
	cd web && npm run dev

.PHONY: demo demo-down tunnel doctor logs

demo:         ## build and start the local stack
	docker compose build
	docker compose up -d

demo-down:    ## stop the stack, including an optional tunnel; keep data
	docker compose --profile tunnel down

tunnel:       ## start a temporary public URL; wait up to 60 seconds for it
	docker compose --profile tunnel up -d tunnel
	@for attempt in $$(seq 1 30); do \
		url=$$(docker compose logs --no-color tunnel 2>&1 | sed -n 's/.*\(https:\/\/[a-zA-Z0-9-]*\.trycloudflare\.com\).*/\1/p' | tail -1); \
		if [ -n "$$url" ]; then echo "$$url"; exit 0; fi; \
		sleep 2; \
	done; echo "No tunnel URL yet. Check: make logs s=tunnel"; exit 1

doctor:
	uv run python scripts/doctor.py

logs:
	docker compose logs -f $(s)
