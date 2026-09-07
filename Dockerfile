# Le service Python : la gateway MCP, canal Streamable HTTP.
#
# Deux étages, pour une raison précise : l'index Chroma se construit ici, au
# build, à partir du corpus — Cloud Run est sans état, il n'y a pas de volume à
# monter et rien à synchroniser au démarrage. Le corpus, lui, n'a plus à voyager
# dans l'image finale une fois l'index construit. Redéployer, c'est réindexer.

# Le modèle d'embeddings est **le même au build et à l'exécution**, et c'est
# cette ligne qui le garantit. L'index est construit avec lui ; une requête
# encodée par un autre modèle ne serait pas dans le même espace vectoriel, et le
# retrieval renverrait des résultats faux sans rien signaler. Le changer se fait
# ici, et impose de reconstruire l'image — donc l'index.
ARG EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2

FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS build
ARG EMBEDDING_MODEL

# `copy` et non `hardlink` : le cache uv et /app sont sur deux couches.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    EMBEDDING_MODEL=${EMBEDDING_MODEL} \
    FASTEMBED_CACHE_PATH=/app/.fastembed

WORKDIR /app

# Les dépendances d'abord, seules : cette couche ne se reconstruit que si
# `pyproject.toml` ou `uv.lock` changent, pas à chaque ligne de code touchée.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY ingest ingest
COPY retrieval retrieval
COPY sql sql
COPY gateway gateway
COPY mcp_server mcp_server
COPY access.yaml ./
RUN uv sync --frozen --no-dev

# L'index et le modèle d'embeddings, construits maintenant plutôt qu'au premier
# appel : le modèle pèse ~250 Mo, le télécharger à froid sur Cloud Run coûterait
# la première requête.
COPY data/corpus data/corpus
RUN uv run python -m ingest.index


FROM python:3.11-slim-bookworm
ARG EMBEDDING_MODEL

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    EMBEDDING_MODEL=${EMBEDDING_MODEL} \
    FASTEMBED_CACHE_PATH=/app/.fastembed \
    PORT=8000 \
    # Le journal est doublé sur stdout, que Cloud Logging capture : une instance
    # recyclée emporte son système de fichiers, pas ses logs. À n'activer que
    # sur le canal HTTP — en stdio, stdout porte le protocole JSON-RPC.
    GATEWAY_JOURNAL_STDOUT=1

WORKDIR /app

COPY --from=build /app/.venv /app/.venv
COPY --from=build /app/.chroma /app/.chroma
COPY --from=build /app/.fastembed /app/.fastembed
COPY ingest ingest
COPY retrieval retrieval
COPY sql sql
COPY gateway gateway
COPY mcp_server mcp_server
COPY access.yaml ./

# `docs/schema.sql` n'est pas embarqué : depuis l'introspection, le schéma vient
# de la base. Le corpus non plus : l'index le remplace.

RUN useradd --system --uid 10001 sorabel && chown -R sorabel /app
USER sorabel

EXPOSE 8000
CMD ["python", "-m", "mcp_server.http_server"]
