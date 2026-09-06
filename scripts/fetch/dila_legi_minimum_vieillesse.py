#!/usr/bin/env python3
"""Montant de l'ASPA, lu dans l'article du code qui le fixe.

    python scripts/fetch/dila_legi_minimum_vieillesse.py

**Ce script télécharge environ 1,1 Go et met un quart d'heure.**

Le minimum vieillesse est le dernier plancher du système, et le seul qui ne
suppose aucune cotisation. Ses montants venaient d'une saisie — `source_id:
legifrance_textes` —, c'est-à-dire d'une lecture humaine de Légifrance, non d'un
fichier confronté au producteur. Or l'**article D. 815-1 du code de la sécurité
sociale** les porte, datés, et la base LEGI en garde les versions :

    « Le montant annuel de l'allocation de solidarité aux personnes âgées est
      fixé : a) Pour les personnes seules […] à 9 998,40 euros par an à compter
      du 1er avril 2018, à 10 418,40 euros par an à compter du 1er janvier 2019
      et à 10 838,40 euros par an à compter du 1er janvier 2020 »

**LE MONTANT EST ANNUEL, ET C'EST CE QUI CORRIGE UNE VALEUR.** Le dépôt portait
le montant MENSUEL maximal multiplié par douze : 708,95 × 12 = 8 507,40 € pour
2010. L'article, lui, fixe 8 507,49 € par an, dont le mensuel arrondi se déduit.
Neuf centimes, mais dans le bon sens : le texte fixe l'annuel, le mensuel en
découle.

**CE QUE L'ARTICLE NE DIT PAS, ET C'EST LA MOITIÉ DE LA SÉRIE.** Il n'a pas été
réécrit à chaque revalorisation. Il porte neuf montants datés, de 2006 à 2020,
et **rien après** — depuis, l'allocation est revalorisée par l'effet de
l'article L. 816-2 sans que D. 815-1 change. Il saute aussi les relèvements de
2013 et de 2015 à 2017 : sa version d'octobre 2014 tient jusqu'en avril 2018 sur
un seul montant, alors que l'allocation a monté entre-temps.

Les ancres transcrites de 2007, 2016 et 2017, et celles d'après 2020, restent
donc au niveau ``haute`` : elles disent ce que l'article tait. C'est le même
partage que pour le plafond de la Sécurité sociale — la source primaire prend ce
qu'elle porte, la transcription garde le reste.

**LE FICHIER EST UN FICHIER D'ANCRES**, non une série année par année : le
modèle projette entre deux ancres. Chaque montant daté donne donc une ancre à
l'année de sa date d'effet, ce qui est déjà la convention des lignes en place —
2010 y porte le montant du 1er avril 2010, 2018 celui du 1er avril 2018.
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
SORTIE = Path("data/brut/dila_legi_minimum_vieillesse.json")

#: L'article du code qui porte le montant.
ARTICLE = "D815-1"

#: Bornes plausibles du montant ANNUEL, en euros. L'allocation d'une personne
#: seule vaut aujourd'hui un peu plus de douze mille euros par an.
MONTANT_PLAUSIBLE = (3000.0, 25000.0)

#: Hausse annuelle au-delà de laquelle la lecture est douteuse.
HAUSSE_MAXIMALE = 0.20

#: Le a) de l'article : le barème d'une PERSONNE SEULE. Le b) porte celui du
#: couple, que le modèle ne connaît pas — il ne simule qu'un individu.
PERSONNE_SEULE = re.compile(
    r"allocation de solidarit[ée] aux personnes [âa]g[ée]es est fix[ée]\s*:?\s*a\)"
    r"(.{0,1200}?)(?:\bb\)|$)",
    re.I | re.S)

#: « 8 507, 49 € par an à compter du 1er avril 2010 » — le Journal officiel aère
#: parfois ses décimales, et alterne « € » et « euros ».
MONTANT_DATE = re.compile(
    r"(\d[\d  ]*(?:,\s?\d+)?)\s*(?:€|euros?)\s*par an\s*[àa] compter du\s*"
    r"(\d{1,2})(?:er)?\s+(\w+)\s+(\d{4})",
    re.I)

MOIS = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "août": 8, "aout": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
}

FILTRE = r"""
import re, sys
ARTICLE = re.compile(r"<NUM>\s*D815-1\s*</NUM>")
CIBLE = re.compile(r"solidarit[ée] aux personnes [âa]g[ée]es", re.I)
BALISES = re.compile(r"<[^>]+>")
tampon = ""
for bloc in iter(lambda: sys.stdin.buffer.read(1 << 20), b""):
    tampon += bloc.decode("utf-8", errors="replace")
    morceaux = tampon.split("<?xml")
    tampon = morceaux.pop()
    for morceau in morceaux:
        if not ARTICLE.search(morceau):
            continue
        texte = re.sub(r"\s+", " ", BALISES.sub(" ", morceau)).strip()
        if not CIBLE.search(texte):
            continue
        debut = re.search(r"<DATE_DEBUT>(.*?)</DATE_DEBUT>", morceau)
        print("@@@ " + (debut.group(1) if debut else "?"))
        print(texte[:12000])
        sys.stdout.flush()
"""


class TransfertIncomplet(RuntimeError):
    """Le dump n'a pas été téléchargé en entier."""


