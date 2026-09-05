#!/usr/bin/env python3
"""Contribution employeur de la CNRACL, dans le décret qui la fixe.

    python scripts/fetch/dila_legi_cnracl.py

**Ce script télécharge environ 1,1 Go et met un quart d'heure.**

À quoi elle sert. Les fiches de régime ne portent, pour les régimes publics,
que la RETENUE DE L'AGENT — 7,85 % hier, 11,10 % aujourd'hui. La contribution
de l'employeur est l'autre moitié de l'effort contributif, celle que les
scénarios 4 et 5 portent au compte notionnel : pour un agent territorial ou
hospitalier, elle vaut aujourd'hui trois fois sa retenue, et elle décide donc
de l'essentiel de ce que ces deux scénarios lui servent.

Elle venait d'OpenFisca-France, transcription plafonnée à ``haute``. Or le
*Journal officiel* la porte, et sous une forme consolidée : l'**article 5 du
décret n° 91-613 du 28 juin 1991**, dont la base LEGI garde vingt versions
datées, de 1992 à 2028 — les trois dernières étant la montée en charge décidée
en janvier 2025, que le dépôt tenait jusqu'ici pour une projection.

    « II.-Le taux de la contribution sur les traitements prévue au I de
      l'article 5 du décret du 7 février 2007 relatif à la Caisse nationale de
      retraites des agents des collectivités locales est fixé à 31,65 %. »

TROIS DIFFICULTÉS DE LECTURE

* **le I n'est pas le II.** Le même article fixe d'abord la RETENUE de l'agent
  (7,85 %, puis 11,10 %), ensuite la CONTRIBUTION de l'employeur. Seul le II est
  lu, et la lecture s'arrête à la contribution SUPPLÉMENTAIRE qui le suit — un
  prélèvement distinct, qui finance la compensation entre régimes ;
* **une version porte plusieurs taux, chacun avec sa date.** « 30,40 % pour
  l'année 2014 ; b) 30,45 % pour l'année 2015 ; c) 30,50 % à compter de l'année
  2016 » : chaque taux est daté par ce qui le SUIT immédiatement, jusqu'au taux
  d'après. Lire la date la plus proche du taux, et non la première rencontrée,
  est ce qui distingue une table juste d'une table décalée d'un cran ;
* **le décret de janvier vaut pour l'année entière.** Ces textes paraissent fin
  janvier et s'appliquent aux traitements versés depuis le 1er janvier — le
  décret du 30 janvier 2024 pour les 31,65 % de 2024, celui du 30 janvier 2025
  pour les 34,65 % de 2025. La version consolidée, elle, s'ouvre au 1er février.
  Une version qui entre en vigueur avant le 1er mars sans autre date vaut donc
  à compter du 1er janvier de son année : sans cette règle, 2024 porterait le
  taux de 2023.

Ce que le décret ne donne pas : les années antérieures à 1993. Les taux d'avant
sont dans les décrets abrogés que 91-613 a remplacés — 83-36, 86-1381,
87-1118 — et restent transcrits d'OpenFisca, au niveau ``haute``.
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
SORTIE = Path("data/brut/dila_legi_cnracl.json")

#: Le décret qui porte le taux, et l'article qui le fixe.
DECRET, ARTICLE = "91-613", "5"

#: Bornes plausibles du taux employeur : il valait 21,30 % en 1992 et monte à
#: 43,65 % en 2028. Au-delà, la phrase lue parle d'autre chose.
TAUX_PLAUSIBLE = (0.15, 0.50)

#: Une version antérieure à cette date dans l'année vaut pour l'année entière.
#: Les décrets de relèvement paraissent fin janvier, avec effet au 1er janvier.
MOIS_RETROACTIF = 3

TAUX = re.compile(r"(\d{1,2},\d+)\s*(?:%|p\.\s?100)")

#: Les quatre façons dont ces textes datent un taux. On retient celle qui suit
#: le taux au plus près.
QUALIFICATIFS = (
    re.compile(r"à\s+compter\s+(?:du\s+1er\s+janvier|de\s+l['’]ann[ée]e)\s+(\d{4})", re.I),
    re.compile(r"pour\s+l['’]ann[ée]e\s+(\d{4})", re.I),
    re.compile(r"du\s+1er\s+(\w+)\s+(\d{4})\s+au\b", re.I),
    re.compile(r"du\s+1er\s+(\w+)\s+au\s+\d{1,2}\s+\w+\s+(\d{4})", re.I),
)

MOIS = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "août": 8, "aout": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
}

#: Le II commence à la contribution de l'employeur et s'arrête à la
#: contribution supplémentaire, qui est un autre prélèvement.
DEBUT_DU_II = re.compile(r"II\s*\.\s*-?\s*Le taux de la contribution")
FIN_DU_II = re.compile(r"Le taux de la contribution (supplémentaire|prévue au II)")

FILTRE = r"""
import re, sys
NUM = re.compile(r"<NUM>\s*5\s*</NUM>")
DECRET = re.compile(r"D[ée]cret n[o°]\s*91-613 du 28 juin 1991")
BALISES = re.compile(r"<[^>]+>")
tampon = ""
for bloc in iter(lambda: sys.stdin.buffer.read(1 << 20), b""):
    tampon += bloc.decode("utf-8", errors="replace")
    morceaux = tampon.split("<?xml")
    tampon = morceaux.pop()
    for morceau in morceaux:
        if not NUM.search(morceau):
            continue
        texte = re.sub(r"\s+", " ", BALISES.sub(" ", morceau)).strip()
        if not DECRET.search(texte[:600]):
            continue
        debut = re.search(r"<DATE_DEBUT>(.*?)</DATE_DEBUT>", morceau)
        print("@@@ " + (debut.group(1) if debut else "?"))
        print(texte[:6000])
        sys.stdout.flush()
