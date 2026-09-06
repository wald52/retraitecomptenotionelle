#!/usr/bin/env python3
"""Les paramètres du scénario 1, lus dans la loi elle-même.

    python scripts/fetch/dila_legi_parametres_retraite.py

**Ce script télécharge environ 1,1 Go et met un quart d'heure.** Il n'a pas à
être relancé souvent : ces tables ne bougent qu'à la faveur d'une réforme.

Quatre tables commandent le scénario « système actuel », et donc l'écart que le
modèle affiche pour les deux autres. Elles étaient saisies depuis les textes,
sans chemin de recontrôle — `docs/limites.md` les tenait pour hors de portée,
au motif que « Légifrance expose une API, mais elle demande une clé et renvoie
du texte juridique, non des paramètres ».

Les deux moitiés de cette phrase étaient vraies et la conclusion fausse. La
base **LEGI** de la DILA est en accès libre et garde chaque version datée de
chaque article codifié ; et si elle renvoie bien du texte juridique, ce texte
est une TABLE, écrite en toutes lettres, article par article :

* `D. 161-2-1-9` du code de la sécurité sociale — l'âge d'ouverture des droits,
  génération par génération : « Soixante-deux ans et trois mois pour les
  assurés nés entre le 1er septembre 1961 et le 31 décembre 1961 inclus » ;
* `L. 161-17-3` — la durée d'assurance requise : « 169 trimestres, pour les
  assurés nés entre le 1er septembre 1961 et le 31 décembre 1962 » ;
* `R. 351-27` II — le coefficient de minoration : « 2,375 % pour l'assuré né en
  1944 […] 1,25 % pour l'assuré né après 1952 » ;
* `D. 351-1-1` — les portes du départ anticipé pour carrière longue : « A
  cinquante-huit ans pour les assurés qui ont débuté leur activité avant l'âge
  de seize ans » ;
* `R. 351-6` II — la durée maximale d'assurance prise en compte par la
  PRORATISATION, qu'il ne faut pas confondre avec la durée requise pour le taux
  plein : « 152 trimestres pour les assurés nés en 1944 » ;
* `R. 351-9` — le nombre d'heures de SMIC qu'il faut avoir cotisé pour valider
  un trimestre : « calculé sur la base de 200 heures », puis de 150 pour la
  période postérieure au 31 décembre 2013 ;
* `R. 351-29-1` — le nombre d'années retenues au salaire annuel moyen,
  génération par génération : « Vingt et une années pour l'assuré né en 1944 ».

Ces deux dernières étaient saisies, et c'est la même leçon une fois de plus :
elles étaient réputées hors de portée parce qu'elles ne ressemblent pas à des
paramètres, alors qu'elles sont écrites en toutes lettres dans l'article. Elles
commandent pourtant, la première le dénominateur de toute carrière incomplète
liquidée par les générations 1944-1948, la seconde le nombre de trimestres que
valide une année de petit salaire — deux endroits où une erreur ne se voit pas
et se paie en pension.

Il n'y avait donc rien à demander à personne : il fallait lire. La leçon est la
même que pour la valeur du point agricole et pour le minimum contributif —
*chercher par le NUMÉRO D'ARTICLE*, LEGI étant organisée par version d'article
et non par thème.

**Un article porte plusieurs codes.** `R. 351-27` existe aussi au code du
travail, à celui de la construction et de l'habitation, à celui de l'action
sociale ; `L. 14` existe au code forestier comme au code électoral. Le script
retient donc, pour chaque article, le code attendu, qu'il lit dans l'en-tête de
la version.

**Une génération coupée en cours d'année.** La loi coupe parfois une génération
à une date — le 1er juillet 1951, le 1er septembre 1961. Le script rendait alors
la valeur couvrant le plus de mois, à égalité la plus exigeante : le modèle ne
connaissait que l'année de naissance, et l'approximation valait un trimestre
d'âge légal. Il rend désormais UN SEGMENT PAR VALEUR, la clé portant le mois de
la coupure — `1951.5` pour le 1er juillet 1951, `1961.667` pour le 1er septembre
1961 —, et le modèle lit ces tables au mois de naissance.
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
SORTIE = Path("data/brut/dila_legi_parametres_retraite.json")

#: Article -> code qui le porte. Un même numéro sert dans plusieurs codes.
ARTICLES = {
    "D161-2-1-9": "sécurité sociale",
    "L161-17-3": "sécurité sociale",
    "R351-27": "sécurité sociale",
    "D351-1-1": "sécurité sociale",
    "R351-6": "sécurité sociale",
    "R351-9": "sécurité sociale",
    "R351-29-1": "sécurité sociale",
    "R351-45": "sécurité sociale",
}

#: Nombres écrits en lettres, tels que le Journal officiel les emploie pour les
#: âges. Au-delà de soixante-neuf, la retraite n'a plus de barème.
MOTS = {
    # « Vingt et une années » : le féminin, que le nombre d'années impose.
    "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6,
    "sept": 7, "huit": 8, "neuf": 9, "dix": 10, "onze": 11, "douze": 12,
    "treize": 13, "quatorze": 14, "quinze": 15, "seize": 16, "vingt": 20,
    "trente": 30, "quarante": 40, "cinquante": 50, "soixante": 60,
}

MOIS = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12,
    "decembre": 12,
}

#: « soixante-deux ans et trois mois », « cinquante-six ans ».
AGE = re.compile(
    r"\b((?:cinquante|soixante)"
    r"(?:[- ](?:et[- ])?(?:un|deux|trois|quatre|cinq|six|sept|huit|neuf))?)"
    r"\s*ans?"
    r"(?:\s*et\s*(un|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze)\s*mois)?",
    re.I,
)

#: Les trois formes par lesquelles un alinéa désigne les générations qu'il vise.
AVANT = re.compile(r"n[ée]s?\s+avant\s+le\s+(\d{1,2})e?r?\s+(\w+)\s+(\d{4})", re.I)
ENTRE = re.compile(
    r"n[ée]s?\s+entre\s+le\s+(\d{1,2})e?r?\s+(\w+)\s+(\d{4})\s+et\s+le\s+"
    r"(\d{1,2})e?r?\s+(\w+)\s+(\d{4})", re.I)
EN_ANNEE = re.compile(r"n[ée]s?\s+en\s+(\d{4})", re.I)
A_COMPTER = re.compile(
    r"n[ée]s?\s+(?:à\s+compter\s+du|à\s+partir\s+du)\s+(\d{1,2})e?r?\s+(\w+)\s+(\d{4})",
    re.I)
APRES_ANNEE = re.compile(r"n[ée]\s+apr[èe]s\s+(\d{4})", re.I)

#: Bornes de génération que le modèle couvre. Au-delà, la table est constante.
PREMIERE_GENERATION, DERNIERE_GENERATION = 1900, 1975


def nombre_en_lettres(texte: str | None) -> int | None:
    if texte is None:
        return 0
    mots = [m for m in re.split(r"[- ]+", texte.strip().lower())
            if m and m != "et"]
    total = 0
    for mot in mots:
        if mot not in MOTS:
            return None
        total += MOTS[mot]
    return total


def age_en_lettres(texte: str) -> float | None:
    """« Soixante et un ans et deux mois » -> 61,17."""
    trouve = AGE.search(texte)
    if trouve is None:
        return None
    annees = nombre_en_lettres(trouve.group(1))
    mois = nombre_en_lettres(trouve.group(2))
    if annees is None or mois is None:
        return None
    return round(annees + mois / 12.0, 2)


def _mois_couverts(alinea: str) -> dict[int, set[int]]:
    """MOIS de chaque génération que cet alinéa vise, un par un.

    Une génération pleine compte douze mois ; une génération coupée en compte
    autant que la période en couvre — et l'on retient LESQUELS, pas seulement
    combien. Le récupérateur ne comptait que le nombre, ce qui suffisait à
    départager deux valeurs à la majorité mais perdait la date de la coupure :
    « nés à compter du 1er septembre 1961 » se réduisait à « quatre mois de la
    génération 1961 », et le modèle opposait alors la valeur majoritaire à
    toute la génération. La table peut désormais couper là où le texte coupe.
    """
    couverts: dict[int, set[int]] = {}

    def ajouter(annee: int, premier: int, dernier: int) -> None:
        if PREMIERE_GENERATION <= annee <= DERNIERE_GENERATION and dernier >= premier:
            couverts.setdefault(annee, set()).update(
                range(max(1, premier), min(12, dernier) + 1)
            )

    trouve = ENTRE.search(alinea)
    if trouve:
        j1, m1, a1, j2, m2, a2 = trouve.groups()
        debut_mois, fin_mois = MOIS.get(m1.lower()), MOIS.get(m2.lower())
        if debut_mois is None or fin_mois is None:
            return {}
        for annee in range(int(a1), int(a2) + 1):
            premier = debut_mois if annee == int(a1) else 1
            dernier = fin_mois if annee == int(a2) else 12
            ajouter(annee, premier, dernier)
        return couverts

    trouve = AVANT.search(alinea)
    if trouve:
        _, mois, annee = trouve.groups()
        borne = MOIS.get(mois.lower())
        if borne is None:
            return {}
        for a in range(PREMIERE_GENERATION, int(annee)):
            ajouter(a, 1, 12)
        ajouter(int(annee), 1, borne - 1)
        return couverts

    trouve = A_COMPTER.search(alinea)
    if trouve:
        _, mois, annee = trouve.groups()
        borne = MOIS.get(mois.lower())
        if borne is None:
            return {}
        ajouter(int(annee), borne, 12)
        for a in range(int(annee) + 1, DERNIERE_GENERATION + 1):
            ajouter(a, 1, 12)
        return couverts

    trouve = APRES_ANNEE.search(alinea)
    if trouve:
        for a in range(int(trouve.group(1)) + 1, DERNIERE_GENERATION + 1):
            ajouter(a, 1, 12)
        return couverts

    trouve = EN_ANNEE.search(alinea)
    if trouve:
        ajouter(int(trouve.group(1)), 1, 12)
    return couverts


def _par_version(versions: list[tuple[str, str]],
                 lire: "callable") -> dict[int, float]:
    """Applique ``lire`` version par version, la plus récente l'emportant.

    Une version d'article REMPLACE la précédente, elle ne s'y ajoute pas : les
    fusionner reviendrait à opposer à une même génération deux états du droit.
    On les parcourt donc dans l'ordre chronologique, chaque version écrasant ce
    que la précédente disait des générations qu'elle couvre — et laissant
    intact ce dont elle ne parle pas.
    """
    valeurs: dict[float, float] = {}
    for _, texte in sorted(versions):
        nouvelles = lire(texte)
        # Une version REMPLACE ce que la précédente disait des générations
        # qu'elle couvre — y compris les coupures : on retire d'abord toutes
        # les clés de ces générations, sans quoi une coupure abandonnée par un
        # texte plus récent survivrait à son abrogation.
        annees = {int(cle) for cle in nouvelles}
        valeurs = {cle: v for cle, v in valeurs.items() if int(cle) not in annees}
        valeurs.update(nouvelles)
    return valeurs


def generation_decimale(annee: int, mois: int) -> float:
    """Génération et mois -> clé de table. Janvier donne l'année toute nue."""
    return annee if mois == 1 else round(annee + (mois - 1) / 12.0, 3)


