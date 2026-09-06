#!/usr/bin/env python3
"""Plafond de la Sécurité sociale, lu dans les décrets qui le fixent.

    python scripts/fetch/jorf_plafond_securite_sociale.py

**Ce script télécharge environ 1,7 Go et met une demi-heure.**

Ce qu'il referme. Le plafond borne l'assiette du régime général et sépare les
tranches des complémentaires : une erreur de plafond déplace, sur toute une
carrière, la frontière entre droits de base et droits complémentaires. Les
années 2002 et suivantes venaient de l'INSEE, certifiées. Les **soixante et
onze années 1931-2001** venaient d'OpenFisca-France — une transcription tierce,
plafonnée à ``haute``, et le plus gros bloc non certifié qui restait au dépôt.

`docs/limites.md` écrivait : « l'INSEE ne publie le plafond mensuel qu'à partir
de 2001 et l'Urssaf ne diffuse aucun historique en accès ouvert ». C'est exact,
et sans portée : le plafond n'est pas une statistique, c'est un décret. La base
**JORF** de la DILA porte le *Journal officiel* lui-même, et chacun de ces
décrets y est.

TROIS ÉCRITURES POUR UNE MÊME GRANDEUR, ET ELLES SE SUIVENT DANS LE TEMPS

* **avant 1997, la notice.** Les textes anciens ne sont dans la base que par
  leur résumé, en capitales et sans accents — mais ce résumé porte les montants
  et leurs dates, ce qui suffit :

      « LES NOUVELLES VALEURS DU PLAFOND S'ETABLISSENT DONC POUR LA PERIODE DU
        01-01-1991 AU 30-06-1991 A 11340FRS ET POUR LA PERIODE DU 01-07-1991 AU
        31-12-1991 A 11620FRS PAR MOIS. »

* **de 1997 à 2002, l'article 1er**, en texte intégral, qui décline le plafond
  par périodicité de paie et date lui-même son application :

      « 14 090 F si les rémunérations ou gains sont versés par mois […] pour les
        rémunérations ou gains versés du 1er janvier au 31 décembre 1998. »

* **depuis 2003, l'arrêté annuel**, qui ne garde que deux valeurs :

      « ― valeur mensuelle : 3 864 euros ; ― valeur journalière : 213 euros. »

**LE PLAFOND ÉTAIT SEMESTRIEL.** Jusqu'en 1996 il était relevé au 1er janvier
ET au 1er juillet : le plafond ANNUEL n'est donc pas douze fois celui de
janvier, c'est la somme des douze plafonds mensuels. C'est la règle qu'applique
déjà `openfisca_plafond.annualiser`, et la même est reprise ici.

**CE QUI SE CONTRÔLE TOUT SEUL.** La notice ancienne écrit le taux qu'elle
applique — « TAUX D'AUGMENTATION DE 5% AU 01-01-1991 […] SOIT 2,5% » : le
montant de juillet se recalcule à partir de celui de janvier, à l'arrondi de
l'article D. 242-19 près. Le récupérateur refait ce calcul et refuse d'écrire
une année dont les deux montants ne s'accordent pas.

**CE QUE CETTE SOURCE NE DONNE PAS.** La base JORF commence en 1947 et ses
notices anciennes sont inégales : les années dont aucun texte n'a été lu ne
sont pas rendues, et restent transcrites d'OpenFisca au niveau ``haute``. Le
récupérateur ne comble jamais un trou par la valeur de l'année d'avant — un
plafond reconduit et un plafond manquant s'écrivent pareil, et seule la seconde
lecture serait fausse.
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

RACINE = "https://echanges.dila.gouv.fr/OPENDATA/JORF/"
SORTIE = Path("data/brut/jorf_plafond_securite_sociale.json")

#: Parité irrévocable du franc et de l'euro, et passage aux nouveaux francs.
FRANC = 6.55957
PREMIER_NOUVEAU_FRANC = date(1960, 1, 1)

MOIS_PAR_AN = 12

#: Bornes plausibles du plafond MENSUEL, une fois ramené en euros. En deçà et
#: au-delà, le montant lu parle d'autre chose que du plafond.
MENSUEL_PLAUSIBLE = (10.0, 10000.0)

#: Hausse annuelle au-delà de laquelle la lecture est douteuse. Le plafond a
#: monté de 14 % en 1957, jamais de plus de vingt.
HAUSSE_MAXIMALE = 0.25

#: L'arrondi de l'article D. 242-19 : le plafond mensuel est arrondi à la
#: dizaine. Le contrôle du taux annoncé se fait donc à une dizaine près.
ARRONDI = 10.0

MOIS = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "août": 8, "aout": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
}

#: La formule qui ouvre la notice ancienne, et sans laquelle ses montants ne
#: sont pas ceux du plafond de la Sécurité sociale. Le Journal officiel emploie
#: le mot « plafond » pour une vingtaine d'autres grandeurs — la participation
#: forfaitaire, le loyer de l'allocation logement, l'aide aux exploitations en
#: difficulté —, et plusieurs les fixent en francs par mois.
NOTICE_ANNONCE = re.compile(r"NOUVELLES VALEURS DU PLAFOND", re.I)

#: « POUR LA PERIODE DU 01-01-1991 AU 30-06-1991 A 11340FRS » — la notice
#: ancienne, qui date chaque montant par la période qu'il couvre.
NOTICE_PERIODE = re.compile(
    r"PERIODE DU (\d\d)-(\d\d)-(\d{4})\s*AU\s*\d\d-\d\d-\d{4}\s*[AÀ]\s*"
    r"([\d  ]+)\s*FRS?",
    re.I)

#: « LE PLAFOND DE SECURITE SOCIALE APPLICABLE AUX REMUNERATIONS OU GAINS
#: VERSES A PARTIR DU 01-07-1984 EST FIXE A 8490FRS PAR MOIS ». Le « PAR MOIS »
#: est ce qui distingue le plafond des cotisations des autres plafonds du
#: Journal officiel, et il est exigé.
NOTICE_A_COMPTER = re.compile(
    r"(?:A (?:COMPTER|PARTIR) DU)\s*(\d\d)-(\d\d)-(\d{4})[^.]{0,100}?"
    r"EST FIXE\s*[AÀ]\s*([\d  ]+)\s*FRS?\s*PAR MOIS",
    re.I)

#: « LE PLAFOND MENSUEL AU 01-01-1997 S'ETABLIT AINSI A 13720FRS ».
NOTICE_MENSUEL = re.compile(
    r"PLAFOND MENSUEL AU (\d\d)-(\d\d)-(\d{4})[^.]{0,60}?"
    r"S'ETABLIT[^.]{0,40}?[AÀ]\s*([\d  ]+)\s*FRS?",
    re.I)

#: La notice des années 1980 ne date que le relèvement de juillet — mais elle
#: rappelle celui de janvier entre parenthèses, pour justifier son taux :
#: « EST FIXE A 8490FRS PAR MOIS, SOIT UNE AUGMENTATION DE 4,69% PAR RAPPORT AU
#: PLAFOND EN VIGUEUR DEPUIS LE 01-01-1984 (8110FRS PAR MOIS) ».
NOTICE_DEPUIS = re.compile(
    r"DEPUIS LE (\d\d)-(\d\d)-(\d{4})\s*\(\s*([\d  ]+)\s*FRS?\s*PAR MOIS\s*\)",
    re.I)

#: L'autre écriture des mêmes années : le TITRE porte les deux dates, et le
#: montant de janvier est la parenthèse du corps. « PORTANT FIXATION A COMPTER
#: DU 01-01-1988 ET DU 01-07-1988 DU PLAFOND DE LA SECURITE SOCIALE […]
#: (PLAFOND: 9950FRS PAR MOIS) ».
TITRE_DEUX_DATES = re.compile(
    r"FIXATION,?\s*A COMPTER DU (\d\d)-(\d\d)-(\d{4})\s*ET DU "
    r"\d\d-\d\d-\d{4},?\s*DU PLAFOND",
    re.I)
NOTICE_PARENTHESE = re.compile(
    r"\(\s*PLAFOND\s*:\s*([\d  ]+)\s*FRS?\s*PAR MOIS\s*\)", re.I)

#: « 14 090 F si les rémunérations ou gains sont versés par mois » — l'article
#: 1er en texte intégral, de 1997 à 2002.
ARTICLE_MENSUEL = re.compile(
    r"([\d  ]{3,10})\s*(?:F|EUR|Euro|euros?|€)\s*si les r[ée]mun[ée]rations ou gains"
    r"\s*sont vers[ée]s par mois",
    re.I)

#: « pour les rémunérations ou gains versés du 1er janvier au 31 décembre
#: 1998 » — la période que cet article 1er couvre.
ARTICLE_PERIODE = re.compile(
    r"vers[ée]s du 1er (\w+)(?: \d{4})? au \d{1,2} (\w+) (\d{4})", re.I)

#: « ― valeur mensuelle : 3 864 euros » — l'arrêté annuel, depuis 2003.
ARRETE_MENSUEL = re.compile(
    r"valeur mensuelle\s*:?\s*([\d  ]+)\s*(euros?|€)", re.I)

#: « portant fixation du plafond de la sécurité sociale pour 2024 » — l'année
#: que cet arrêté commande, lue dans son titre.
ARRETE_ANNEE = re.compile(
    r"fixation (?:du|de ce) plafond de la s[ée]curit[ée] sociale "
    r"(?:pour |pour l'ann[ée]e )(\d{4})",
    re.I)

#: Le taux qui lie les deux montants d'une même notice, dans les trois
#: écritures qu'elle en a eues. L'ORDRE COMPTE : la notice de 1987 annonce
#: aussi le taux de janvier — « TAUX D'AUGMENTATION DE 3,32% » —, qui se
#: rapporte à l'année précédente et non aux deux montants qu'elle porte.
#: Chercher celui de juillet d'abord est ce qui évite de contrôler à l'envers.
NOTICE_TAUX = (
    re.compile(r"MAJORATION DE\s*(\d+(?:[,.]\d+)?)\s*%\s*DE LA VALEUR", re.I),
    re.compile(r"SOIT UNE AUGMENTATION DE\s*(\d+(?:[,.]\d+)?)\s*%", re.I),
    re.compile(r"SOIT\s*(\d+(?:[,.]\d+)?)\s*%", re.I),
)

FILTRE = r"""
import re, sys
PLAFOND = re.compile(r"plafond", re.I)
SS = re.compile(r"s[ée]curit[ée] sociale", re.I)
MONTANT = re.compile(
    r"S'ETABLISSENT|S'ETABLIT|FRS PAR MOIS|FRS\.|"
    r"sont vers[ée]s par mois|valeur mensuelle|"
    r"EST FIXE [AÀ] ?[\d ]+ ?FRS",
    re.I)
