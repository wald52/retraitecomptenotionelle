#!/usr/bin/env python3
"""Point d'indice de la fonction publique, lu dans le décret qui le fixe.

    python scripts/fetch/dila_legi_point_indice.py

**Ce script télécharge environ 1,1 Go et met un quart d'heure.** Une exécution
par an suffit.

À quoi il sert ici. Une seule grandeur en dépend, mais elle est décisive : le
MINIMUM GARANTI de la fonction publique, dont l'article L. 17 du code des
pensions fixe la référence à « la valeur du traitement brut afférent à l'indice
majoré 227 au 1er janvier 2004 ». Les liquidations antérieures à 2004 prennent,
elles, le point de leur année.

La série venait d'OpenFisca-France, transcription plafonnée à ``haute``. Or le
*Journal officiel* est ici à portée : le point d'indice n'est pas un article de
code, c'est **l'article 3 du décret n° 85-1148 du 24 octobre 1985**, dont la
base LEGI garde chaque version datée — quarante-six depuis 1985 :

    « La valeur annuelle du traitement et de la solde […] afférents à l'indice
      100 majoré et soumis aux retenues pour pension est fixée à 5 907,34 € »

DEUX PIÈGES, ET UN TROISIÈME QUI N'EN EST PAS UN

* **la valeur est ANNUELLE et porte sur cent points.** Le dépôt stocke le
  traitement d'UN point : c'est la valeur du décret divisée par cent ;
* **le franc jusqu'en 2001.** Le décret écrit « 33 990 F » jusqu'à la version
  du 29 septembre 2001, « 5 181,75 » à celle du 1er janvier 2002 — et le
  passage des deux se contrôle tout seul, l'euro devant valoir 6,55957 francs ;
* **les années sans version ne sont pas des trous.** Le point a été gelé de
  2010 à 2016, de 2017 à 2022, et il l'est depuis juillet 2023 : le décret n'est
  alors pas modifié, et la valeur en vigueur au 1er janvier reste celle de la
  dernière version. C'est la règle du dépôt, et elle rend la série continue.

**CE QUE CETTE SOURCE NE DONNE PAS, ET COMMENT ON LE SAIT.** La base ne garde
pas toutes les versions anciennes de l'article : deux relèvements manquent, celui
du 1er novembre 1991 et celui du 1er janvier 1994, l'un et l'autre pris par un
décret qui en portait deux d'un coup. La série qu'on en tirerait serait fausse
de 1,0 % en 1992 et de 0,15 % en 1994 — plate là où le point a monté, et rien ne
le dirait. C'est la confrontation à la transcription d'OpenFisca qui l'a établi,
année par année : les deux séries se séparent sur ces deux années-là, et sur
elles seules.

Le récupérateur s'arrête donc à **1996**, première année d'une chaîne dont on a
vérifié qu'elle ne saute rien. Ce qui précède — et l'avant-1986, que le décret
de 1985 ne couvre pas — reste transcrit d'OpenFisca, au niveau ``haute``.
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
SORTIE = Path("data/brut/dila_legi_point_indice.json")

#: Le décret qui porte la valeur, et l'article qui la fixe.
DECRET = "85-1148"

#: Parité irrévocable du franc et de l'euro.
FRANC = 6.55957
#: La version du 1er janvier 2002 est la première écrite en euros.
PREMIER_EURO = date(2002, 1, 1)

#: Le décret fixe le traitement de CENT points d'indice majoré.
POINTS_PAR_TRAITEMENT = 100

#: Première année dont la chaîne de versions est complète dans le dump. Avant
#: elle, deux relèvements manquent — 1er novembre 1991 et 1er janvier 1994 —, ce
#: qui rendrait la série plate là où le point a monté.
PREMIERE_ANNEE = 1996

#: Hausse annuelle au-delà de laquelle la lecture est douteuse. Le point a
#: monté de 2,5 % en 1992, jamais de plus de 4 %.
HAUSSE_MAXIMALE = 0.15

#: « est fixée à 5 907,34 € », « est fixée à 33 990 F », « est fixée à
#: 5 512, 17 € » — le Journal officiel aère ses milliers, et parfois ses
#: décimales.
MONTANT = re.compile(
    r"est\s+fix[ée]e?\s+à\s+((?:\d[\d  ]*)(?:,[\d  ]+)?)\s*(F|francs?|€|euros?)?",
    re.I)

#: L'article qu'on cherche, et lui seul : d'autres textes citent le décret sans
#: porter la valeur.
VALEUR_ANNUELLE = re.compile(r"valeur annuelle du traitement", re.I)

FILTRE = r"""
import re, sys
CIBLE = re.compile(r"valeur annuelle du traitement", re.I)
DECRET = re.compile(r"85-1148")
BALISES = re.compile(r"<[^>]+>")
tampon = ""
for bloc in iter(lambda: sys.stdin.buffer.read(1 << 20), b""):
    tampon += bloc.decode("utf-8", errors="replace")
    morceaux = tampon.split("<?xml")
    tampon = morceaux.pop()
    for morceau in morceaux:
        texte = re.sub(r"\s+", " ", BALISES.sub(" ", morceau)).strip()
        if not (CIBLE.search(texte) and DECRET.search(texte)):
            continue
        debut = re.search(r"<DATE_DEBUT>(.*?)</DATE_DEBUT>", morceau)
        print("@@@ " + (debut.group(1) if debut else "?"))
        print(texte[:4000])
        sys.stdout.flush()