def table_par_generation(alineas: list[tuple[float, str]]) -> dict[float, float]:
    """Valeur opposable à chaque génération, coupures comprises.

    La table était annuelle : une génération que le texte coupe en cours
    d'année — 1951 au 1er juillet, 1961 au 1er septembre — s'y voyait attribuer
    la valeur couvrant le plus de mois. L'approximation valait un trimestre
    d'âge légal, et le récupérateur la fabriquait alors qu'il avait le mois
    sous les yeux.

    Elle rend désormais un SEGMENT par valeur : la clé est l'année pour un
    segment ouvert en janvier, l'année plus la part écoulée sinon —
    ``1951.5`` pour le 1er juillet 1951. Un mois qu'aucun alinéa ne vise hérite
    du segment précédent, la lecture du modèle étant en escalier.

    À valeurs concurrentes sur un même mois — deux alinéas qui se recouvrent —
    c'est la PLUS EXIGEANTE qui l'emporte : le modèle ne prête jamais à
    personne le régime le plus favorable quand il ne sait pas trancher.
    """
    par_mois: dict[int, dict[int, float]] = {}
    for valeur, alinea in alineas:
        for annee, mois in _mois_couverts(alinea).items():
            cible = par_mois.setdefault(annee, {})
            for m in mois:
                cible[m] = max(cible[m], valeur) if m in cible else valeur

    table: dict[float, float] = {}
    for annee, mois in sorted(par_mois.items()):
        precedente = None
        for m in sorted(mois):
            valeur = mois[m]
            if valeur != precedente:
                table[generation_decimale(annee, m)] = valeur
                precedente = valeur
    return table