BALISES = re.compile(r"<[^>]+>")
tampon = ""
for bloc in iter(lambda: sys.stdin.buffer.read(1 << 20), b""):
    tampon += bloc.decode("utf-8", errors="replace")
    morceaux = tampon.split("<?xml")
    tampon = morceaux.pop()
    for morceau in morceaux:
        texte = re.sub(r"\s+", " ", BALISES.sub(" ", morceau)).strip()
        if not (PLAFOND.search(texte) and SS.search(texte) and MONTANT.search(texte)):
            continue
        print("@@@")
        print(texte[:12000])
        sys.stdout.flush()
"""


def dernier_dump() -> str:
    with urllib.request.urlopen(RACINE, timeout=120) as reponse:
        page = reponse.read().decode("utf-8", errors="replace")
    noms = sorted(set(re.findall(r'href="(Freemium_jorf_global_[^"]+\.tar\.gz)"', page)))
    if not noms:
        raise LookupError("aucun dump global dans le répertoire JORF de la DILA")
    return RACINE + noms[-1]


def _nombre(brut: str) -> float:
    """« 14 090 », « 11340 », « 3 864 » : le Journal officiel aère ses milliers."""
    return float(re.sub(r"[\s ]", "", brut).replace(",", "."))


def _en_euros(montant: float, effet: date) -> float:
    """Le montant du jour, ramené en euros. Avant 1960, ce sont des anciens francs."""
    if effet.year >= 2002:
        return montant
    if effet < PREMIER_NOUVEAU_FRANC:
        return montant / 100.0 / FRANC
    return montant / FRANC


def _retenir(par_date: dict[date, float], effet: date, montant: float,
             griefs: list[str]) -> None:
    """Un montant daté, retenu s'il est plausible et s'il ne contredit rien."""
    valeur = _en_euros(montant, effet)
    if not MENSUEL_PLAUSIBLE[0] <= valeur <= MENSUEL_PLAUSIBLE[1]:
        return
    ancien = par_date.get(effet)
    if ancien is not None and abs(ancien - valeur) > 0.01:
        griefs.append(f"{effet} : deux plafonds mensuels, {ancien:.2f} € et "
                      f"{valeur:.2f} €")
        return
    par_date[effet] = valeur


def _controle_du_taux(texte: str, montants: list[tuple[date, float]],
                      griefs: list[str]) -> None:
    """La notice annonce le taux du 1er juillet : on le refait.

    Le montant de juillet vaut celui de janvier majoré du taux annoncé, arrondi
    à la dizaine de francs par l'article D. 242-19. Un écart plus grand qu'un
    arrondi signale une lecture de travers, et l'année entière est refusée.
    """
    if len(montants) != 2:
        return
    taux = next(filter(None, (motif.search(texte) for motif in NOTICE_TAUX)), None)
    if taux is None:
        return
    (_, janvier), (juillet_date, juillet) = montants
    attendu = janvier * (1 + float(taux.group(1).replace(",", ".")) / 100)
    ecart = abs(juillet - attendu)
    if ecart > ARRONDI / FRANC * 1.5:
        griefs.append(
            f"{juillet_date} : le taux annoncé de {taux.group(1)} % donnerait "
            f"{attendu:.2f} €, la notice écrit {juillet:.2f} €")


def montants_dates(textes: list[str]) -> tuple[dict[date, float], list[str]]:
    """Plafond MENSUEL en euros, par date d'entrée en vigueur."""
    par_date: dict[date, float] = {}
    griefs: list[str] = []
    for texte in textes:
        # La notice ancienne, qui date chaque montant par sa période.
        trouves: list[tuple[date, float]] = []
        if NOTICE_ANNONCE.search(texte):
            for jour, mois, annee, montant in NOTICE_PERIODE.findall(texte):
                trouves.append((date(int(annee), int(mois), int(jour)),
                                _nombre(montant)))
        for motif in (NOTICE_A_COMPTER, NOTICE_MENSUEL, NOTICE_DEPUIS):
            for jour, mois, annee, montant in motif.findall(texte):
                trouves.append((date(int(annee), int(mois), int(jour)),
                                _nombre(montant)))
        # Le montant de janvier entre parenthèses, que seul le titre date.
        titre, parenthese = (TITRE_DEUX_DATES.search(texte),
                             NOTICE_PARENTHESE.search(texte))
        if titre and parenthese:
            trouves.append((date(int(titre.group(3)), int(titre.group(2)),
                                 int(titre.group(1))),
                            _nombre(parenthese.group(1))))
        trouves.sort()
        if len(trouves) == 2:
            _controle_du_taux(
                texte,
                [(d, _en_euros(m, d)) for d, m in trouves],
                griefs)
        for effet, montant in trouves:
            _retenir(par_date, effet, montant, griefs)

        # L'article 1er en texte intégral, qui se date lui-même.
        mensuel = ARTICLE_MENSUEL.search(texte)
        periode = ARTICLE_PERIODE.search(texte)
        if mensuel and periode and periode.group(1).lower() in MOIS:
            effet = date(int(periode.group(3)), MOIS[periode.group(1).lower()], 1)
            _retenir(par_date, effet, _nombre(mensuel.group(1)), griefs)

        # L'arrêté annuel, qui porte l'année dans son titre.
        arrete, annee = ARRETE_MENSUEL.search(texte), ARRETE_ANNEE.search(texte)
        if arrete and annee:
            _retenir(par_date, date(int(annee.group(1)), 1, 1),
                     _nombre(arrete.group(1)), griefs)
    return par_date, griefs


