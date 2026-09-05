#!/usr/bin/env python3
"""Durée d'assurance requise des générations 1953-1957, dans leurs décrets.

    python scripts/fetch/dila_legi_duree_requise.py

**Ce script télécharge environ 1,1 Go et met un quart d'heure.**

Ce qu'il referme. `docs/limites.md` écrivait des générations 1934 à 1957 :
« leur durée a été fixée, génération par génération, par des décrets pris sous
l'ancien article L. 351-1, textes abrogés ou non codifiés que la base LEGI
n'expose pas sous un numéro d'article unique. La voie automatisable s'arrête
là. » La première moitié de la phrase est vraie, la seconde ne l'est pas : ces
décrets ne sont pas codifiés, mais la base les garde comme textes autonomes, et
l'on peut les chercher par leur PHRASE plutôt que par leur numéro d'article —
la même leçon que pour le SMIC et le point d'indice.

    « La durée d'assurance nécessaire pour bénéficier d'une pension de retraite
      à taux plein […] sont fixées à 166 trimestres pour les assurés nés en
      1955. »

Quatre décrets couvrent les générations 1953 à 1957 : celui du 30 décembre 2010
(1953 et 1954), du 1er août 2011 (1955), du 27 décembre 2012 (1956) et du
13 décembre 2013 (1957). Ce que le dépôt tenait pour hors de portée est donc
lu, pour ces cinq générations-là.

**CE QUI RESTE HORS D'ATTEINTE, ET POURQUOI.** Les générations 1934 à 1952 ne
sont pas dans la base sous cette forme : leur montée en charge vient de la loi
du 22 juillet 1993 et de la loi du 21 août 2003, dont les tableaux ne sont pas
des textes consolidés séparés. Elles restent transcrites, au niveau ``haute``.

**UN PIÈGE, ET IL EST GROS.** Saint-Pierre-et-Miquelon a son propre régime, et
sa loi du 17 juillet 1987 porte une table de durées écrite exactement comme
celle du régime général — 152 trimestres pour les assurés nés en 1956, quand le
régime général en exige 166. Un dépouillement qui ne l'écarterait pas
écraserait la table du modèle avec celle d'un archipel de six mille habitants.
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
SORTIE = Path("data/brut/dila_legi_duree_requise.json")

#: Générations que ces décrets peuvent légitimement viser. Au-delà, c'est
#: l'article L. 161-17-3 qui porte la table, et le dépôt le lit déjà.
GENERATIONS = (1949, 1957)

#: Durées plausibles, en trimestres. En deçà et au-delà, la phrase lue parle
#: d'autre chose que de la durée requise du régime général.
TRIMESTRES_PLAUSIBLES = (160, 172)

#: « sont fixées à 166 trimestres pour les assurés nés en 1955 », « à 165
#: trimestres pour les assurés nés en 1953 et 1954 » — un décret peut viser
#: deux générations d'un coup.
DUREE = re.compile(
    r"(\d{3})\s+trimestres?\s+pour\s+les\s+assur[ée]s\s+n[ée]s\s+en\s+(\d{4})"
    r"(?:\s+et\s+(\d{4}))?",
    re.I)

#: Le régime de Saint-Pierre-et-Miquelon écrit sa propre table dans les mêmes
#: termes, avec d'autres valeurs. On l'écarte sur le nom de son territoire.
AUTRE_REGIME = re.compile(r"Saint-Pierre", re.I)

FILTRE = r"""
import re, sys
CIBLE = re.compile(r"dur[ée]e d.assurance n[ée]cessaire", re.I)
TABLE = re.compile(r"\d{3} trimestres? pour les assur[ée]s n[ée]s en \d{4}", re.I)
BALISES = re.compile(r"<[^>]+>")
tampon = ""
for bloc in iter(lambda: sys.stdin.buffer.read(1 << 20), b""):
    tampon += bloc.decode("utf-8", errors="replace")
    morceaux = tampon.split("<?xml")
    tampon = morceaux.pop()
    for morceau in morceaux:
        texte = re.sub(r"\s+", " ", BALISES.sub(" ", morceau)).strip()
        if not (CIBLE.search(texte) and TABLE.search(texte)):
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


def durees(versions: list[tuple[str, str]]) -> tuple[dict[int, float], list[str]]:
    """Durée requise par génération, et ce que le dépouillement a trouvé de louche."""
    table: dict[int, float] = {}
    griefs: list[str] = []
    for _, texte in sorted(versions):
        if AUTRE_REGIME.search(texte):
            continue
        for trimestres, premiere, seconde in DUREE.findall(texte):
            valeur = float(trimestres)
            if not TRIMESTRES_PLAUSIBLES[0] <= valeur <= TRIMESTRES_PLAUSIBLES[1]:
                continue
            for generation in (premiere, seconde):
                if not generation:
                    continue
                annee = int(generation)
                if not GENERATIONS[0] <= annee <= GENERATIONS[1]:
                    continue
                if table.get(annee, valeur) != valeur:
                    griefs.append(
                        f"génération {annee} : deux durées, {table[annee]:g} et "
                        f"{valeur:g} trimestres"
                    )
                table[annee] = valeur
    return table, griefs


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
    table, griefs = durees(versions)
    for grief in griefs:
        print(f"ÉCHEC   {grief}", file=sys.stderr)
    if griefs:
        return 1
    if not table:
        print("ÉCHEC   aucun décret de durée requise lu dans le dump", file=sys.stderr)
        return 1

    generations = sorted(table)
    for precedente, courante in zip(generations, generations[1:]):
        if table[courante] < table[precedente]:
            print(f"ÉCHEC   la durée recule de {precedente} à {courante}",
                  file=sys.stderr)
            return 1

    for generation in generations:
        print(f"OK      génération {generation} : {table[generation]:g} trimestres")

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(
        json.dumps({
            "source": url,
            "recupere_le": date.today().isoformat(),
            "versions_lues": len(versions),
            "note": "décrets pris pour l'application du IV de l'article 5 de la loi "
                    "du 21 août 2003 et de l'article 17 de la loi du 9 novembre "
                    "2010, qui fixent la durée requise génération par génération. "
                    "Les générations d'avant 1953 ne sont pas dans la base sous "
                    "cette forme ; celles d'après 1957 sont dans l'article "
                    "L. 161-17-3, que dila_legi_parametres_retraite.py lit.",
            "serie": {str(g): v for g, v in sorted(table.items())},
        }, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"\n{len(table)} générations écrites dans {SORTIE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
