#!/usr/bin/env python3
"""Récupération de l'espérance de vie française auprès de l'OCDE.

    python scripts/fetch/oecd_esperance_vie.py

Pourquoi l'OCDE pour une donnée française : le modèle calibre sa table de
mortalité sur **e60 et e65** — le premier fixe le niveau de la force de
mortalité, le second sa pente. Or l'INSEE publie l'espérance de vie à 0, 1, 20,
40 et 60 ans, **jamais à 65 ans**. Il faut donc la chercher ailleurs :

* Eurostat (``demo_mlexpec``) la publie, mais pas avant 1986 pour la France ;
* l'OCDE (``DSD_HEALTH_STAT@DF_LE``) la publie **depuis 1960**, et ses valeurs
  françaises sont celles que l'INSEE lui transmet.

Les deux sources coïncident exactement sur leurs 78 valeurs communes ; c'est
scripts/verifier_donnees.py qui le vérifie. L'OCDE est retenue comme source
parce qu'elle remonte vingt-six ans plus haut.

Avant 1960, rien n'est automatisable : e65 reste saisi depuis les tables TD/TV.
"""

from __future__ import annotations

import csv
import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Clé SDMX : REF_AREA suivi des douze autres dimensions laissées libres.
URL = ("https://sdmx.oecd.org/public/rest/data/OECD.ELS.HD,DSD_HEALTH_STAT@DF_LE,"
       "/FRA............?format=csvfilewithlabels&startPeriod=1950")
AGES = {"0 years": "e0", "60 years": "e60", "65 years": "e65"}
SEXES = {"Male": "H", "Female": "F"}
SORTIE = Path("data/brut/oecd_esperance_vie.json")


def extraire(texte: str) -> dict[str, float]:
    """Aplatit le CSV libellé de l'OCDE en clés ``annee|sexe|mesure``."""
    serie: dict[str, float] = {}
    for ligne in csv.DictReader(io.StringIO(texte)):
        mesure = AGES.get(ligne.get("Age", ""))
        sexe = SEXES.get(ligne.get("Sex", ""))
        if mesure is None or sexe is None:
            continue
        serie[f"{ligne['TIME_PERIOD']}|{sexe}|{mesure}"] = float(ligne["OBS_VALUE"])
    return dict(sorted(serie.items()))


def main() -> int:
    try:
        demande = urllib.request.Request(
            URL, headers={"User-Agent": "retraite-notionnelle/0.1"}
        )
        with urllib.request.urlopen(demande, timeout=300) as reponse:
            texte = reponse.read().decode("utf-8")
    except (urllib.error.HTTPError, urllib.error.URLError) as erreur:
        print(f"OCDE indisponible : {erreur}", file=sys.stderr)
        return 1

    serie = extraire(texte)
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(
        json.dumps({"source": URL, "serie": serie}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    annees = sorted({int(cle.split("|")[0]) for cle in serie})
    print(f"{len(serie)} valeurs écrites dans {SORTIE}")
    if annees:
        print(f"Couverture {annees[0]}-{annees[-1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