def _alineas(texte: str) -> list[str]:
    """Découpe un article en ses alinéas numérotés, plus le corps qui précède."""
    morceaux = re.split(r"\s\d{1,2}°\s*[-.]?\s*", texte)
    return [m.strip() for m in morceaux if m.strip()]


def age_ouverture(versions: list[tuple[str, str]]) -> dict[int, float]:
    """Âge d'ouverture des droits, par génération — D. 161-2-1-9."""
    def lire(texte: str) -> dict[int, float]:
        alineas = [(age_en_lettres(a), a) for a in _alineas(texte)]
        return table_par_generation(
            [(v, a) for v, a in alineas if v is not None and 55.0 <= v <= 70.0]
        )
    return _par_version(versions, lire)


def duree_requise(versions: list[tuple[str, str]]) -> dict[int, float]:
    """Durée d'assurance requise, par génération — L. 161-17-3."""
    def lire(texte: str) -> dict[int, float]:
        alineas = []
        for alinea in _alineas(texte):
            trouve = re.search(r"\b(1[5-7]\d)\s*trimestres", alinea)
            if trouve:
                alineas.append((float(trouve.group(1)), alinea))
        return table_par_generation(alineas)
    return _par_version(versions, lire)


#: « 151 trimestres pour l'assuré né en 1934 ; 152 trimestres pour l'assuré né
#: en 1935 » — la montée en charge de la loi du 22 juillet 1993, au II de
#: l'article R. 351-45. L'article est abrogé depuis 2009 ; la base le garde.
DUREE_1993 = re.compile(
    r"(\d{3})\s*trimestres\s*pour\s*l['’]assur[ée]\s*n[ée]\s*en\s*(19[34]\d)",
    re.I)

