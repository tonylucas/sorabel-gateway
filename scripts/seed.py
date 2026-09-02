"""Construit et peuple la base Sorabel (``data/sorabel.db``).

Génération déterministe (graine fixe) : chaque exécution reproduit exactement
la même base — catalogue, stocks, clients, commandes, ventes — alignée sur les
références produit du corpus documentaire (``data/corpus/``).

Usage : ``make seed`` ou ``uv run python scripts/seed.py``.
Le schéma de référence est décrit dans ``docs/schema.sql``.
"""

from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "sorabel.db"

rng = random.Random(8842)

FAMILIES = {
    "disjoncteur": ("Protection électrique", ["Voltane", "Protec+", "Ampria"]),
    "interrupteur différentiel": ("Protection électrique", ["Voltane", "Protec+"]),
    "câble": ("Câblage", ["Cablor", "Filtech"]),
    "tableau électrique": ("Distribution", ["Voltane", "Ampria"]),
    "goulotte": ("Câblage", ["Cablor"]),
    "perceuse": ("Outillage électroportatif", ["Ferrix", "Torqua"]),
    "visseuse": ("Outillage électroportatif", ["Ferrix", "Torqua"]),
    "meuleuse": ("Outillage électroportatif", ["Ferrix"]),
    "scie circulaire": ("Outillage électroportatif", ["Torqua"]),
    "multimètre": ("Mesure", ["Metrix Pro", "Ampria"]),
    "pince à sertir": ("Outillage à main", ["Ferrix"]),
    "gants isolants": ("EPI", ["Securo"]),
    "casque de chantier": ("EPI", ["Securo"]),
    "projecteur LED": ("Éclairage", ["Lumea"]),
    "baladeuse LED": ("Éclairage", ["Lumea"]),
    "vis autoperceuse": ("Visserie", ["Fixor"]),
    "cheville": ("Visserie", ["Fixor"]),
}
VARIANTS = {
    "disjoncteur": ["monophasé 10 A courbe C", "monophasé 16 A courbe C", "monophasé 20 A courbe C",
                    "monophasé 32 A courbe D", "triphasé 25 A courbe C", "triphasé 63 A courbe D",
                    "tétrapolaire 40 A courbe C"],
    "interrupteur différentiel": ["30 mA type A", "30 mA type AC", "300 mA type A"],
    "câble": ["R2V 3G1,5 mm² (100 m)", "R2V 3G2,5 mm² (50 m)", "R2V 5G6 mm² (50 m)",
              "H07V-U 1,5 mm² (100 m)", "H07V-U 2,5 mm² (100 m)"],
    "tableau électrique": ["1 rangée 13 modules", "2 rangées 26 modules", "3 rangées 39 modules",
                           "4 rangées 52 modules"],
    "goulotte": ["25×40 mm (2 m)", "40×60 mm (2 m)", "60×80 mm (2 m)"],
    "perceuse": ["à percussion 750 W", "sans fil 18 V", "à colonne 500 W", "sans fil 12 V compacte"],
    "visseuse": ["à chocs 18 V", "sans fil 12 V", "plaquiste 550 W"],
    "meuleuse": ["d'angle 125 mm 900 W", "d'angle 230 mm 2000 W"],
    "scie circulaire": ["185 mm 1200 W", "plongeante 160 mm"],
    "multimètre": ["numérique TRMS", "de chantier IP54", "pince multimètre 400 A"],
    "pince à sertir": ["cosses 0,5-6 mm²", "embouts 0,25-10 mm²"],
    "gants isolants": ["classe 0 (1000 V)", "classe 00 (500 V)"],
    "casque de chantier": ["isolé 1000 V", "ventilé standard"],
    "projecteur LED": ["50 W IP65", "100 W IP65 sur trépied", "30 W rechargeable"],
    "baladeuse LED": ["10 W IP54", "20 W rechargeable"],
    "vis autoperceuse": ["4,2×13 mm (boîte 500)", "4,8×19 mm (boîte 250)"],
    "cheville": ["à frapper 6×40 (boîte 200)", "métallique M8 (boîte 100)"],
}

SEGMENTS = ["artisan", "PME", "grand compte", "collectivité"]
VILLES = ["Lille", "Roubaix", "Lyon", "Villeurbanne", "Nantes", "Rennes", "Amiens", "Arras",
          "Valenciennes", "Dunkerque", "Angers", "Tours", "Orléans", "Reims", "Metz"]
SOCIETES = ["Élec", "Bâti", "Instal", "Courant", "Volt", "Chantier", "Renov", "Tech",
            "Azur", "Nord", "Delta", "Ohm", "Phase", "Prisme", "Sillage"]
STATUTS = ["en_attente", "preparee", "expediee", "livree", "livree", "livree", "annulee"]

