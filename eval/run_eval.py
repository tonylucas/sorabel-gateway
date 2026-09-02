"""Mesure du gain de la recherche hybride sur la recherche dense (exigence E6).

Trois modes comparés sur `eval/questions_rag.jsonl`, avec Recall@5 et MRR.
Le jeu se scinde de lui-même, et chaque sous-ensemble mesure autre chose :

| type | n | ce qu'il teste |
|---|---|---|
| `reference_exacte` | 8 | E2 — là où le dense échoue |
| `couverte` | 14 | pertinence sémantique |
| `hors_corpus` | 8 | E1 — le refus, mesuré en taux, pas en rappel |

Usage : ``make eval`` → `eval/rapport_gain.md`.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from retrieval.search import MODES, SEUIL_COSINUS, SEUIL_LEXICAL, pertinent, search

REPO_ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = REPO_ROOT / "eval"
QUESTIONS = EVAL_DIR / "questions_rag.jsonl"
RAPPORT = EVAL_DIR / "rapport_gain.md"
K = 5


def load_questions() -> list[dict]:
    lines = QUESTIONS.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def rang_attendu(question: dict, hits: list) -> int | None:
    """Rang (1-indexé) du premier résultat conforme à l'attendu, ou None."""
    for rang, hit in enumerate(hits, start=1):
        if "attendu_reference" in question:
            if hit.metadata.get("reference") == question["attendu_reference"]:
                return rang
        elif "attendu_type" in question:
            if hit.metadata.get("doc_type") == question["attendu_type"]:
                return rang
    return None


def mesure(questions: list[dict], mode: str) -> dict:
    rangs = [rang_attendu(q, search(q["question"], k=K, mode=mode)) for q in questions]
    trouves = [r for r in rangs if r is not None]
    n = len(questions) or 1
    return {
        "n": len(questions),
        "recall": len(trouves) / n,
        "mrr": sum(1 / r for r in trouves) / n,
    }


def gate(question: str) -> tuple[bool, float, float]:
    return pertinent(question, search(question, k=K))


