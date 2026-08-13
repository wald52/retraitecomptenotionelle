#!/usr/bin/env python3
"""Valeur de service du point de la retraite complémentaire agricole, chez DILA.

    python scripts/fetch/dila_legi_msa.py

**Ce script télécharge environ 1,1 Go et met un quart d'heure.** Il n'a pas à
être lancé souvent — une fois par an suffit — mais il est le seul chemin
reproductible vers cette série, et c'est pourquoi il existe.

La MSA a longtemps été le dernier régime en points dont le dépôt n'avait aucune
valeur publiée. Ni la caisse ni son service statistique n'en diffusent : les
« Chiffres utiles » sont un annuaire d'effectifs, et les pages de barèmes du
site sont construites en JavaScript. La valeur est pourtant écrite noir sur
blanc, chaque année depuis 2005, dans un article du code rural :

    « La valeur de service du point de retraite complémentaire obligatoire
      mentionnée à l'article L. 732-60 est fixée pour l'année 2013 à
      0,336 2 euros. »

Légifrance sert cet article, mais refuse les requêtes automatisées — 403 sur
toute requête non navigateur — et son API demande une clé. Reste la base
**LEGI**, que la Direction de l'information légale et administrative publie en
accès libre : elle contient chaque version datée de chaque article codifié.
C'est la publication officielle elle-même, non une transcription, d'où le
niveau ``certifiee``.

Le dépouillement se fait **en flux**, sans écriture disque : le tar est
décompressé à la volée et seuls les articles portant le bon numéro sont
retenus — dix-neuf versions sur les quelque deux millions d'articles que
compte la base.

Trois pièges, qu'on ne voit qu'en lisant les textes :

* le *Journal officiel* aère les décimales par groupes de trois — « 0,336 2 » —
  et parfois le chiffre des unités lui-même : « 0, 311 9 » ;
* la rédaction change au fil des ans. Trois formes coexistent : « fixée pour
  l'année N à X », « fixée à X pour l'année N » et « fixée à X à compter du
  1er juillet N » ;
* un même article peut fixer **deux années** d'un coup (« pour l'année 2018 à
  0,3382 euros et pour l'année 2019 à 0,3392 euros »), et une année peut
  recevoir deux valeurs successives — 2022 a été revalorisée en cours d'année.
  La convention du dépôt étant la valeur en vigueur au 31 décembre, c'est la
  dernière qui l'emporte.

Les valeurs sont écrites sous le code **``msa_rco``**, que le catalogue des
régimes ne connaît pas. C'est délibéré, et pour la même raison que la CNBF : la
fiche ``msa_non_salaries`` agrège le régime de base — deux parts, l'une
forfaitaire, l'autre proportionnelle en points — et la RCO, qui n'en est que
l'étage complémentaire, créé en 2003. Verser toutes les cotisations dans le
second gonflerait la complémentaire et ferait disparaître la base.
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

#: Le seul article utile. Son numéro est stable depuis sa création en 2005 ;
#: ce sont ses versions, datées, qui forment la série.
ARTICLE = "D732-166"

#: Le régime créé en 2003 : rien avant, et les décrets de 2003 et 2004 ont
#: précédé la création de l'article, si bien que ces deux années n'y figurent
#: pas. La série commence donc en 2005.
PREMIERE_ANNEE = 2005

SORTIE = Path("data/brut/dila_legi_msa.json")

# « 0,336 2 euros », « 0, 311 9 euros », « 0,3475 euro » — sans oublier le
# singulier, que le JO emploie une année sur deux.
NOMBRE = r"(\d+\s*[,.][\d  ]+?)\s*euros?"
FORMES = (
    re.compile(rf"pour l'année (\d{{4}})\s*à\s*{NOMBRE}"),
    re.compile(rf"à\s*{NOMBRE}\s*pour l'année (\d{{4}})"),
    re.compile(rf"à\s*{NOMBRE}\s*à compter du \d+\s*e?r?\s*\w+\s*(\d{{4}})"),
)


def _nombre(brut: str) -> float:
    return float(re.sub(r"\s", "", brut).replace(",", "."))


def valeurs(texte: str) -> list[tuple[int, float]]:
    """Toutes les paires (année, valeur) que porte une version de l'article.

    Une version en fixe une, parfois deux. On les collecte toutes plutôt que
    de s'arrêter à la première : c'est ainsi que 2019 et 2021 entrent dans la
    série, aucun décret ne leur étant propre.
    """
    trouvees: dict[int, float] = {}
    for indice, forme in enumerate(FORMES):
        for m in forme.finditer(texte):
            annee, valeur = (m.group(1), m.group(2)) if indice == 0 else (m.group(2), m.group(1))
            trouvees[int(annee)] = _nombre(valeur)
    return sorted(trouvees.items())


def dernier_dump() -> str:
    """L'adresse du dump global le plus récent, que DILA renomme à chaque envoi."""
    with urllib.request.urlopen(RACINE, timeout=120) as reponse:
        page = reponse.read().decode("utf-8", errors="replace")
    noms = sorted(re.findall(r'href="(Freemium_legi_global_[^"]+\.tar\.gz)"', page))
    if not noms:
        raise LookupError("aucun dump global dans le répertoire LEGI de la DILA")
    return RACINE + noms[-1]


