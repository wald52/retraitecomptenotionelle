#!/usr/bin/env python3
"""Espérances de vie projetées, dérivées des quotients de l'INSEE.

    python scripts/fetch/insee_projections_mortalite.py

Le dépôt portait, pour les années projetées, six valeurs saisies à la main aux
années rondes 2030, 2040, 2050, 2060, 2070 — plus 2080, qui dépassait l'horizon
de la source dont elle se réclamait — et les gelait au-delà. Trois défauts d'un
coup : un millésime périmé, une extrapolation non déclarée, et une espérance de
vie qui cessait de progresser vingt ans avant la fin de la projection.

L'INSEE publie mieux, et le publie en clair : ses **projections de population
2026** livrent les quotients de mortalité par âge et par année, de 0 à 120 ans
et de 2023 à 2125, pour les trois hypothèses d'espérance de vie. On reprend la
centrale et on en dérive e0, e60 et e65, année par année.

POURQUOI DÉRIVER PLUTÔT QUE SAISIR
-----------------------------------
Parce que l'INSEE ne publie pas e65, ici pas plus qu'ailleurs — et que la
calibration du modèle en a besoin pour fixer la pente de la force de mortalité.
La méthode est celle qui sert déjà aux années d'avant 1960 dans
``verifier_donnees.py`` : une espérance de vie n'est que la somme cumulée des
survies, et le dépôt a les quotients.

LA CONVENTION D'ÂGE N'EST PAS CELLE DES TABLES DU MOMENT, ET LE CONTRÔLE LE DIT
-------------------------------------------------------------------------------
Ce classeur indexe ses quotients par **âge atteint dans l'année**, non par âge
exact. Le demi-an que la formule usuelle ajoute — ``e = 0,5 + Σ survies`` — est
donc déjà compris dans l'indexation, et l'ajouter une seconde fois surestimerait
chaque espérance d'un demi-an.

Ce n'est pas un raisonnement, c'est une mesure : l'INSEE publie l'espérance de
vie à la naissance que son scénario central implique en 2070, **89,5 ans pour
les femmes et 86,7 ans pour les hommes** (Insee Première n° 2108). La somme des
survies sans demi-an rend 89,50 et 86,71 ; avec demi-an, 90,00 et 87,21. Le
contrôle est reconduit à chaque exécution, et le script échoue s'il casse.

Sur 2025, dernière année que le dépôt certifie par ailleurs depuis la Banque de
données macroéconomiques, la même somme rend 85,85 et 80,30 contre 85,90 et
80,40 publiés — et pour e60, 27,89 et 23,84 contre 28,00 et 23,90. Moins d'un
dixième d'année d'écart, la marge que le dépôt accepte déjà de ses autres
dérivations.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lecture_xlsx import feuilles  # noqa: E402

URL = ("https://www.insee.fr/fr/statistiques/fichier/8990899/hyp_mortalite.xlsx")

SORTIE = Path("data/brut/insee_projections_mortalite.json")

#: Feuille du classeur -> code de sexe du dépôt. Le classeur en porte huit :
#: hypothèses centrale, basse, haute et mortalité constante, par sexe. On ne
#: reprend que la centrale, seule dont le COR et le dépôt se réclament.
FEUILLES = {"centralF": "F", "centralH": "H"}

#: Première année reprise. Le classeur commence en 2023, mais 2023 à 2025 sont
#: observées et le dépôt les certifie déjà depuis l'INSEE BDM et l'OCDE :
#: l'observé prime sur le projeté, y compris quand le projeté vient du même
#: producteur.
PREMIERE_ANNEE_PROJETEE = 2026

#: Espérances dérivées, aux âges dont le modèle se sert.
AGES = (0, 60, 65)

#: Contrôle de la convention d'âge : espérance de vie à la naissance que le
#: scénario central implique en 2070, telle que l'INSEE la publie.
CONTROLE = {("F", 2070): 89.5, ("H", 2070): 86.7}
TOLERANCE_CONTROLE = 0.1


def _quotients(grille: dict) -> dict[int, dict[int, float]]:
    """Quotients ``annee -> age -> qx`` lus dans une feuille du classeur.

    Disposition : la ligne d'en-tête porte les années à partir de la deuxième
    colonne, chaque ligne suivante un âge en première colonne. Les quotients
    sont exprimés pour 100 000.
    """
    annees = {
        colonne: int(valeur)
        for (ligne, colonne), valeur in grille.items()
        if ligne == 1 and colonne > 0 and isinstance(valeur, float)
    }
    if not annees:
        raise LookupError("aucune année en en-tête de feuille")

    table: dict[int, dict[int, float]] = {}
    ages = {
        ligne: int(valeur)
        for (ligne, colonne), valeur in grille.items()
        if colonne == 0 and ligne > 1 and isinstance(valeur, float)
    }
    for ligne, age in ages.items():
        for colonne, annee in annees.items():
            quotient = grille.get((ligne, colonne))
            if not isinstance(quotient, float):
                continue
            # Un quotient est une probabilité : ce qui n'en est pas une n'est
            # pas une valeur de la table.
            probabilite = quotient / 100_000.0
            if not 0.0 <= probabilite <= 1.0:
                continue
            table.setdefault(annee, {})[age] = probabilite
    return table


def esperance(quotients: dict[int, float], age: int) -> float:
    """Espérance de vie résiduelle à ``age``, somme cumulée des survies.

    Sans le demi-an de la formule usuelle : le classeur indexe ses quotients par
    âge atteint dans l'année, qui le comprend déjà. Voir l'en-tête du module.
    """
    total, survie, courant = 0.0, 1.0, age
    while courant in quotients:
        survie *= 1.0 - quotients[courant]
        total += survie
        courant += 1
    return total


def extraire(donnees: bytes) -> dict[str, float]:
    """Espérances ``annee|sexe|mesure`` dérivées du classeur."""
    classeur = feuilles(donnees)
    manquantes = set(FEUILLES) - set(classeur)
    if manquantes:
        raise LookupError(
            f"feuilles absentes du classeur : {sorted(manquantes)} "
            f"(présentes : {sorted(classeur)})"
        )

    serie: dict[str, float] = {}
    for feuille, sexe in FEUILLES.items():
        table = _quotients(classeur[feuille])
        for annee, quotients in table.items():
            if annee < PREMIERE_ANNEE_PROJETEE:
                continue
            # Une table tronquée rendrait une espérance trop courte : on exige
            # que la table aille jusqu'au grand âge avant d'en tirer un chiffre.
            if max(quotients) < 105:
                continue
            for age in AGES:
                serie[f"{annee}|{sexe}|e{age}"] = round(esperance(quotients, age), 2)
    return serie


def main() -> int:
    print(f"Source    {URL}")
    try:
        with urllib.request.urlopen(URL, timeout=300) as reponse:
            donnees = reponse.read()
    except (urllib.error.HTTPError, urllib.error.URLError) as erreur:
        print(f"ÉCHEC   téléchargement : {erreur}", file=sys.stderr)
        return 1
    print(f"Classeur  {len(donnees) / 1024:,.0f} Ko")

    try:
        serie = extraire(donnees)
    except (LookupError, ValueError) as erreur:
        print(f"ÉCHEC   lecture du classeur : {erreur}", file=sys.stderr)
        return 1

    annees = sorted({int(cle.split("|")[0]) for cle in serie})
    if not annees:
        print("ÉCHEC   aucune espérance dérivée", file=sys.stderr)
        return 1

    # Le contrôle qui autorise la méthode : la convention d'âge du classeur
    # n'est pas celle des tables du moment, et seule la valeur publiée par
    # l'INSEE peut trancher. Sans lui, un demi-an d'erreur passerait dans le
    # diviseur de conversion de toutes les liquidations à venir.
    for (sexe, annee), attendu in CONTROLE.items():
        obtenu = serie.get(f"{annee}|{sexe}|e0")
        if obtenu is None or abs(obtenu - attendu) > TOLERANCE_CONTROLE:
            print(f"ÉCHEC   espérance à la naissance {sexe} en {annee} : "
                  f"{obtenu} contre {attendu} publié par l'INSEE", file=sys.stderr)
            return 1
        print(f"Contrôle  e0 {sexe} {annee} : {obtenu} ans, INSEE {attendu} ans")

    # Deux contrôles de vraisemblance, sans lesquels un décalage de colonne
    # passerait inaperçu : l'espérance de vie croît sur toute la projection, et
    # les femmes vivent plus longtemps que les hommes à chaque année.
    for sexe in FEUILLES.values():
        suite = [serie[f"{a}|{sexe}|e0"] for a in annees]
        if any(b < a - 0.01 for a, b in zip(suite, suite[1:])):
            print(f"ÉCHEC   espérance à la naissance non croissante ({sexe})",
                  file=sys.stderr)
            return 1
    for annee in annees:
        if serie[f"{annee}|F|e60"] <= serie[f"{annee}|H|e60"]:
            print(f"ÉCHEC   e60 des femmes sous celle des hommes en {annee}",
                  file=sys.stderr)
            return 1

    manquantes = [a for a in range(annees[0], annees[-1] + 1) if a not in annees]
    if manquantes:
        print(f"\nAnnées sans espérance : {manquantes}", file=sys.stderr)

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(
        json.dumps({
            "source": URL,
            "publication": "INSEE, projections de population 2026 pour la "
                           "France — hypothèses de mortalité jusqu'en 2125, "
                           "hypothèse centrale (Insee Résultats, 2026)",
            "recupere_le": date.today().isoformat(),
            "note": "e0, e60 et e65 DÉRIVÉES des quotients de mortalité par âge "
                    "publiés par l'INSEE, dont l'espérance à 65 ans que l'INSEE "
                    "ne publie jamais. Somme cumulée des survies, sans le "
                    "demi-an usuel : le classeur indexe ses quotients par âge "
                    "atteint dans l'année, qui le comprend déjà. La méthode "
                    "retrouve l'espérance à la naissance publiée pour 2070 "
                    "(89,5 ans et 86,7 ans) à un centième près.",
            "serie": dict(sorted(
                serie.items(),
                key=lambda kv: (int(kv[0].split("|")[0]), kv[0].split("|")[1],
                                kv[0].split("|")[2]),
            )),
        }, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"\n{len(serie)} espérances écrites dans {SORTIE}")
    print(f"Couverture {annees[0]}-{annees[-1]}, {len(FEUILLES)} sexes, "
          f"e0, e60 et e65")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
