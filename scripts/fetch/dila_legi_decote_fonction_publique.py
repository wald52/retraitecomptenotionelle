#!/usr/bin/env python3
"""Montée en charge de la décote de la fonction publique, dans la loi de 2003.

    python scripts/fetch/dila_legi_decote_fonction_publique.py

**Ce script télécharge environ 1,1 Go et met un quart d'heure.**

Ce qu'il referme. La fonction publique n'a pas la décote du régime général :
l'article L. 14 du code des pensions lui donne la sienne, qui n'existe qu'à
compter de 2006 et monte en charge d'un huitième de point par an jusqu'en 2015.
Son âge d'annulation n'est pas davantage un âge en propre — c'est la LIMITE
D'ÂGE du grade, diminuée d'un nombre de trimestres qui décroît jusqu'à
s'annuler en 2020. Opposer 1,25 % et 67 ans à une liquidation de 2008, comme le
faisait le modèle, décote dix fois trop.

Ces quinze lignes étaient saisies, et `docs/limites.md` les rangeait parmi les
paramètres « repris des textes, non recontrôlés ». Elles sont pourtant écrites,
et dans un seul tableau : l'**article 66 III de la loi n° 2003-775 du 21 août
2003**, que la base LEGI garde comme texte consolidé. Le dépouillement en flux
le rend à plat, une ligne à la suite de l'autre :

    « I : 2006 II : 0,125 % III : Limite d'âge moins 16 trimestres »

DEUX CHOSES À SAVOIR

* **le tableau s'arrête en 2019**, et la dernière ligne perd ses repères de
  colonne — « 2019 1,25 % Limite d'âge moins 1 trimestre ». Le récupérateur
  tolère l'omission plutôt que de manquer une ligne ;
* **la ligne 2020 n'est pas dans le tableau.** La dérogation court « jusqu'au
  31 décembre 2019 » : au-delà, c'est l'article L. 14 qui s'applique en plein —
  coefficient de 1,25 %, âge d'annulation égal à la limite d'âge, soit zéro
  trimestre. Cette ligne-là est une jonction entre deux textes, et reste hors
  de la certification.

Le même article 66 porte, à son II, le nombre de trimestres nécessaires au
pourcentage maximum de la pension civile — une autre table, que le modèle lit
ailleurs. Elle n'est pas reprise ici : ses lignes ne portent ni pourcentage ni
limite d'âge, et le motif de lecture les écarte de lui-même.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

RACINE = "https://echanges.dila.gouv.fr/OPENDATA/LEGI/"
SORTIE = Path("data/brut/dila_legi_decote_fonction_publique.json")

#: La loi qui porte le tableau, et l'article qui le fixe.
LOI, ARTICLE = "2003-775", "66"

#: Années que le tableau couvre. Il s'ouvre avec la décote et se ferme avec la
#: fin de la dérogation ; au-delà, l'article L. 14 s'applique en plein.
ANNEES = (2006, 2019)

#: Coefficient par trimestre : un huitième de point la première année, un et
#: quart à la cible. Hors de cette plage, la ligne lue parle d'autre chose.
COEFFICIENT_PLAUSIBLE = (0.00125, 0.0125)

#: « I : 2006 II : 0,125 % III : Limite d'âge moins 16 trimestres », et la
#: dernière ligne du tableau, qui a perdu ses repères de colonne : « 2019
#: 1,25 % Limite d'âge moins 1 trimestre ».
LIGNE = re.compile(
    r"(?:I\s*:\s*)?(20\d\d)\s*(?:II\s*:\s*)?(\d(?:,\d+)?)\s*%\s*"
    r"(?:III\s*:\s*)?Limite d['’]âge moins (\d{1,2}) trimestres?",
    re.I)

FILTRE = r"""
import re, sys
LOI = re.compile(r"2003-775")
CIBLE = re.compile(r"Limite d['’]âge moins", re.I)
BALISES = re.compile(r"<[^>]+>")
tampon = ""
for bloc in iter(lambda: sys.stdin.buffer.read(1 << 20), b""):
    tampon += bloc.decode("utf-8", errors="replace")
    morceaux = tampon.split("<?xml")
    tampon = morceaux.pop()
    for morceau in morceaux:
        texte = re.sub(r"\s+", " ", BALISES.sub(" ", morceau)).strip()
        if not (LOI.search(texte[:600]) and CIBLE.search(texte)):
            continue
        debut = re.search(r"<DATE_DEBUT>(.*?)</DATE_DEBUT>", morceau)
        print("@@@ " + (debut.group(1) if debut else "?"))
        print(texte[:20000])
        sys.stdout.flush()
