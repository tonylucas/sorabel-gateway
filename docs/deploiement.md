# Déploiement — ce qu'il y a à configurer à la main

Le déploiement n'est pas automatisé : pas de CD, pas de pipeline. Ce document
est la liste des actions à faire soi-même, dans l'ordre, et de ce qu'elles
doivent produire.

**Tout ce qui se configure se fait depuis les portails** — console Google Cloud
et portail Azure. C'est délibéré : le but est de connaître les plateformes, pas
de coller des commandes. Chaque étape donne son équivalent CLI en fin de
section, comme rappel et comme moyen de vérifier ce que le portail a produit —
pas comme raccourci.

Seul ce qui relève du code — migration, rôles, images — est joué depuis le poste
via le `Makefile`, avec les mots de passe pris dans le `.env` local et jamais
écrits dans le dépôt.

## Ce qui existe déjà

| | |
|---|---|
| Serveur PostgreSQL | `tony-velmo` — `tlucasRG`, Sweden Central, PG 18, Burstable B1ms, 32 Gio |
| FQDN | `tony-velmo.postgres.database.azure.com` |
| Accès public | activé ; pare-feu : IP du poste + services Azure |
| Base voisine | `velmo` — **sur le même serveur**, donc les rôles créés y seront visibles (§ 2.4) |
| Projet d'infrastructure | `projet-perso-f22c7` (« Sorabel »), facturation activée |
| Projet de la clé Gemini | `api-projet-perso`, **sans facturation** |
| Région retenue | **`europe-north1`** (Finlande) — la région Cloud Run la plus proche de Sweden Central |

## Pourquoi deux projets Google Cloud

Cloud Run, Artifact Registry et Cloud NAT exigent un compte de facturation lié
au projet. Le free tier de l'API Gemini exige l'inverse : un projet *sans*
facturation, sans quoi les appels basculent au tarif payant — et échouent en
`prepayment credits are depleted` dès que le solde est vide.

Les deux contraintes ne tiennent pas dans un projet. On en garde donc deux :

| Projet | Facturation | Porte |
|---|---|---|
| `api-projet-perso` | **non** | la clé API Gemini, et rien d'autre |
| `projet-perso-f22c7` | oui | Cloud Run, Artifact Registry, réseau, secrets |

Une clé API Gemini est un identifiant portable : le service déployé dans le
projet facturé la présente et est servi sur le quota free tier
d'`api-projet-perso`. Rien à changer dans le code, seule la **valeur** de
`GOOGLE_API_KEY` change.

## Le budget, et ce qu'il impose

Un seul crédit est actif sur le compte `018EF2-F0B44E-ED34CB` : le bonus
mensuel du Google Developer Program, **8,59 € par mois**, de portée « all of
Google Cloud Platform ». Le crédit *Free Trial* affiche encore 263,69 € mais il
a expiré le 2025-08-15 : il n'est pas mobilisable.

Deux postes dépassent ce plafond à eux seuls s'ils tournent au mois :

| Poste | Ordre de grandeur | Décision |
|---|---|---|
| Cloud NAT | ~1 €/jour, soit le crédit en 8 jours | créé la veille de la soutenance, supprimé après |
| `--min-instances 1` | une instance allumée en permanence | mis à `1` le jour même, remis à `0` ensuite |
| Adresse IP réservée | quelques centimes par jour | gardée : elle survit à la suppression du NAT et évite de retoucher le pare-feu Azure |

Le reste — Artifact Registry, Cloud Logging, Cloud Run au repos — tient
largement dans le crédit.

Aucun budget n'est configuré sur le compte de facturation, et `gcloud` ne sait
pas dire ce qui a été dépensé : l'API Cloud Billing expose les comptes, les
projets et les budgets, jamais un montant consommé ni le solde d'un crédit. Ces
deux chiffres ne se lisent que dans la console (*Facturation → Rapports* et
*Facturation → Crédits*), ou dans un export BigQuery qui n'existe pas ici. Une
alerte de budget à 8,59 € est donc le seul garde-fou automatique disponible —
elle prévient avant l'épuisement, là où une estimation à la main ne prévient de
rien.