"""


def dernier_dump() -> str:
    with urllib.request.urlopen(RACINE, timeout=120) as reponse:
        page = reponse.read().decode("utf-8", errors="replace")
    noms = sorted(set(re.findall(r'href="(Freemium_legi_global_[^"]+\.tar\.gz)"', page)))
    if not noms:
        raise LookupError("aucun dump global dans le répertoire LEGI de la DILA")
    return RACINE + noms[-1]


def contribution_employeur(texte: str) -> str:
    """Le II de l'article, et lui seul."""
    depart = DEBUT_DU_II.search(texte)
    if depart is None:
        return ""
    reste = texte[depart.start() + 10:]
    fin = FIN_DU_II.search(reste)
    return reste[:fin.start()] if fin else reste[:900]


def _date_du_taux(fenetre: str, defaut: date) -> date:
    """Date que porte le texte qui SUIT un taux, ou celle de la version.

    Une version qui s'ouvre avant le 1er mars sans autre date vaut à compter du
    1er janvier : ces décrets paraissent fin janvier et s'appliquent aux
    traitements versés depuis le début de l'année.
    """
    trouvees = []
    for rang, motif in enumerate(QUALIFICATIFS):
        trouve = motif.search(fenetre)
        if trouve is not None:
            trouvees.append((trouve.start(), rang, trouve))
    if not trouvees:
        return date(defaut.year, 1, 1) if defaut.month < MOIS_RETROACTIF else defaut
    _, rang, trouve = min(trouvees)
    if rang < 2:
        return date(int(trouve.group(1)), 1, 1)
    return date(int(trouve.group(2)), MOIS.get(trouve.group(1).lower(), 1), 1)


def taux_par_date(versions: list[tuple[str, str]]) -> dict[date, float]:
    """Taux de contribution employeur par date d'effet.

    Les versions sont lues dans l'ordre où elles entrent en vigueur : une
    rédaction plus récente qui redate un taux l'emporte sur l'ancienne, comme
    le fait le droit.
    """
    par_date: dict[date, float] = {}
    for debut, texte in sorted(versions):
        bloc = contribution_employeur(texte)
        if not bloc:
            continue
        try:
            entree = date.fromisoformat(debut)
        except ValueError:
            continue
        trouves = list(TAUX.finditer(bloc))
        for rang, trouve in enumerate(trouves):
            fin = trouves[rang + 1].start() if rang + 1 < len(trouves) else len(bloc)
            valeur = float(trouve.group(1).replace(",", ".")) / 100
            if not TAUX_PLAUSIBLE[0] <= valeur <= TAUX_PLAUSIBLE[1]:
                continue
            par_date[_date_du_taux(bloc[trouve.end():fin][:140], entree)] = valeur
    return par_date


def serie_annuelle(par_date: dict[date, float]) -> dict[int, float]:
    """Taux en vigueur au 1er janvier de chaque année, la règle du dépôt."""
    dates = sorted(par_date)
    if not dates:
        return {}
    serie: dict[int, float] = {}
    for annee in range(dates[0].year, dates[-1].year + 1):
        applicables = [d for d in dates if d <= date(annee, 1, 1)]
        if applicables:
            serie[annee] = par_date[applicables[-1]]
    return serie


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
    versions = depouiller(url)
    par_date = taux_par_date(versions)
    serie = serie_annuelle(par_date)
    if not serie:
        print(f"ÉCHEC   aucune version de l'article {ARTICLE} du décret {DECRET} lue",
              file=sys.stderr)
        return 1

    annees = sorted(serie)
    for precedente, courante in zip(annees, annees[1:]):
        if serie[courante] < serie[precedente]:
            print(f"ÉCHEC   le taux recule de {precedente} à {courante} : "
                  f"{serie[precedente]:.2%} puis {serie[courante]:.2%}",
                  file=sys.stderr)
            return 1

    for annee in annees:
        print(f"OK      {annee} : contribution employeur {serie[annee]:.2%}")

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(
        json.dumps({
            "source": url,
            "article": f"décret n° {DECRET} du 28 juin 1991, article {ARTICLE}, II",
            "recupere_le": date.today().isoformat(),
            "versions_lues": len(versions),
            "note": "taux de la contribution employeur due à la CNRACL, en vigueur "
                    "au 1er janvier de l'année. Le I du même article porte la "
                    "retenue de l'agent et la contribution supplémentaire qui suit "
                    "le II est un autre prélèvement : ni l'un ni l'autre n'est lu. "
                    "Les années d'avant 1993 sont dans des décrets abrogés que "
                    "91-613 a remplacés, et restent transcrites d'OpenFisca.",
            "serie": {str(annee): valeur for annee, valeur in sorted(serie.items())},
        }, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"\n{len(versions)} versions lues, {len(serie)} années écrites dans {SORTIE}")
    print(f"Couverture {annees[0]}-{annees[-1]} ; "
          f"{serie[annees[0]]:.2%} puis {serie[annees[-1]]:.2%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
