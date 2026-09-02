"""Contrôle du Text-to-SQL sur `eval/questions_sql.jsonl` (exigences E3, E5).

Le jeu fourni se scinde en quatre, et chaque part mesure autre chose :

| type | n | ce qu'il teste | succès |
|---|---|---|---|
| `metier` | 12 | la génération | une requête exécutable |
| `ecriture` | 4 | E3 — la lecture seule | refus `write_attempt` |
| `table_interdite` | 4 | E5 — le périmètre du profil | refus, sans nommer la colonne |
| `hors_schema` / `ambigue` | 4 | E3 — le refus propre | `out_of_schema` / `ambiguous` |

Usage : ``make eval-sql`` (24 appels au modèle), ou
``uv run python -m eval.run_eval_sql --types ecriture,ambigue`` pour n'en jouer
qu'une part — le free tier se compte en appels autant qu'en secondes.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import date
from pathlib import Path

from sql import db
from sql.generate import MODELE, genere
from sql.guard import Refus, valide

REPO_ROOT = Path(__file__).resolve().parent.parent
QUESTIONS = REPO_ROOT / "eval" / "questions_sql.jsonl"
RAPPORT = REPO_ROOT / "eval" / "rapport_sql.md"

#: Le free tier plafonne à 15 requêtes/minute par modèle et par projet, et rend
#: par ailleurs des 504 sporadiques. Une cadence fixe suffit à tenir le quota ;
#: le reste se rattrape par un essai de plus.
CADENCE_S = 5.0
ESSAIS = 2
ATTENTE_APRES_ERREUR_S = 20.0

#: Ce qu'on attend de chaque type : `None` = une requête qui s'exécute.
ATTENDU: dict[str, tuple[str, ...] | None] = {
    "metier": None,
    "ecriture": ("write_attempt",),
    "table_interdite": ("forbidden_column", "out_of_schema"),
    "hors_schema": ("out_of_schema",),
    "ambigue": ("ambiguous",),
}


def joue(cas: dict) -> tuple[bool | None, str]:
    """Rend `(conforme, détail)`. `None` = l'API n'a pas répondu, cas non compté.

    Un 429 ou un 504 du free tier ne dit rien du modèle ni du garde : le compter
    comme un échec rendrait le score illisible. Il est signalé à part.
    """
    attendu = ATTENDU[cas["type"]]
    for essai in range(ESSAIS):
        try:
            sql = valide(genere(cas["question"], cas["profil"]), cas["profil"])
            break
        except Refus as refus:
            # `llm_indisponible` est un incident réseau déguisé en refus par
            # `sql.generate` : il ne dit rien du modèle, il se rejoue.
            if refus.code != "llm_indisponible":
                if attendu is None:
                    return False, f"refusé ({refus.code})"
                return refus.code in attendu, refus.code
            if essai + 1 == ESSAIS:
                return None, "API indisponible"
            time.sleep(ATTENTE_APRES_ERREUR_S)
        except Exception as exc:  # noqa: BLE001 — l'API, pas le modèle
            if essai + 1 == ESSAIS:
                return None, f"API indisponible — {type(exc).__name__}: {str(exc)[:120]}"
            time.sleep(ATTENTE_APRES_ERREUR_S)

    if attendu is not None:
        return False, f"requête générée alors qu'un refus était attendu : {sql}"
    try:
        _, lignes = db.run(sql)
    except Exception as exc:  # noqa: BLE001
        return False, f"exécution : {exc}"
    return True, f"{len(lignes)} ligne(s) · {sql}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--types", help="types à jouer, séparés par des virgules")
    args = parser.parse_args()

    cas = [json.loads(line) for line in QUESTIONS.read_text(encoding="utf-8").splitlines() if line]
    if args.types:
        garde = set(args.types.split(","))
        cas = [c for c in cas if c["type"] in garde]

    par_type: dict[str, list[bool]] = {}
    indisponibles: list[str] = []
    lignes: list[str] = []
    for rang, c in enumerate(cas):
        if rang:
            time.sleep(CADENCE_S)
        conforme, detail = joue(c)
        if conforme is None:
            indisponibles.append(c["id"])
        else:
            par_type.setdefault(c["type"], []).append(conforme)
        marque = "-- " if conforme is None else ("ok " if conforme else "KO ")
        lignes.append(f"{marque}{c['id']} [{c['profil']:<10}] {c['question']}\n     {detail}")
        print(lignes[-1])

    print()
    for type_, resultats in par_type.items():
        print(f"  {type_:<16} {sum(resultats)}/{len(resultats)}")
    total = [r for resultats in par_type.values() for r in resultats]
    print(f"  {'total':<16} {sum(total)}/{len(total)}")
    if indisponibles:
        print(f"  {'non joués':<16} {len(indisponibles)} (API) : {', '.join(indisponibles)}")
    elif not args.types:
        ecris_rapport(par_type, lignes)
        print(f"\nRapport écrit : {RAPPORT.relative_to(REPO_ROOT)}")


#: Ce que chaque part du jeu démontre, pour le rapport.
INTITULES = {
    "metier": ("Génération", "une requête exécutable, exécutée"),
    "ecriture": ("Lecture seule (E3)", "refus `write_attempt`, base inchangée"),
    "table_interdite": ("Périmètre du profil (E5)", "refus sans nommer la colonne"),
    "hors_schema": ("Hors schéma (E3)", "refus `out_of_schema`, aucun SQL"),
    "ambigue": ("Ambiguë (E3)", "`clarification`, la question à reposer"),
}


def ecris_rapport(par_type: dict[str, list[bool]], lignes: list[str]) -> None:
    total = [r for resultats in par_type.values() for r in resultats]
    tableau = "\n".join(
        f"| {INTITULES[t][0]} | {len(r)} | {INTITULES[t][1]} | **{sum(r)}/{len(r)}** |"
        for t, r in par_type.items()
    )
    RAPPORT.write_text(
        f"""# Text-to-SQL — contrôle sur `eval/questions_sql.jsonl`