FILTRE = r"""
import re, sys
CIBLE = re.compile(r"<NUM>\s*%s\s*</NUM>")
BALISES = re.compile(r"<[^>]+>")
tampon = ""
for bloc in iter(lambda: sys.stdin.buffer.read(1 << 20), b""):
    tampon += bloc.decode("utf-8", errors="replace")
    morceaux = tampon.split("<?xml")
    tampon = morceaux.pop()
    for morceau in morceaux:
        if not CIBLE.search(morceau):
            continue
        debut = re.search(r"<DATE_DEBUT>(.*?)</DATE_DEBUT>", morceau)
        texte = re.sub(r"\s+", " ", BALISES.sub(" ", morceau)).strip()
        print("@@@ " + (debut.group(1) if debut else "?"))
        print(texte[:3000])
        sys.stdout.flush()
"""


def depouiller(url: str) -> list[tuple[str, str]]:
    """Lit le dump en flux et renvoie les versions de l'article, datées."""
    lecture = subprocess.Popen(
        ["curl", "-sS", "--max-time", "5400", url], stdout=subprocess.PIPE
    )
    detar = subprocess.Popen(
        ["tar", "-xzO"], stdin=lecture.stdout, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    lecture.stdout.close()
    filtre = subprocess.Popen(
        [sys.executable, "-c", FILTRE % ARTICLE],
        stdin=detar.stdout, stdout=subprocess.PIPE, text=True,
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
    if not versions:
        print(f"ÉCHEC   aucune version de l'article {ARTICLE} dans le dump",
              file=sys.stderr)
        return 1

    # La convention du dépôt est la valeur en vigueur au 31 décembre : on
    # parcourt les versions dans l'ordre où elles sont entrées en vigueur, et
    # la dernière écrase la précédente pour une même année.
    serie: dict[int, float] = {}
    for debut, corps in sorted(versions):
        for annee, valeur in valeurs(corps):
            if annee >= PREMIERE_ANNEE:
                serie[annee] = valeur

    for annee, valeur in sorted(serie.items()):
        print(f"OK      {annee} : valeur de service {valeur} €")

    annees = sorted(serie)
    manquantes = [a for a in range(annees[0], annees[-1] + 1) if a not in serie]
    if manquantes:
        print(f"\nAnnées sans valeur : {manquantes}", file=sys.stderr)
    for precedente, courante in zip(annees, annees[1:]):
        if serie[courante] < serie[precedente]:
            print(f"\nSérie incohérente, rien n'est écrit : la valeur du point recule "
                  f"de {precedente} ({serie[precedente]}) à {courante} "
                  f"({serie[courante]})", file=sys.stderr)
            return 1

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(
        json.dumps({
            "source": url,
            "article": f"code rural, {ARTICLE}",
            "recupere_le": date.today().isoformat(),
            "versions_lues": len(versions),
            "note": "retraite complémentaire obligatoire des non-salariés agricoles, "
                    "créée en 2003 ; les valeurs de 2003 et 2004 précèdent la "
                    "création de l'article et n'y figurent pas. Le régime de base, "
                    "lui, reste sans série : son point n'est entré dans le code "
                    "qu'en 2025 (R. 732-66, 4,589 € au 1er janvier 2025)",
            "serie": {f"msa_rco|{a}|valeur_service": v for a, v in sorted(serie.items())},
        }, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"\n{len(serie)} valeurs écrites dans {SORTIE}")
    print(f"Couverture {annees[0]}-{annees[-1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
