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

**Résultat des deux spikes** :
- **Header custom vers un MCP distant : oui.** CopilotKit 1.70 expose
  `mcpServers: [{ type: "http", url, options: { fetch } }]` ; le `fetch` enveloppé
  y injecte `X-Sorabel-Profile`. Vérifié de bout en bout — le tool `ping` renvoie
  le profil vu par le serveur. Le repli « profil dans l'URL » est abandonné.
- **Profil par requête** : `CopilotRuntime({ agents: ({ request }) => … })` lit
  l'en-tête posé par `<CopilotKit headers>` et construit l'agent en conséquence.
  Un seul endpoint runtime pour les trois profils.
- **API Gemini : oui, sur un projet sans facturation.** Google AI Pro ne donne
  pas de quota API, et un projet GCP en prépaiement épuisé renvoie `429` sans
  retomber sur le free tier. Un projet neuf, non lié à un compte de facturation,
  est sur le free tier et répond. Modèle : `gemini-3.6-flash` — les `2.5` ne sont
  plus servies aux nouveaux projets (404). Raisonnement coupé par
  `thinkingConfig.thinkingLevel: "minimal"` — 0 token de pensée mesuré, contre
  329 par défaut ; `thinkingBudget: 0` est refusé sur les Gemini 3.
- **Latence du free tier : ~13 s par appel**, quel que soit le raisonnement (une
  boucle « choisir un tool puis rédiger » prend ~27 s). C'est le tier, pas le
  modèle. À surveiller : la suite d'acceptance coupe à 30 s par appel, et
  `ask_database` fera un appel Gemini depuis Python. Si ça frotte, basculer sur
  un projet facturé ou sur Vertex AI.

---

## 2 · Serveur MCP complet — *les 8 tools, vides* — **fait**

Le catalogue au complet, chaque tool renvoyant une enveloppe conforme et une
charge utile vide.

- `gateway/tools.py` — les 8 fonctions, signatures définitives
- `gateway/access.py` — enveloppe `{status, payload, message}` + journal JSONL
- `mcp_server/server.py` — canal **stdio** (celui que lancent les tests)
- `mcp_server/http_server.py` — canal HTTP, mêmes tools
- `resolve_profile()` — header s'il existe, sinon `SORABEL_PROFILE`

**Vérification** : `make test` donne **17 passés / 9 échoués**, et les neuf
restants attendent tous un moteur — quatre pour le RAG (étape 3), quatre pour le
SQL (étape 4), plus `test_briques_du_rag_utilisables_separement`, qui a besoin
de vrais résultats de recherche. Les trois tests de `test_mcp.py` qui portent sur
la matrice, le refus et le journal passent.

Les charges utiles des tools sont **vides, pas factices** : une donnée bidon
ferait passer `test_rag` pour de mauvaises raisons et masquerait le travail
restant.

Deux contraintes de la suite à respecter dès maintenant :
- **une entrée de journal par appel**, ni plus ni moins (égalité stricte) ;
- **30 s de timeout** et un process relancé à chaque session : chargement des
  modèles **paresseux**.

---

## 3 · RAG — *la première vraie démo* — **fait**

- `ingest/` — normalisation PDF/HTML/MD, métadonnées déclarées, dédoublonnage
  par `doc_id`, un chunk par document, indexation Chroma (docker, port 8002)
- `retrieval/` — dense, puis hybride, puis rerank ; **les trois modes exposés**
  par `search_docs(mode=…)`, c'est l'instrument de mesure de E6
- routage par référence : `REF-\d+` détectée ⇒ pré-filtre `product_ref $in [...]`
- gate de pertinence après rerank ⇒ `status: hors_corpus` sans génération
- `answer_question` — citations construites **depuis les métadonnées**
- `eval/run_eval.py` → `eval/rapport_gain.md`

**Vérification** : `make test` donne **34 passés / 4 échoués**, les quatre
restants étant ceux du Text-to-SQL (étape 4). `test_rag.py` et `test_mcp.py` sont
au vert.

**Gain mesuré** (`eval/rapport_gain.md`, régénérable par `make eval`) :

| Mode | `reference_exacte` | `couverte` |
|---|---|---|
| dense (baseline) | **0 %** | 79 % |
| lexical | 100 % | 86 % |
| **hybride** | **100 %** | **93 %** |

Le dense à 0 % sur la référence exacte est le résultat attendu : `REF-8842` n'a
pas de sens à encoder, c'est une chaîne. Le routage par référence appartient à
l'hybride, pas à la baseline — sans quoi la comparaison serait truquée.

Porte de pertinence : **8/8 refus corrects, 20/22 réponses correctes**, et
surtout **aucune réponse hors corpus** — c'est la contrainte de calibrage, une
réponse manquée coûte moins qu'une réponse inventée.