def dernier_dump() -> str:
    with urllib.request.urlopen(RACINE, timeout=120) as reponse:
        page = reponse.read().decode("utf-8", errors="replace")
    noms = sorted(set(re.findall(r'href="(Freemium_legi_global_[^"]+\.tar\.gz)"', page)))
    if not noms:
        raise LookupError("aucun dump global dans le répertoire LEGI de la DILA")
    return RACINE + noms[-1]


def _nombre(brut: str) -> float:
    """« 8 507, 49 » : les espaces du Journal officiel sautent, la virgule reste."""
    return float(re.sub(r"[\s ]", "", brut).replace(",", "."))


def montants_dates(textes: list[str]) -> tuple[dict[date, float], list[str]]:
    """Montant ANNUEL de l'allocation d'une personne seule, par date d'effet."""
    par_date: dict[date, float] = {}
    griefs: list[str] = []
    for texte in textes:
        bloc = PERSONNE_SEULE.search(texte)
        if bloc is None:
            continue
        for valeur, jour, mois, annee in MONTANT_DATE.findall(bloc.group(1)):
            if mois.lower() not in MOIS:
                continue
            montant = _nombre(valeur)
            if not MONTANT_PLAUSIBLE[0] <= montant <= MONTANT_PLAUSIBLE[1]:
                continue
            effet = date(int(annee), MOIS[mois.lower()], int(jour))
            ancien = par_date.get(effet)
            if ancien is not None and abs(ancien - montant) > 0.005:
                griefs.append(f"{effet} : deux montants, {ancien:.2f} € et "
                              f"{montant:.2f} €")
                continue
            par_date[effet] = montant
    return par_date, griefs


def ancres(par_date: dict[date, float]) -> dict[int, float]:
    """Une ancre par montant daté, à l'année de sa date d'effet.

    Deux montants dans la même année ne se sont jamais produits ; s'ils se
    produisaient, c'est le dernier qui vaudrait — celui que l'année laisse en
    place, comme partout ailleurs dans le dépôt.
    """
    return {effet.year: par_date[effet] for effet in sorted(par_date)}


def depouiller(url: str) -> list[str]:
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
    # Un transfert coupé ne se voit pas dans ce qui a été lu : le dépouillement
    # rend une série plus courte, et les contrôles de continuité la trouvent
    # bonne — un dump à moitié lu n'a pas de trou, il a une fin prématurée.
    # C'est arrivé, et rien ne l'avait dit.
    if lecture.wait() != 0:
        raise TransfertIncomplet(
            f"curl s'est interrompu (code {lecture.returncode}) : le dump n'a "
            "pas été lu en entier, et la série qu'on en tirerait serait muette "
            "sur ce qui manque")
    return [re.sub(r"\s+", " ", bloc.partition("\n")[2]).strip()
            for bloc in sortie.split("@@@ ")[1:]]


def main() -> int:
    try:
        url = dernier_dump()
    except (urllib.error.HTTPError, urllib.error.URLError, LookupError) as erreur:
        print(f"ÉCHEC   répertoire LEGI : {erreur}", file=sys.stderr)
        return 1

    print(f"Dump      {url.rsplit('/', 1)[-1]}")
    print("Lecture en flux d'environ 9 Go décompressés : comptez un quart d'heure.\n")
    try:
        textes = depouiller(url)
    except TransfertIncomplet as erreur:
        print(f"ÉCHEC   {erreur}", file=sys.stderr)
        return 1
    par_date, griefs = montants_dates(textes)
    for grief in griefs:
        print(f"ÉCHEC   {grief}", file=sys.stderr)
    if griefs:
        return 1
    if not par_date:
        print(f"ÉCHEC   aucune version de l'article {ARTICLE} lue", file=sys.stderr)
        return 1

    # L'allocation n'a jamais reculé : un recul signale une lecture de travers,
    # et un bond de plus d'un cinquième aussi.
    dates = sorted(par_date)
    for precedente, courante in zip(dates, dates[1:]):
        if par_date[courante] < par_date[precedente]:
            print(f"ÉCHEC   le montant recule du {precedente} au {courante} : "
                  f"{par_date[precedente]:.2f} € puis {par_date[courante]:.2f} €",
                  file=sys.stderr)
            return 1
        if par_date[courante] / par_date[precedente] - 1 > HAUSSE_MAXIMALE:
            print(f"ÉCHEC   le montant bondit de "
                  f"{par_date[courante] / par_date[precedente] - 1:.1%} entre "
                  f"{precedente} et {courante}", file=sys.stderr)
            return 1

    table = ancres(par_date)
    for effet in dates:
        print(f"OK      {effet} : {par_date[effet]:.2f} € par an, "
              f"soit {par_date[effet] / 12:.2f} € par mois")

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(
        json.dumps({
            "source": url,
            "article": f"code de la sécurité sociale, article {ARTICLE}",
            "recupere_le": date.today().isoformat(),
            "versions_lues": len(textes),
            "dates_lues": [effet.isoformat() for effet in dates],
            "note": "montant ANNUEL de l'allocation de solidarité aux personnes "
                    "âgées d'une personne seule, une ancre par montant daté. "
                    "L'article n'est pas réécrit à chaque revalorisation : il "
                    "s'arrête en 2020 et saute les relèvements de 2013 et de 2015 "
                    "à 2017. Les ancres que le dépôt tient d'ailleurs comblent ce "
                    "que l'article tait, au niveau haute.",
            "serie": {str(annee): valeur for annee, valeur in sorted(table.items())},
        }, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"\n{len(textes)} versions lues, {len(table)} ancres écrites dans {SORTIE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