#: Générations que ce II couvre. Il s'ouvre sur « l'assuré né AVANT le
#: 1er janvier 1934 », que le motif ci-dessus n'attrape pas — et c'est voulu :
#: le dépôt tient la table à partir de 1934.
GENERATIONS_1993 = (1934, 1942)


def duree_requise_1993(versions: list[tuple[str, str]]) -> dict[int, float]:
    """Durée requise des générations 1934-1942 — R. 351-45 II.

    `docs/limites.md` tenait ces générations pour hors de portée : « leur montée
    en charge vient de la loi du 22 juillet 1993 et de la loi du 21 août 2003,
    dont les tableaux ne sont pas des textes consolidés séparés ». La seconde
    moitié est vraie et la conclusion fausse : le tableau de 1993 n'est pas un
    texte séparé, il est CODIFIÉ — à l'article R. 351-45, une disposition
    transitoire que la base garde bien qu'elle soit abrogée depuis 2009.

    **CE QUE L'ARTICLE DIT DE PLUS QUE LE DÉPÔT.** Son II ne s'applique qu'aux
    « pensions prenant effet avant le 1er janvier 2003 » ; son I porte 160
    trimestres au-delà de cette date, « quelle que soit la date de naissance ».
    Le dépôt, lui, indexe la durée sur la seule génération. Les deux lectures ne
    se séparent que pour un assuré de ces générations qui aurait liquidé après
    2002 — donc à plus de soixante ans, à une époque où l'âge légal en était
    soixante. C'est écrit ici parce que l'écart existe, non parce qu'il pèse.
    """
    def lire(texte: str) -> dict[int, float]:
        table: dict[int, float] = {}
        for trimestres, generation in DUREE_1993.findall(texte):
            annee = int(generation)
            if GENERATIONS_1993[0] <= annee <= GENERATIONS_1993[1]:
                table[annee] = float(trimestres)
        return table
    return _par_version(versions, lire)


def coefficient_minoration(versions: list[tuple[str, str]]) -> dict[int, float]:
    """Coefficient de minoration, par génération — R. 351-27 II.

    L'article n'écrit pas ses alinéas en numéros mais en phrases séparées par
    des points-virgules, et il ne parle pas des « assurés nés » mais de
    « l'assuré né » : le découpage lui est propre.
    """
    def lire(texte: str) -> dict[int, float]:
        partie = texte.split("II.-", 1)
        if len(partie) < 2:
            return {}
        alineas = []
        for alinea in partie[1].split(";"):
            trouve = re.search(r"(\d[,.]\d+|\d)\s*%", alinea)
            if trouve is None:
                continue
            valeur = float(trouve.group(1).replace(",", "."))
            if 1.0 <= valeur <= 3.0:
                alineas.append((valeur / 100.0, alinea))
        return table_par_generation(alineas)
    return _par_version(versions, lire)


