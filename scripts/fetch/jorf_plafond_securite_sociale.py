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

QUATRE ÉCRITURES POUR UNE MÊME GRANDEUR, ET ELLES SE SUIVENT DANS LE TEMPS

* **avant 1982, le titre suffit.** Le plafond était fixé une fois l'an, et le
  titre du décret porte l'année et le montant ANNUEL :

      « PORTANT FIXATION POUR L'ANNEE 1969 DU PLAFOND DES COTISATIONS DE
        SECURITE SOCIALE A 16 320 FRS »

* **de 1982 à 1996, la notice.** Les textes anciens ne sont dans la base que par
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

**LE PLAFOND EST DEVENU SEMESTRIEL EN 1982**, et l'est resté jusqu'en 1996 :
relevé au 1er janvier ET au 1er juillet, son montant ANNUEL n'est pas douze fois
celui de janvier, c'est la somme des douze plafonds mensuels. C'est la règle
qu'applique déjà `openfisca_plafond.annualiser`, et la même est reprise ici.

**ET C'EST LE PIÈGE DE LA QUATRIÈME ÉCRITURE.** « POUR L'ANNEE 1969 » vaut pour
l'année ; « A COMPTER DU 01-01-1982 » ne vaut que jusqu'au relèvement suivant,
et le décret du 30 décembre 1981 écrit le second — « (GAIN OU REMUNERATION
ANNUEL : 79 080 FRS) » — six mois avant qu'un décret de juin 1982 ne relève le
plafond. Lire les deux de la même façon donnerait 1982 à −3,6 %. La distinction
est dans le texte : seule la première est lue, et un titre annuel est de toute
façon refusé pour une année dont un relèvement en cours d'année a été lu.

**CE QUI SE CONTRÔLE TOUT SEUL.** La notice ancienne écrit le taux qu'elle
applique — « TAUX D'AUGMENTATION DE 5% AU 01-01-1991 […] SOIT 2,5% » : le
montant de juillet se recalcule à partir de celui de janvier, à l'arrondi de
l'article D. 242-19 près. Le récupérateur refait ce calcul et refuse d'écrire
une année dont les deux montants ne s'accordent pas.

**CE QUE CETTE SOURCE NE DONNE PAS, ET POURQUOI — CAS PAR CAS.** Le
récupérateur ne comble jamais un trou par la valeur de l'année d'avant : un
plafond reconduit et un plafond manquant s'écrivent pareil, et seule la seconde
lecture serait fausse. Les années non rendues restent transcrites d'OpenFisca,
au niveau ``haute``. Ce qui les bloque a été regardé une à une :

* **avant 1963**, le décret ne nomme pas l'année qu'il commande. Celui du
  24 décembre 1963 écrit « LE PLAFOND ANNUEL […] EST FIXE A 11 400 FRS », et
  rien d'autre : le dater de sa publication serait une inférence, non une
  lecture. C'est là que la voie s'arrête, et c'est une affaire de rédaction ;
* **1982 et 1983**, parce que le plafond y devient semestriel avant que la
  notice ne s'y mette : les décrets de juillet 1982 et de juillet 1983 renvoient
  aux « SOMMES FIXEES PAR CE DECRET » sans les écrire ;
* **1985 et 1986**, parce que la base n'en garde que le titre et les mots-clés,
  sans notice ;
* **1989**, parce que le décret de juillet n'annonce qu'un taux — « REVALORISATION
  DE 1,9% » — et non un montant. L'appliquer au plafond de janvier serait un
  calcul, et un calcul ne se certifie pas ;
* **1994 et 1995**, parce que l'article renvoie à une image : « Vous pouvez
  consulter le tableau dans le JO no 0301 du 29/12/94 Page 18669 a 18670 ».
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
NOTICE_ANNONCE = re.compile(r"NOUVELLES? VALEURS? DU PLAFOND", re.I)

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
    r"(?:EST FIXE\s*[AÀ]|IL SERA DE)\s*([\d  ]+)\s*FRS?\s*PAR MOIS",
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
NOTICE_PARENTHESE = (
    re.compile(r"\(\s*PLAFOND\s*:\s*([\d  ]+)\s*FRS?\s*PAR MOIS\s*\)", re.I),
    re.compile(r"LA VALEUR DU NOUVEAU PLAFOND EST DE\s*([\d  ]+)\s*FRS?\s*PAR MOIS",
               re.I),
)

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

