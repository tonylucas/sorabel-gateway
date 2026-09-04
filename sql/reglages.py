"""Les réglages d'exécution : l'environnement d'abord, `.env` en repli.

Module à part, et non une fonction de `sql.generate`, pour une raison
mécanique : `sql.db` en a besoin, et `generate → guard → db` boucle. Un
réglage n'appartient de toute façon ni au générateur ni à la connexion.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values

REPO_ROOT = Path(__file__).resolve().parent.parent


@lru_cache(maxsize=1)
def _fichier_env() -> dict[str, str | None]:
    return dotenv_values(REPO_ROOT / ".env")


def reglage(nom: str, defaut: str = "") -> str:
    """L'environnement d'abord, `.env` en repli — sans injecter le fichier entier.

    `load_dotenv()` pousserait tout `.env` dans `os.environ` et rendrait actives
    des variables que d'autres modules lisent (`EMBEDDING_MODEL`, `CHROMA_URL`,
    `SORABEL_PROFILE`) : on changerait le comportement de code qui ne demande
    rien. Chaque appelant ne lit ici que les réglages dont il a besoin.
    """
    return os.environ.get(nom) or _fichier_env().get(nom) or defaut
