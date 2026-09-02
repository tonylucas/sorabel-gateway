.PHONY: install up down seed ingest eval eval-sql test fmt lint serve serve-http client journal ui ui-fmt ui-install ui-clean

install:
	uv sync

seed:
	uv run python scripts/seed.py

ingest:
	uv run python -m ingest.index

eval:
	uv run python -m eval.run_eval

eval-sql:
	uv run python -m eval.run_eval_sql $${TYPES:+--types $$TYPES}

up:
	docker compose up -d

down:
	docker compose down

# Le budget par appel de la suite vaut 30 s par défaut. `ask_database` passe par
# le free tier Gemini, qui répond parfois en 35 s : sans ce relèvement, un appel
# lent mais valide fait échouer un test qui n'a rien à voir avec le code.
test:
	GATEWAY_TEST_TIMEOUT=$${GATEWAY_TEST_TIMEOUT:-60} uv run pytest

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

# Turbopack garde son cache dans `ui/.next`, indexé sur l'arbre du moment. Un
# `git checkout` qui change `ui/package.json` sous un cache existant le laisse
# incohérent, et le serveur de dev reste bloqué sur « Compiling / ». Vider.
ui-clean:
	rm -rf ui/.next

ui-fmt:
	cd ui && npm run format

ui-install:
	cd ui && npm install

ui:
	cd ui && npm run dev

client:
	uv run python scripts/mcp_client.py --profile $${PROFILE:-support}

journal:
	@tail -n 20 logs/journal.jsonl 2>/dev/null || echo "journal vide"
