# Roadmap

Ordre choisi : **le canal de démo d'abord**, pour voir chaque brique fonctionner
dès qu'elle existe. Tout tourne en local jusqu'à l'étape 6.

La suite `tests/acceptance/` est la spécification et reste rouge tant que les
briques ne sont pas là — c'est normal, elle sert de compteur d'avancement.

---

## 1 · App bot + squelette MCP — *le circuit vide* — **fait**

Un chat qui parle à un serveur MCP qui ne sait encore rien faire. L'intérêt est
de valider la chaîne complète avant d'y mettre quoi que ce soit de coûteux.

- `mcp_server/http_server.py` — Streamable HTTP, un seul tool `ping`
- `ui/` — Next.js, CopilotKit UI + runtime sur `/api/copilotkit`, adapter Gemini
- `ui/.env.local` — `GOOGLE_API_KEY`, `MCP_URL`

**Vérification** : dans le chat, « appelle ping » déclenche `tools/call` et la
réponse s'affiche.

**Résultat des deux spikes** :
- **Header custom vers un MCP distant : oui.** CopilotKit 1.70 expose
  `mcpServers: [{ type: "http", url, options: { fetch } }]` ; le `fetch` enveloppé
  y injecte `X-Sorabel-Profile`. Vérifié de bout en bout — le tool `ping` renvoie
  le profil vu par le serveur. Le repli « profil dans l'URL » est abandonné.
- **Profil par requête** : `CopilotRuntime({ agents: ({ request }) => … })` lit
  l'en-tête posé par `<CopilotKit headers>` et construit l'agent en conséquence.
  Un seul endpoint runtime pour les trois profils.
- **API Gemini** : reste à confirmer avec une vraie clé (`GOOGLE_API_KEY`
  d'AI Studio). Google AI Pro est un abonnement grand public, il ne donne pas de
  quota API — voir le README.

---

## 2 · Serveur MCP complet — *les 8 tools, vides*

Le catalogue au complet, chaque tool renvoyant une enveloppe conforme avec des
données factices.

- `gateway/tools.py` — les 8 fonctions, signatures définitives
- `gateway/access.py` — enveloppe `{status, payload, message}` + journal JSONL
- `mcp_server/server.py` — canal **stdio** (celui que lancent les tests)
- `mcp_server/http_server.py` — canal HTTP, mêmes tools
- `resolve_profile()` — header s'il existe, sinon `SORABEL_PROFILE`

**Vérification** : `make test` ne tombe plus sur « module introuvable » ;
`tests/acceptance/test_mcp.py::test_journal_exhaustif` passe.

Deux contraintes de la suite à respecter dès maintenant :
- **une entrée de journal par appel**, ni plus ni moins (égalité stricte) ;
- **30 s de timeout** et un process relancé à chaque session : chargement des
  modèles **paresseux**.

---

## 3 · RAG — *la première vraie démo*

- `ingest/` — normalisation PDF/HTML/MD, métadonnées déclarées, dédoublonnage
  par `doc_id`, un chunk par document, indexation Chroma (docker, port 8002)
- `retrieval/` — dense, puis hybride, puis rerank ; **les trois modes exposés**
  par `search_docs(mode=…)`, c'est l'instrument de mesure de E6
- routage par référence : `REF-\d+` détectée ⇒ pré-filtre `product_ref $in [...]`
- gate de pertinence après rerank ⇒ `status: hors_corpus` sans génération
- `answer_question` — citations construites **depuis les métadonnées**
- `eval/run_eval.py` → `eval/rapport_gain.md`

**Vérification** : `test_rag.py` au vert (4 tests). Dans le bot : une question
métier reçoit une réponse sourcée, une question hors corpus un refus.

---

## 4 · Text-to-SQL

- `make migrate` — SQLite → **PostgreSQL local** (docker). `data/sorabel.db`
  reste : `conftest.py` s'en sert pour calculer les attendus.
- `sql/schema.py` — introspection : le dict pour `sqlglot` **et** le DDL commenté
  du prompt viennent de la même source
- `sql/guard.py` — 5 étapes : parsing, périmètre, `LIMIT`, `EXPLAIN`, plafond de
  coût. Retry (1 max) **uniquement** après une erreur de syntaxe
- `sql/generate.py` — tri avant génération, 7 few-shots, `payload.rows` en
  **liste de listes**
- `check_stock(reference)` / `order_status(order_id)` — SQL paramétré, sans LLM

**Vérification** : `test_sql.py` au vert (4 tests). Dans le bot : « combien de
commandes en avril ? » répond juste, avec le SQL dépliable.

---

## 5 · Matrice d'accès et gouvernance

- `access.yaml` — profils × tools × collections × tables/colonnes
- `roles.sql` — un rôle PostgreSQL par profil, `GRANT SELECT` colonne par colonne
- `@tool_access` posé sur les 8 fonctions — même un appel Python direct y passe
- `tools/list` **filtré par profil**
- pools : un par rôle, `min=1 max=3`, test de connexion avant emprunt
- sélecteur de profil dans le bot

**Vérification** : `test_mcp.py` au vert, `make test` entièrement vert.
`scripts/mcp_client.py` démontre support vs commercial côte à côte.

---

## 6 · Déploiement

- PostgreSQL : bascule du docker local vers le **serveur Azure Flexible
  existant**, base dédiée. `roles.sql` doit inclure un
  `REVOKE CONNECT ON DATABASE <autre_base>` par rôle — les rôles sont au niveau
  du serveur, pas de la base.
- Chroma : index construit au `docker build` et **embarqué dans l'image**
  (Cloud Run est sans état).
- Journal : doublé sur `stdout` → Cloud Logging.
- Deux services **Cloud Run** : le Python, et l'app Next.js.
- Réseau : **VPC connector + Cloud NAT** pour une IP sortante fixe, à
  whitelister côté Azure. À valider tôt, c'est le point le plus susceptible de
  bloquer une mise en ligne.
- `require authentication` IAM sur le service Python ; `scripts/mcp_client.py`
  devra présenter un jeton (`gcloud auth print-identity-token`).
- `min-instances=1` pendant la soutenance : le chargement des modèles rend le
  démarrage à froid trop long.

**Vérification** : la démo tourne depuis l'URL Cloud Run, journal consultable.

---

## Ce qui reste ouvert

- **Seuil de pertinence** (E1) et **pondération RRF** — à calibrer sur le jeu
  d'éval, pas à choisir d'avance.
- **Plafond de coût SQL** — à régler pour qu'aucune des 12 questions métier
  légitimes ne tombe dessus.
- **Profil `dev`** — prévu par la conception, absent des tests fournis. À ajouter
  seulement s'il sert la démo.
