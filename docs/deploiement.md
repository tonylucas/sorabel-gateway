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
| `sorabel-mcp` — le service Python | `Accesseur de secrets Secret Manager`, `Rédacteur de journaux` |
| `sorabel-ui` — l'app Next.js | `Accesseur de secrets Secret Manager`, `Rédacteur de journaux`, **`Demandeur Cloud Run`** |

Le dernier rôle est la barrière 1 du modèle de confiance : le service Python
est déployé en *authentification requise*, et seul `sorabel-ui` peut l'appeler.

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
REGISTRY=europe-north1-docker.pkg.dev/projet-perso-f22c7/sorabel
TAG=$(git rev-parse --short HEAD)

docker build --platform linux/amd64 -t $REGISTRY/mcp:$TAG .
docker push $REGISTRY/mcp:$TAG

docker build --platform linux/amd64 -t $REGISTRY/ui:$TAG ui/
docker push $REGISTRY/ui:$TAG
```

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
| Nombre minimal d'instances | **1** | le modèle d'embeddings rend le démarrage à froid trop long |
| Nombre maximal d'instances | 3 | le plafond de connexions du serveur Azure |

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
`/mcp`, plus les secrets `GOOGLE_API_KEY` et `SORABEL_KEY`.

Pas de connexion VPC ici : l'app bot ne parle qu'à Cloud Run et à Gemini, jamais
à PostgreSQL.

> **Après la soutenance**, remettre `sorabel-mcp` à *nombre minimal
> d'instances* `0` et supprimer la passerelle NAT. Ce sont les deux seuls postes
> qui courent quand personne ne se sert du service.

### En ligne de commande, pour rejouer à l'identique

```sh
REGISTRY=europe-north1-docker.pkg.dev/projet-perso-f22c7/sorabel
TAG=$(git rev-parse --short HEAD)

gcloud run deploy sorabel-mcp --image $REGISTRY/mcp:$TAG \
  --region europe-north1 --no-allow-unauthenticated \
  --service-account sorabel-mcp@projet-perso-f22c7.iam.gserviceaccount.com \
  --network default --subnet default --vpc-egress all-traffic \
  --min-instances 1 --max-instances 3 \
  --set-secrets PG_SUPPORT=pg-support:latest,GOOGLE_API_KEY=gemini-api-key:latest

gcloud run services add-iam-policy-binding sorabel-mcp --region europe-north1 \
  --member serviceAccount:sorabel-ui@projet-perso-f22c7.iam.gserviceaccount.com \
  --role roles/run.invoker
```

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

Enfin, depuis le poste, en pointant le client de test sur l'URL du service :

```sh
MCP_URL=<url Cloud Run>/mcp make client PROFILE=support
```

Le service exigeant une authentification, le client doit présenter un jeton
d'identité — `gcloud auth print-identity-token`.
