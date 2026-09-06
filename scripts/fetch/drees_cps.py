#!/usr/bin/env python3
"""Récupération des Comptes de la protection sociale auprès de la DREES.

    python scripts/fetch/drees_cps.py

Les Comptes de la protection sociale sont la comptabilité nationale du social :
ils recensent, année par année et régime par régime, les prestations réellement
versées. Le risque ``VIEILLESSE-SURVIE`` est celui qui porte les retraites — et
c'est la SEULE série longue française de dépenses de retraite publiée par leur
producteur.

Deux grains, et deux couvertures :

* le **total tous régimes** remonte à 1959, sans interruption ;
* la **ventilation par régime** ne commence qu'en 1990. De 1981 à 1989, la DREES
  publie bien une ventilation, mais dans une nomenclature qui n'est pas celle
  qui suit — « Régime général de la Sécurité sociale » et « Régimes spéciaux »
  y recouvrent des périmètres que 1990 redécoupe. Les rapprocher demanderait
  une reconstitution que personne n'a publiée : ces neuf années restent donc
  hors de la ventilation, et le total les couvre.

L'API est celle d'Opendatasoft, interrogeable **sans clé**. Le fichier produit,
``data/brut/drees_cps.json``, est le document source : il n'est pas lu par le
modèle, seulement par ``scripts/verifier_donnees.py``, qui y applique le
regroupement des régimes et écrit ``data/reference/macro/``.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = (
    "https://data.drees.solidarites-sante.gouv.fr/api/explore/v2.1/catalog"
    "/datasets/305_les-comptes-de-la-protection-sociale/exports/json"
)
ENTETES = {"User-Agent": "retraite-notionnelle/0.1 (recherche publique)"}
SORTIE = Path("data/brut/drees_cps.json")

#: Poste des comptes retenu. ``E11-2`` est le risque vieillesse-survie tout
#: entier : pensions de droit direct et de droit dérivé, minimum vieillesse,
#: prestations liées à la dépendance des personnes âgées. C'est le seul niveau
#: publié sans interruption depuis 1959 ; les sous-postes ne le sont que depuis
#: 2020, et ils sont récupérés aussi, pour dire quelle part du total est de la
#: retraite au sens strict.
POSTE = "E11-2"

#: Sous-postes récupérés en plus, au niveau national seulement.
SOUS_POSTES = ("E11-21.1", "E11-22.1")


def recuperer(condition: str) -> list[dict]:
    url = f"{BASE}?{urllib.parse.urlencode({'where': condition})}"
    demande = urllib.request.Request(url, headers=ENTETES)
    with urllib.request.urlopen(demande, timeout=180) as reponse:
        return json.loads(reponse.read())


def main() -> int:
    codes = ", ".join(f'"{code}"' for code in (POSTE, *SOUS_POSTES))
    try:
        lignes = recuperer(f"ps_code in ({codes})")
    except (urllib.error.HTTPError, urllib.error.URLError) as erreur:
        print(f"DREES indisponible : {erreur}", file=sys.stderr)
        return 1

    # Trois séries, dans la forme où le vérificateur les attend : le total
    # national du risque, ses deux sous-postes de pensions, et la ventilation
    # par régime — celle-ci sous le libellé exact que publie la DREES, dont le
    # regroupement en systèmes lisibles relève du vérificateur et non d'ici.
    total: dict[str, float] = {}
    pensions: dict[str, dict[str, float]] = {code: {} for code in SOUS_POSTES}
    regimes: dict[str, dict[str, float]] = {}
    for ligne in lignes:
        annee, valeur = str(ligne["annee"]), ligne["val"]
        if valeur is None:
            continue
        if ligne["ps_code"] != POSTE:
            if ligne["si_niveau"] == "0":
                pensions[ligne["ps_code"]][annee] = valeur
            continue
        if ligne["si_niveau"] == "0":
            total[annee] = valeur
        elif ligne["si_niveau"] == "2":
            regimes.setdefault(ligne["nom_regime"], {})[annee] = valeur

    charge = {
        "source": BASE,
        "poste": POSTE,
        "total": dict(sorted(total.items())),
        "pensions": {code: dict(sorted(v.items())) for code, v in pensions.items()},
        "regimes": {nom: dict(sorted(v.items())) for nom, v in sorted(regimes.items())},
        "unite": "millions d'euros courants",
    }
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(
        json.dumps(charge, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    annees = sorted(int(a) for a in total)
    print(f"{len(annees)} années écrites dans {SORTIE}")
    print(f"Total tous régimes : {min(annees)}-{max(annees)}")
    print(f"Ventilation : {len(regimes)} régimes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
