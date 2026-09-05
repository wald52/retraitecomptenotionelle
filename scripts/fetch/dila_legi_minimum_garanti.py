#!/usr/bin/env python3
"""Barème du minimum garanti de la fonction publique, dans la loi de 2003.

    python scripts/fetch/dila_legi_minimum_garanti.py

**Ce script télécharge environ 1,1 Go et met un quart d'heure.**

Le minimum garanti est le plancher de la fonction publique, le pendant du
minimum contributif du privé. Son barème est un escalier à trois marches sur la
durée de SERVICES, et la loi du 21 août 2003 en a rabattu chacune, année après
année : 60 % du traitement de référence à quinze ans de services en 2003,
57,5 % en 2013 ; quatre points par année supplémentaire jusqu'à vingt-cinq ans,
deux et demi jusqu'à trente. Ces onze lignes étaient saisies d'OpenFisca.

Elles sont pourtant écrites, et dans le même article que la décote de la
fonction publique — le **V de l'article 66 de la loi n° 2003-775**, qui déroge
aux a et b de l'article L. 17 du code des pensions le temps de la montée en
charge. Le dépouillement en flux rend son tableau à plat, colonne par colonne :

    « I : 2004 II : 59,7 % III : 217 IV : 3,8 points V : Vingt-cinq ans et
      demi VI : 0,04 point »

CE QUE CHAQUE COLONNE DEVIENT DANS LE DÉPÔT

* **II** — la fraction servie à quinze ans de services : `part_15_ans` ;
* **III** — l'indice majoré dont le traitement au 1er janvier 2004 sert de
  référence : `indice_majore` ;
* **IV** — les points gagnés par année supplémentaire de quinze ans à la borne
  de la colonne V. Le dépôt les compte PAR TRIMESTRE et en fraction, non en
  points de pourcentage : 3,8 points par an font 0,0095 ;
* **V** — cette borne, écrite en toutes lettres et parfois en demi-années :
  « Vingt-cinq ans et demi » fait 102 trimestres ;
* **VI** — les points gagnés au-delà, jusqu'à quarante ans : `points_30_40`,
  compté de la même façon.

**LA LIGNE 1976 DU DÉPÔT N'EST PAS DANS LE TABLEAU.** Celui-ci s'ouvre sur une
ligne « 2003 » qui décrit le droit antérieur — 60 %, indice 216, quatre points,
vingt-cinq ans —, que le dépôt date de 1976, année où le barème a pris cette
forme. Les valeurs sont les mêmes, la clé ne l'est pas : cette ligne-là reste
une transcription, et le récupérateur ne lit que les années 2004 et suivantes.
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
SORTIE = Path("data/brut/dila_legi_minimum_garanti.json")

#: La loi qui porte le tableau, et l'article qui le fixe.
LOI, ARTICLE = "2003-775", "66"

#: Années que le récupérateur retient. Le tableau s'ouvre sur 2003, qui décrit
#: le droit antérieur et que le dépôt date de 1976 : elle n'est pas lue.
ANNEES = (2004, 2013)

#: Un trimestre est un quart d'année, et le dépôt compte en fraction quand la
#: loi compte en points de pourcentage.
TRIMESTRES_PAR_AN = 4
POINTS_PAR_FRACTION = 100

#: Bornes plausibles de la fraction servie à quinze ans de services : la loi la
#: rabat de 60 % à 57,5 %.
PART_PLAUSIBLE = (0.55, 0.62)

#: « I : 2004 II : 59,7 % III : 217 IV : 3,8 points V : Vingt-cinq ans et demi
#: VI : 0,04 point » — les six colonnes du tableau, rendues à plat.
LIGNE = re.compile(
    r"I\s*:\s*(20\d\d)\s*"
    r"II\s*:\s*([\d,]+)\s*%\s*"
    r"III\s*:\s*(\d{3})\s*"
    r"IV\s*:\s*([\d,]+)\s*points?\s*"
    r"V\s*:\s*([A-Za-zÀ-ÿ' -]+?)\s*"
    r"VI\s*:\s*(?:([\d,]+)\s*points?|Sans objet)",
    re.I)

#: Les bornes de la colonne V sont en toutes lettres, et parfois en demies.
DIZAINES = {"vingt": 20, "trente": 30}
UNITES = {
    "un": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6,
    "sept": 7, "huit": 8, "neuf": 9,
}

FILTRE = r"""
import re, sys
LOI = re.compile(r"2003-775")
CIBLE = re.compile(r"d[ée]roga?tion aux a et b de l'article L\. 17|par d[ée]rogation aux a et b", re.I)
TABLEAU = re.compile(r"I\s*:\s*20\d\d\s*II\s*:", re.I)
BALISES = re.compile(r"<[^>]+>")
tampon = ""
for bloc in iter(lambda: sys.stdin.buffer.read(1 << 20), b""):
    tampon += bloc.decode("utf-8", errors="replace")
    morceaux = tampon.split("<?xml")
    tampon = morceaux.pop()
    for morceau in morceaux:
        texte = re.sub(r"\s+", " ", BALISES.sub(" ", morceau)).strip()
        if not (LOI.search(texte[:600]) and TABLEAU.search(texte)):
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


