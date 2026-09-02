.PHONY: install up down seed ingest eval test fmt lint serve serve-http client journal ui ui-install

install:
	uv sync

seed:
	uv run python scripts/seed.py

ingest:
	uv run python -m ingest.index

eval:
	uv run python -m eval.run_eval

up:
	docker compose up -d

down:
	docker compose down

test:
	uv run pytest

fmt:
	uv run ruff format .
	uv run ruff check --fix .

lint:
	uv run ruff check .
	uv run mypy ingest retrieval sql gateway mcp_server eval

serve:
	uv run python -m mcp_server.server

serve-http:
	uv run python -m mcp_server.http_server

ui-install:
	cd ui && npm install

ui:
	cd ui && npm run dev

client:
	uv run python scripts/mcp_client.py --profile $${PROFILE:-support}

journal:
	@tail -n 20 logs/journal.jsonl 2>/dev/null || echo "journal vide"
