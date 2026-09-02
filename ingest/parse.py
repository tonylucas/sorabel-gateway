"""Lecture du corpus : un document, ses métadonnées **déclarées**, son texte.

Trois formats, trois porteurs de métadonnées — jamais une inférence sur le
contenu :

| Format | Où sont les métadonnées |
|---|---|
| PDF (fiches, notices) | lignes en clair `Référence produit :`, `Version :`, `Date :` |
| HTML (procédures SAV) | `<meta name="version|date|type">` et `<title>` |
| Markdown (notes) | frontmatter YAML |

Le nom de fichier redit la référence et la version : il sert de contrôle croisé
et de clé de dédoublonnage, pas de source.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup
from pypdf import PdfReader

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = REPO_ROOT / "data" / "corpus"

REF_PATTERN = re.compile(r"REF-\d{4}")
VERSION_SUFFIX = re.compile(r"-v\d+(?:\.\d+)*$")

#: En-têtes de première ligne des PDF — c'est le document qui déclare son type.
PDF_TYPES = {
    "FICHE TECHNIQUE": "fiche_technique",
    "NOTICE D'INSTALLATION": "notice",
}


@dataclass
class Document:
    doc_id: str
    path: Path
    doc_type: str
    titre: str
    version: str
    date: str
    text: str
    reference: str | None = None
    mentioned_refs: list[str] = field(default_factory=list)

    @property
    def version_key(self) -> tuple:
        """Ordre de version : 2.1 > 2.0 > 1.0, la date départageant les ex æquo."""
        numbers = tuple(int(n) for n in re.findall(r"\d+", self.version))
        return (numbers, self.date)


def doc_id_from(path: Path) -> str:
    """`REF-1024-v2.1.pdf` → `REF-1024` ; `notice-REF-1459-v1.1.pdf` → `notice-REF-1459`.

    La clé d'unicité est le nom de fichier privé de son suffixe de version, et
    **pas** la référence produit : la fiche `REF-1459` et la notice `REF-1459`
    sont deux documents distincts, et les procédures SAV n'ont aucune référence.
    """
    return VERSION_SUFFIX.sub("", path.stem)


def _mentioned(text: str, declared: str | None) -> list[str]:
    """Références citées dans le corps — utiles au lexical, sans valeur d'identité.

    Les procédures SAV citent une référence *en exemple* ; la prendre pour la
    référence du document ferait passer une procédure générique pour une fiche
    produit.
    """
    return sorted({ref for ref in REF_PATTERN.findall(text) if ref != declared})


def parse_pdf(path: Path) -> Document:
    text = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages).strip()
    first_line = text.splitlines()[0] if text else ""

    doc_type = next((t for header, t in PDF_TYPES.items() if first_line.startswith(header)), "")
    titre = first_line.split(" - ", 1)[-1].strip() if " - " in first_line else first_line.strip()

    def declared(label: str) -> str:
        found = re.search(rf"{label}\s*:\s*([^\s]+)", text)
        return found.group(1).strip() if found else ""

    reference = declared("Référence produit") or None
    return Document(
        doc_id=doc_id_from(path),
        path=path,
        doc_type=doc_type,
        titre=titre,
        version=declared("Version"),
        date=declared("Date"),
        text=text,
        reference=reference,
        mentioned_refs=_mentioned(text, reference),
    )


def parse_html(path: Path) -> Document:
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")

    def meta(name: str) -> str:
        tag = soup.find("meta", attrs={"name": name})
        return str(tag.get("content") or "").strip() if tag else ""

    # Le corps seul : `get_text()` sur tout le document reprendrait le `<title>`,
    # que le `<h1>` répète déjà et que l'indexation préfixe une troisième fois.
    body = soup.body or soup
    text = body.get_text("\n", strip=True)
    return Document(
        doc_id=doc_id_from(path),
        path=path,
        doc_type=meta("type"),
        titre=soup.title.get_text(strip=True) if soup.title else "",
        version=meta("version"),
        date=meta("date"),
        text=text,
        reference=None,
        mentioned_refs=_mentioned(text, None),
    )


def parse_markdown(path: Path) -> Document:
    raw = path.read_text(encoding="utf-8")
    front: dict[str, str] = {}
    body = raw

    if raw.startswith("---"):
        _, block, body = raw.split("---", 2)
        for line in block.strip().splitlines():
            key, _, value = line.partition(":")
            front[key.strip()] = value.strip().strip("'\"")

    body = body.strip()
    return Document(
        doc_id=doc_id_from(path),
        path=path,
        doc_type=front.get("type", ""),
        titre=front.get("titre", ""),
        version=front.get("version", ""),
        date=front.get("date", ""),
        text=body,
        reference=None,
        mentioned_refs=_mentioned(body, None),
    )


PARSERS = {".pdf": parse_pdf, ".html": parse_html, ".md": parse_markdown}


def load_corpus(root: Path = CORPUS_DIR) -> list[Document]:
    documents = []
    for path in sorted(root.rglob("*")):
        parser = PARSERS.get(path.suffix.lower())
        if parser is not None:
            documents.append(parser(path))
    return documents


def dedupe(documents: list[Document]) -> tuple[list[Document], list[Document]]:
    """Ne garde que la version la plus récente de chaque `doc_id`.

    Renvoie (retenus, écartés) — les écartés sont le rapport d'ingestion, c'est
    là que le dédoublonnage se démontre.
    """
    latest: dict[str, Document] = {}
    for doc in documents:
        current = latest.get(doc.doc_id)
        if current is None or doc.version_key > current.version_key:
            latest[doc.doc_id] = doc

    kept = sorted(latest.values(), key=lambda d: d.doc_id)
    retained = {id(d) for d in kept}
    dropped = [d for d in documents if id(d) not in retained]
    return kept, dropped