#: « A soixante-deux pour les assurés qui ont débuté leur activité avant l'âge
#: de vingt ans » — le décret de 2023 a perdu le mot « ans » à son 3°. On
#: tolère l'omission plutôt que de manquer une porte.
PORTE = re.compile(
    r"[Aa]\s+((?:cinquante|soixante)(?:[- ](?:et[- ])?"
    r"(?:un|deux|trois|quatre|cinq|six|sept|huit|neuf))?)"
    r"(?:\s*ans?)?(?:\s*et\s*(un|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze)"
    r"\s*mois)?[^.;]*?"
    r"avant\s+l['’]?\s*âge\s+de\s+((?:seize|dix-sept|dix-huit|dix-neuf|vingt|"
    r"vingt[- ]et[- ]un))\s*ans",
    re.I)


#: « 152 trimestres pour les assurés nés en 1944 », « 150 trimestres pour les
#: assurés nés avant 1944 » — la table de proratisation de l'article R. 351-6.
PRORATISATION = re.compile(
    r"(\d{3})\s+trimestres\s+pour\s+les\s+assur[ée]s\s+n[ée]s\s+"
    r"(avant|en)\s+(\d{4})",
    re.I)

#: « sur la base de 200 heures » — l'assiette d'un trimestre, à l'article
#: R. 351-9. L'alinéa qui la porte dit sur quelle période elle vaut, de deux
#: façons : « comprise entre le 1er janvier 1972 et le 31 décembre 2013 » ou
#: « postérieure au 31 décembre 2013 ».
ASSIETTE = re.compile(r"sur\s+la\s+base\s+de\s+(\d{2,3})\s+heures", re.I)
PERIODE_ENTRE = re.compile(r"comprise\s+entre\s+le\s+1er\s+janvier\s+(\d{4})", re.I)
PERIODE_APRES = re.compile(r"post[ée]rieure\s+au\s+31\s+d[ée]cembre\s+(\d{4})", re.I)


def duree_proratisation(versions: list[tuple[str, str]]) -> dict[int, float]:
    """Durée maximale d'assurance prise en compte par la proratisation.

    C'est le DÉNOMINATEUR du rapport qui réduit la pension d'une carrière
    incomplète, et la loi du 22 juillet 1993 l'a fait monter de 150 à 160
    trimestres pour les seules générations 1944 à 1948 — deux trimestres par
    génération, quand la durée REQUISE, elle, montait de dix trimestres sur
    dix générations. Confondre les deux retire 2,5 % de pension à un assuré né
    en 1945 qui a validé 156 trimestres.

    L'article s'arrête à la génération 1947 et renvoie, au-delà, à la durée du
    troisième alinéa de l'article L. 351-1 : la table du dépôt porte donc une
    dernière ligne, pour 1948, que cet article-ci ne fixe pas et que la
    certification ne touche pas.

    Version en vigueur seulement : les rédactions antérieures à 2004 ne
    portaient pas de table par génération, mais une durée unique.
    """
    table: dict[int, float] = {}
    for _, texte in sorted(versions)[-1:]:
        for trimestres, portee, generation in PRORATISATION.findall(texte):
            debut = PREMIERE_GENERATION if portee.lower() == "avant" else int(generation)
            table[debut] = float(trimestres)
    return table


def heures_par_trimestre(versions: list[tuple[str, str]]) -> dict[int, float]:
    """Heures de SMIC qu'il faut avoir cotisé pour valider un trimestre.

    Un trimestre d'assurance ne s'acquiert pas par le temps passé mais par un
    montant cotisé, que l'article exprime en multiples du SMIC horaire de
    l'année : 200 heures depuis 1972, 150 depuis 2014 — l'abaissement destiné
    aux temps très partiels et aux carrières hachées.

    Chaque alinéa porte sa période, et la clé est l'année où elle s'ouvre : une
    période « postérieure au 31 décembre 2013 » commence en 2014.
    """
    table: dict[int, float] = {}
    for _, texte in sorted(versions)[-1:]:
        for alinea in re.split(r"(?=Pour la période)", texte):
            heures = ASSIETTE.search(alinea)
            if heures is None:
                continue
            entre = PERIODE_ENTRE.search(alinea)
            apres = PERIODE_APRES.search(alinea)
            if entre is not None:
                table[int(entre.group(1))] = float(heures.group(1))
            elif apres is not None:
                table[int(apres.group(1)) + 1] = float(heures.group(1))
    return table


#: « Vingt et une années pour l'assuré né en 1944 », « Dix années pour l'assuré
#: né avant le 1er janvier 1934 » — la table du salaire de référence.
ANNEES_RETENUES = re.compile(
    r"([\w-]+(?:\s+et\s+[\w-]+)?)\s+ann[ée]es?\s+pour\s+l['’]assur[ée]\s+n[ée]\s+"
    r"(?:en\s+(\d{4})|avant\s+le\s+\d{1,2}e?r?\s+\w+\s+(\d{4}))",
    re.I)

