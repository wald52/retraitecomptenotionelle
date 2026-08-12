#!/usr/bin/env python3
"""Fabrique le paquet que la page web charge dans le navigateur.

``moteur/simulateur.zip`` contient le modèle et les données de référence. La
page ``index.html`` le décompresse dans le système de fichiers virtuel de
Pyodide, puis importe le paquet : c'est le même code que sur un poste de
travail, à la ligne près.

Le site est servi depuis la racine du dépôt — c'est ce que GitHub Pages publie
sans réglage — d'où ``index.html`` à la racine et les fichiers lourds rangés
dans ``moteur/``.

    python scripts/construire_site.py            # reconstruit le paquet
    python scripts/construire_site.py --verifier # échoue s'il est périmé

Le paquet est versionné dans le dépôt, pour que le site n'ait aucune étape de
construction : ouvrir l'adresse suffit. Il faut donc le reconstruire après toute
modification du code ou des données — le test ``test_le_paquet_est_a_jour`` y
veille.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import sys
import zipfile
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
PAQUET = RACINE / "moteur" / "simulateur.zip"

#: Répertoires embarqués, avec leur chemin d'arrivée dans le paquet.
CONTENU = (
    (RACINE / "src" / "retraite_notionnelle", "retraite_notionnelle", "*.py"),
    (RACINE / "data" / "reference", "data/reference", "*"),
    (RACINE / "data" / "derive", "data/derive", "*"),
)

#: Fichiers isolés à embarquer.
FICHIERS = ((RACINE / "data" / "sources.yaml", "data/sources.yaml"),)


def _fichiers() -> list[tuple[Path, str]]:
    """Liste (source, destination) triée, pour un paquet reproductible."""
    trouves: list[tuple[Path, str]] = []
    for source, destination, motif in CONTENU:
        for chemin in sorted(source.rglob(motif)):
            if not chemin.is_file() or "__pycache__" in chemin.parts:
                continue
            relatif = chemin.relative_to(source).as_posix()
            trouves.append((chemin, f"{destination}/{relatif}"))
    trouves.extend((source, destination) for source, destination in FICHIERS
                   if source.is_file())
    return sorted(trouves, key=lambda paire: paire[1])


def construire() -> bytes:
    """Paquet zip, à contenu identique pour un contenu source identique."""
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for source, destination in _fichiers():
            # Date fixe : deux constructions du même code donnent le même octet,
            # donc aucune modification parasite dans le dépôt.
            info = zipfile.ZipInfo(destination, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, source.read_bytes())
    return tampon.getvalue()


def main(argv: list[str] | None = None) -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument(
        "--verifier", action="store_true",
        help="ne rien écrire ; échouer si le paquet versionné est périmé",
    )
    arguments = analyseur.parse_args(argv)

    attendu = construire()
    empreinte = hashlib.sha256(attendu).hexdigest()[:12]

    if arguments.verifier:
        if not PAQUET.exists():
            print(f"{PAQUET} est absent — lancer python scripts/construire_site.py",
                  file=sys.stderr)
            return 1
        if PAQUET.read_bytes() != attendu:
            print(f"{PAQUET} est périmé — lancer python scripts/construire_site.py",
                  file=sys.stderr)
            return 1
        print(f"paquet à jour ({len(attendu) / 1024:.0f} Ko, {empreinte})")
        return 0

    PAQUET.parent.mkdir(parents=True, exist_ok=True)
    PAQUET.write_bytes(attendu)
    print(f"{PAQUET.relative_to(RACINE)} : {len(_fichiers())} fichiers, "
          f"{len(attendu) / 1024:.0f} Ko ({empreinte})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
