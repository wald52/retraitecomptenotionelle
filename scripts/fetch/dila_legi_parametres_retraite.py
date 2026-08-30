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
  de seize ans ».

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
à une date — le 1er juillet 1951, le 1er septembre 1961. Le modèle ne connaît
que l'année de naissance : il retient la valeur qui couvre le plus grand nombre
de mois, et, à égalité, la plus exigeante. C'est la convention qu'annonçaient
déjà les fichiers, appliquée ici au texte plutôt qu'à la main.
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
}

#: Nombres écrits en lettres, tels que le Journal officiel les emploie pour les
#: âges. Au-delà de soixante-neuf, la retraite n'a plus de barème.
MOTS = {
    "un": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6,
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


def _mois_couverts(alinea: str) -> dict[int, int]:
    """Nombre de mois de chaque génération que cet alinéa vise.

    Une génération pleine compte douze mois ; une génération coupée en compte
    autant que la période en couvre. C'est ce décompte qui départage, ensuite,
    deux valeurs opposées à une même année de naissance.
    """
    couverts: dict[int, int] = {}

    def ajouter(annee: int, mois: int) -> None:
        if PREMIERE_GENERATION <= annee <= DERNIERE_GENERATION and mois > 0:
            couverts[annee] = couverts.get(annee, 0) + mois

    trouve = ENTRE.search(alinea)
    if trouve:
        j1, m1, a1, j2, m2, a2 = trouve.groups()
        debut_mois, fin_mois = MOIS.get(m1.lower()), MOIS.get(m2.lower())
        if debut_mois is None or fin_mois is None:
            return {}
        for annee in range(int(a1), int(a2) + 1):
            premier = debut_mois if annee == int(a1) else 1
            dernier = fin_mois if annee == int(a2) else 12
            ajouter(annee, dernier - premier + 1)
        return couverts

    trouve = AVANT.search(alinea)
    if trouve:
        _, mois, annee = trouve.groups()
        borne = MOIS.get(mois.lower())
        if borne is None:
            return {}
        for a in range(PREMIERE_GENERATION, int(annee)):
            ajouter(a, 12)
        ajouter(int(annee), borne - 1)
        return couverts

    trouve = A_COMPTER.search(alinea)
    if trouve:
        _, mois, annee = trouve.groups()
        borne = MOIS.get(mois.lower())
        if borne is None:
            return {}
        ajouter(int(annee), 12 - borne + 1)
        for a in range(int(annee) + 1, DERNIERE_GENERATION + 1):
            ajouter(a, 12)
        return couverts

    trouve = APRES_ANNEE.search(alinea)
    if trouve:
        for a in range(int(trouve.group(1)) + 1, DERNIERE_GENERATION + 1):
            ajouter(a, 12)
        return couverts

    trouve = EN_ANNEE.search(alinea)
    if trouve:
        ajouter(int(trouve.group(1)), 12)
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
    valeurs: dict[int, float] = {}
    for _, texte in sorted(versions):
        valeurs.update(lire(texte))
    return valeurs


def table_par_generation(alineas: list[tuple[float, str]]) -> dict[int, float]:
    """Valeur opposable à chaque génération, la plus couvrante l'emportant.

    À égalité de couverture — une génération coupée en son milieu, comme 1951 —
    c'est la valeur la PLUS EXIGEANTE qui est retenue : le modèle ne prête
    jamais à personne le régime le plus favorable quand il ne sait pas trancher.
    """
    poids: dict[int, dict[float, int]] = {}
    for valeur, alinea in alineas:
        for annee, mois in _mois_couverts(alinea).items():
            poids.setdefault(annee, {})
            poids[annee][valeur] = poids[annee].get(valeur, 0) + mois
    return {
        annee: max(valeurs, key=lambda v: (valeurs[v], v))
        for annee, valeurs in sorted(poids.items())
    }


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
    return trouvees


def main() -> int:
    try:
        url = dernier_dump()
    except (urllib.error.HTTPError, urllib.error.URLError, LookupError) as erreur:
        print(f"Base LEGI indisponible : {erreur}", file=sys.stderr)
        return 1

    print(f"Dump    {url}")
    print("Lecture en flux d'environ 9 Go décompressés : comptez un quart d'heure.\n")
    versions = depouiller(url)
    for article, trouvees in versions.items():
        print(f"  {article:12} {len(trouvees):3} version(s) au {ARTICLES[article]}")
    if not all(versions.values()):
        print("\nÉCHEC   un article n'a pas été trouvé dans le dump", file=sys.stderr)
        return 1

    tables = {
        "age_ouverture": age_ouverture(versions["D161-2-1-9"]),
        "duree_requise": duree_requise(versions["L161-17-3"]),
        "coefficient_minoration": coefficient_minoration(versions["R351-27"]),
        "carriere_longue": carriere_longue(versions["D351-1-1"]),
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

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(
        json.dumps({
            "source": url,
            "articles": ARTICLES,
            "recupere_le": date.today().isoformat(),
            "note": "tables par génération lues dans le texte des articles, "
                    "une génération coupée en cours d'année étant attribuée à "
                    "la valeur qui couvre le plus de mois, et à la plus "
                    "exigeante en cas d'égalité",
            "serie": {
                f"{nom}|{cle}": valeur
                for nom in ("age_ouverture", "duree_requise",
                            "coefficient_minoration")
                for cle, valeur in tables[nom].items()
            },
            "carriere_longue": tables["carriere_longue"],
        }, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )

    print(f"\nÂge d'ouverture        {len(ages)} générations, "
          f"{min(ages.values()):g} -> {max(ages.values()):g} ans")
    print(f"Durée requise          {len(durees)} générations, "
          f"{min(durees.values()):g} -> {max(durees.values()):g} trimestres")
    print(f"Coefficient minoration {len(coefficients)} générations, "
          f"{max(coefficients.values()):.3%} -> {min(coefficients.values()):.3%}")
    print(f"Carrière longue        {len(tables['carriere_longue'])} portes")
    print(f"Écrit dans {SORTIE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
