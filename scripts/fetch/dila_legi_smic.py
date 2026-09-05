#!/usr/bin/env python3
"""SMIC horaire, lu dans les décrets qui le relèvent, chez la DILA.

    python scripts/fetch/dila_legi_smic.py

**Ce script télécharge environ 1,1 Go et met un quart d'heure.** Une exécution
par an suffit.

À quoi le SMIC sert ici, et pourquoi il mérite mieux qu'une transcription. Il
n'entre dans le modèle qu'à un seul endroit, mais cet endroit décide de la
décote : un trimestre d'assurance ne s'acquiert pas par le temps passé mais par
un montant cotisé, égal à 150 fois le SMIC horaire depuis 2014, 200 fois avant
(article R. 351-9, lu par `dila_legi_parametres_retraite.py`). Un SMIC trop
haut retire des trimestres, un SMIC trop bas en donne.

Sa série venait d'OpenFisca-France, transcription du *Journal officiel*
plafonnée à ``haute``. Or le *Journal officiel* est ici à portée de main : le
SMIC n'est pas fixé par un article de code mais par un décret annuel, et la
base LEGI garde ces décrets. Ils disent, en une phrase :

    « A compter du 1er juillet 1997 […] le montant du salaire minimum de
      croissance est porté à 39,43 F de l'heure en métropole […] »

CE QU'IL FAUT LIRE, ET CE QU'IL FAUT ÉCARTER

* **la métropole, et elle seule.** Mayotte a son propre SMIC, relevé par ses
  propres décrets, et ils sont dans le même dump. Un décret qui ne mentionne
  pas la métropole n'est pas retenu ;
* **la date d'EFFET, non celle du décret.** Le relèvement était au 1er juillet
  jusqu'en 2009, au 1er janvier depuis 2010, et il y a eu des relèvements
  exceptionnels en cours d'année — trois pour la seule année 2022 ;
* **la monnaie.** Francs jusqu'au relèvement de juillet 2001, euros ensuite,
  avec des rédactions qui écrivent « 6,83 Euros », « 8,86 € », ou rien du tout
  (le décret du 29 juin 2006 dit « porté à 8,27 l'heure »).

LA CONVENTION DU DÉPÔT est celle de l'article R. 351-9 : le SMIC à retenir est
celui **en vigueur au 1er janvier** de l'année considérée. La valeur d'une année
est donc celle du dernier décret entré en vigueur avant cette date — le plus
souvent celui de l'année précédente.

**Une chaîne de décrets ne se devine pas.** Si le dump ne portait pas l'un
d'eux, la règle ci-dessus rendrait sans bruit la valeur de l'année d'avant, et
la série serait fausse là où elle est plate. Le script n'écrit donc une année
que si le décret qui la commande date de moins de dix-huit mois : au-delà, il y
a un trou, et l'année est laissée à la transcription plutôt que devinée.

**L'ANNÉE DE LA BASCULE À L'EURO N'EST PAS CERTIFIABLE PAR CETTE VOIE**, et
c'est le même principe. Au 1er janvier 2002, le SMIC opposable n'est pas la
conversion arithmétique des 43,72 F du décret de juillet 2001 — 6,6651 € — mais
6,67 €, arrondi fixé par le texte de conversion. Ce texte-là n'est pas dans le
dump : une année dont le décret en vigueur est encore écrit en francs alors
qu'elle se compte en euros n'est donc pas écrite, et reste à la transcription.

**CE QUE LE DUMP NE PORTE PAS.** Les relèvements postérieurs à celui du
1er janvier 2017 n'y figurent pas : la base LEGI garde les textes consolidés, et
les décrets récents n'y sont pas entrés. La couverture s'arrête donc à 2018 —
l'année que commande le dernier décret connu — et les suivantes restent
transcrites d'OpenFisca, au niveau `haute`.

Et ce n'est pas une particularité de LEGI : le dump **JORF** de la même DILA,
qui porte le *Journal officiel* lui-même et remonte à 1946, s'arrête au même
point pour ces décrets — vingt-trois relèvements, de juillet 1996 à janvier
2017, et rien après, alors qu'il contient bien des textes de 2024. Les deux
voies ont été essayées ; c'est écrit ici pour ne pas l'essayer une troisième
fois.
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
SORTIE = Path("data/brut/dila_legi_smic.json")

#: Parité irrévocable du franc et de l'euro. Une définition, pas un change.
FRANC = 6.55957
#: Le SMIC est écrit en francs jusqu'au relèvement de juillet 2001 inclus.
DERNIER_FRANC = date(2001, 12, 31)

#: Première année que le modèle demande. La transcription d'OpenFisca commence
#: en 1970 ; ce que les décrets de LEGI ne couvrent pas lui reste.
PREMIERE_ANNEE = 1970

#: Au-delà de ce délai entre le dernier décret connu et le 1er janvier d'une
#: année, on tient qu'un décret manque : l'année n'est pas écrite. Une année
#: pleine, moins un jour — l'article L. 3231-5 impose un relèvement au moins
#: annuel, si bien qu'un intervalle de trois cent soixante-cinq jours signale un
#: texte absent du dump, non une année sans décision. C'est ce qui écarte 2018,
#: dont le décret de décembre 2017 n'y est pas.
FRAICHEUR_MAXIMALE_JOURS = 364

#: Hausse annuelle au-delà de laquelle il y a lieu de douter de la lecture. Le
#: SMIC a monté de 13 % en 1968 et de plus de 11 % en 1982 ; 25 % laisse la
#: place à l'histoire sans laisser passer un facteur d'échelle.
HAUSSE_MAXIMALE = 0.25

MOIS = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "août": 8, "aout": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
}

#: « le montant du salaire minimum de croissance est porté à 39,43 F de l'heure »
MONTANT = re.compile(
    r"salaire minimum de croissance est (?:port[ée]|fix[ée])\s*à\s*"
    r"(\d{1,3}(?:[,.]\d{1,4})?)\s*(F|francs?|€|euros?)?",
    re.I)

#: « A compter du 1er juillet 1997 » — la date d'EFFET, à ne pas confondre avec
#: celle du décret, que son intitulé porte quelques jours plus tôt : « Décret
#: n° 96-571 DU 26 JUIN 1996 portant relèvement… A compter du 1er juillet 1996 ».
#: Un « du » nu attraperait la seconde.
EFFET = re.compile(
    r"[àa]\s+compter\s+du\s+(\d{1,2})e?r?\s+(\w+)\s+(\d{4})", re.I)
#: « Du 1er juillet au 31 décembre 2001 inclus » — l'autre rédaction, où
#: l'année ne suit pas le mois de la date d'effet mais celui de la fin.
EFFET_PERIODE = re.compile(
    r"\bdu\s+(\d{1,2})e?r?\s+(\w+)\s+au\s+\d{1,2}e?r?\s+\w+\s+(\d{4})", re.I)

#: Le SMIC de Mayotte a ses propres décrets, dans le même dump.
METROPOLE = re.compile(r"m[ée]tropole", re.I)

FILTRE = r"""
import re, sys
CIBLE = re.compile(r"salaire minimum de croissance est (port|fix)", re.I)
BALISES = re.compile(r"<[^>]+>")
tampon = ""
for bloc in iter(lambda: sys.stdin.buffer.read(1 << 20), b""):
    tampon += bloc.decode("utf-8", errors="replace")
    morceaux = tampon.split("<?xml")
    tampon = morceaux.pop()
    for morceau in morceaux:
        texte = re.sub(r"\s+", " ", BALISES.sub(" ", morceau)).strip()
        if not CIBLE.search(texte):
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