> Si cette fenêtre courte est trop contraignante, l'alternative n'est pas un
> réglage mais un déplacement : **Azure Container Apps**, dans l'abonnement qui
> porte déjà `tony-velmo`. Le service et la base sont alors dans le même cloud,
> ce qui supprime le VPC, le NAT, l'IP réservée et la règle de pare-feu — soit
> le poste de coût principal et le risque de mise en ligne que le plan désignait
> comme le plus élevé. Les PR 1 à 4 sont les mêmes dans les deux cas.

---

## 1 · Google Cloud — depuis la console

Tout ce qui suit se fait sur <https://console.cloud.google.com>, projet
**Sorabel** sélectionné.

### 1.1 Le projet de la clé Gemini

Le projet `api-projet-perso` existe déjà et n'a **pas** de compte de
facturation associé : c'est cela, et rien d'autre, qui vaut le free tier à une
clé. Ne pas lui en associer un.

*API et services → Activer des API et des services* → **Generative Language
API**. Puis, sur <https://aistudio.google.com/apikey>, *Créer une clé API*
**dans ce projet**.

La nouvelle valeur remplace `GOOGLE_API_KEY` dans `.env` et dans `ui/.env`, et
c'est elle qu'on met en secret à l'étape 1.6.

### 1.2 Activer les API

Sur le projet d'infrastructure — `projet-perso-f22c7`, pas celui du dessus.
*API et services → Activer des API et des services*, une par une :

| API | Pour |
|---|---|
| Cloud Run Admin API | les deux services |
| Artifact Registry API | héberger les images |
| Compute Engine API | le VPC, le routeur, le NAT |
| Secret Manager API | mots de passe et clés |
| Cloud Logging API | le journal des appels |

Pas de Cloud Build : les images sont construites sur le poste et poussées
telles quelles.

### 1.3 Réserver l'adresse IP de sortie

*Réseaux VPC → Adresses IP → Réserver une adresse statique externe*

- Nom : `sorabel-egress`
- Type : **Régional**, région **`europe-north1`**
- Niveau de service réseau : Premium

**Noter l'adresse obtenue** : c'est elle qu'on autorisera côté Azure, et c'est
la seule valeur de cette étape qui compte.

### 1.4 Cloud Router puis Cloud NAT

Sans ça, Cloud Run sort par des adresses qui changent, et le pare-feu Azure ne
peut rien autoriser de stable.

*Services réseau → Cloud NAT → Commencer*

- Nom de la passerelle : `sorabel-nat`
- Réseau : `default` · Région : `europe-north1`
- Cloud Router : *Créer un routeur* → nom `sorabel-router`
- Adresses IP NAT : **Personnalisé** → sélectionner `sorabel-egress`
- Tout le reste : valeurs par défaut

> **Coût.** Cloud NAT est le poste principal du déploiement, facturé à l'heure
> tant que la passerelle existe, plus le trafic. C'est de l'ordre de l'euro par
> jour. Le créer au moment de déployer, le supprimer après la soutenance — la
> passerelle se recrée en deux minutes, et l'IP réservée en 1.3 lui revient, donc
> sans retoucher au pare-feu Azure.

### 1.5 Dépôt d'images

*Artifact Registry → Créer un dépôt*

- Nom : `sorabel` · Format : **Docker** · Région : `europe-north1`

Puis, une seule fois sur le poste, pour que `docker push` sache s'authentifier :

```sh
gcloud auth configure-docker europe-north1-docker.pkg.dev
```

### 1.6 Comptes de service

*IAM et administration → Comptes de service → Créer*

| Compte | Rôles à lui donner |
|---|---|
| `sorabel-mcp` — le service Python | `Accesseur de secrets Secret Manager` |
| `sorabel-ui` — l'app Next.js | `Accesseur de secrets Secret Manager`, **`Demandeur Cloud Run`** |

