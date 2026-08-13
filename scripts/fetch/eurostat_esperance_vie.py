#!/usr/bin/env python3
"""Récupération des espérances de vie à 60 et 65 ans auprès d'Eurostat.

    python scripts/fetch/eurostat_esperance_vie.py

Pourquoi Eurostat pour une donnée française : l'INSEE publie l'espérance de vie
à 0, 1, 20, 40 et 60 ans, **mais pas à 65 ans**, alors que la calibration de la
table de mortalité du modèle a besoin des deux (e60 et e65 fixent à la fois le
niveau et la pente de la force de mortalité). La table ``demo_mlexpec``
d'Eurostat donne l'espérance de vie âge par âge ; les valeurs françaises y sont
celles transmises par l'INSEE.

Deux territoires sont demandés, et leur ordre de priorité est délibéré :

* ``FR`` — France y compris départements d'outre-mer, 1998-2024 ;
* ``FX`` — France métropolitaine, 1986-2012, qui prolonge la série vers l'amont
  sur le même champ que les séries INSEE du modèle.

Avant 1986, aucune source n'est automatisable : l'espérance de vie à 65 ans y
reste saisie à partir des tables TD/TV. Voir docs/limites.md §1.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = ("https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
        "demo_mlexpec?format=JSON&age=Y60&age=Y65&sex=M&sex=F&unit=YR")
TERRITOIRES = ("FX", "FR")  # ordre de priorité croissante : FR écrase FX
SEXES = {"M": "H", "F": "F"}
SORTIE = Path("data/brut/eurostat_esperance_vie.json")


def aplatir(charge: dict) -> dict[str, float]:
    """Aplatit la structure JSON-stat en clés ``annee|sexe|mesure``.

    Eurostat renvoie un tableau creux : la position d'une valeur encode les
    coordonnées de toutes les dimensions, du plus lent au plus rapide.
    """
    dimensions = charge["id"]
    tailles = charge["size"]
    index = {
        nom: {rang: code
              for code, rang in charge["dimension"][nom]["category"]["index"].items()}
        for nom in dimensions
    }

    resultat: dict[str, float] = {}
    for position, valeur in charge["value"].items():
        if valeur is None:
            continue
        reste = int(position)
        coordonnees = {}
        for rang in reversed(range(len(dimensions))):
            nom = dimensions[rang]
            coordonnees[nom] = index[nom][reste % tailles[rang]]
            reste //= tailles[rang]
        sexe = SEXES.get(coordonnees["sex"])
        if sexe is None:
            continue
        mesure = "e" + coordonnees["age"].removeprefix("Y")
        resultat[f"{coordonnees['time']}|{sexe}|{mesure}"] = float(valeur)
    return resultat


def main() -> int:
    serie: dict[str, float] = {}
    territoires_utilises = []
    for territoire in TERRITOIRES:
        url = f"{BASE}&geo={territoire}"
        try:
            demande = urllib.request.Request(
                url, headers={"User-Agent": "retraite-notionnelle/0.1"}
            )
            with urllib.request.urlopen(demande, timeout=120) as reponse:
                charge = json.loads(reponse.read())
        except (urllib.error.HTTPError, urllib.error.URLError) as erreur:
            print(f"Eurostat indisponible ({territoire}) : {erreur}", file=sys.stderr)
            return 1
        valeurs = aplatir(charge)
        serie.update(valeurs)
        territoires_utilises.append(f"{territoire} ({len(valeurs)} valeurs)")
        print(f"OK      {territoire} : {len(valeurs)} valeurs")

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(
        json.dumps({"source": BASE, "territoires": territoires_utilises,
                    "serie": dict(sorted(serie.items()))},
                   ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    annees = sorted({int(cle.split("|")[0]) for cle in serie})
    print(f"\n{len(serie)} valeurs écrites dans {SORTIE}")
    if annees:
        print(f"Couverture {annees[0]}-{annees[-1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
