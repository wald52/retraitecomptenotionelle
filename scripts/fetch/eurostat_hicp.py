#!/usr/bin/env python3
"""Récupération de l'inflation harmonisée française auprès d'Eurostat.

    python scripts/fetch/eurostat_hicp.py

Sert de **contrôle croisé** sur la partie récente de la série d'inflation :
l'IPCH ne remonte qu'à 1996 et ne peut donc pas remplacer la série longue INSEE,
mais un écart significatif sur 1996-2025 signalerait une erreur de saisie.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

# unit=RCH_A_AVG : taux de variation annuel de l'indice moyen. Attention,
# le code RCH_A existe dans la nomenclature mais renvoie un jeu vide pour cette
# table — il faut bien demander la variante « _AVG ».
URL = (
    "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
    "prc_hicp_aind?format=JSON&geo=FR&unit=RCH_A_AVG&coicop=CP00&lang=fr"
)
SORTIE = Path("data/brut/eurostat_hicp.json")


def extraire(charge: dict) -> dict[int, float]:
    """Aplatit la structure JSON-stat d'Eurostat en série année -> taux."""
    temps = charge["dimension"]["time"]["category"]["index"]
    index_vers_annee = {position: int(annee) for annee, position in temps.items()}
    resultat = {}
    for position, valeur in charge["value"].items():
        annee = index_vers_annee.get(int(position))
        if annee is not None and valeur is not None:
            resultat[annee] = valeur / 100.0
    return dict(sorted(resultat.items()))


def main() -> int:
    try:
        demande = urllib.request.Request(
            URL, headers={"User-Agent": "retraite-notionnelle/0.1"}
        )
        with urllib.request.urlopen(demande, timeout=120) as reponse:
            charge = json.loads(reponse.read())
    except (urllib.error.HTTPError, urllib.error.URLError) as erreur:
        print(f"Eurostat indisponible : {erreur}", file=sys.stderr)
        return 1

    serie = extraire(charge)
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(
        json.dumps({"source": URL, "serie": serie}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"{len(serie)} années écrites dans {SORTIE}")
    if serie:
        premiere, derniere = min(serie), max(serie)
        print(f"Couverture {premiere}-{derniere}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