"""


def dernier_dump() -> str:
    with urllib.request.urlopen(RACINE, timeout=120) as reponse:
        page = reponse.read().decode("utf-8", errors="replace")
    noms = sorted(set(re.findall(r'href="(Freemium_legi_global_[^"]+\.tar\.gz)"', page)))
    if not noms:
        raise LookupError("aucun dump global dans le répertoire LEGI de la DILA")
    return RACINE + noms[-1]


def montee_en_charge(versions: list[tuple[str, str]]) -> dict[int, dict[str, float]]:
    """Coefficient et trimestres retranchés à la limite d'âge, année par année."""
    table: dict[int, dict[str, float]] = {}
    for _, texte in sorted(versions):
        for annee, coefficient, trimestres in LIGNE.findall(texte):
            valeur = float(coefficient.replace(",", ".")) / 100
            if not COEFFICIENT_PLAUSIBLE[0] <= valeur <= COEFFICIENT_PLAUSIBLE[1]:
                continue
            table[int(annee)] = {
                "coefficient": valeur,
                "trimestres_avant_limite": float(trimestres),
            }
    return table


def depouiller(url: str) -> list[tuple[str, str]]:
    lecture = subprocess.Popen(
        ["curl", "-sS", "--max-time", "7200", url], stdout=subprocess.PIPE
    )
    detar = subprocess.Popen(
        ["tar", "-xzO"], stdin=lecture.stdout, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    lecture.stdout.close()
    filtre = subprocess.Popen(
        [sys.executable, "-c", FILTRE], stdin=detar.stdout,
        stdout=subprocess.PIPE, text=True,
    )
    detar.stdout.close()
    sortie, _ = filtre.communicate()
    lecture.wait()

    versions = []
    for bloc in sortie.split("@@@ ")[1:]:
        entete, _, corps = bloc.partition("\n")
        versions.append((entete.strip(), corps))
    return versions


def main() -> int:
    try:
        url = dernier_dump()
    except (urllib.error.HTTPError, urllib.error.URLError, LookupError) as erreur:
        print(f"ÉCHEC   répertoire LEGI : {erreur}", file=sys.stderr)
        return 1

    print(f"Dump      {url.rsplit('/', 1)[-1]}")
    print("Lecture en flux d'environ 9 Go décompressés : comptez un quart d'heure.\n")
    table = montee_en_charge(depouiller(url))
    annees = sorted(table)
    if not annees or (annees[0], annees[-1]) != ANNEES:
        print(f"ÉCHEC   le tableau couvre "
              f"{annees[0] if annees else '—'}-{annees[-1] if annees else '—'}, "
              f"et non {ANNEES[0]}-{ANNEES[1]}", file=sys.stderr)
        return 1
    if annees != list(range(ANNEES[0], ANNEES[1] + 1)):
        print("ÉCHEC   la suite des années a des trous", file=sys.stderr)
        return 1

    # La décote monte, l'âge d'annulation monte avec elle : le nombre de
    # trimestres retranchés à la limite d'âge décroît d'une année sur l'autre.
    for precedente, courante in zip(annees, annees[1:]):
        if table[courante]["coefficient"] < table[precedente]["coefficient"]:
            print(f"ÉCHEC   le coefficient recule de {precedente} à {courante}",
                  file=sys.stderr)
            return 1
        if (table[courante]["trimestres_avant_limite"]
                > table[precedente]["trimestres_avant_limite"]):
            print(f"ÉCHEC   les trimestres retranchés montent de {precedente} "
                  f"à {courante}", file=sys.stderr)
            return 1

    for annee in annees:
        ligne = table[annee]
        print(f"OK      {annee} : {ligne['coefficient']:.5%} par trimestre, "
              f"limite d'âge moins {ligne['trimestres_avant_limite']:g} trimestres")

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(
        json.dumps({
            "source": url,
            "article": f"loi n° {LOI} du 21 août 2003, article {ARTICLE} III",
            "recupere_le": date.today().isoformat(),
            "note": "montée en charge de la décote de la fonction publique, lue à "
                    "l'année de liquidation. La ligne 2020 du dépôt n'est pas dans "
                    "ce tableau : la dérogation court jusqu'au 31 décembre 2019, "
                    "et l'article L. 14 s'applique en plein ensuite.",
            "serie": {
                f"{mesure}|{annee}": valeur
                for annee, ligne in sorted(table.items())
                for mesure, valeur in sorted(ligne.items())
            },
        }, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"\n{len(table)} années écrites dans {SORTIE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