Le dernier rôle est la barrière 1 du modèle de confiance : le service Python
est déployé en *authentification requise*, et seul `sorabel-ui` peut l'appeler.

Pas de `Rédacteur de journaux` : Cloud Run capture `stdout` et `stderr` du
conteneur pour son propre compte, sans que le compte de service ait le moindre
droit sur Cloud Logging. Ce rôle ne servirait qu'à une application qui
appellerait l'API Logging elle-même — ce que la gateway ne fait pas, elle
imprime.

### 1.7 Secrets

*Sécurité → Secret Manager → Créer un secret*, un par ligne :

| Nom du secret | Valeur |
|---|---|
| `pg-support` | mot de passe du rôle `sorabel_support` — à générer, 32 caractères |
| `pg-commercial` | idem pour `sorabel_commercial` |
| `pg-dev` | idem pour `sorabel_dev` |
| `pg-catalog` | idem pour `sorabel_catalog` |
| `gemini-api-key` | la clé AI Studio créée en 1.1 |
| `sorabel-key` | secret partagé entre l'app bot et la gateway — à générer |

Garder les quatre mots de passe PostgreSQL également dans le `.env` local (le
`.gitignore` le couvre déjà) : `scripts/roles.py` et `scripts/migrate.py` sont
joués depuis le poste et les liront là.

---

## 2 · Azure — depuis le portail

Sur <https://portal.azure.com>, abonnement *REMOTE_WCS_211537_DEV IA*,
ressource **`tony-velmo`** (groupe `tlucasRG`).

### 2.1 Créer la base dédiée

*tony-velmo → Paramètres → Bases de données → + Ajouter*

- Nom : `sorabel`
- Jeu de caractères : `UTF8` · Classement : `en_US.utf8`

La base voisine `velmo` reste intacte : on ajoute, on ne touche à rien.

### 2.2 Autoriser l'IP de sortie de Cloud Run

À faire **après** l'étape 1.3, avec l'adresse notée là-bas.

*tony-velmo → Paramètres → Mise en réseau → Règles de pare-feu → + Ajouter une
règle de pare-feu*

- Nom : `cloudrun-nat`
- IP de début et IP de fin : la même, l'adresse réservée en 1.3

Puis **Enregistrer** — le portail n'applique rien tant qu'on ne le fait pas.

Ne pas supprimer la règle `FirewallIPAddress_…` existante : c'est l'IP du
poste, et la migration comme la création des rôles partent de là, pas de
Cloud Run.

### 2.3 Vérifier que TLS est exigé

*tony-velmo → Paramètres → Paramètres du serveur*, chercher
`require_secure_transport`. Doit valoir **`on`**.

C'est ce qui rend `sslmode=require` obligatoire côté client. C'est la valeur par
défaut d'Azure : la confirmer plutôt que la supposer, parce qu'une `DATABASE_URL`
sans `sslmode` échouerait alors à la connexion, et non au premier `SELECT`.

### 2.4 Le serveur est partagé — ce qu'on ne fait pas, et pourquoi

Les rôles PostgreSQL vivent au niveau du **serveur**, pas de la base : les
quatre rôles créés par `make roles` seront visibles depuis `velmo`.

La roadmap prévoyait un `REVOKE CONNECT ON DATABASE velmo` par rôle.
`scripts/roles.py` ne le fait pas, et c'est volontaire : `PUBLIC` détient
`CONNECT` par défaut, donc révoquer le droit *du rôle* ne lui retire rien — il
continue de se connecter par `PUBLIC`. Le seul ordre efficace est

```sql
REVOKE CONNECT ON DATABASE velmo FROM PUBLIC;
```

qui porte sur **tous** les rôles du serveur, y compris ceux de l'application
`velmo`. L'automatiser reviendrait à risquer de couper une autre application
pour un gain nul ici : un rôle Sorabel qui se connecterait à `velmo` n'y a
aucun `GRANT`, donc n'y lit rien. À jouer à la main, en connaissance de cause,
si l'on veut fermer la porte plutôt que la pièce.

