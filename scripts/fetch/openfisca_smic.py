#!/usr/bin/env python3
"""Récupération du SMIC horaire brut, depuis OpenFisca-France.

    python scripts/fetch/openfisca_smic.py

À quoi il sert. Un trimestre de retraite ne s'acquiert pas par le temps qui
passe mais par un MONTANT COTISÉ : depuis 2014, il faut avoir cotisé sur
150 fois le SMIC horaire pour en valider un, et 200 fois entre 1972 et 2013.
Sans cette série, le modèle validait quatre trimestres par année de carrière
quelle que soit la rémunération, ce qui surestimait la durée d'assurance des
carrières à temps très partiel — précisément celles que le système actuel
protège le plus, et donc celles où l'écart avec les comptes notionnels est le
plus grand.

L'INSEE ne publie pas de série longue du SMIC horaire en accès ouvert. La
seule série machine qui remonte à 1970 est celle d'**OpenFisca-France**, le
modèle socio-fiscal maintenu par l'administration : un fichier YAML daté
décret par décret, chaque valeur portant sa référence au *Journal officiel*.

Statut de fiabilité. OpenFisca n'est pas le producteur de la donnée mais une
**transcription tierce** du *Journal officiel*. Les valeurs qui en viennent
sont donc versées au niveau ``haute``, jamais ``certifiee`` — même règle que
pour le plafond de la Sécurité sociale et les valeurs du point.

Unités. Les valeurs sont en francs jusqu'au barème de juillet 2001, en euros à
partir de celui de janvier 2002. La conversion est arithmétique (÷ 6,55957),
sans revalorisation. Le modèle retient, pour chaque année, le barème en vigueur
au 1er janvier — c'est celui qu'oppose la caisse pour l'année entière.

Le fichier produit, ``data/brut/openfisca_smic.json``, est le **document
source** : il n'est pas lu par le modèle, seulement par le vérificateur.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

import yaml

URL = ("https://raw.githubusercontent.com/openfisca/openfisca-france/master/"
       "openfisca_france/parameters/marche_travail/salaire_minimum/smic/"
       "smic_b_horaire.yaml")
SORTIE = Path("data/brut/openfisca_smic.json")
ENTETES = {"User-Agent": "retraite-notionnelle/0.1 (recherche publique)"}

#: Passage à l'euro : les barèmes antérieurs sont libellés en francs.
ANNEE_EURO = 2002
TAUX_FRANC_EURO = 6.55957


def _texte(cle) -> str:
    return cle if isinstance(cle, str) else cle.isoformat()


def telecharger() -> dict:
    requete = urllib.request.Request(URL, headers=ENTETES)
    with urllib.request.urlopen(requete, timeout=60) as reponse:
        return yaml.safe_load(reponse.read().decode("utf-8"))


def serie_annuelle(parametre: dict) -> dict[int, dict]:
    """Barème en vigueur au 1er janvier de chaque année, converti en euros."""
    baremes = sorted(
        (_texte(cle), valeur["value"])
        for cle, valeur in parametre["values"].items()
        if valeur.get("value") is not None
    )
    if not baremes:
        raise SystemExit("aucun barème exploitable dans le paramètre OpenFisca")

    premiere = int(baremes[0][0][:4])
    derniere = int(baremes[-1][0][:4])
    annuelle: dict[int, dict] = {}
    for annee in range(premiere, derniere + 1):
        applicables = [b for b in baremes if b[0] <= f"{annee}-01-01"]
        if not applicables:
            continue
        date_bareme, valeur = applicables[-1]
        euros = valeur if annee >= ANNEE_EURO else valeur / TAUX_FRANC_EURO
        annuelle[annee] = {
            "valeur_euros": round(euros, 6),
            "valeur_source": valeur,
            "unite_source": "euro" if annee >= ANNEE_EURO else "franc",
            "bareme_du": date_bareme,
        }
    return annuelle


def main() -> int:
    try:
        parametre = telecharger()
    except (urllib.error.URLError, urllib.error.HTTPError) as erreur:
        print(f"échec du téléchargement : {erreur}", file=sys.stderr)
        return 1

    annuelle = serie_annuelle(parametre)
    document = {
        "source": URL,
        "recupere_le": date.today().isoformat(),
        "description": parametre.get("description", ""),
        "avertissement": (
            "Transcription tierce du Journal officiel : fiabilité plafonnée à "
            "« haute », jamais « certifiee »."
        ),
        "valeurs": {str(annee): valeurs for annee, valeurs in sorted(annuelle.items())},
    }
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"{SORTIE} : {len(annuelle)} années, {min(annuelle)}-{max(annuelle)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