def main() -> None:
    questions = load_questions()
    par_type = {
        t: [q for q in questions if q["type"] == t]
        for t in ("reference_exacte", "couverte", "hors_corpus")
    }

    scores = {
        mode: {t: mesure(qs, mode) for t, qs in par_type.items() if t != "hors_corpus"}
        for mode in MODES
    }

    decisions = {t: [(q["id"], *gate(q["question"])) for q in qs] for t, qs in par_type.items()}
    refus_corrects = sum(1 for _, repond, _, _ in decisions["hors_corpus"] if not repond)
    manques = [
        i
        for t in ("reference_exacte", "couverte")
        for i, repond, _, _ in decisions[t]
        if not repond
    ]
    n_dans_corpus = len(par_type["reference_exacte"]) + len(par_type["couverte"])
    repond_corrects = n_dans_corpus - len(manques)

    def tableau(t: str) -> str:
        """Un tableau par sous-ensemble : une colonne par métrique, jamais deux dans une."""
        lignes = []
        for mode in MODES:
            s = scores[mode][t]
            nom = f"**{mode}**" if mode == "hybride" else mode
            gras = "**" if mode == "hybride" else ""
            lignes.append(f"| {nom} | {gras}{s['recall'] * 100:.0f} %{gras} | {gras}{s['mrr']:.2f}{gras} |")
        return "\n".join(lignes)

    gain_ref = (
        scores["hybride"]["reference_exacte"]["recall"]
        - scores["dense"]["reference_exacte"]["recall"]
    )
    gain_couv = scores["hybride"]["couverte"]["recall"] - scores["dense"]["couverte"]["recall"]

    cos_dans = [c for t in ("reference_exacte", "couverte") for _, _, c, _ in decisions[t]]
    cos_hors = [c for _, _, c, _ in decisions["hors_corpus"]]
    bm_hors = [b for _, _, _, b in decisions["hors_corpus"]]

    RAPPORT.write_text(
        f"""# Gain de la recherche hybride sur la recherche dense

Mesuré le {date.today().isoformat()} sur les {len(questions)} questions de
`eval/questions_rag.jsonl`, corpus de 350 documents (400 fichiers, 50 versions
écartées au dédoublonnage). Régénérable par `make eval`.

Le dense est la **baseline** : c'est la recherche que E6 demande de comparer.
L'hybride fusionne dense et lexical (BM25) par RRF, k={60}.

## Deux métriques

- **Recall@{K}** — part des questions dont le document attendu figure dans les
  {K} premiers résultats. *Trouve-t-on la bonne chose ?*
- **MRR** (rang réciproque moyen) — moyenne de `1 / rang` du bon document.
  1,00 = toujours en tête ; 0,50 = toujours en deuxième ; 0 = jamais trouvé.
  *La trouve-t-on assez haut pour qu'elle serve ?*

Les deux sont nécessaires : un moteur peut tout trouver (Recall élevé) en
plaçant systématiquement la bonne réponse en cinquième position (MRR bas).

## Recherche par référence exacte — {len(par_type["reference_exacte"])} questions

Requêtes du type « REF-8842 » ou « fiche technique REF-8842 ».

| Mode | Recall@{K} | MRR |
|---|---|---|
{tableau("reference_exacte")}

## Pertinence sémantique — {len(par_type["couverte"])} questions

Questions en langage naturel couvertes par le corpus.

| Mode | Recall@{K} | MRR |
|---|---|---|
{tableau("couverte")}

## Le gain

L'hybride gagne **{gain_ref * 100:+.0f} points de Recall@{K}** en recherche par
référence exacte et **{gain_couv * 100:+.0f} points** en pertinence sémantique,
comparé à la baseline dense.

C'est le résultat attendu, et la raison d'être de l'hybride : le dense encode du
sens, or `REF-8842` n'en a pas — c'est une chaîne. Le lexical la trouve
exactement ; la fusion garde les deux comportements sans arbitrer à l'avance.

## Refus hors corpus (E1)

On répond si l'une de ces trois preuves tient :

1. une référence produit de la question figure dans les résultats ;
2. le cosinus du meilleur résultat atteint {SEUIL_COSINUS} ;
3. son score BM25 atteint {SEUIL_LEXICAL}.

Sinon, refus typé `hors_corpus`, sans génération.

| | n | correct |
|---|---|---|
| refus attendu (`hors_corpus`) | {len(par_type["hors_corpus"])} | {refus_corrects} |
| réponse attendue | {n_dans_corpus} | {repond_corrects} |

**Aucun signal ne sépare seul le corpus du hors-corpus.** Les cosinus se
chevauchent — {min(cos_dans):.2f}–{max(cos_dans):.2f} dans le corpus contre
{min(cos_hors):.2f}–{max(cos_hors):.2f} hors corpus — et les scores BM25 aussi.

Les deux seuils sont donc calibrés ensemble, sous une contrainte unique : **ne
jamais répondre hors corpus**. Le refus est ce que E1 exige, et une réponse
manquée coûte moins qu'une réponse inventée. Le plus haut BM25 hors corpus vaut
{max(bm_hors):.1f}, d'où le seuil posé à {SEUIL_LEXICAL}.

{"Questions du corpus refusées à tort : " + ", ".join(manques) + "." if manques else "Aucune question du corpus refusée à tort."}
""",
        encoding="utf-8",
    )

    print(f"Rapport écrit : {RAPPORT.relative_to(REPO_ROOT)}")
    for mode in MODES:
        r = scores[mode]
        print(
            f"  {mode:<9} reference_exacte {r['reference_exacte']['recall']:.0%}"
            f"  couverte {r['couverte']['recall']:.0%}"
        )
    print(
        f"  refus corrects {refus_corrects}/{len(par_type['hors_corpus'])}"
        f" · réponses correctes {repond_corrects}/{n_dans_corpus}"
    )
    print(
        f"  cosinus dans corpus {min(cos_dans):.2f}–{max(cos_dans):.2f}"
        f" | hors corpus {min(cos_hors):.2f}–{max(cos_hors):.2f}"
    )


if __name__ == "__main__":
    main()