def date_d_effet(texte: str, defaut: str) -> date | None:
    """Date à laquelle le relèvement prend effet, telle que le décret la dit.

    À défaut — une rédaction inhabituelle —, la date d'entrée en vigueur de la
    version, que la base porte séparément.
    """
    for motif in (EFFET, EFFET_PERIODE):
        trouve = motif.search(texte)
        if trouve is None:
            continue
        jour, mois, annee = trouve.groups()
        if mois.lower() in MOIS:
            return date(int(annee), MOIS[mois.lower()], int(jour))
    try:
        return date.fromisoformat(defaut)
    except ValueError:
        return None


def en_euros(montant: float, unite: str | None, effet: date) -> float:
    """Le franc jusqu'à la fin de 2001, l'euro ensuite — sauf mention contraire."""
    if unite and unite.lower().startswith(("€", "eur")):
        return montant
    if unite and unite.lower().startswith("f"):
        return montant / FRANC
    return montant / FRANC if effet <= DERNIER_FRANC else montant


def relevements(versions: list[tuple[str, str]]) -> dict[date, float]:
    """Montant du SMIC horaire par date d'effet, en euros."""
    par_date: dict[date, float] = {}
    for debut, texte in versions:
        if not METROPOLE.search(texte):
            continue
        montant = MONTANT.search(texte)
        if montant is None:
            continue
        effet = date_d_effet(texte, debut)
        if effet is None:
            continue
        valeur = en_euros(float(montant.group(1).replace(",", ".")),
                          montant.group(2), effet)
        # Deux décrets peuvent porter la même date d'effet — un rectificatif :
        # le plus récent est lu en dernier et l'emporte.
        par_date[effet] = valeur
    return par_date