def serie_annuelle(par_date: dict[date, float]) -> dict[int, float]:
    """Plafond ANNUEL, somme des douze plafonds mensuels de l'année.

    Le plafond a été semestriel jusqu'en 1996 : douze fois la valeur de janvier
    serait faux d'un demi-relèvement sur toutes ces années-là.

    **Une année dont le texte n'a pas été lu n'est pas rendue.** Le plafond a
    été relevé chaque année sans exception : reconduire la valeur de l'année
    précédente, comme le ferait une lecture par report, écrirait un gel qui n'a
    pas eu lieu. On exige donc un montant daté du 1er janvier de l'année même.
    """
    dates = sorted(par_date)
    if not dates:
        return {}
    serie: dict[int, float] = {}
    for annee in range(dates[0].year, dates[-1].year + 1):
        if date(annee, 1, 1) not in par_date:
            continue
        total = 0.0
        for mois in range(1, 13):
            fin = date(annee, mois, 28)
            applicables = [d for d in dates if d <= fin]
            total += par_date[applicables[-1]]
        serie[annee] = total
    return serie


def depouiller(url: str) -> list[str]:
    lecture = subprocess.Popen(
        ["curl", "-sS", "--max-time", "10800", url], stdout=subprocess.PIPE
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
    return [bloc.strip() for bloc in sortie.split("@@@\n")[1:] if bloc.strip()]


def main() -> int:
    try:
        url = dernier_dump()
    except (urllib.error.HTTPError, urllib.error.URLError, LookupError) as erreur:
        print(f"ÉCHEC   répertoire JORF : {erreur}", file=sys.stderr)
        return 1

    print(f"Dump      {url.rsplit('/', 1)[-1]}")
    print("Lecture en flux d'environ 12 Go décompressés : comptez une demi-heure.\n")
    textes = depouiller(url)
    par_date, griefs = montants_dates(textes)
    for grief in griefs:
        print(f"ÉCHEC   {grief}", file=sys.stderr)
    if griefs:
        return 1
    if not par_date:
        print("ÉCHEC   aucun décret de plafond lu dans le dump", file=sys.stderr)
        return 1

    serie = serie_annuelle(par_date)
    annees = sorted(serie)
    for precedente, courante in zip(annees, annees[1:]):
        if courante != precedente + 1:
            continue
        if serie[courante] < serie[precedente]:
            print(f"ÉCHEC   le plafond recule de {precedente} à {courante} : "
                  f"{serie[precedente]:.2f} € puis {serie[courante]:.2f} €",
                  file=sys.stderr)
            return 1
        if serie[courante] / serie[precedente] - 1 > HAUSSE_MAXIMALE:
            print(f"ÉCHEC   le plafond bondit de "
                  f"{serie[courante] / serie[precedente] - 1:.1%} entre "
                  f"{precedente} et {courante}", file=sys.stderr)
            return 1

    manquantes = [a for a in range(annees[0], annees[-1] + 1) if a not in serie]
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(
        json.dumps({
            "source": url,
            "recupere_le": date.today().isoformat(),
            "textes_lus": len(textes),
            "dates_lues": len(par_date),
            "annees_manquantes": manquantes,
            "note": "plafond ANNUEL de la Sécurité sociale, somme des douze "
                    "plafonds mensuels de l'année — le plafond a été relevé deux "
                    "fois l'an jusqu'en 1996. Montants ramenés en euros : ÷100 "
                    "avant 1960 pour les anciens francs, ÷6,55957 jusqu'en 2001. "
                    "Les années dont aucun texte n'a été lu ne sont pas rendues "
                    "et restent transcrites d'OpenFisca.",
            "serie": {str(annee): serie[annee] for annee in annees},
        }, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"{len(textes)} textes retenus, {len(par_date)} dates, "
          f"{len(serie)} années écrites dans {SORTIE}")
    print(f"Couverture {annees[0]}-{annees[-1]} ; "
          f"{len(manquantes)} années sans texte : "
          f"{manquantes if len(manquantes) <= 30 else str(manquantes[:30]) + '…'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