**Limite de connexions** : le tier Burstable B1ms plafonne aux alentours de 50,
**partagées avec `velmo`**. C'est ce plafond qui fixe `max_size=3` sur les
pools, et non la charge attendue.

### En ligne de commande, pour vérifier

```sh
az postgres flexible-server db list -g tlucasRG -s tony-velmo -o table
az postgres flexible-server firewall-rule list -g tlucasRG -s tony-velmo -o table
az postgres flexible-server parameter show \
  -g tlucasRG -s tony-velmo -n require_secure_transport --query value -o tsv
```

---

## 3 · Depuis le poste

Trois choses ne passent pas par un portail, parce qu'elles ne configurent rien :
les réglages locaux, la migration des données et la construction des images. Le
déploiement lui-même revient en console, § 4.

### 3.1 Le `.env`

Deux blocs s'ajoutent à `.env.example`. D'abord l'adresse du serveur, une
seule fois, en administrateur :

```sh
DATABASE_URL=postgresql://<admin>:<mot de passe>@tony-velmo.postgres.database.azure.com/sorabel?sslmode=require
```

`migrate.py` et `roles.py` s'y connectent : c'est la seule chose pour laquelle
ce compte sert. La gateway, elle, n'ouvre que des connexions de rôle — elle
reprend cette URL et n'en remplace que l'identité, si bien que le FQDN et le
nom de la base ne sont écrits qu'ici.

Puis un mot de passe par rôle, ceux générés à l'étape 1.7 :

```sh
PG_SUPPORT=…
PG_COMMERCIAL=…
PG_DEV=…
PG_CATALOG=…
```

### 3.2 Base et rôles

```sh
make seed        # SQLite de référence — inchangé, elle reste l'attendu des tests
make migrate     # SQLite → PostgreSQL, structure et données
make roles       # 4 rôles, GRANT SELECT colonne par colonne, dérivés d'access.yaml
```

### 3.3 Images

Les images sont construites sur le poste. **`--platform linux/amd64` n'est pas
facultatif** : un Mac Apple Silicon produit sinon une image `arm64` que Cloud
Run refuse au démarrage, sans message explicite.

```sh
make push        # construit les deux images et les pousse, tag = HEAD court
```

`REGISTRY` et `TAG` sont surchargeables (`make push TAG=demo`). Construire sans
pousser : `make images`.

**Committer avant de construire.** Le tag vient de `git rev-parse --short HEAD`
mais le contexte de build est l'arbre de travail : construire avec des
modifications non validées produit une image étiquetée d'un commit qui ne la
décrit pas, et que personne ne pourra reconstruire.

L'index Chroma est construit **pendant** le `docker build` du service Python et
embarqué dans l'image : Cloud Run est sans état, et le corpus ne bouge pas.
Redéployer, c'est réindexer.

---

## 4 · Déployer — console Cloud Run

*Cloud Run → Déployer un conteneur → Service*, deux fois. Les images sont déjà
dans Artifact Registry : le portail les propose dans un sélecteur, il n'y a rien
à taper.

### 4.1 Le service Python — `sorabel-mcp`

| Champ | Valeur | Pourquoi |
|---|---|---|
| URL de l'image | *Sélectionner* → `sorabel/mcp:<tag>` | poussée en 3.3 |
| Nom du service | `sorabel-mcp` | |
| Région | **`europe-north1`** | celle du NAT ; ailleurs, le service sortirait par une autre IP que celle autorisée chez Azure |
| Authentification | **Exiger une authentification** | barrière 1 du modèle de confiance |
| Entrée | **Tout** | voir ci-dessous — c'est le piège de cette page |
| Nombre minimal d'instances | **1** | le modèle d'embeddings rend le démarrage à froid trop long |
| Nombre maximal d'instances | **3** | le plafond de connexions du serveur Azure |

