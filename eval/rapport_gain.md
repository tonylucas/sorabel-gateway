# Gain de la recherche hybride sur la recherche dense

Mesuré le 2026-09-02 sur les 30 questions de
`eval/questions_rag.jsonl`, corpus de 350 documents (400 fichiers, 50 versions
écartées au dédoublonnage). Régénérable par `make eval`.

Le dense est la **baseline** : c'est la recherche que E6 demande de comparer.
L'hybride fusionne dense et lexical (BM25) par RRF, k=60.

## Deux métriques

- **Recall@5** — part des questions dont le document attendu figure dans les
  5 premiers résultats. *Trouve-t-on la bonne chose ?*
- **MRR** (rang réciproque moyen) — moyenne de `1 / rang` du bon document.
  1,00 = toujours en tête ; 0,50 = toujours en deuxième ; 0 = jamais trouvé.
  *La trouve-t-on assez haut pour qu'elle serve ?*

Les deux sont nécessaires : un moteur peut tout trouver (Recall élevé) en
plaçant systématiquement la bonne réponse en cinquième position (MRR bas).

## Recherche par référence exacte — 8 questions

Requêtes du type « REF-8842 » ou « fiche technique REF-8842 ».

| Mode | Recall@5 | MRR |
|---|---|---|
| dense | 0 % | 0.00 |
| lexical | 100 % | 0.73 |
| **hybride** | **100 %** | **1.00** |

## Pertinence sémantique — 14 questions

Questions en langage naturel couvertes par le corpus.

| Mode | Recall@5 | MRR |
|---|---|---|
| dense | 79 % | 0.68 |
| lexical | 86 % | 0.81 |
| **hybride** | **93 %** | **0.84** |

## Le gain

L'hybride gagne **+100 points de Recall@5** en recherche par
référence exacte et **+14 points** en pertinence sémantique,
comparé à la baseline dense.

C'est le résultat attendu, et la raison d'être de l'hybride : le dense encode du
sens, or `REF-8842` n'en a pas — c'est une chaîne. Le lexical la trouve
exactement ; la fusion garde les deux comportements sans arbitrer à l'avance.

## Refus hors corpus (E1)

On répond si l'une de ces trois preuves tient :

1. une référence produit de la question figure dans les résultats ;
2. le cosinus du meilleur résultat atteint 0.48 ;
3. son score BM25 atteint 18.0.

Sinon, refus typé `hors_corpus`, sans génération.

| | n | correct |
|---|---|---|
| refus attendu (`hors_corpus`) | 8 | 8 |
| réponse attendue | 22 | 20 |

**Aucun signal ne sépare seul le corpus du hors-corpus.** Les cosinus se
chevauchent — 0.32–0.68 dans le corpus contre
0.34–0.47 hors corpus — et les scores BM25 aussi.

Les deux seuils sont donc calibrés ensemble, sous une contrainte unique : **ne
jamais répondre hors corpus**. Le refus est ce que E1 exige, et une réponse
manquée coûte moins qu'une réponse inventée. Le plus haut BM25 hors corpus vaut
16.6, d'où le seuil posé à 18.0.

Questions du corpus refusées à tort : RAG-17, RAG-18.
