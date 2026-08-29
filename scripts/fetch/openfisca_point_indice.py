#!/usr/bin/env python3
"""Point d'indice de la fonction publique et barème du minimum garanti.

    python scripts/fetch/openfisca_point_indice.py

Deux séries, une seule finalité : le **minimum garanti** de l'article L. 17 du
code des pensions civiles et militaires, plancher de la retraite des
fonctionnaires que ce modèle ne servait pas.

* le **point d'indice** — traitement annuel brut d'un point d'indice majoré,
  daté décret par décret depuis 1960. L'article fixe la référence du minimum
  garanti à « la valeur du traitement brut afférent à l'indice majoré 227 au
  1er janvier 2004 » : 227 × 52,7558 = 11 975,57 € par an, soit exactement les
  997,96 € par mois que publie le Service des retraites de l'État. Deux chemins
  indépendants, même chiffre — c'est ce qui rend l'ancre vérifiable.
  Les liquidations antérieures à 2004, où le gel n'existait pas encore, prennent
  bien le point de leur année : c'est à quoi sert le reste de la série.

* le **barème** — indice de référence, part acquise à quinze ans de services, et
  les deux pentes qui mènent à cent pour cent à quarante ans. La loi du 21 août
  2003 en a étalé la montée en charge sur dix ans, de 2004 à 2013, et l'a
  durcie : le barème d'avant servait la totalité dès vingt-cinq ans de services.

Statut de fiabilité. OpenFisca est une transcription tierce, pas le producteur :
ces valeurs plafonnent au niveau ``haute``. Le montant EN EUROS, lui, ne vient
pas d'ici : il est transcrit des publications du Service des retraites de l'État
dans ``legislation/minimum_garanti_montants.csv``, et prime sur toute projection
— la revalorisation des pensions à laquelle l'article renvoie ayant été gelée en
2014 et sous-indexée depuis, la projeter sur les prix donne pour 2024 un montant
supérieur de 4,6 % à celui qui a été payé.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

FRANCE = ("https://raw.githubusercontent.com/openfisca/openfisca-france/master/"
          "openfisca_france/parameters/marche_travail/"
          "remuneration_dans_fonction_publique/indicefp")
PENSION = ("https://raw.githubusercontent.com/openfisca/openfisca-france-pension/"
           "master/openfisca_france_pension/parameters/retraites/secteur_public/"
           "pension_civile/minimum_garanti")

#: Les cinq paramètres du barème, et la colonne qu'ils alimentent.
BAREME = {
    "valeur_indice_maj": "indice_majore",
    "part_valeur_indice_majore": "part_15_ans",
    "points_plus_15_ans": "points_15_30",
    "points_moins_40_ans": "points_30_40",
    "annee_moins_40_ans": "trimestres_seuil",
}

SORTIE = Path("data/brut/openfisca_point_indice.json")


def _lire(url: str) -> str:
    demande = urllib.request.Request(
        url, headers={"User-Agent": "retraite-notionnelle/0.1"}
    )
    with urllib.request.urlopen(demande, timeout=120) as reponse:
        return reponse.read().decode("utf-8")


def _serie_datee(texte: str) -> dict[str, float]:
    """Lit un fichier ``values: {date: {value: montant}}``."""
    import yaml

    charge = yaml.safe_load(texte)
    valeurs = {}
    for cle, contenu in (charge.get("values") or {}).items():
        montant = (contenu or {}).get("value")
        if montant is not None:
            valeurs[str(cle)] = float(montant)
    return dict(sorted(valeurs.items()))


def _bareme_par_annee(texte: str) -> dict[int, float]:
    """Lit un paramètre du minimum garanti, organisé en blocs datés.

    Le fichier n'est pas une série mais une collection de sous-paramètres
    ``before_2004_01_01`` / ``after_YYYY_01_01``, chacun portant une valeur
    unique : c'est la montée en charge, année de liquidation par année de
    liquidation. ``before`` désigne l'état du droit antérieur à la réforme ; on
    le range à l'année où il a commencé de s'appliquer, 1976.
    """
    import yaml

    charge = yaml.safe_load(texte)
    valeurs: dict[int, float] = {}
    for cle, contenu in charge.items():
        if not isinstance(contenu, dict) or "values" not in contenu:
            continue
        montants = [
            (str(d), (v or {}).get("value"))
            for d, v in (contenu.get("values") or {}).items()
        ]
        montants = [(d, v) for d, v in montants if v is not None]
        if not montants:
            continue
        montant = float(sorted(montants)[-1][1])
        if cle.startswith("before_"):
            valeurs[1976] = montant
        elif cle.startswith("after_"):
            valeurs[int(cle.split("_")[1])] = montant
    return dict(sorted(valeurs.items()))


def annualiser(valeurs: dict[str, float]) -> dict[int, float]:
    """Valeur EN VIGUEUR AU 1er JANVIER de chaque année.

    Contrairement au plafond de la Sécurité sociale, le point d'indice n'a pas
    à être moyenné sur l'année : le minimum garanti se calcule sur le traitement
    en vigueur à la liquidation, et le modèle ne connaît que l'année.
    """
    dates = sorted(valeurs)
    if not dates:
        return {}
    resultat: dict[int, float] = {}
    for annee in range(int(dates[0][:4]), date.today().year + 2):
        applicables = [d for d in dates if d <= f"{annee}-01-01"]
        if applicables:
            resultat[annee] = valeurs[applicables[-1]]
    return resultat


def main() -> int:
    try:
        point = annualiser(_serie_datee(_lire(f"{FRANCE}/point_indice_en_euros.yaml")))
        bareme = {
            colonne: _bareme_par_annee(_lire(f"{PENSION}/{fichier}.yaml"))
            for fichier, colonne in BAREME.items()
        }
    except (urllib.error.HTTPError, urllib.error.URLError) as erreur:
        print(f"OpenFisca indisponible : {erreur}", file=sys.stderr)
        return 1

    annees = sorted(point)
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(
        json.dumps({
            "source_point_indice": f"{FRANCE}/point_indice_en_euros.yaml",
            "source_bareme": PENSION,
            "recupere_le": date.today().isoformat(),
            "unite": "euros par an et par point d'indice majoré",
            "point_indice": {str(a): point[a] for a in annees},
            "bareme_minimum_garanti": {
                colonne: {str(a): v for a, v in serie.items()}
                for colonne, serie in bareme.items()
            },
        }, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )

    reference = point.get(2004)
    print(f"Point d'indice : {len(annees)} années, {annees[0]}-{annees[-1]}")
    if reference:
        print(f"Ancre de l'article L. 17 : 227 × {reference:.4f} = "
              f"{227 * reference:,.2f} € par an, soit {227 * reference / 12:,.2f} "
              f"€ par mois au 1er janvier 2004")
    print(f"Barème du minimum garanti : "
          f"{len(bareme['indice_majore'])} étapes de montée en charge")
    print(f"Écrit dans {SORTIE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