**Reranking écarté**, pas oublié : le Recall@5 par référence exacte est déjà à
100 %, un cross-encoder ne peut rien y améliorer, et il pèse 1 Go de plus dans
l'image Cloud Run. À reprendre si le corpus grossit.

**Réponse extractive**, pas générée côté serveur : les documents font une page,
le passage *est* la réponse, et le LLM du host la met en forme en la recevant
comme *tool result*. Une génération de plus côté Python coûterait une latence et
un quota pour reformuler ce qu'on a déjà.

---

## 4 · Text-to-SQL — **fait**

- `sql/schema.py` — `docs/schema.sql` lu **une seule fois** : il produit le DDL
  commenté du prompt *et* le dictionnaire de colonnes de `sqlglot.qualify()`.
  Ce que le modèle croit interrogeable ne peut pas diverger de ce que le garde
  autorise. Filtré par profil, comme tout le reste.
- `sql/guard.py` — trois refus, la sécurité avant la base : un seul `SELECT`
  (`write_attempt`), tables et colonnes du profil (`forbidden_column`), puis
  `LIMIT` injecté et `EXPLAIN`.
- `sql/generate.py` — **tri et génération en un seul appel** : le modèle répond
  en JSON avec une décision parmi `sql` / `ecriture` / `hors_schema` / `ambigue`.
  Deux appels doubleraient la latence pour une décision qu'il prend de toute
  façon en lisant le schéma.
- `sql/db.py` — connexion `mode=ro` + `PRAGMA query_only`, `rows` en liste de
  listes.
- `check_stock(reference)` / `order_status(order_id)` — SQL paramétré, sans LLM.

**Vérification** : `make test` est **entièrement vert** — 61 tests, dont les 4
d'acceptance SQL. `make eval-sql` donne **24/24** sur `eval/questions_sql.jsonl`
(`eval/rapport_sql.md`), les trois quarts du jeu se jouant en *refusant*.

**Le prompt est filtré par profil sur trois plans** — DDL, exemples et
consignes. Le support ne lit nulle part les mots `ventes`, `marge_pct`,
`marge_ht`, `prix_achat_ht` : il ne peut pas produire la requête qu'on lui
refuserait, et il n'apprend pas au passage ce qu'on lui cache. Épinglé par
`tests/test_guard.py`, qui tourne sans appeler le modèle.

Conséquence : les quatre cas `table_interdite` sont refusés en `out_of_schema`
plutôt qu'en `forbidden_column` — le modèle ne voit pas la colonne, la requête
interdite n'est jamais produite. `forbidden_column` reste la réponse du garde
quand elle l'est malgré tout, couvert par les tests unitaires.

**Deux mesures qui ont changé le code**, et non l'inverse :

