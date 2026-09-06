#!/usr/bin/env python3
"""Traitement de référence du minimum garanti, chez celui qui le sert.

    python scripts/fetch/sre_minimum_garanti.py

Le minimum garanti est le plancher de la fonction publique. Son montant plein
est le traitement de l'indice majoré 227 au 1er janvier 2004, « revalorisé
depuis cette date dans les mêmes conditions que les pensions » — une chaîne que
personne ne republie année par année, et que le dépôt suivait donc par des
ancres transcrites de publications diverses, au niveau ``haute``.

Or le **Service des retraites de l'État**, qui liquide et paie ces pensions,
publie les deux bornes de cette chaîne sur une même page :

* l'ancre d'origine — « du traitement indiciaire brut au 1er janvier 2004 de
  l'indice majoré 227 (997,96 € par mois ou 11 975,57 € par an) » ;
* le montant courant, avec sa date — « 16 396,19 € (montant du traitement
  indiciaire brut annuel de l'indice majoré 227 revalorisé au 01/01/2026) ».

C'est le producteur : ce n'est pas une transcription du barème, c'est le barème
que la caisse oppose à l'assuré.

**DEUX CHEMINS INDÉPENDANTS SUR L'ANCRE DE 2004.** Le dépôt la recoupait déjà
par le calcul — 227 × 52,7558 € le point, soit 11 975,57 € —, et
``verifier_donnees.py`` refait ce produit à chaque exécution. La page du service
le confirme au centime, par un troisième chemin qui ne doit rien aux deux
autres.

**CE QUE CETTE SOURCE NE DONNE PAS.** Les années intermédiaires. La page ne
porte que l'ancre et l'année courante ; les ancres de 2020, 2023, 2024 et 2025
restent transcrites de publications, au niveau ``haute``. Une exécution par an
en ajoute une.
"""

from __future__ import annotations

import gzip
import io
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

URL = ("https://retraitesdeletat.gouv.fr/actif/le-calcul-de-ma-retraite/"
       "le-minimum-garanti")
SORTIE = Path("data/brut/sre_minimum_garanti.json")

#: L'indice dont le traitement sert de référence, et l'année de l'ancre.
INDICE, ANNEE_ANCRE = 227, 2004

#: Bornes plausibles du traitement ANNUEL de l'indice majoré 227. Il valait
#: 11 975,57 € en 2004 ; il ne doublera pas de sitôt.
MONTANT_PLAUSIBLE = (10000.0, 30000.0)

#: « (997,96 € par mois ou 11 975,57 € par an) » — l'ancre de 2004, que la page
#: donne sous ses deux formes. On lit l'ANNUELLE : c'est celle que le barème
#: multiplie, et le mensuel en est l'arrondi.
ANCRE = re.compile(
    r"([\d  ]+,\d{2})\s*€\s*par mois\s*ou\s*([\d  ]+,\d{2})\s*€\s*par an",
    re.I)

#: « 16 396,19 € (montant du traitement indiciaire brut annuel de l'indice
#: majoré 227 revalorisé au 01/01/2026) » — le montant courant se date lui-même.
COURANT = re.compile(
    r"([\d  ]+,\d{2})\s*€\s*\(montant du traitement indiciaire brut annuel "
    r"de l'indice majoré\s*227\s*revaloris[ée] au\s*(\d{2})/(\d{2})/(\d{4})\)",
    re.I)

MOIS_PAR_AN = 12


class PageIllisible(RuntimeError):
    """La page du service ne porte pas ce qu'on venait y chercher."""


def _texte(url: str) -> str:
    """La page, réduite à son texte. Le service sert du gzip sans le dire."""
    demande = urllib.request.Request(
        url, headers={"User-Agent": "retraite-notionnelle/0.1",
                      "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(demande, timeout=120) as reponse:
        brut = reponse.read()
        if reponse.headers.get("Content-Encoding") == "gzip":
            brut = gzip.GzipFile(fileobj=io.BytesIO(brut)).read()
    page = brut.decode("utf-8", errors="replace")
    page = re.sub(r"<script.*?</script>", " ", page, flags=re.S)
    page = re.sub(r"<[^>]+>", " ", page)
    return re.sub(r"\s+", " ", page.replace("&nbsp;", " ").replace("&#039;", "'"))


def _nombre(brut: str) -> float:
    """« 16 396,19 » : les espaces, insécables compris, sautent."""
    return float(re.sub(r"[\s ]", "", brut).replace(",", "."))


def montants(page: str) -> dict[int, float]:
    """Traitement annuel de l'indice majoré 227, par année d'effet."""
    table: dict[int, float] = {}

    ancre = ANCRE.search(page)
    if ancre is None:
        raise PageIllisible("l'ancre de 2004 (« … € par mois ou … € par an ») "
                            "n'est plus sur la page")
    mensuel, annuel = _nombre(ancre.group(1)), _nombre(ancre.group(2))
    # Le mensuel est l'arrondi au centime de l'annuel divisé par douze : s'ils
    # ne s'accordent pas, c'est que la phrase lue parle d'autre chose.
    if abs(annuel / MOIS_PAR_AN - mensuel) > 0.01:
        raise PageIllisible(f"l'ancre se contredit : {annuel:.2f} € par an et "
                            f"{mensuel:.2f} € par mois")
    table[ANNEE_ANCRE] = annuel

    courant = COURANT.search(page)
    if courant is None:
        raise PageIllisible("le montant courant et sa date ne sont plus sur la page")
    table[int(courant.group(4))] = _nombre(courant.group(1))

    for annee, valeur in table.items():
        if not MONTANT_PLAUSIBLE[0] <= valeur <= MONTANT_PLAUSIBLE[1]:
            raise PageIllisible(f"{annee} : {valeur:.2f} € hors de la plage "
                                "plausible")
    return table


def main() -> int:
    try:
        page = _texte(URL)
    except (urllib.error.HTTPError, urllib.error.URLError) as erreur:
        print(f"ÉCHEC   Service des retraites de l'État : {erreur}",
              file=sys.stderr)
        return 1

    try:
        table = montants(page)
    except PageIllisible as erreur:
        print(f"ÉCHEC   {erreur}", file=sys.stderr)
        return 1

    annees = sorted(table)
    # Le minimum garanti suit les pensions : il ne recule pas, et n'a pas
    # doublé depuis 2004.
    if table[annees[-1]] < table[annees[0]]:
        print("ÉCHEC   le montant recule depuis l'ancre", file=sys.stderr)
        return 1

    for annee in annees:
        print(f"OK      {annee} : {table[annee]:.2f} € par an, "
              f"soit {table[annee] / MOIS_PAR_AN:.2f} € par mois")
    print(f"        revalorisation cumulée depuis {annees[0]} : "
          f"{table[annees[-1]] / table[annees[0]] - 1:+.1%}")

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(
        json.dumps({
            "source": URL,
            "producteur": "Service des retraites de l'État, qui liquide et paie "
                          "les pensions civiles et militaires",
            "recupere_le": date.today().isoformat(),
            "note": "traitement annuel brut de l'indice majoré 227, référence du "
                    "minimum garanti : l'ancre du 1er janvier 2004 que l'article "
                    "L. 17 désigne, et le montant courant que la page date "
                    "elle-même. Les années intermédiaires ne sont pas publiées et "
                    "restent transcrites.",
            "serie": {str(annee): valeur for annee, valeur in sorted(table.items())},
        }, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"\n{len(table)} ancres écrites dans {SORTIE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
