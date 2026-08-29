#!/usr/bin/env python3
"""Quotients de mortalité par âge d'avant 1986, chez l'INED.

    python scripts/fetch/ined_vallin_mesle.py

`docs/limites.md` a longtemps rangé cette série parmi ce qui est « hors de
portée » : Eurostat ne publie rien avant 1986, ses classes ouvertes ne sont pas
des quotients à un âge donné, et « la Human Mortality Database, seule à couvrir
la France depuis 1816, exige une inscription : elle n'est donc pas récupérable
par script ».

C'est inexact, et de peu : la HMD n'est pas seule. Jacques Vallin et France
Meslé ont reconstitué les **tables de mortalité françaises de 1806 à 1997**,
publiées par l'INED en 2001, et l'INED en sert librement le contenu du cédérom,
sans inscription, à l'adresse ci-dessous. Le fichier `Tableau-II-B-1.xls` porte
exactement ce qui manquait :

    « Quotients du moment par année d'âge (de 0 à 104 ans), de 1806 à 2102 »

trois feuilles — hommes, femmes, ensemble des deux sexes.

Deux gains d'un coup, donc : les années d'AVANT 1986, et les âges AU-DELÀ DE 94
que le modèle raccordait jusqu'ici à sa loi de Gompertz-Makeham.

**Contrôle croisé.** Les deux sources se recouvrent de 1986 à 1997. Sur ces
douze années et 85 âges, l'écart médian entre la reconstitution de l'INED et
les tables d'Eurostat est de 0,4 à 0,7 % — l'écart maximal, autour de 9 %, ne
se rencontre qu'aux âges où le quotient est minuscule et l'écart relatif donc
trompeur. Deux reconstructions indépendantes qui concordent à ce point valent
mieux qu'une seule.

**Périmètre repris.** 1899-1985 seulement, tous âges. Le XIXe siècle est hors
du champ du modèle, dont la répartition commence en 1941 ; et à partir de 1986,
c'est Eurostat qui est le producteur de la donnée observée — on ne mélange pas
deux sources sur une même année. L'INED couvre pourtant 1986-1997 lui aussi, et
jusqu'à 104 ans là où Eurostat s'arrête à 94 : c'est un complément possible,
laissé de côté pour ne pas panacher.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lecture_xls import feuilles  # noqa: E402

URL = ("https://www.ined.fr/Xtradocs/cdrom_vallin_mesle/"
       "Fonctions-de-mortalite/Indicateurs-du-moment/Tableau-II-B-1.xls")

SORTIE = Path("data/brut/ined_vallin_mesle.json")

#: Bornes reprises. Voir la note de périmètre ci-dessus.
PREMIERE_ANNEE, DERNIERE_ANNEE = 1899, 1985

#: Feuille du classeur -> code de sexe du dépôt.
SEXES = {"Hommes": "H", "Femmes": "F"}

#: Dernier âge publié par la table.
AGE_MAXIMAL = 104


def extraire(donnees: bytes) -> dict[str, float]:
    """Quotients ``annee|sexe|age`` lus dans le classeur.

    Disposition du classeur : une ligne par année, la colonne 0 portant
    l'année et les colonnes 1 à 105 les âges 0 à 104.
    """
    classeur = feuilles(donnees)
    manquantes = set(SEXES) - set(classeur)
    if manquantes:
        raise LookupError(
            f"feuilles absentes du classeur : {sorted(manquantes)} "
            f"(présentes : {sorted(classeur)})"
        )

    serie: dict[str, float] = {}
    for feuille, sexe in SEXES.items():
        cellules = classeur[feuille]
        lignes = {int(cellules[(ligne, 0)]): ligne
                  for (ligne, colonne) in cellules if colonne == 0}
        for annee in range(PREMIERE_ANNEE, DERNIERE_ANNEE + 1):
            ligne = lignes.get(annee)
            if ligne is None:
                continue
            for age in range(0, AGE_MAXIMAL + 1):
                quotient = cellules.get((ligne, age + 1))
                # Un quotient est une probabilité : ce qui n'en est pas une
                # n'est pas une valeur de la table, c'est une cellule de
                # mise en forme qu'on aurait mal lue.
                if quotient is None or not 0.0 < quotient <= 1.0:
                    continue
                serie[f"{annee}|{sexe}|{age}"] = round(quotient, 6)
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
        print("ÉCHEC   aucun quotient lu", file=sys.stderr)
        return 1

    # Deux contrôles de vraisemblance, sans lesquels une erreur de décalage de
    # colonne passerait inaperçue : la mortalité infantile recule tout au long
    # du siècle, et le quotient croît avec l'âge chez les adultes.
    infantile = {a: serie.get(f"{a}|H|0") for a in (1900, 1950, 1980)}
    if not all(infantile.values()):
        print(f"ÉCHEC   mortalité infantile absente : {infantile}", file=sys.stderr)
        return 1
    if not infantile[1900] > infantile[1950] > infantile[1980]:
        print(f"ÉCHEC   mortalité infantile non décroissante : {infantile}",
              file=sys.stderr)
        return 1
    for annee in (1900, 1950, 1980):
        for sexe in SEXES.values():
            profil = [serie.get(f"{annee}|{sexe}|{age}") for age in range(60, 91)]
            # Le quotient CROÎT AVEC L'ÂGE — en tendance, pas pas à pas : sur
            # des effectifs anciens il recule d'un âge au suivant sans que rien
            # ne soit faux. On exige donc que la décennie 80-90 soit partout
            # au-dessus de la décennie 60-70, ce qu'un décalage de colonne ne
            # produirait pas.
            if any(v is None for v in profil) or min(profil[20:]) <= max(profil[:11]):
                print(f"ÉCHEC   profil par âge invraisemblable de 60 à 90 ans "
                      f"({annee}, {sexe})", file=sys.stderr)
                return 1

    manquantes = [a for a in range(annees[0], annees[-1] + 1) if a not in annees]
    if manquantes:
        print(f"\nAnnées sans quotient : {manquantes}", file=sys.stderr)

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(
        json.dumps({
            "source": URL,
            "publication": "Vallin (Jacques) et Meslé (France), « Tables de "
                           "mortalité françaises pour les XIXe et XXe siècles et "
                           "projections pour le XXIe siècle », INED, Données "
                           "statistiques n° 4, 2001 — Tableau II-B-1",
            "recupere_le": date.today().isoformat(),
            "note": "quotients du moment par année d'âge, 0 à 104 ans. Le dépôt "
                    "n'en reprend que 1899-1985 : à partir de 1986 la donnée "
                    "observée vient d'Eurostat, son producteur, et l'on ne "
                    "panache pas deux sources sur une même année.",
            "serie": dict(sorted(
                serie.items(),
                key=lambda kv: (int(kv[0].split("|")[0]), kv[0].split("|")[1],
                                int(kv[0].split("|")[2])),
            )),
        }, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"\n{len(serie)} quotients écrits dans {SORTIE}")
    print(f"Couverture {annees[0]}-{annees[-1]}, âges 0-{AGE_MAXIMAL}, "
          f"{len(SEXES)} sexes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