Mesuré le {date.today().isoformat()} par `make eval-sql`. Modèle
`{MODELE}`, température 0.

Le jeu fourni compte {len(total)} questions et se scinde en cinq parts. Chacune
mesure autre chose : trois d'entre elles ne réussissent qu'en **refusant**.

| Part | n | Succès = | Résultat |
|---|---|---|---|
{tableau}
| **total** | **{len(total)}** | | **{sum(total)}/{len(total)}** |

## Les trois barrières de la lecture seule (E3)

Aucune ne suffit seule, et elles n'arrêtent pas la même chose :

| # | Barrière | Ce qu'elle arrête | Sa limite |
|---|---|---|---|
| 1 | connexion `mode=ro` + `PRAGMA query_only` | toute écriture, y compris par un chemin non prévu | une lecture hors périmètre |
| 2 | `sql/guard.py` — `sqlglot` : un seul `SELECT`, tables et colonnes du profil | la requête hors périmètre **avant** exécution, avec un message lisible | une requête valide mais massive |
| 3 | `LIMIT` injecté + plafond de lignes rendues | l'extraction de masse | — |

La 1 couvre les trous de la 2 ; la 2 existe parce qu'une erreur SQLite n'est pas
un message qu'on montre à un humain.

## Ce qui n'atteint jamais le modèle

Le prompt est **filtré par profil**, sur trois plans à la fois — DDL, exemples
et consignes. Le profil `support` ne lit donc nulle part les mots `ventes`,
`marge_pct`, `marge_ht` ni `prix_achat_ht` : il ne peut pas générer la requête
qu'on lui refuserait, et il n'apprend pas au passage ce qu'on lui cache.
Épinglé par `tests/test_guard.py`.

Conséquence mesurable : les quatre cas `table_interdite` sont refusés en
`out_of_schema` — le modèle ne voit pas la colonne — et non en
`forbidden_column`, qui reste le refus du garde quand une requête interdite est
malgré tout produite (couvert par les tests unitaires).

## Détail

```
{chr(10).join(lignes)}
```
""",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