"""


def dernier_dump() -> str:
    with urllib.request.urlopen(RACINE, timeout=120) as reponse:
        page = reponse.read().decode("utf-8", errors="replace")
    noms = sorted(set(re.findall(r'href="(Freemium_legi_global_[^"]+\.tar\.gz)"', page)))
    if not noms:
        raise LookupError("aucun dump global dans le répertoire LEGI de la DILA")
    return RACINE + noms[-1]


def _nombre(brut: str) -> float:
    """« 5 907,34 » et « 5 512, 17 » : les espaces du Journal officiel sautent."""
    return float(re.sub(r"[\s ]", "", brut).replace(",", "."))


def versions_datees(versions: list[tuple[str, str]]) -> dict[date, float]:
    """Traitement annuel de l'indice 100 majoré, par date d'entrée en vigueur.

    La date est celle que la base porte : pour cet article, la version entre en
    vigueur le jour même où le relèvement prend effet.
    """
    par_date: dict[date, float] = {}
    for debut, texte in versions:
        if DECRET not in texte[:1200] or not VALEUR_ANNUELLE.search(texte):
            continue
        montant = MONTANT.search(texte)
        if montant is None:
            continue
        try:
            effet = date.fromisoformat(debut)
        except ValueError:
            continue
        valeur = _nombre(montant.group(1))
        unite = (montant.group(2) or "").lower()
        if unite.startswith("f") or (not unite and effet < PREMIER_EURO):
            valeur /= FRANC
        par_date[effet] = valeur
    return par_date


def serie_annuelle(par_date: dict[date, float]) -> dict[int, float]:
    """Valeur d'UN point, en vigueur au 1er janvier de chaque année."""
    dates = sorted(par_date)
    if not dates:
        return {}
    serie: dict[int, float] = {}
    for annee in range(max(PREMIERE_ANNEE, dates[0].year + 1), date.today().year + 2):
        applicables = [d for d in dates if d <= date(annee, 1, 1)]
        if applicables:
            serie[annee] = par_date[applicables[-1]] / POINTS_PAR_TRAITEMENT
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
    par_date = versions_datees(depouiller(url))
    serie = serie_annuelle(par_date)
    if not serie:
        print(f"ÉCHEC   aucune version de l'article 3 du décret {DECRET} lue",
              file=sys.stderr)
        return 1

    annees = sorted(serie)
    for precedente, courante in zip(annees, annees[1:]):
        if serie[courante] < serie[precedente]:
            print(f"ÉCHEC   le point recule de {precedente} à {courante} : "
                  f"{serie[precedente]:.4f} puis {serie[courante]:.4f}",
                  file=sys.stderr)
            return 1
        if serie[courante] / serie[precedente] - 1 > HAUSSE_MAXIMALE:
            print(f"ÉCHEC   le point bondit de "
                  f"{serie[courante] / serie[precedente] - 1:.1%} entre "
                  f"{precedente} et {courante}", file=sys.stderr)
            return 1

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(
        json.dumps({
            "source": url,
            "article": f"décret n° {DECRET} du 24 octobre 1985, article 3",
            "recupere_le": date.today().isoformat(),
            "versions_lues": len(par_date),
            "note": "valeur annuelle du traitement afférent à l'indice 100 majoré, "
                    "divisée par cent pour donner celle d'un point ; valeur en "
                    "vigueur au 1er janvier de l'année, une année sans version "
                    "reconduisant la précédente — le point a été gelé plusieurs "
                    "fois. Les années antérieures à la première version restent "
                    "transcrites d'OpenFisca.",
            "serie": {str(annee): valeur for annee, valeur in sorted(serie.items())},
        }, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"{len(par_date)} versions datées, {len(serie)} années écrites dans {SORTIE}")
    print(f"Couverture {annees[0]}-{annees[-1]} ; "
          f"{serie[annees[0]]:.4f} € puis {serie[annees[-1]]:.4f} € le point")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
