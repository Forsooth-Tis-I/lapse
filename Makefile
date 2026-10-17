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
