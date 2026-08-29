#!/usr/bin/env python3
"""Minimum contributif et plafond d'écrêtement, dans le code de la sécurité sociale.

    python scripts/fetch/dila_legi_minimum_contributif.py

**Ce script télécharge environ 1,1 Go et met un quart d'heure.** Comme celui de
la MSA, dont il reprend la mécanique, il n'a pas à être lancé souvent.

`docs/limites.md` a longtemps écrit que le minimum contributif ne figurait
« dans aucune source machine ouverte », que ses montants n'étaient publiés que
dans des circulaires CNAV en PDF, et qu'il n'y avait donc « pas de chemin de
certification automatique à écrire ». C'était la même erreur que pour la MSA,
et elle se corrige de la même façon : *la donnée est dans la loi, il suffisait
de chercher par le numéro d'article*.

Deux articles suffisent, et ils disent tout :

* **D. 351-2-1** du code de la sécurité sociale porte les deux montants, en
  euros et par an — 8 509,61 € pour le minimum, 10 170,86 € pour le minimum
  majoré au titre des périodes cotisées, au 1er septembre 2023 ;
* **D. 173-21-0-0-1** porte le plafond d'écrêtement de l'article L. 173-2 :
  « Le montant mensuel total des pensions personnelles de retraite […] est fixé
  à 1 120 euros au 1er février 2014. Ce montant est revalorisé aux mêmes dates
  et dans les mêmes proportions que le salaire minimum de croissance. »

Ce sont des **ancres datées**, non des séries : le code n'est pas modifié
chaque année, les montants sont revalorisés par l'effet de la loi. C'est ce que
fait le modèle, qui les indexe sur le SMIC à partir de leur date — la règle
depuis la réforme du 14 avril 2023 pour le minimum, depuis 2014 pour le
plafond. Le contrôle est immédiat : l'ancre de 2014 rapportée au SMIC de 2025
redonne 1 396 €/mois là où les caisses publient 1 394,86 €, et celle de 2023
redonne 8 970 €/an là où elles publient 8 972,28 €. Deux chemins indépendants
qui se rejoignent à 0,03 % près.

Les montants sont écrits en euros PAR AN, unité du dépôt ; le plafond, publié
au mois, est donc multiplié par douze.
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

#: Les deux articles utiles, et ce qu'on va y chercher.
ARTICLES = ("D351-2-1", "D173-21-0-0-1")

SORTIE = Path("data/brut/dila_legi_minimum_contributif.json")

# Le Journal officiel aère les milliers par une espace insécable et sépare les
# décimales par une virgule : « 8 509,61 euros », « 1 120 euros ».
NOMBRE = r"(\d[\d  ]*(?:,\d+)?)\s*euros?"

#: Les deux montants de D. 351-2-1 sont dans la même unité et se suivent :
#:
#:     « Le montant minimum […] est fixé à 8 509,61 euros par an au
#:       1er septembre 2023. Ce montant minimum est MAJORÉ au titre des
#:       périodes ayant donné lieu à cotisations à la charge de l'assuré, de
#:       façon à atteindre 10 170,86 euros par an au 1er septembre 2023. »
#:
#: Plutôt que de s'accrocher à un verbe — « est fixé à », « est porté à », « de
#: façon à atteindre » : la rédaction a changé trois fois en vingt ans — on
#: relève TOUS les montants annuels de l'article et l'on retient le plus petit
#: pour le minimum, le plus grand pour le majoré. C'est ce que dit le texte, et
#: c'est vérifiable : le script refuse d'écrire si le second n'excède pas le
#: premier.
FORME_ANNUELLE = re.compile(rf"{NOMBRE}\s*par an")
FORME_PLAFOND = re.compile(rf"est fixé à\s*{NOMBRE}\s*au 1er \w+ (\d{{4}})")

#: Bornes de vraisemblance d'un minimum de pension, en euros par an. Elles
#: écartent une année ou un numéro d'article qu'on aurait pris pour un montant.
MONTANT_MINIMAL, MONTANT_MAXIMAL = 1_000.0, 30_000.0


def _nombre(brut: str) -> float:
    return float(re.sub(r"[\s ]", "", brut).replace(",", "."))


def montants(texte: str) -> dict[str, float]:
    """Montants annuels portés par une version de D. 351-2-1.

    Le plus petit est le minimum, le plus grand sa majoration au titre des
    périodes cotisées. Une version qui n'en porte qu'un — les rédactions
    d'avant la création de la majoration — ne renseigne que le premier.
    """
    valeurs = sorted({
        v for v in (_nombre(m.group(1)) for m in FORME_ANNUELLE.finditer(texte))
        if MONTANT_MINIMAL <= v <= MONTANT_MAXIMAL
    })
    if not valeurs:
        return {}
    if len(valeurs) == 1:
        return {"montant_base": valeurs[0]}
    return {"montant_base": valeurs[0], "montant_majore": valeurs[-1]}


def plafond(texte: str) -> tuple[int, float] | None:
    """Plafond mensuel de D. 173-21-0-0-1, ramené à l'année, et sa date d'effet."""
    m = FORME_PLAFOND.search(texte)
    if m is None:
        return None
    return int(m.group(2)), _nombre(m.group(1)) * 12


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
CIBLE = re.compile(r"<NUM>\s*(%s)\s*</NUM>")
BALISES = re.compile(r"<[^>]+>")
tampon = ""
for bloc in iter(lambda: sys.stdin.buffer.read(1 << 20), b""):
    tampon += bloc.decode("utf-8", errors="replace")
    morceaux = tampon.split("<?xml")
    tampon = morceaux.pop()
    for morceau in morceaux:
        trouve = CIBLE.search(morceau)
        if not trouve:
            continue
        debut = re.search(r"<DATE_DEBUT>(.*?)</DATE_DEBUT>", morceau)
        texte = re.sub(r"\s+", " ", BALISES.sub(" ", morceau)).strip()
        print("@@@ %%s %%s" %% (trouve.group(1), debut.group(1) if debut else "?"))
        print(texte[:3000])
        sys.stdout.flush()
"""