#: « Les durées de vingt-cinq années fixées aux premier et troisième alinéas de
#: l'article R. 351-29 sont applicables aux assurés nés après 1947 » — la cible,
#: et la génération à partir de laquelle elle vaut. Le point qui sépare les deux
#: moitiés de la phrase n'en est pas un : « R. 351-29 » en porte un.
ANNEES_CIBLE = re.compile(
    r"dur[ée]es?\s+de\s+([\w-]+(?:\s+et\s+[\w-]+)?)\s+ann[ée]es?"
    r".{0,200}?assur[ée]s\s+n[ée]s\s+apr[èe]s\s+(\d{4})",
    re.I)


def annees_salaire_reference(versions: list[tuple[str, str]]) -> dict[int, float]:
    """Nombre d'années retenues au salaire annuel moyen, par génération.

    La loi du 22 juillet 1993 fait passer le salaire de référence des dix aux
    vingt-cinq meilleures années, à raison d'une année par génération de 1934 à
    1948, et l'article l'écrit en toutes lettres. Le paramètre se lit à l'ANNÉE
    DE NAISSANCE : le lire à l'année de liquidation opposait vingt-cinq années à
    des générations auxquelles la loi n'en a jamais opposé plus de dix, et
    minorait leur pension d'autant — étendre une moyenne aux années les plus
    faibles ne peut que l'abaisser.

    Le II donne les générations 1934 à 1947 et le plancher d'avant 1934 ; le I
    donne la cible et la première génération qu'elle vise, « nés après 1947 ».
    """
    table: dict[int, float] = {}
    for _, texte in sorted(versions)[-1:]:
        for lettres, en_annee, avant_annee in ANNEES_RETENUES.findall(texte):
            annees = nombre_en_lettres(lettres)
            if annees is None:
                continue
            generation = int(en_annee) if en_annee else PREMIERE_GENERATION
            table[generation] = float(annees)
        cible = ANNEES_CIBLE.search(texte)
        if cible is not None:
            annees = nombre_en_lettres(cible.group(1))
            if annees is not None:
                table[int(cible.group(2)) + 1] = float(annees)
    return table


def carriere_longue(versions: list[tuple[str, str]]) -> list[dict]:
    """Portes du départ anticipé — D. 351-1-1.

    Chaque porte associe un âge de départ à un âge de début d'activité : « A
    cinquante-huit ans pour les assurés […] ayant débuté leur activité avant
    l'âge de seize ans ». La condition de durée cotisée se lit dans le chapeau,
    en trimestres ajoutés à la durée requise.

    **Seules la RÈGLE GÉNÉRALE et la VERSION EN VIGUEUR sont lues.** La règle
    générale, c'est le texte qui précède le « II », où le décret loge ses
    adaptations transitoires génération par génération : les reprendre
    reviendrait à opposer à une même année de liquidation autant de portes qu'il
    y a de générations concernées, quand le modèle ne connaît que l'année de
    liquidation. La version en vigueur, parce que les rédactions successives se
    chevauchent — le décret de 2012 a été modifié six fois en onze ans, chaque
    modification ne portant que sur une génération — et qu'un dépouillement
    automatique ne saurait démêler la règle du transitoire sur ces versions-là.
    Les portes d'avant 2023 restent donc saisies, et confrontées à la main aux
    mêmes articles.
    """
    portes = []
    for entree_en_vigueur, texte in sorted(versions)[-1:]:
        general = re.split(r"\sII\s*\.?\s*-", texte, maxsplit=1)[0]
        supplement_chapeau = 0
        chapeau = re.split(r"\s1°\s", general, maxsplit=1)[0]
        trouve = re.search(r"major[ée]e?\s+de\s+(\w+)\s+trimestres", chapeau, re.I)
        if trouve:
            supplement_chapeau = nombre_en_lettres(trouve.group(1)) or 0
        for morceau in re.split(r";", general):
            trouve = PORTE.search(morceau)
            if trouve is None:
                continue
            annees = nombre_en_lettres(trouve.group(1))
            mois = nombre_en_lettres(trouve.group(2))
            age_debut = nombre_en_lettres(trouve.group(3))
            if annees is None or mois is None or age_debut is None:
                continue
            supplement = supplement_chapeau
            minoree = re.search(r"minor[ée]e?\s+de\s+(\w+)\s+trimestres", morceau, re.I)
            if minoree:
                supplement -= nombre_en_lettres(minoree.group(1)) or 0
            elif re.search(r"limite fixée en application|prévue au deuxième alinéa",
                           morceau, re.I):
                supplement = 0
            portes.append({
                "entree_en_vigueur": entree_en_vigueur,
                "age_debut_maximum": age_debut,
                "age_depart": round(annees + mois / 12.0, 2),
                "trimestres_supplementaires": max(0, supplement),
            })
    return portes


