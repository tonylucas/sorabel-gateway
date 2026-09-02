# Gain de la recherche hybride sur la recherche dense

Mesuré le 2026-09-02 sur les 30 questions de
`eval/questions_rag.jsonl`, corpus de 350 documents (400 fichiers, 50 versions
écartées au dédoublonnage). Régénérable par `make eval`.

Le dense est la **baseline** : c'est la recherche que E6 demande de comparer.
L'hybride fusionne dense et lexical (BM25) par RRF, k=60.

## Recall@5 · MRR

| Mode | `reference_exacte` (8) | `couverte` (14) |
|---|---|---|
| dense | 0% · 0.00 | 79% · 0.68 |
| lexical | 100% · 0.73 | 86% · 0.81 |
| **hybride** | **100% · 1.00** | **93% · 0.84** |

**Gain de l'hybride sur le dense : +100 points de Recall@5 en
recherche par référence exacte, +14 points en pertinence
sémantique.**

C'est le résultat attendu, et la raison d'être de l'hybride : le dense encode du
sens, or `REF-8842` n'en a pas — c'est une chaîne. Le lexical la trouve
exactement ; la fusion garde les deux comportements sans arbitrer à l'avance.

## Refus hors corpus (E1)

On répond si l'une des trois preuves tient : une référence produit de la question
figure dans les résultats, ou le cosinus du meilleur ≥ 0.48, ou son
score BM25 ≥ 18.0. Sinon, refus typé `hors_corpus`, sans génération.

| | n | correct |
|---|---|---|
| refus attendu (`hors_corpus`) | 8 | 8 |
| réponse attendue | 22 | 20 |

**Aucun signal ne sépare seul le corpus du hors-corpus** : les cosinus se
chevauchent (0.32–0.68 dans le corpus,
0.34–0.47 hors corpus), les scores BM25 aussi. Les
seuils sont donc calibrés ensemble, avec pour contrainte de ne jamais répondre
hors corpus — le refus est ce que E1 exige, une réponse manquée coûte moins
qu'une réponse inventée. Le plus haut BM25 hors corpus est 16.6,
d'où le seuil à 18.0.

Questions du corpus refusées à tort : RAG-17, RAG-18.