def depouiller(url: str) -> list[tuple[str, str, str]]:
    """Lit le dump en flux et renvoie (article, date d'entrée en vigueur, texte)."""
    motif = "|".join(re.escape(a) for a in ARTICLES)
    lecture = subprocess.Popen(
        ["curl", "-sS", "--max-time", "5400", url], stdout=subprocess.PIPE
    )
    detar = subprocess.Popen(
        ["tar", "-xzO"], stdin=lecture.stdout, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    lecture.stdout.close()
    filtre = subprocess.Popen(
        [sys.executable, "-c", FILTRE % motif],
        stdin=detar.stdout, stdout=subprocess.PIPE, text=True,
    )
    detar.stdout.close()
    sortie, _ = filtre.communicate()
    lecture.wait()

    versions = []
    for bloc in sortie.split("@@@ ")[1:]:
        entete, _, corps = bloc.partition("\n")
        article, _, debut = entete.strip().partition(" ")
        versions.append((article, debut.strip(), corps))
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
        print("ÉCHEC   aucune version des articles "
              f"{', '.join(ARTICLES)} dans le dump", file=sys.stderr)
        return 1

    # On garde la version la plus récente de chaque article : ce sont des
    # ancres, pas des séries, et c'est l'ancre en vigueur qui vaut.
    serie: dict[str, float] = {}
    ancres: dict[str, int] = {}
    for article, debut, corps in sorted(versions, key=lambda v: (v[0], v[1])):
        annee = int(debut[:4]) if debut[:4].isdigit() else 0
        if article == "D351-2-1":
            trouves = montants(corps)
            for mesure, valeur in trouves.items():
                serie[f"{mesure}|{annee}"] = valeur
                ancres[mesure] = annee
        else:
            lu = plafond(corps)
            if lu is not None:
                annee_effet, valeur = lu
                serie[f"plafond_ecretement|{annee_effet}"] = valeur
                ancres["plafond_ecretement"] = annee_effet

    for cle, valeur in sorted(serie.items()):
        mesure, _, annee = cle.partition("|")
        print(f"OK      {mesure} au 1er janvier {annee} : {valeur:,.2f} €/an")

    manquantes = {"montant_base", "montant_majore", "plafond_ecretement"} - set(ancres)
    if manquantes:
        print(f"\nÉCHEC   mesures introuvables : {sorted(manquantes)}", file=sys.stderr)
        return 1
    if serie[f"montant_majore|{ancres['montant_majore']}"] <= serie[
            f"montant_base|{ancres['montant_base']}"]:
        print("\nÉCHEC   le minimum majoré n'est pas supérieur au minimum : "
              "la lecture est fausse, rien n'est écrit", file=sys.stderr)
        return 1

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(
        json.dumps({
            "source": url,
            "articles": "code de la sécurité sociale, D. 351-2-1 et D. 173-21-0-0-1",
            "recupere_le": date.today().isoformat(),
            "versions_lues": len(versions),
            "note": "ancres datées, non séries : le code n'est pas modifié chaque "
                    "année, les montants sont revalorisés par l'effet de la loi — "
                    "comme le SMIC depuis 2014 pour le plafond, depuis la réforme "
                    "du 14 avril 2023 pour les deux minima. Montants en euros par "
                    "an ; le plafond, publié au mois, est multiplié par douze.",
            "serie": dict(sorted(serie.items())),
        }, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"\n{len(serie)} ancres écrites dans {SORTIE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