SCHEMA = """
CREATE TABLE produits (
  ref TEXT PRIMARY KEY, nom TEXT NOT NULL, categorie TEXT NOT NULL,
  fabricant TEXT NOT NULL, unite TEXT NOT NULL,
  prix_vente_ht REAL NOT NULL, prix_achat_ht REAL NOT NULL, marge_pct REAL NOT NULL,
  actif INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE stocks (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT NOT NULL REFERENCES produits(ref),
  entrepot TEXT NOT NULL, quantite INTEGER NOT NULL, seuil_reappro INTEGER NOT NULL
);
CREATE TABLE clients (
  id TEXT PRIMARY KEY, raison_sociale TEXT NOT NULL, segment TEXT NOT NULL,
  ville TEXT NOT NULL, email TEXT NOT NULL
);
CREATE TABLE commandes (
  id TEXT PRIMARY KEY, client_id TEXT NOT NULL REFERENCES clients(id),
  date_commande TEXT NOT NULL, statut TEXT NOT NULL, montant_ht REAL NOT NULL
);
CREATE TABLE ventes (
  id INTEGER PRIMARY KEY AUTOINCREMENT, commande_id TEXT NOT NULL REFERENCES commandes(id),
  ref TEXT NOT NULL REFERENCES produits(ref), quantite INTEGER NOT NULL,
  prix_unitaire_ht REAL NOT NULL, remise_pct REAL NOT NULL, marge_ht REAL NOT NULL
);
"""


def gen_refs(n: int) -> list[str]:
    seen, out = {"8842"}, []
    while len(out) < n:
        r = f"{rng.randint(1000, 9999)}"
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def build_products() -> list[dict]:
    products: list[dict] = [{
        "ref": "REF-8842", "famille": "disjoncteur",
        "nom": "Disjoncteur tétrapolaire triphasé 40 A courbe C",
        "categorie": "Protection électrique", "fabricant": "Voltane",
    }]
    pool = [(fam, var) for fam, vars_ in VARIANTS.items() for var in vars_]
    pool = pool * 3
    rng.shuffle(pool)
    refs = gen_refs(119)
    for i in range(119):
        fam, var = pool[i]
        cat, brands = FAMILIES[fam]
        products.append({"ref": f"REF-{refs[i]}", "famille": fam,
                         "nom": f"{fam.capitalize()} {var}",
                         "categorie": cat, "fabricant": rng.choice(brands)})
    for p in products:
        pv = round(rng.uniform(3, 480), 2)
        pa = round(pv * rng.uniform(0.45, 0.75), 2)
        p["prix_vente_ht"] = pv
        p["prix_achat_ht"] = pa
        p["marge_pct"] = round((pv - pa) / pv * 100, 1)
        p["unite"] = ("conditionnement"
                      if p["famille"] in ("câble", "vis autoperceuse", "cheville") else "pièce")
    return products


def main() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    products = build_products()

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.executescript(SCHEMA)

    for p in products:
        cur.execute("INSERT INTO produits VALUES (?,?,?,?,?,?,?,?,1)",
                    (p["ref"], p["nom"], p["categorie"], p["fabricant"], p["unite"],
                     p["prix_vente_ht"], p["prix_achat_ht"], p["marge_pct"]))

    for p in products:
        for ent in ("LILLE", "LYON", "NANTES"):
            if rng.random() < 0.85:
                cur.execute(
                    "INSERT INTO stocks (ref, entrepot, quantite, seuil_reappro) VALUES (?,?,?,?)",
                    (p["ref"], ent, rng.randint(0, 480), rng.choice([10, 20, 50])))

    clients = []
    for i in range(60):
        name = (f"{rng.choice(SOCIETES)}"
                f"{rng.choice(['', ' Pro', ' Services', ' & Fils', ' Groupe'])} "
                f"{rng.choice(['SARL', 'SAS', 'EURL'])}")
        cid = f"CLI-{1000 + i}"
        clients.append(cid)
        cur.execute("INSERT INTO clients VALUES (?,?,?,?,?)",
                    (cid, name, rng.choice(SEGMENTS), rng.choice(VILLES),
                     f"contact{i}@client{i}.example"))

    start = date(2025, 9, 1)
    end = date(2026, 8, 20)
    n_days = (end - start).days
    oid = 0
    for _ in range(340):
        oid += 1
        d = start + timedelta(days=rng.randint(0, n_days))
        cmd_id = f"CMD-{d.year}-{oid:04d}"
        cid = rng.choice(clients)
        lignes = []
        for _ in range(rng.randint(1, 5)):
            p = rng.choice(products)
            q = rng.randint(1, 40)
            remise = rng.choice([0, 0, 0, 5, 10])
            pu = round(p["prix_vente_ht"] * (1 - remise / 100), 2)
            marge = round((pu - p["prix_achat_ht"]) * q, 2)
            lignes.append((p["ref"], q, pu, remise, marge))
        montant = round(sum(q * pu for _, q, pu, _, _ in lignes), 2)
        cur.execute("INSERT INTO commandes VALUES (?,?,?,?,?)",
                    (cmd_id, cid, d.isoformat(), rng.choice(STATUTS), montant))
        for ref, q, pu, remise, marge in lignes:
            cur.execute(
                "INSERT INTO ventes (commande_id, ref, quantite, prix_unitaire_ht, remise_pct, marge_ht)"
                " VALUES (?,?,?,?,?,?)",
                (cmd_id, ref, q, pu, remise, marge))

    con.commit()
    counts = {t: cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("produits", "stocks", "clients", "commandes", "ventes")}
    con.close()
    print(f"Base créée : {DB_PATH}")
    for table, count in counts.items():
        print(f"  {table}: {count}")


if __name__ == "__main__":
    main()