#: **LE TITRE SUFFIT, AVANT 1982.** Le plafond était alors fixé une fois l'an,
#: et le titre du décret porte l'année ET le montant ANNUEL : « PORTANT FIXATION
#: POUR L'ANNEE 1969 DU PLAFOND DES COTISATIONS DE SECURITE SOCIALE A 16 320
#: FRS ». Trois séparateurs se rencontrent — « A », « : », la parenthèse —, et
#: le mot « FIXE » s'intercale parfois.
#:
#: **« POUR L'ANNEE N » N'EST PAS « A COMPTER DU 1er JANVIER N ».** La seconde
#: écriture existe aussi, et elle ne dit rien du reste de l'année : le décret du
#: 30 décembre 1981 fixe « (GAIN OU REMUNERATION ANNUEL : 79 080 FRS) » à
#: compter du 1er janvier 1982, mais un décret du 29 juin 1982 a relevé le
#: plafond au 1er juillet. Lire la première comme la seconde donnerait 1982 à
#: −3,6 %. La distinction est dans le texte, et elle est respectée : seule
#: « POUR L'ANNEE » est lue.
ANNUEL_POUR_L_ANNEE = re.compile(
    r"POUR (?:L'ANNEE )?(19\d\d),? DU PLAFOND DES COTISATIONS DE (?:LA )?"
    r"SECURITE SOCIALE\.?\s*(?:FIXE\s*)?(?:[AÀ]|:|\()\s*([\d  ]+)\s*FRS",
    re.I)