> **L'entrée réseau n'est pas la barrière.** En *Interne*, le frontend Google
> refuse tout ce qui n'arrive pas du VPC, **avant** d'évaluer IAM — et l'app bot
> n'a pas de connecteur VPC (§4.3), ses appels viennent de l'internet public.
> Le symptôme est une page `404 Page not found` renvoyée au client MCP, sans
> aucune trace dans les journaux du conteneur, qui n'a rien vu passer. Ce qui
> protège le service, c'est *Exiger une authentification* ; l'entrée fermée ne
> fait que l'isoler de son propre appelant.

> **Le nombre maximal d'instances n'est pas cosmétique.** `sql/db.py` ouvre un
> pool par profil, `max_size=3`, soit jusqu'à 12 connexions par instance sur
> quatre rôles. À 10 instances — la valeur par défaut — c'est 120 connexions
> demandées à un serveur Burstable B1ms qui en plafonne une cinquantaine,
> **partagées avec `velmo`** : la montée en charge casserait aussi la base
> voisine. À vérifier sur la révision et pas seulement sur le service : un
> `gcloud run services update` ultérieur peut réécrire le gabarit et perdre les
> valeurs posées par la console.

Puis déplier **Conteneurs, volumes, mise en réseau, sécurité** :

- **Conteneur → Paramètres** : port du conteneur `8000`.
- **Conteneur → Variables et secrets** :
  - variables : `DATABASE_URL` sans mot de passe n'aurait pas de sens — la mettre
    en secret elle aussi si l'admin y figure, sinon en variable ;
  - *Référencer un secret* pour `PG_SUPPORT`, `PG_COMMERCIAL`, `PG_DEV`,
    `PG_CATALOG`, `GOOGLE_API_KEY`, `SORABEL_KEY` → **Exposé en tant que
    variable d'environnement**, version `latest`.
- **Mise en réseau** : cocher *Se connecter à un VPC pour le trafic sortant*,
  puis **Envoyer tout le trafic vers le VPC** — réseau `default`, sous-réseau
  `default`. C'est ce réglage, et lui seul, qui fait passer les requêtes vers
  Azure par le NAT et donc par l'IP autorisée.

  En *Trafic privé uniquement*, les destinations publiques sortent en direct,
  par une adresse éphémère : le pare-feu Azure les refuse. Et une fois *tout le
  trafic* envoyé au VPC, **la passerelle NAT devient nécessaire à Gemini
  autant qu'à PostgreSQL** — `generativelanguage.googleapis.com` est un
  endpoint public comme un autre, et sans NAT le VPC n'a aucune route vers
  l'internet. Supprimer le NAT sans repasser en *Trafic privé uniquement*
  n'économise pas le SQL : ça coupe aussi la génération et la synthèse.
- **Sécurité** : compte de service `sorabel-mcp`.

### 4.2 Autoriser l'app bot à l'appeler

Le service exige une authentification : il faut nommer qui a le droit.

*Cloud Run → `sorabel-mcp` → onglet Sécurité (ou Autorisations) → Ajouter un
compte principal*

- Compte principal : le compte de service `sorabel-ui`
- Rôle : **Demandeur Cloud Run** (`roles/run.invoker`)

### 4.3 Le service Next.js — `sorabel-ui`

Même écran, mêmes région et image (`sorabel/ui:<tag>`), avec trois différences :

| Champ | Valeur |
|---|---|
| Authentification | **Autoriser les appels non authentifiés** — c'est l'interface, elle est publique |
| Nombre minimal d'instances | `0` |
| Compte de service | `sorabel-ui` |

Variables et secrets : `MCP_URL` = l'URL du service `sorabel-mcp` suivie de
`/mcp`, plus les secrets `GOOGLE_API_KEY` et `SORABEL_KEY` — **en références de
secrets, pas en variables** : une variable d'environnement se lit en clair dans
la description du service et dans les journaux de déploiement.

Pas de connexion VPC ici : l'app bot ne parle qu'à Cloud Run et à Gemini, jamais
à PostgreSQL.