def annees_en_lettres(texte: str) -> float | None:
    """« Vingt-cinq ans et demi » -> 25,5. « Trente ans » -> 30."""
    mots = [m for m in re.split(r"[-\s]+", texte.strip().lower()) if m]
    total, demi = 0.0, False
    for mot in mots:
        if mot in DIZAINES:
            total += DIZAINES[mot]
        elif mot in UNITES:
            total += UNITES[mot]
        elif mot == "demi":
            demi = True
        elif mot not in ("ans", "an", "et"):
            return None
    if not total:
        return None
    return total + (0.5 if demi else 0.0)


def bareme(versions: list[tuple[str, str]]) -> dict[int, dict[str, float]]:
    """Barème du minimum garanti, année de liquidation par année."""
    table: dict[int, dict[str, float]] = {}
    for _, texte in sorted(versions):
        for annee, part, indice, points, borne, au_dela in LIGNE.findall(texte):
            if not ANNEES[0] <= int(annee) <= ANNEES[1]:
                continue
            seuil = annees_en_lettres(borne)
            if seuil is None:
                continue
            table[int(annee)] = {
                "part_15_ans": float(part.replace(",", ".")) / POINTS_PAR_FRACTION,
                "indice_majore": float(indice),
                "points_15_30": (float(points.replace(",", "."))
                                 / POINTS_PAR_FRACTION / TRIMESTRES_PAR_AN),
                "points_30_40": (float((au_dela or "0").replace(",", "."))
                                 / POINTS_PAR_FRACTION / TRIMESTRES_PAR_AN),
                "trimestres_seuil": seuil * TRIMESTRES_PAR_AN,
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
    table = bareme(depouiller(url))
    annees = sorted(table)
    if annees != list(range(ANNEES[0], ANNEES[1] + 1)):
        print(f"ÉCHEC   le tableau couvre {annees or '—'}, et non "
              f"{ANNEES[0]}-{ANNEES[1]}", file=sys.stderr)
        return 1

    # La loi rabat la marche des quinze ans et repousse celle des trente : la
    # première décroît, la seconde monte. Une inversion signale une colonne lue
    # de travers.
    for precedente, courante in zip(annees, annees[1:]):
        if table[courante]["part_15_ans"] > table[precedente]["part_15_ans"]:
            print(f"ÉCHEC   la part des quinze ans monte de {precedente} à "
                  f"{courante}", file=sys.stderr)
            return 1
        if table[courante]["trimestres_seuil"] < table[precedente]["trimestres_seuil"]:
            print(f"ÉCHEC   le seuil recule de {precedente} à {courante}",
                  file=sys.stderr)
            return 1
    for annee, ligne in table.items():
        if not PART_PLAUSIBLE[0] <= ligne["part_15_ans"] <= PART_PLAUSIBLE[1]:
            print(f"ÉCHEC   {annee} : part de {ligne['part_15_ans']:.1%} hors de "
                  "la plage plausible", file=sys.stderr)
            return 1

    for annee in annees:
        ligne = table[annee]
        print(f"OK      {annee} : {ligne['part_15_ans']:.1%} à quinze ans, indice "
              f"{ligne['indice_majore']:g}, seuil "
              f"{ligne['trimestres_seuil']:g} trimestres")

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(
        json.dumps({
            "source": url,
            "article": f"loi n° {LOI} du 21 août 2003, article {ARTICLE} V",
            "recupere_le": date.today().isoformat(),
            "note": "barème du minimum garanti de la fonction publique, lu à l'année "
                    "de liquidation. La ligne 1976 du dépôt n'est pas dans ce "
                    "tableau : elle décrit le droit antérieur, que la loi range sous "
                    "l'année 2003.",
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
