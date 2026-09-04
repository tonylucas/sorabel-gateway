# Déploiement — ce qu'il y a à configurer à la main

Le déploiement n'est pas automatisé : pas de CD, pas de pipeline. Ce document
est la liste des actions à faire soi-même, dans l'ordre, et de ce qu'elles
doivent produire. Ce qui relève du code — migration, rôles, images — est joué
depuis le poste via le `Makefile`, avec les mots de passe pris dans le `.env`
local et jamais écrits dans le dépôt.

## Ce qui existe déjà

| | |
|---|---|
| Serveur PostgreSQL | `tony-velmo` — `tlucasRG`, Sweden Central, PG 18, Burstable B1ms, 32 Gio |
| FQDN | `tony-velmo.postgres.database.azure.com` |
| Accès public | activé ; pare-feu : IP du poste + services Azure |
| Base voisine | `velmo` — **sur le même serveur**, d'où le `REVOKE CONNECT` de `roles.sql` |
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
`.gitignore` le couvre déjà) : `roles.sql` et `migrate.py` sont joués depuis le
poste et les liront là.

---

## 2 · Azure — le pare-feu et la base

Le compte `az` du poste est déjà connecté sur le bon abonnement. Ces commandes
se collent telles quelles, mais rien n'empêche de les faire depuis le portail
(*tony-velmo → Mise en réseau* et *→ Bases de données*).

### 2.1 Créer la base dédiée

```sh
az postgres flexible-server db create \
  -g tlucasRG -s tony-velmo -d sorabel
```

### 2.2 Autoriser l'IP de sortie de Cloud Run

À faire **après** l'étape 1.3, avec l'adresse notée là-bas :

```sh
az postgres flexible-server firewall-rule create \
  -g tlucasRG -s tony-velmo -r cloudrun-nat \
  --start-ip-address <IP> --end-ip-address <IP>
```

La règle `FirewallIPAddress_…` existante (l'IP du poste) reste nécessaire : la
migration et la création des rôles partent du poste, pas de Cloud Run.

### 2.3 Vérifier que TLS est exigé

```sh
az postgres flexible-server parameter show \
  -g tlucasRG -s tony-velmo -n require_secure_transport --query value -o tsv
```

Doit rendre `on`. C'est ce qui rend `sslmode=require` obligatoire côté client —
la valeur par défaut d'Azure, à confirmer plutôt qu'à supposer.

> **Serveur partagé.** Les rôles PostgreSQL vivent au niveau du *serveur*, pas
> de la base : les quatre rôles créés seront visibles depuis `velmo`, et
> `PUBLIC` y a `CONNECT` par défaut. `roles.sql` révoque cet accès rôle par
> rôle. Le tier Burstable B1ms plafonne par ailleurs les connexions aux
> alentours de 50, **partagées avec `velmo`** : d'où des pools à `max_size=3`.

---

## 3 · Depuis le poste

Une fois les deux sections ci-dessus faites, plus rien ne se passe dans une
console web.

### 3.1 Le `.env`

Quatre variables s'ajoutent à celles de `.env.example` :

```sh
PGHOST=tony-velmo.postgres.database.azure.com
PGDATABASE=sorabel
PGUSER=<administrateur du serveur>
PGPASSWORD=<son mot de passe>
```

`migrate.py` et `roles.sql` s'y connectent en administrateur ; c'est la seule
chose pour laquelle ce compte sert. La gateway, elle, ne connaît que les rôles.

### 3.2 Base et rôles

```sh
make seed        # SQLite de référence — inchangé, elle reste l'attendu des tests
make migrate     # SQLite → PostgreSQL, structure et données
make roles       # 4 rôles, GRANT colonne par colonne, REVOKE CONNECT sur velmo
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

### 3.4 Déploiement

`make deploy` enchaîne les deux `gcloud run deploy`. Ce qu'ils portent, et qui
n'est pas négociable :

| Réglage | Sur quel service | Pourquoi |
|---|---|---|
| `--region europe-north1` | les deux | la région du NAT ; un service ailleurs sortirait par une autre IP |
| `--network default --subnet default --vpc-egress all-traffic` | Python | sortie par le NAT, donc par l'IP autorisée côté Azure |
| `--no-allow-unauthenticated` | Python | barrière 1 : seul `sorabel-ui` peut l'appeler |
| `--allow-unauthenticated` | Next.js | c'est l'interface, elle est publique |
| `--service-account` | les deux | les comptes de l'étape 1.6 |
| `--set-secrets` | les deux | les secrets de l'étape 1.7, jamais de valeur en clair |
| `--min-instances 1` | Python | le chargement du modèle d'embeddings rend le démarrage à froid trop long |

`--min-instances 1` se remet à `0` après la soutenance : c'est, avec le NAT, le
seul poste qui court quand personne ne s'en sert.

### 3.5 Vérifier

```sh
gcloud run services list --region europe-north1
make client PROFILE=support --http   # avec MCP_URL sur l'URL Cloud Run
gcloud logging read 'resource.type=cloud_run_revision' --limit 20
```

Le journal des appels part sur `stdout` en plus du JSONL : sur Cloud Run, une
instance recyclée emporte son système de fichiers, Cloud Logging non.
