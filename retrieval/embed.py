"""Embeddings locaux, chargés paresseusement.

Le modèle n'est chargé qu'au premier appel : la suite d'acceptance relance un
process par session avec 30 s par appel, un chargement au démarrage la ferait
tomber. `fastembed` passe par ONNX Runtime — pas de PyTorch, donc ~250 Mo au
lieu de ~2,5 Go, ce qui compte autant pour ce délai que pour le démarrage à
froid sur Cloud Run.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from functools import lru_cache

#: Multilingue, 384 dimensions, 0,22 Go. Le corpus est en français.
MODEL_NAME = os.environ.get(
    "EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)
DIMENSIONS = 384


@lru_cache(maxsize=1)
def _model():
    from fastembed import TextEmbedding

    return TextEmbedding(MODEL_NAME)


def embed(texts: list[str]) -> list[Sequence[float]]:
    return [vector.tolist() for vector in _model().embed(texts)]


def embed_query(text: str) -> Sequence[float]:
    return embed([text])[0]