def serie_annuelle(par_date: dict[date, float]) -> dict[int, float]:
    """SMIC en vigueur au 1er janvier de chaque année, sans deviner les trous."""
    dates = sorted(par_date)
    if not dates:
        return {}
    serie: dict[int, float] = {}
    for annee in range(max(PREMIERE_ANNEE, dates[0].year), date.today().year + 2):
        premier_janvier = date(annee, 1, 1)
        applicables = [d for d in dates if d <= premier_janvier]
        if not applicables:
            continue
        dernier = applicables[-1]
        if (premier_janvier - dernier).days > FRAICHEUR_MAXIMALE_JOURS:
            continue
        # L'année de la bascule : le dernier décret est en francs, le SMIC
        # opposable est en euros, et l'arrondi de la conversion vient d'un texte
        # que le dump ne porte pas. On ne l'invente pas.
        if premier_janvier > DERNIER_FRANC >= dernier:
            continue
        serie[annee] = par_date[dernier]
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
    par_date = relevements(versions)
    serie = serie_annuelle(par_date)
    if not serie:
        print("ÉCHEC   aucun décret de relèvement lu dans le dump", file=sys.stderr)
        return 1

    annees = sorted(serie)
    for precedente, courante in zip(annees, annees[1:]):
        if serie[courante] < serie[precedente]:
            print(f"ÉCHEC   le SMIC recule de {precedente} à {courante} : "
                  f"{serie[precedente]:.4f} puis {serie[courante]:.4f}",
                  file=sys.stderr)
            return 1
        if serie[courante] / serie[precedente] - 1 > HAUSSE_MAXIMALE:
            print(f"ÉCHEC   le SMIC bondit de "
                  f"{serie[courante] / serie[precedente] - 1:.1%} entre "
                  f"{precedente} et {courante}", file=sys.stderr)
            return 1

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(
        json.dumps({
            "source": url,
            "recupere_le": date.today().isoformat(),
            "versions_lues": len(versions),
            "relevements_lus": len(par_date),
            "note": "décrets portant relèvement du salaire minimum de croissance, "
                    "métropole ; valeur en vigueur au 1er janvier de l'année, "
                    "comme l'exige l'article R. 351-9 pour la validation des "
                    "trimestres. Les années dont le décret manque au dump ne sont "
                    "pas écrites : elles restent à la transcription d'OpenFisca.",
            "serie": {str(annee): valeur for annee, valeur in sorted(serie.items())},
        }, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"{len(par_date)} relèvements lus, {len(serie)} années écrites dans {SORTIE}")
    print(f"Couverture {annees[0]}-{annees[-1]} ; "
          f"{serie[annees[0]]:.4f} € puis {serie[annees[-1]]:.4f} €")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
