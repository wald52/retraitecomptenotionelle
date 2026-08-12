#!/usr/bin/env python3
"""Récupération des jeux de données INSEE exposés par l'API Melodi.

    python scripts/fetch/insee_melodi.py --catalogue
    python scripts/fetch/insee_melodi.py --jeu DS_IPC_PRINC --sortie data/brut/

Portée réelle de cette API — à savoir avant de compter dessus : Melodi expose
les jeux de données récents. L'indice des prix n'y remonte pas au-delà des
années 1990, et les séries longues de comptes nationaux n'y figurent pas. Les
séries antérieures doivent être téléchargées manuellement depuis insee.fr et
déposées dans ``data/brut/`` (voir data/sources.yaml, champ ``acces: fichier``).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://api.insee.fr/melodi"
ENTETES = {"User-Agent": "retraite-notionnelle/0.1 (recherche publique)"}


def requete(url: str, timeout: int = 120) -> dict | list:
    demande = urllib.request.Request(url, headers=ENTETES)
    with urllib.request.urlopen(demande, timeout=timeout) as reponse:
        return json.loads(reponse.read())


def catalogue() -> list[tuple[str, str]]:
    donnees = requete(f"{BASE}/catalog/all")
    entrees = []
    for jeu in donnees:
        titre = ""
        for libelle in jeu.get("title") or []:
            if libelle.get("lang") == "fr":
                titre = libelle.get("content", "")
        entrees.append((jeu.get("identifier", ""), titre))
    return sorted(entrees)


def telecharger(identifiant: str, filtres: dict[str, str], sortie: Path,
                pages_max: int = 50) -> Path:
    """Télécharge toutes les pages d'un jeu et écrit un JSON unique."""
    observations: list[dict] = []
    page = 1
    while page <= pages_max:
        parametres = {**filtres, "maxResult": "1000", "page": str(page)}
        url = f"{BASE}/data/{identifiant}?{urllib.parse.urlencode(parametres)}"
        charge = requete(url)
        lot = charge.get("observations", [])
        if not lot:
            break
        observations.extend(lot)
        if len(lot) < 1000:
            break
        page += 1

    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(
        json.dumps(
            {"identifier": identifiant, "filtres": filtres,
             "observations": observations},
            ensure_ascii=False, indent=1,
        ),
        encoding="utf-8",
    )
    return sortie


def main(argv: list[str] | None = None) -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--catalogue", action="store_true",
                           help="liste les jeux de données disponibles")
    analyseur.add_argument("--jeu", help="identifiant du jeu à télécharger")
    analyseur.add_argument("--filtre", action="append", default=[],
                           help="filtre de dimension, format CLE=VALEUR, répétable")
    analyseur.add_argument("--sortie", default="data/brut",
                           help="répertoire de destination")
    arguments = analyseur.parse_args(argv)

    try:
        if arguments.catalogue:
            for identifiant, titre in catalogue():
                print(f"{identifiant:<48} {titre[:80]}")
            return 0

        if not arguments.jeu:
            analyseur.error("indiquer --catalogue ou --jeu")

        filtres = {}
        for expression in arguments.filtre:
            if "=" not in expression:
                analyseur.error(f"filtre mal formé : {expression!r}, attendu CLE=VALEUR")
            cle, valeur = expression.split("=", 1)
            filtres[cle] = valeur

        chemin = Path(arguments.sortie) / f"insee_{arguments.jeu.lower()}.json"
        resultat = telecharger(arguments.jeu, filtres, chemin)
        charge = json.loads(resultat.read_text(encoding="utf-8"))
        print(f"{len(charge['observations'])} observations écrites dans {resultat}")
        return 0

    except urllib.error.HTTPError as erreur:
        print(f"Erreur HTTP {erreur.code} : {erreur.reason}", file=sys.stderr)
        return 1
    except urllib.error.URLError as erreur:
        print(f"Réseau indisponible : {erreur.reason}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