- Le DDL fourni annote les colonnes sensibles d'un `-- SENSIBLE : … — ne sort
  jamais pour le profil support`. Ces annotations sont **retirées** du DDL
  envoyé au modèle : le filtrage par profil ayant déjà ôté la colonne à qui
  elle est interdite, la phrase ne décrivait plus qu'une règle inapplicable au
  lecteur — et le modèle, lisant « ne sort jamais », refusait. SQL-11 est passé
  de 1/3 à 5/5.
- Le jeu de few-shots du dossier de conception n'enseignait pas l'agrégation sur
  `ventes` filtrée par période, qui exige la jointure vers `commandes`. Un
  huitième exemple l'enseigne — sur une question différente de SQL-11 : on
  apprend la jointure, pas la réponse.

**Toujours sur SQLite.** La bascule PostgreSQL est reportée à l'étape 6, où elle
sert à quelque chose : `conftest.py` calcule ses attendus sur `data/sorabel.db`,
la CI n'a pas de service Postgres, et le dialecte tient dans la constante
`sql.schema.DIALECT`. À l'étape 5, les `GRANT` colonne par colonne deviendront
la source de vérité de `sql_scope()` — dont la signature ne bougera pas.

**Écarté, pas oublié** : le retry après erreur de syntaxe (le free tier répond
entre 1 s et 30 s, un second appel ferait sauter le budget de 30 s de la suite),
et le plafond de coût `EXPLAIN` (SQLite n'estime pas de coût — à reprendre avec
PostgreSQL, où `EXPLAIN` en donne un).

**Risque connu** : le free tier plafonne à **15 requêtes/minute** par modèle et
par projet, et rend des `504` sporadiques. `make eval-sql` cadence ses appels et
compte les incidents à part ; la CI relève `GATEWAY_TEST_TIMEOUT` à 60 s. Un
projet facturé ou Vertex AI supprime les deux.

## 5 · Matrice d'accès et gouvernance — **fait**

- `access.yaml` — profils × tools × collections × tables/colonnes, à la racine :
  un document de gouvernance, relu et amendé sans toucher au code.
  `gateway/access.py` en est la **seule** lecture (`can`, `tools_of`,
  `collections`, `sql_scope`) ; aucun tool n'ouvre le fichier.
- **validé au chargement** — un tool, une collection ou une colonne interdite
  mal orthographiés arrêtent le démarrage. C'est la frontière de confiance de
  l'autorisation : `note_intern` au lieu de `note_interne`, et le filtre ne
  correspond plus à rien, donc le support hérite des notes internes. Une faute
  y coûte un démarrage, pas une fuite.
- `tools/list` **filtré par profil** (`mcp_server/app.py`) — le support annonce
  7 tools, le commercial 8.
- `mcp_server/profile.py` lit désormais les profils connus dans la matrice : un
  profil ajouté au YAML est accepté par le résolveur sans retouche, et celui-ci
  ne peut pas en connaître un que la matrice ignore.
- **Un profil inconnu n'a droit à rien** — le repli sur `support` se joue à la
  résolution du profil, pas dans le périmètre : hériter des droits du support
  serait une élévation de privilège silencieuse.
- `@tool_access` posé sur les 8 fonctions — **déjà en place depuis l'étape 2**.
- sélecteur de profil dans le bot — **déjà en place depuis l'étape 1**.
- `scripts/mcp_client.py --compare` (`make demo`) — le même appel joué en
  support puis en commercial, catalogue annoncé compris.

**Le filtrage porte sur la découverte, pas sur l'exécution.** Les huit fonctions
restent enregistrées : un appel hors matrice doit revenir en refus métier
(`{status: refused}`, journalisé, explicable par le host), pas en erreur de
protocole « unknown tool » — que le journal ne verrait pas passer et qu'un host
lirait comme une panne. C'est aussi ce qu'exige `test_matrice_d_acces_respectee`,
qui appelle les tools hors matrice et attend une enveloppe. Le prix est un
`WARNING` du SDK à chaque appel filtré (« tool not listed, no validation ») :
sans conséquence, nos tools rendant du texte.

**`roles.sql` et les pools par rôle partent à l'étape 6**, avec la bascule
PostgreSQL. Les installer ici — psycopg, un Postgres local, `migrate.py` — pour
que `has_column_privilege` renvoie exactement ce que le YAML dit déjà serait du
travail à double : la CI n'a pas de service Postgres et `conftest.py` calcule
ses attendus sur `data/sorabel.db`. Le seul gain, un garde qui ne peut pas
diverger de la base, n'existe que le jour où il y a une base à faire diverger.
`sql_scope()` gardera sa signature.

**Vérification** : `make test` entièrement vert — **70 tests**, dont 9 neufs sur
le chargement de la matrice, sa validation et le catalogue filtré.
`make demo` montre les deux profils côte à côte :

```
support     7 tools annoncés : answer_question, ask_database, check_stock, …
            → refused · unauthorized_tool
              Ce profil n'a pas accès à cet outil. …
commercial  8 tools annoncés : answer_question, ask_database, check_stock, get_schema, …
            → ok
```

---

## 6 · Déploiement

- PostgreSQL : bascule du docker local vers le **serveur Azure Flexible
  existant**, base dédiée. `roles.sql` doit inclure un
  `REVOKE CONNECT ON DATABASE <autre_base>` par rôle — les rôles sont au niveau
  du serveur, pas de la base.
- **`roles.sql` et les pools par rôle** (reportés de l'étape 5) : un rôle par
  profil, `GRANT SELECT` colonne par colonne, `default_transaction_read_only` ;
  un pool par rôle, `min=1 max=3`, test de connexion avant emprunt (Cloud Run
  endort les instances, Azure coupe les connexions inactives). `sql_scope()`
  lira alors `has_column_privilege` au lieu du bloc `sql` d'`access.yaml` — sa
  signature ne bouge pas, seule sa source change.
- **Plafond de coût `EXPLAIN`** : possible seulement ici, SQLite n'estime pas de
  coût.
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
- **Plafond de coût SQL** — sans objet sur SQLite, qui n'estime pas de coût. À
  régler à l'étape 6, sur PostgreSQL.
- **`get_schema` pour `commercial`** — tranché en faveur du `conftest.py`
  fourni, qui l'accorde aux deux profils ; le dossier de conception le
  réservait au `dev`. La suite d'acceptance fait foi, `access.yaml` la suit —
  reste à répercuter dans le dossier de conception.
- **Profil `dev`** — gardé : il est dans `access.yaml` comme les deux autres,
  aucun test ne le couvre, et il ne coûte rien. La démonstration de la matrice
  se joue sur `support` vs `commercial`.