# ---------------------------------------------------------------------------
# Lecture du dump
# ---------------------------------------------------------------------------

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
        print(texte[:12000])
        sys.stdout.flush()
"""


class TransfertIncomplet(RuntimeError):
    """Le dump n'a pas été téléchargé en entier."""


def dernier_dump() -> str:
    with urllib.request.urlopen(RACINE, timeout=120) as reponse:
        page = reponse.read().decode("utf-8", errors="replace")
    noms = sorted(set(re.findall(r'href="(Freemium_legi_global_[^"]+\.tar\.gz)"', page)))
    if not noms:
        raise LookupError("aucun dump global dans le répertoire LEGI de la DILA")
    return RACINE + noms[-1]


def depouiller(url: str) -> dict[str, list[tuple[str, str]]]:
    """Versions datées de chaque article, filtrées sur le code qui le porte."""
    motif = "|".join(re.escape(a) for a in ARTICLES)
    lecture = subprocess.Popen(
        ["curl", "-sS", "--max-time", "7200", url], stdout=subprocess.PIPE
    )
    detar = subprocess.Popen(["tar", "-xzO"], stdin=lecture.stdout,
                             stdout=subprocess.PIPE)
    lecture.stdout.close()
    filtre = subprocess.Popen([sys.executable, "-c", FILTRE % motif],
                              stdin=detar.stdout, stdout=subprocess.PIPE)
    detar.stdout.close()

    trouvees: dict[str, list[tuple[str, str]]] = {a: [] for a in ARTICLES}
    article = debut = None
    for brut in filtre.stdout:
        ligne = brut.decode("utf-8", errors="replace").rstrip("\n")
        if ligne.startswith("@@@ "):
            _, article, debut = ligne.split(" ", 2)
            continue
        if article is None:
            continue
        code = re.search(r"AUTONOME (Code [^A-Z]*?) (Partie|Livre|Titre)", ligne)
        if code and ARTICLES[article] in code.group(1):
            trouvees[article].append((debut, ligne))
        article = None
    filtre.wait()
    # Un transfert coupé ne se voit pas dans ce qui a été lu : le dépouillement
    # rend moins de versions, et les garde-fous les trouvent bonnes — un dump à
    # moitié lu n'a pas de trou, il a une fin prématurée.
    if lecture.wait() != 0:
        raise TransfertIncomplet(
            f"curl s'est interrompu (code {lecture.returncode}) : le dump n'a "
            "pas été lu en entier")
    return trouvees