> **Le quota Gemini est le point de rupture d'une démonstration.** Le free tier
> plafonne à une vingtaine de requêtes par jour *et par modèle*, et l'agent en
> consomme plusieurs par message. Les compteurs étant séparés par modèle, mettre
> `GEMINI_MODEL` sur le même modèle léger que la génération SQL
> (`sql/generate.py`) répartit la charge sans rebuild. Si ça ne suffit pas, la
> seule autre sortie est une clé prise dans le projet facturé — quelques
> centimes pour une heure de démonstration, mais on quitte le free tier.

### 4.4 Ce que l'app bot doit présenter — et que la console ne configure pas

Les deux barrières du modèle de confiance sont dans le code, pas dans les
formulaires. Il n'y a rien à cocher ici, mais tout à vérifier avant de conclure
que le déploiement fonctionne.

**Le jeton d'identité.** `sorabel-mcp` exigeant une authentification, chaque
requête doit porter un `Authorization: Bearer <jeton>`. L'app bot le prend sur le
serveur de métadonnées de son instance (`ui/app/identity.ts`), pour une audience
qui est l'**URL du service appelé, chemin exclu** — un jeton émis pour
`…/mcp` est rejeté comme s'il n'y en avait pas. Le symptôme d'un jeton absent est
un `403 Forbidden` du frontend Google, à ne pas confondre avec le `404` de
l'entrée réseau fermée.

Hors Cloud Run la variable `K_SERVICE` est absente : pas de jeton, et pas d'appel
au serveur de métadonnées — sans quoi chaque requête locale attendrait un échec
DNS.

**La clé partagée.** `SORABEL_KEY` est vérifiée par un middleware ASGI
(`mcp_server/http_server.py`), en comparaison à temps constant, et un client qui
ne la présente pas reçoit un `403` portant l'enveloppe habituelle
(`unauthorized_client`). Elle est la barrière 2 parce qu'IAM vérifie qu'un jeton
`run.invoker` accompagne la requête, **pas lequel** : tout compte de service à
qui ce rôle serait accordé parlerait à la gateway sans elle.

Sans `SORABEL_KEY` dans l'environnement, le contrôle est inactif — c'est ce qui
laisse `make serve-http` et la suite d'acceptance tourner en local. Le
déploiement arme la barrière en montant le secret ; un service déployé sans ce
secret est un service sans barrière 2, et rien ne le signalera.

> **Après la soutenance**, remettre `sorabel-mcp` à *nombre minimal
> d'instances* `0` et supprimer la passerelle NAT. Ce sont les deux seuls postes
> qui courent quand personne ne se sert du service.

### En ligne de commande, pour rejouer à l'identique

```sh
P=projet-perso-f22c7
REGISTRY=europe-north1-docker.pkg.dev/$P/sorabel
TAG=$(git rev-parse --short HEAD)
SECRETS=PG_SUPPORT=pg-support:latest,PG_COMMERCIAL=pg-commercial:latest
SECRETS=$SECRETS,PG_DEV=pg-dev:latest,PG_CATALOG=pg-catalog:latest
SECRETS=$SECRETS,GOOGLE_API_KEY=gemini-api-key:latest,SORABEL_KEY=sorabel-key:latest

gcloud run deploy sorabel-mcp --image $REGISTRY/mcp:$TAG \
  --region europe-north1 --no-allow-unauthenticated --ingress all \
  --service-account sorabel-mcp@$P.iam.gserviceaccount.com \
  --network default --subnet default --vpc-egress all-traffic \
  --min-instances 1 --max-instances 3 \
  --set-env-vars DATABASE_URL=… --set-secrets "$SECRETS"

gcloud run services add-iam-policy-binding sorabel-mcp --region europe-north1 \
  --member serviceAccount:sorabel-ui@$P.iam.gserviceaccount.com \
  --role roles/run.invoker

gcloud run deploy sorabel-ui --image $REGISTRY/ui:$TAG \
  --region europe-north1 --allow-unauthenticated \
  --service-account sorabel-ui@$P.iam.gserviceaccount.com \
  --min-instances 0 \
  --set-env-vars MCP_URL=<url de sorabel-mcp>/mcp \
  --set-secrets GOOGLE_API_KEY=gemini-api-key:latest,SORABEL_KEY=sorabel-key:latest
```

