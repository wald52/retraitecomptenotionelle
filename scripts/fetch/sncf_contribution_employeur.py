#!/usr/bin/env python3
"""Contribution employeur de la SNCF, lue dans ses deux textes.

    python scripts/fetch/sncf_contribution_employeur.py

**Ce script télécharge environ 2,8 Go et met une heure** : il lit les deux
dumps de la DILA, JORF puis LEGI, car la grandeur cherchée est écrite dans deux
textes de nature différente.

Ce qu'il referme. `docs/limites.md` rangeait ce taux parmi les limites
« localisées, pas encore lues » : « le travail est écrit ici plutôt que fait,
faute d'avoir tranché la convention de date. » Il est fait.

DEUX COMPOSANTES, DEUX TEXTES, DEUX RYTHMES

Le **décret n° 2007-1056 du 28 juin 2007** définit à son article 2 le taux à la
charge de la SNCF comme « la somme de deux composantes, ci-après désignées T1
et T2 » :

* **T1** est le taux qui couvrirait le régime général et les complémentaires si
  les cheminots en relevaient. Il n'est pas dans le décret : un **arrêté annuel**
  le fixe, et le *Journal officiel* le publie —

      « le taux T1 définitif […] est fixé à 23,81 % pour l'année 2022 » ;

* **T2** est le complément propre au régime. Il est dans le décret lui-même, au
  IV de son article 2, dont la base LEGI garde les versions datées.

**LA CONVENTION DE DATE, ET C'EST ELLE QUI TRANCHAIT.** Chaque arrêté porte DEUX
taux T1 : le **définitif** de l'année écoulée et le **provisionnel** de l'année
qui vient. Le taux d'une année est le définitif — celui qui est dû, arrêté une
fois l'exercice connu —, non le provisionnel appelé en décembre. Les deux
diffèrent : 23,87 % et 23,25 % pour 2018, soit six dixièmes de point. Le
récupérateur lit les deux et ne retient que le définitif ; le provisionnel est
conservé au fichier brut pour que l'écart reste visible.

Deux rédactions coexistent, et l'arrêté fondateur emploie la seconde : « le taux
T1 définitif » et « le taux définitif T1 ». Ne lire que la première coûtait
l'année 2007, la seule que cet arrêté-là porte.

**CE QUI SE CERTIFIE, ET CE QUI NE SE CERTIFIE PAS.** La somme n'est lisible que
là où ses deux termes le sont. T1 l'est de 2007 à 2022, à deux exceptions près
que le dump ne porte pas ; **T2 ne l'est que de 2007 à 2011**, parce que le
décret l'énumère année par année jusque-là et bascule ensuite sur une formule :

    « Après le 31 décembre 2011, le taux T2 évolue au 1er janvier de chaque
      année comme le rapport […] entre le montant des cotisations d'assurance
      vieillesse assis sur le montant maximum des rémunérations […] »

Un taux qui évolue par renvoi n'est écrit nulle part : aucun texte ne le porte,
et le calculer serait le reconstituer, non le lire. La réécriture de 2017 —
« A partir du 1er mai 2017, le taux T2 est fixé à 13,85 % » — ne rouvre pas la
série : elle donne une valeur à une date, que la même formule fait dériver dès
le 1er janvier suivant.

**CINQ ANNÉES SE CERTIFIENT DONC**, 2007 à 2011, et elles se sont trouvées
identiques au centième de point à ce que portait la transcription d'OpenFisca.
Les autres restent `haute`, et l'on sait maintenant pourquoi.
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

JORF = "https://echanges.dila.gouv.fr/OPENDATA/JORF/"
LEGI = "https://echanges.dila.gouv.fr/OPENDATA/LEGI/"
SORTIE = Path("data/brut/sncf_contribution_employeur.json")

#: Le décret qui définit la somme, et l'article qui la porte.
DECRET, ARTICLE = "2007-1056", "2"

#: Années que T2 est énuméré dans le décret. Au-delà, il évolue par formule.
ANNEES_T2 = (2007, 2011)

#: Bornes plausibles, en points de pourcentage. T1 tourne autour de 23, T2
#: autour de 12, et leur somme autour de 35 : hors de ces plages, la phrase lue
#: parle d'autre chose.
T1_PLAUSIBLE = (15.0, 30.0)
T2_PLAUSIBLE = (8.0, 18.0)
SOMME_PLAUSIBLE = (28.0, 45.0)

#: Écart maximal toléré entre le provisionnel et le définitif d'une même année.
#: Le premier est une prévision du second ; ils tiennent dans un point.
ECART_PROVISIONNEL = 2.0

#: « le taux T1 définitif […] est fixé à 23,81 % pour l'année 2022 », et
#: « le taux définitif T1 […] est fixé à 22,52 % pour l'année 2007 » — l'arrêté
#: fondateur de 2008 emploie l'ordre inverse, et il est le seul à porter 2007.
TAUX_T1 = re.compile(
    r"taux\s*(?:T\s*1\s*(d[ée]finitif|provisionnel)|(d[ée]finitif|provisionnel)"
    r"\s*T\s*1)\b.{0,320}?est fix[ée]\s*[àa]\s*(\d+,\d+)\s*%\s*"
    r"pour l'ann[ée]e\s*(\d{4})",
    re.I | re.S)

#: La date de l'arrêté qui porte le taux. Un définitif se prend après coup :
#: l'arrêté est postérieur à l'année qu'il arrête, et c'est vérifié.
DATE_ARRETE = re.compile(r"Arr[êe]t[ée] du \d{1,2}\s+\w+\s+(\d{4})", re.I)

#: « Le taux T2 est fixé à : - 11,96 % pour l'année 2007 ; - 12,27 % pour
#: l'année 2008 ». Le Journal officiel aère parfois ses décimales — « 11, 96 % ».
TAUX_T2 = re.compile(
    r"(\d+\s*,\s*\d+)\s*%\s*pour l'ann[ée]e\s*(\d{4})", re.I)

#: Le IV de l'article 2, seul endroit du décret où T2 est chiffré.
IV_DU_DECRET = re.compile(r"IV\s*\.?\s*[-–—]\s*Le taux T2 est fix[ée]", re.I)

FILTRE_JORF = r"""
import re, sys
CIBLE = re.compile(r"taux\s*(T\s*1|d[ée]finitif\s*T\s*1|provisionnel\s*T\s*1)", re.I)
SNCF = re.compile(r"chemins de fer fran[çc]ais", re.I)
BALISES = re.compile(r"<[^>]+>")
tampon = ""
for bloc in iter(lambda: sys.stdin.buffer.read(1 << 20), b""):
    tampon += bloc.decode("utf-8", errors="replace")
    morceaux = tampon.split("<?xml")
    tampon = morceaux.pop()
    for morceau in morceaux:
        texte = re.sub(r"\s+", " ", BALISES.sub(" ", morceau)).strip()
        if not (CIBLE.search(texte) and SNCF.search(texte)):
            continue
        print("@@@")
        print(texte[:12000])
        sys.stdout.flush()