def main() -> int:
    try:
        url = dernier_dump()
    except (urllib.error.HTTPError, urllib.error.URLError, LookupError) as erreur:
        print(f"Base LEGI indisponible : {erreur}", file=sys.stderr)
        return 1

    print(f"Dump    {url}")
    print("Lecture en flux d'environ 9 Go décompressés : comptez un quart d'heure.\n")
    try:
        versions = depouiller(url)
    except TransfertIncomplet as erreur:
        print(f"\nÉCHEC   {erreur}", file=sys.stderr)
        return 1
    for article, trouvees in versions.items():
        print(f"  {article:12} {len(trouvees):3} version(s) au {ARTICLES[article]}")
    if not all(versions.values()):
        print("\nÉCHEC   un article n'a pas été trouvé dans le dump", file=sys.stderr)
        return 1

    tables = {
        "age_ouverture": age_ouverture(versions["D161-2-1-9"]),
        "duree_requise": duree_requise(versions["L161-17-3"]),
        "duree_requise_1993": duree_requise_1993(versions["R351-45"]),
        "coefficient_minoration": coefficient_minoration(versions["R351-27"]),
        "carriere_longue": carriere_longue(versions["D351-1-1"]),
        "duree_proratisation": duree_proratisation(versions["R351-6"]),
        "heures_par_trimestre": heures_par_trimestre(versions["R351-9"]),
        "annees_salaire_reference": annees_salaire_reference(versions["R351-29-1"]),
    }

    # Garde-fous : une table lue de travers ne doit pas s'écrire en silence.
    ages = tables["age_ouverture"]
    if not (ages and min(ages.values()) >= 60.0 and max(ages.values()) == 64.0):
        print(f"\nÉCHEC   âges d'ouverture invraisemblables : "
              f"{sorted(set(ages.values()))}", file=sys.stderr)
        return 1
    durees = tables["duree_requise"]
    if not (durees and max(durees.values()) == 172.0):
        print(f"\nÉCHEC   durées requises invraisemblables : "
              f"{sorted(set(durees.values()))}", file=sys.stderr)
        return 1
    coefficients = tables["coefficient_minoration"]
    if not (coefficients and max(coefficients.values()) == 0.025
            and min(coefficients.values()) == 0.0125):
        print(f"\nÉCHEC   coefficients invraisemblables : "
              f"{sorted(set(coefficients.values()))}", file=sys.stderr)
        return 1

    # La montée en charge de 1993 : un trimestre par génération, de 151 à 159.
    # Une table qui ne serait pas cette suite-là est lue de travers.
    montee = tables["duree_requise_1993"]
    attendue = {annee: 151.0 + annee - 1934
                for annee in range(GENERATIONS_1993[0], GENERATIONS_1993[1] + 1)}
    if montee != attendue:
        print(f"\nÉCHEC   montée en charge de 1993 invraisemblable : "
              f"{sorted(montee.items())}", file=sys.stderr)
        return 1

    proratisation = tables["duree_proratisation"]
    if not (proratisation and min(proratisation.values()) == 150.0
            and max(proratisation.values()) == 158.0):
        print(f"\nÉCHEC   durées de proratisation invraisemblables : "
              f"{sorted(set(proratisation.values()))}", file=sys.stderr)
        return 1
    annees_salaire = tables["annees_salaire_reference"]
    if not (annees_salaire and min(annees_salaire.values()) == 10.0
            and max(annees_salaire.values()) == 25.0):
        print(f"\nÉCHEC   années du salaire de référence invraisemblables : "
              f"{sorted(set(annees_salaire.values()))}", file=sys.stderr)
        return 1
    heures = tables["heures_par_trimestre"]
    if sorted(heures.items()) != [(1972, 200.0), (2014, 150.0)]:
        print(f"\nÉCHEC   assiette du trimestre invraisemblable : "
              f"{sorted(heures.items())}", file=sys.stderr)
        return 1

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(
        json.dumps({
            "source": url,
            "articles": ARTICLES,
            "recupere_le": date.today().isoformat(),
            "note": "tables par génération lues dans le texte des articles, "
                    "une génération coupée en cours d'année étant rendue en "
                    "deux segments — la clé porte alors le mois de la coupure, "
                    "1951.5 pour le 1er juillet 1951 — et deux alinéas qui se "
                    "recouvrent étant départagés par la valeur la plus "
                    "exigeante",
            "serie": {
                f"{nom}|{cle}": valeur
                for nom in ("age_ouverture", "duree_requise",
                            "duree_requise_1993",
                            "coefficient_minoration", "duree_proratisation",
                            "heures_par_trimestre", "annees_salaire_reference")
                for cle, valeur in tables[nom].items()
            },
            "carriere_longue": tables["carriere_longue"],
        }, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )

    print(f"\nÂge d'ouverture        {len(ages)} segments, "
          f"{min(ages.values()):g} -> {max(ages.values()):g} ans")
    print(f"Durée requise          {len(durees)} segments, "
          f"{min(durees.values()):g} -> {max(durees.values()):g} trimestres")
    print(f"Coefficient minoration {len(coefficients)} segments, "
          f"{max(coefficients.values()):.3%} -> {min(coefficients.values()):.3%}")
    print(f"Carrière longue        {len(tables['carriere_longue'])} portes")
    print(f"Montée en charge 1993  {len(montee)} générations, "
          f"{min(montee.values()):g} -> {max(montee.values()):g} trimestres")
    print(f"Durée proratisation    {len(proratisation)} segments, "
          f"{min(proratisation.values()):g} -> {max(proratisation.values()):g} "
          f"trimestres")
    print(f"Années salaire réf.    {len(annees_salaire)} générations, "
          f"{min(annees_salaire.values()):g} -> {max(annees_salaire.values()):g} années")
    print(f"Assiette du trimestre  "
          + ", ".join(f"{heure:g} heures depuis {annee}"
                      for annee, heure in sorted(heures.items())))
    print(f"Écrit dans {SORTIE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