Les quatre mots de passe PostgreSQL doivent tous être montés : la gateway ouvre
un pool par rôle au premier appel du profil, y compris `sorabel_catalog` qui lit
le schéma. Un secret manquant ne se voit qu'à l'appel du tool qui en dépend.

`--set-env-vars` **remplace** toutes les variables, `--set-secrets` tous les
secrets : réécrire les deux listes en entier à chaque déploiement, ou passer par
`--update-env-vars` pour n'en changer qu'une.

---

## 5 · Vérifier

*Cloud Run → liste des services* : deux services, région `europe-north1`, une
révision servant 100 % du trafic chacun.

*Cloud Run → `sorabel-mcp` → onglet Journaux* : le journal des appels de la
gateway y apparaît, une ligne JSON par appel. Il part sur `stdout` en plus du
JSONL, parce qu'une instance recyclée emporte son système de fichiers — pas
Cloud Logging.

*Journalisation → Explorateur de journaux* pour filtrer : requête
`resource.type="cloud_run_revision"`, puis `jsonPayload.tool="ask_database"`
pour ne voir que les appels SQL, refus compris.

### Les deux barrières, à l'appel

```sh
U=<url Cloud Run>/mcp
T=$(gcloud auth print-identity-token)
INIT='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'

en_tetes=(-H "Content-Type: application/json" -H "Accept: application/json, text/event-stream")

# sans jeton -> 403 du frontend Google, en HTML : barrière 1
curl -s -o /dev/null -w '%{http_code}\n' -X POST "$U" "${en_tetes[@]}" -d "$INIT"

# jeton valide, clé absente ou fausse -> 403 de la gateway, en JSON : barrière 2
curl -s -X POST "$U" -H "Authorization: Bearer $T" "${en_tetes[@]}" \
  -H "x-sorabel-key: fausse" -d "$INIT"

# les deux -> 200
curl -s -o /dev/null -w '%{http_code}\n' -X POST "$U" -H "Authorization: Bearer $T" \
  "${en_tetes[@]}" -H "x-sorabel-key: <le secret>" -d "$INIT"
```

`initialize` suffit : pas besoin d'une session MCP établie. Les deux refus se
distinguent à l'œil — le premier est une page HTML de Google, le second
l'enveloppe `{status, payload, message}` de la gateway avec le code
`unauthorized_client`.

### Le client de test, sans manipuler de jeton

`gcloud` sait ouvrir un tunnel local authentifié, ce qui évite d'apprendre au
client de test à signer ses requêtes :

```sh
gcloud run services proxy sorabel-mcp --region europe-north1 --port 8080
# dans un autre terminal
MCP_URL=http://127.0.0.1:8080/mcp make client PROFILE=support
```

Le proxy injecte le jeton d'identité mais **pas** la clé partagée : avec la
barrière 2 armée, exporter `SORABEL_KEY` dans le terminal du client reste
nécessaire.

### L'index documentaire, tel qu'il sert

L'index est dans l'image, pas dans un service : il n'y a rien à interroger côté
GCP. L'image locale porte le même digest que la révision déployée, donc
l'inspecter en local revient au même — sans NAT, sans jeton, sans coût :

```sh
docker run --rm -i --platform linux/amd64 --entrypoint python \
  europe-north1-docker.pkg.dev/projet-perso-f22c7/sorabel/mcp:<tag> - <<EOPY
import chromadb
coll = chromadb.PersistentClient(path="/app/.chroma").get_collection("sorabel")
print(coll.count(), coll.metadata)
for m in coll.get(include=["metadatas"])["metadatas"][:10]:
    print(m["doc_type"], m["doc_id"], m["reference"], m["version"], m["date"], m["titre"])
EOPY
```

`list_sources` ne remplace pas cette inspection : le tool renvoie les catégories
visibles par le profil, pas l'inventaire des documents.