"""

FILTRE_LEGI = r"""
import re, sys
DECRET = re.compile(r"2007-1056")
CIBLE = re.compile(r"d[ée]sign[ée]es T1 et T2", re.I)
BALISES = re.compile(r"<[^>]+>")
tampon = ""
for bloc in iter(lambda: sys.stdin.buffer.read(1 << 20), b""):
    tampon += bloc.decode("utf-8", errors="replace")
    morceaux = tampon.split("<?xml")
    tampon = morceaux.pop()
    for morceau in morceaux:
        texte = re.sub(r"\s+", " ", BALISES.sub(" ", morceau)).strip()
        if not (DECRET.search(texte) and CIBLE.search(texte)):
            continue
        print("@@@")
        print(texte[:20000])
        sys.stdout.flush()
"""


def dernier_dump(racine: str, prefixe: str) -> str:
    with urllib.request.urlopen(racine, timeout=120) as reponse:
        page = reponse.read().decode("utf-8", errors="replace")
    noms = sorted(set(re.findall(rf'href="({prefixe}[^"]+\.tar\.gz)"', page)))
    if not noms:
        raise LookupError(f"aucun dump {prefixe} dans le répertoire de la DILA")
    return racine + noms[-1]


def _nombre(brut: str) -> float:
    """« 23,81 » et « 11, 96 » : le Journal officiel aère parfois ses décimales."""
    return float(re.sub(r"\s", "", brut).replace(",", "."))


def composantes_t1(
        textes: list[str]) -> tuple[dict[int, float], dict[int, float], list[str]]:
    """Taux T1 définitif et provisionnel, par année, lus dans les arrêtés."""
    definitif: dict[int, float] = {}
    provisionnel: dict[int, float] = {}
    griefs: list[str] = []
    for texte in textes:
        arrete = DATE_ARRETE.search(texte)
        for premier, second, valeur, annee in TAUX_T1.findall(texte):
            nature = (premier or second).lower()
            taux, an = _nombre(valeur), int(annee)
            if not T1_PLAUSIBLE[0] <= taux <= T1_PLAUSIBLE[1]:
                continue
            cible = definitif if nature.startswith("d") else provisionnel
            # Un taux définitif est arrêté une fois l'exercice connu : son
            # arrêté est postérieur à l'année qu'il arrête. Un arrêté qui
            # prétendrait le contraire serait mal lu.
            if nature.startswith("d") and arrete and int(arrete.group(1)) <= an:
                griefs.append(
                    f"T1 définitif {an} : arrêté de {arrete.group(1)}, "
                    "antérieur ou contemporain de l'année qu'il arrête")
                continue
            if cible.get(an, taux) != taux:
                griefs.append(f"T1 {nature} {an} : deux valeurs, "
                              f"{cible[an]:g} % et {taux:g} %")
                continue
            cible[an] = taux
    return definitif, provisionnel, griefs


def composante_t2(textes: list[str]) -> tuple[dict[int, float], list[str]]:
    """Taux T2 par année, lu au IV de l'article 2 du décret de 2007."""
    table: dict[int, float] = {}
    griefs: list[str] = []
    for texte in textes:
        depart = IV_DU_DECRET.search(texte)
        if depart is None:
            continue
        for valeur, annee in TAUX_T2.findall(texte[depart.start():depart.end() + 400]):
            taux, an = _nombre(valeur), int(annee)
            if not T2_PLAUSIBLE[0] <= taux <= T2_PLAUSIBLE[1]:
                continue
            if not ANNEES_T2[0] <= an <= ANNEES_T2[1]:
                continue
            if table.get(an, taux) != taux:
                griefs.append(f"T2 {an} : deux valeurs, {table[an]:g} % "
                              f"et {taux:g} %")
                continue
            table[an] = taux
    return table, griefs


