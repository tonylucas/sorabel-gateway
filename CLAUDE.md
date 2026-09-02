# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## État du dépôt

**`tests/acceptance/` est la spécification.** Cette suite est fournie, adossée
aux exigences E1–E6 de `docs/cadrage_dsi.md`, et fait foi : elle fige les noms
de champs, l'enveloppe `{status, payload, message}` et le format du journal. La
lire avant d'implémenter, et ne pas la modifier pour faire passer du code.

En place et fourni : le corpus (`data/corpus/`, ~400 documents), `docs/schema.sql`,
`scripts/seed.py` (base SQLite déterministe), `eval/questions_rag.jsonl` et
`questions_sql.jsonl`, `scripts/mcp_client.py`, le `Makefile`, `docker-compose.yml`.

Construit : `mcp_server/` (deux canaux), `gateway/` (matrice, journal, les 8
tools), `ingest/`, `retrieval/`, `sql/`, `ui/` (app bot). Reste l'étape 5
(externalisation de la matrice, rôles PostgreSQL) et l'étape 6 (déploiement).

`ROADMAP.md` donne l'ordre des chantiers et l'état de chacun.

## Ce qu'on construit

La **Sorabel Data Gateway** : un serveur MCP unique, gouverné, qui expose à tous
les clients internes (bot Slack support, IDE, poste commercial) deux capacités —
recherche documentaire RAG et interrogation SQL en langage naturel — sous une
matrice d'accès commune.

Trois chantiers, dans cet ordre de dépendance :

1. **RAG** — ingestion (PDF/HTML/Markdown → normalisation → dédoublonnage par
   version → chunking + métadonnées) → indexation Chroma → retrieval dense, puis
   hybride (dense + lexical) + reranking.
2. **Text-to-SQL** — `get_schema` (schéma commenté) → génération → **validation**
   → exécution lecture seule → résultat *accompagné de la requête générée*.
3. **Serveur MCP** — catalogue de tools + matrice d'accès + journalisation.

### Catalogue de tools imposé

RAG : `answer_question` (haut niveau), et ses briques utilisables séparément —
`search_docs`, `get_document`, `list_sources`.
Données : `ask_database` (génératif), `get_schema` (aide), et les tools figés
paramétrés `check_stock(ref)`, `order_status(order_id)`.

Le découpage haut niveau / briques est une exigence, pas un détail : un client
IDE doit pouvoir chercher sans générer de réponse.

## Invariants non négociables

Ils viennent de E1–E6 et des tests d'acceptance. Ne jamais les simplifier :

- **Citations systématiques** (titre + référence + date) sur toute réponse
  documentaire ; en dessous du seuil de pertinence, l'outil dit qu'il ne sait pas
  au lieu d'inventer.
- **Recherche par référence exacte** (`REF-8842`) aussi fiable que par question
  naturelle — c'est la raison d'être de l'hybride, le dense seul rate les
  identifiants.
- **SQL lecture seule, en défense multiple** : droits de la connexion *et*
  validation de la requête générée *et* `LIMIT` par défaut. Une seule barrière ne
  suffit pas (exigence explicite du brief).
- **Périmètre par profil** : le profil support ne voit jamais prix d'achat ni
  marges — filtrage au niveau des tables *et* des colonnes.
- **Refus propre** plutôt que hallucination : question hors corpus, hors schéma,
  ambiguë, ou tool non autorisé → message clair et code d'erreur distinguable
  d'une réponse.
- **Tout appel est journalisé**, autorisé comme refusé, avec le SQL exécuté quand
  il y en a.
- **Le gain hybride vs dense est chiffré** sur `eval/questions_rag.jsonl` et
  documenté — pas affirmé.

La matrice d'accès (client × tool × collections × tables/colonnes) est la source
de vérité unique de l'autorisation. Quand un contrôle est à ajouter, l'ajouter là
où tous les appels passent, pas dans le tool qui a motivé le ticket.

## Stack et commandes

Python géré par **uv** (cf. instructions globales) : `uv add`, `uv sync`,
`uv run <cmd>`. Chroma pour le vector store, SDK MCP Python pour le serveur,
Gemini pour la génération SQL et la synthèse RAG. L'app bot (`ui/`) est une
application Next.js + CopilotKit, en npm.

Tout passe par le `Makefile` :

| | |
|---|---|
| `make install` · `make seed` · `make up` | dépendances, base SQLite, Chroma |
| `make test` | la suite d'acceptance — la spécification |
| `make eval` · `make eval-sql` | mesures E6 (RAG) et contrôle du Text-to-SQL |
| `make lint` · `make fmt` | ruff + mypy |
| `make serve` · `make serve-http` | serveur MCP, canal stdio ou HTTP |
| `make client` | client de test (`PROFILE=support\|commercial`, ou `--http`) |
| `make ui-install` · `make ui` | app bot sur localhost:3000 |
| `make ui-fmt` | Biome : formatage et imports inutilisés de `ui/` |

## Langue

Code, tests et messages d'erreur développeur en anglais ; documentation, logs et
messages destinés aux équipes métier en français (les refus renvoyés aux clients
MCP sont lus par des humains → français).

## Convention de commit et de PR

Conventional Commits 1.0.0. Messages de commit et titres de PR **en anglais**.

Format : `<type>(<scope>): <description>`

Types : feat | fix | refactor | test | docs | chore | perf | ci | build
Scopes : ingest | retrieval | sql | gateway | mcp | ui | eval | infra

Les scopes suivent les modules du dépôt. `gateway` couvre la matrice d'accès,
le décorateur et le journal — tout ce qui gouverne ; `mcp` couvre les deux
canaux (stdio et HTTP), qui ne sont qu'un transport. `ui` couvre l'app bot,
front et route API confondus : un scope de plus ne dirait rien qu'un chemin de
fichier ne dise déjà.

Règles :
- description en anglais, à l'impératif, en minuscules, sans point final, ≤ 72 caractères
- `!` après le scope pour une rupture de compatibilité (`feat(gateway)!:`)
- un commit = un changement logique ; ne jamais mélanger refactor et feat
- ne jamais committer avec des tests en échec

Exemples :

```
feat(retrieval): add RRF fusion of dense and lexical hits
fix(sql): reject qualified columns outside the profile scope
test(eval): add reference_exacte cases to the RAG golden set
refactor(mcp)!: move tool registration into gateway/tools.py
chore(ui): pin gemini model instead of the -latest alias
```

Les titres de PR suivent le même format