#: **CE QUI DIT QU'UNE LECTURE COUVRE L'ANNÉE ENTIÈRE.** Un montant daté du
#: 1er janvier ne vaut pour les douze mois que si le texte le dit : « POUR LA
#: PERIODE DU 01-01-1997 AU 31-12-1997 », « versés du 1er janvier au 31 décembre
#: 1998 », ou le titre d'un arrêté « pour 2024 ». Sans cette mention, l'année
#: n'est rendue que si un second montant y a été lu — car le plafond a été
#: semestriel de 1982 à 1996, et janvier seul vaudrait un an trop longtemps.
#: 1989 en est le cas : sa notice de janvier est lisible, celle de juillet
#: n'annonce qu'un taux, et l'année n'est donc pas rendue.
ANNEE_ENTIERE = (
    re.compile(r"PERIODE DU 01-01-(\d{4}) AU 31-12-\1", re.I),
    re.compile(r"vers[ée]s du 1er janvier(?: \d{4})? au 31 d[ée]cembre (\d{4})", re.I),
)

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
# Large à dessein : avant 1982 le montant est dans le TITRE, sans autre repère
# que le mot « FRS ». Ce qui trie vraiment, c'est le dépouillement.
MONTANT = re.compile(
    r"FRS|S'ETABLI|sont vers[ée]s par mois|valeur mensuelle|"
    r"portant fixation|PORTANT FIXATION",
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


class TransfertIncomplet(RuntimeError):
    """Le dump n'a pas été téléchargé en entier."""


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


def montants_dates(
        textes: list[str]) -> tuple[dict[date, float], set[int], list[str]]:
    """Plafond MENSUEL en euros par date, et les années déclarées entières."""
    par_date: dict[date, float] = {}
    entieres: set[int] = set()
    griefs: list[str] = []
    for texte in textes:
        for motif in ANNEE_ENTIERE:
            entieres.update(int(a) for a in motif.findall(texte))
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
        titre = TITRE_DEUX_DATES.search(texte)
        parenthese = next(
            filter(None, (motif.search(texte) for motif in NOTICE_PARENTHESE)), None)
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
            entieres.add(int(annee.group(1)))
    return par_date, entieres, griefs


def annuels_du_titre(textes: list[str]) -> tuple[dict[int, float], list[str]]:
    """Plafond ANNUEL en euros, lu dans le titre des décrets d'avant 1982."""
    par_annee: dict[int, float] = {}
    griefs: list[str] = []
    for texte in textes:
        for annee, montant in ANNUEL_POUR_L_ANNEE.findall(texte):
            effet = date(int(annee), 1, 1)
            valeur = _en_euros(_nombre(montant), effet)
            if not (MOIS_PAR_AN * MENSUEL_PLAUSIBLE[0] <= valeur
                    <= MOIS_PAR_AN * MENSUEL_PLAUSIBLE[1]):
                continue
            ancien = par_annee.get(int(annee))
            if ancien is not None and abs(ancien - valeur) > 0.01:
                griefs.append(f"{annee} : deux plafonds annuels, {ancien:.2f} € "
                              f"et {valeur:.2f} €")
                continue
            par_annee[int(annee)] = valeur
    return par_annee, griefs


def serie_annuelle(par_date: dict[date, float],
                   entieres: set[int]) -> dict[int, float]:
    """Plafond ANNUEL, somme des douze plafonds mensuels de l'année.

    Le plafond a été semestriel jusqu'en 1996 : douze fois la valeur de janvier
    serait faux d'un demi-relèvement sur toutes ces années-là.

    **Une année dont le texte n'a pas été lu n'est pas rendue.** Le plafond a
    été relevé chaque année sans exception : reconduire la valeur de l'année
    précédente, comme le ferait une lecture par report, écrirait un gel qui n'a
    pas eu lieu. On exige donc un montant daté du 1er janvier de l'année même.

    **Et janvier seul ne suffit pas non plus**, sauf si le texte déclare
    couvrir l'année entière : de 1982 à 1996, un second décret relevait le
    plafond au 1er juillet, et l'étendre aux douze mois le sous-estimerait de
    tout le second relèvement. Il faut donc, ou bien la mention de l'année
    entière, ou bien un second montant lu dans l'année.
    """
    dates = sorted(par_date)
    if not dates:
        return {}
    serie: dict[int, float] = {}
    for annee in range(dates[0].year, dates[-1].year + 1):
        if date(annee, 1, 1) not in par_date:
            continue
        if annee not in entieres and not [
                d for d in dates if d.year == annee and d.month != 1]:
            continue
        total = 0.0
        for mois in range(1, 13):
            fin = date(annee, mois, 28)
            applicables = [d for d in dates if d <= fin]
            total += par_date[applicables[-1]]
        serie[annee] = total
    return serie


def fusionner(mensuels: dict[int, float], annuels: dict[int, float],
              par_date: dict[date, float]) -> tuple[dict[int, float], list[str]]:
    """Les deux lectures réunies, et ce qu'elles se disent l'une de l'autre.

    Le titre d'avant 1982 donne l'annuel directement ; la notice et les articles
    d'après le donnent mois par mois. Les deux périodes ne se recouvrent pas —
    le plafond est devenu semestriel en 1982, et le mot « POUR L'ANNEE » a
    disparu des titres au même moment. Ce n'est pas une raison pour le supposer :
    UN TITRE ANNUEL EST REFUSÉ POUR TOUTE ANNÉE OÙ UN RELÈVEMENT EN COURS
    D'ANNÉE A ÉTÉ LU, puisqu'il ne vaudrait alors que jusqu'à ce relèvement.
    """
    serie, griefs = dict(mensuels), []
    for annee, valeur in sorted(annuels.items()):
        en_cours = [d for d in par_date if d.year == annee and d.month != 1]
        if en_cours:
            griefs.append(f"{annee} : titre annuel écarté, un relèvement au "
                          f"{en_cours[0]} a été lu")
            continue
        if annee in serie and abs(serie[annee] - valeur) > 1.0:
            griefs.append(f"{annee} : le titre annuel dit {valeur:.2f} €, les "
                          f"mois lus donnent {serie[annee]:.2f} €")
            continue
        serie[annee] = valeur
    return serie, griefs


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
    # Un transfert coupé ne se voit pas dans ce qui a été lu : le dépouillement
    # rend une série plus courte, et les contrôles de continuité la trouvent
    # bonne — un dump à moitié lu n'a pas de trou, il a une fin prématurée.
    # C'est arrivé, et rien ne l'avait dit.
    if lecture.wait() != 0:
        raise TransfertIncomplet(
            f"curl s'est interrompu (code {lecture.returncode}) : le dump n'a "
            "pas été lu en entier, et la série qu'on en tirerait serait muette "
            "sur ce qui manque")
    return [bloc.strip() for bloc in sortie.split("@@@\n")[1:] if bloc.strip()]


def main() -> int:
    try:
        url = dernier_dump()
    except (urllib.error.HTTPError, urllib.error.URLError, LookupError) as erreur:
        print(f"ÉCHEC   répertoire JORF : {erreur}", file=sys.stderr)
        return 1

    print(f"Dump      {url.rsplit('/', 1)[-1]}")
    print("Lecture en flux d'environ 12 Go décompressés : comptez une demi-heure.\n")
    try:
        textes = depouiller(url)
    except TransfertIncomplet as erreur:
        print(f"ÉCHEC   {erreur}", file=sys.stderr)
        return 1
    par_date, entieres, griefs = montants_dates(textes)
    for grief in griefs:
        print(f"ÉCHEC   {grief}", file=sys.stderr)
    if griefs:
        return 1
    if not par_date:
        print("ÉCHEC   aucun décret de plafond lu dans le dump", file=sys.stderr)
        return 1

    annuels, autres_griefs = annuels_du_titre(textes)
    serie, fusion = fusionner(serie_annuelle(par_date, entieres), annuels,
                              par_date)
    for grief in autres_griefs + fusion:
        print(f"ÉCHEC   {grief}", file=sys.stderr)
    if autres_griefs:
        return 1
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
            "annees_du_titre": sorted(a for a in annuels if a in serie),
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