def depouiller(url: str, filtre: str) -> list[str]:
    lecture = subprocess.Popen(
        ["curl", "-sS", "--max-time", "10800", url], stdout=subprocess.PIPE
    )
    detar = subprocess.Popen(
        ["tar", "-xzO"], stdin=lecture.stdout, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    lecture.stdout.close()
    sonde = subprocess.Popen(
        [sys.executable, "-c", filtre], stdin=detar.stdout,
        stdout=subprocess.PIPE, text=True,
    )
    detar.stdout.close()
    sortie, _ = sonde.communicate()
    lecture.wait()
    return [re.sub(r"\s+", " ", bloc).strip()
            for bloc in sortie.split("@@@\n")[1:] if bloc.strip()]


def main() -> int:
    try:
        url_jorf = dernier_dump(JORF, "Freemium_jorf_global_")
        url_legi = dernier_dump(LEGI, "Freemium_legi_global_")
    except (urllib.error.HTTPError, urllib.error.URLError, LookupError) as erreur:
        print(f"ÉCHEC   répertoires de la DILA : {erreur}", file=sys.stderr)
        return 1

    print(f"Dump JORF {url_jorf.rsplit('/', 1)[-1]}")
    print("Arrêtés annuels du taux T1 : comptez une demi-heure.\n")
    definitif, provisionnel, griefs = composantes_t1(
        depouiller(url_jorf, FILTRE_JORF))

    print(f"Dump LEGI {url_legi.rsplit('/', 1)[-1]}")
    print("Article 2 IV du décret de 2007 : autant.\n")
    t2, autres = composante_t2(depouiller(url_legi, FILTRE_LEGI))
    griefs += autres

    for annee in sorted(set(definitif) & set(provisionnel)):
        ecart = abs(definitif[annee] - provisionnel[annee])
        if ecart > ECART_PROVISIONNEL:
            griefs.append(f"{annee} : le provisionnel ({provisionnel[annee]:g} %) "
                          f"et le définitif ({definitif[annee]:g} %) s'écartent "
                          f"de {ecart:g} points")
    for grief in griefs:
        print(f"ÉCHEC   {grief}", file=sys.stderr)
    if griefs:
        return 1
    if not definitif or not t2:
        print("ÉCHEC   T1 ou T2 introuvable dans les dumps", file=sys.stderr)
        return 1

    # La somme n'est lisible que là où ses deux termes le sont.
    somme = {annee: (definitif[annee] + t2[annee]) / 100
             for annee in sorted(set(definitif) & set(t2))}
    for annee, taux in somme.items():
        if not SOMME_PLAUSIBLE[0] <= taux * 100 <= SOMME_PLAUSIBLE[1]:
            print(f"ÉCHEC   {annee} : somme de {taux:.2%}, hors de la plage "
                  "plausible", file=sys.stderr)
            return 1
    if not somme:
        print("ÉCHEC   aucune année ne porte ses deux composantes", file=sys.stderr)
        return 1

    for annee in sorted(somme):
        print(f"OK      {annee} : T1 {definitif[annee]:g} % + T2 {t2[annee]:g} % "
              f"= {somme[annee]:.2%}")
    print(f"\nT1 définitif lu sur {len(definitif)} années "
          f"({min(definitif)}-{max(definitif)}), T2 sur {len(t2)} ; "
          f"{len(somme)} sommes complètes")

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(
        json.dumps({
            "source": f"{url_jorf} (arrêtés T1), {url_legi} (décret, T2)",
            "article": f"décret n° {DECRET} du 28 juin 2007, article {ARTICLE}",
            "recupere_le": date.today().isoformat(),
            "note": "contribution employeur de la SNCF, somme des composantes T1 "
                    "et T2. T1 est le taux DÉFINITIF de l'année, arrêté l'année "
                    "suivante, et non le provisionnel appelé en décembre — les "
                    "deux sont rendus, seul le premier compose la somme. T2 n'est "
                    "chiffré par le décret que de 2007 à 2011 ; au-delà il évolue "
                    "par formule, et aucun texte ne le porte. La somme n'est donc "
                    "rendue que pour les années dont les deux composantes sont "
                    "lues.",
            "serie": {
                **{f"t1_definitif|{a}": v for a, v in sorted(definitif.items())},
                **{f"t1_provisionnel|{a}": v for a, v in sorted(provisionnel.items())},
                **{f"t2|{a}": v for a, v in sorted(t2.items())},
                **{f"taux|{a}": v for a, v in sorted(somme.items())},
            },
        }, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"écrit dans {SORTIE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
