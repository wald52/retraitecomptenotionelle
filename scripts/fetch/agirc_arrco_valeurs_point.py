#!/usr/bin/env python3
"""Valeurs du point Agirc-Arrco, publiées par la fédération elle-même.

    pip install pypdf
    python scripts/fetch/agirc_arrco_valeurs_point.py

À quoi elles servent. La pension complémentaire est calculée EN POINTS : la
cotisation d'une année divisée par la valeur d'achat donne les points acquis,
que la valeur de service convertit en rente. Sans ces deux barèmes pour une
année, le modèle retombe sur un rendement instantané — une approximation qui
n'est pas le calcul du régime.

POURQUOI UNE SOURCE DE PLUS. Ces valeurs venaient d'OpenFisca-France-Pension,
c'est-à-dire d'une transcription, plafonnée au niveau ``haute``. Or la fédération
publie elle-même, chaque année, l'historique complet de ses deux barèmes : c'est
le PRODUCTEUR de la donnée. Le dépôt applique déjà cette règle à l'Ircantec, dont
les barèmes viennent de la Caisse des dépôts qui la gère, et dont les lignes sont
retirées de la couverture d'OpenFisca — deux contrôles ne doivent pas se disputer
les mêmes lignes.

Et la transcription était en retard : elle s'arrête à 2025, alors que la
fédération publie déjà la valeur d'achat de 2026. Faute de ce barème, les
cotisations de 2026 retombaient sur le rendement instantané, ce qui SUR-ESTIME
la pension Agirc-Arrco de 1,7 % et le total de 0,6 % pour une liquidation en
2026 — c'est-à-dire dans l'année où le site simule par défaut.

DEUX NIVEAUX, PARCE QUE L'ANNÉE EN COURS N'EST PAS CLOSE. La fédération publie
la valeur d'achat par ANNÉE CIVILE — celle de 2026 est connue et gelée à
20,1877 € — mais la valeur de service par DATE D'EFFET, au 1er novembre. La règle
de ce dépôt retient la valeur en vigueur au 31 décembre : celle de l'année en
cours dépend donc d'une décision de novembre qui n'est pas encore prise.

Ne rien écrire n'était pas neutre pour autant. Faute de barème, le modèle
prolongeait la dernière valeur PAR LES PRIX : il servait 1,46378 € pour 2026,
c'est-à-dire une revalorisation de +1,75 % que personne n'a décidée, là où la
fédération publie un gel à 1,4386 € jusqu'au 1er novembre 2026. Entre inventer
une décision et reconduire celle qui est en vigueur, la seconde est la seule qui
ait une source.

Ce récupérateur écrit donc les deux, séparément : les valeurs arrêtées, versées
au niveau `certifiee`, et **la valeur de service en vigueur dans l'année en
cours**, versée au niveau `haute` — elle est publiée et opposable, mais la
décision de novembre peut encore la déplacer avant le 31 décembre.
`docs/limites.md` le dit aussi.

LES TABLES D'AVANT LA FUSION SONT DANS LE MÊME DOCUMENT, et elles y sont
désormais lues. Cette page écrivait qu'elles étaient « sous une présentation
différente et avec des conventions de date qui leur sont propres », et les
laissait transcrites d'OpenFisca. La présentation diffère en effet — une ligne
par année, une ou deux valeurs de point selon que le barème a bougé en cours
d'année, des francs jusqu'en 2001 et des anciens francs jusqu'en 1959 — mais
rien de tout cela n'est une raison de préférer une transcription au producteur.

Trois tables sont reprises, et une quatrième laissée de côté :

* **Agirc, 1947-2018** — valeur du point et salaire de référence, 144 valeurs ;
* **Arrco, 1999-2018** — le régime unifié des caisses Arrco, 40 valeurs ;
* **Unirs, 1961-1998** — la plus grosse caisse Arrco, dont le barème tient lieu
  de point Arrco avant l'unification de 1999. Ses valeurs sont certifiées comme
  celles de l'UNIRS ; les lignes `arrco` qui les reprennent restent au niveau
  `moyenne`, parce que la SUBSTITUTION, elle, est une décision de modélisation
  et non un fait publié ;
* la **série reconstituée du salaire de référence Arrco depuis 1948**, que la
  fédération publie aussi, n'est pas reprise : elle ne porte que le salaire de
  référence, sans la valeur de service qui lui correspond, et un rendement ne
  se calcule pas avec deux barèmes qui ne parlent pas du même point — 68,11 F
  en 1998 pour l'Arrco reconstituée contre 26,43 F pour l'UNIRS.

DEUX CONTRÔLES AUTORISENT CETTE LECTURE, et ils portent sur ce que le document
publie en regard de chaque valeur : son évolution en pourcentage. Le script
recalcule cette évolution depuis les valeurs qu'il vient de lire — celle du
salaire de référence d'une année sur l'autre, celle de chaque valeur de point
sur la précédente — et refuse d'écrire si l'écart dépasse un dixième de point.
Ce contrôle vaut aussi bien pour les changements de monnaie : de 1959 à 1960,
142,00 anciens francs et 1,52 nouveau franc donnent les 7,04 % publiés, ce
qu'une conversion fautive ne rendrait pas.

CE QUE LA CONFRONTATION A DONNÉ. Les 260 valeurs transcrites d'OpenFisca sont
confirmées par le producteur, au centième de centime près : l'écart maximal est
de 5 · 10⁻⁵ €, et il vient de ce que la transcription arrondissait la
conversion en euros à quatre décimales quand le document donne le franc exact.
C'est une confirmation, pas une correction — et c'est le contraire d'un
non-événement : ces barèmes pèsent, dans la pension d'un salarié du privé, plus
lourd que tous les autres réunis.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

#: Compilation publiée par la fédération. L'adresse porte le millésime de la
#: revalorisation : à reprendre chaque automne.
URL = ("https://www.agirc-arrco.fr/storage/2024/10/"
       "Compilation_valeurs_de_point_novembre_2025.pdf")

SORTIE = Path("data/brut/agirc_arrco_valeurs_point.json")
ENTETES = {"User-Agent": "retraite-notionnelle/0.1 (recherche publique)"}

#: Le régime unifié n'existe pas avant cette date.
PREMIERE_ANNEE = 2019

#: Le document empile ses tableaux : le régime unifié d'abord, puis l'Agirc,
#: l'Arrco et les caisses d'avant la fusion. Le premier s'arrête à cet
#: intertitre ; les autres sont lus page par page, à leur intitulé.
FIN_DU_TABLEAU = "Agirc-Arrco - Valeurs de service"

#: Parité irrévocable du franc et de l'euro, fixée le 31 décembre 1998. Elle
#: n'est pas un taux de change : c'est une définition, et la conversion d'un
#: montant en francs est exacte.
FRANC = 6.55957

#: Le nouveau franc vaut cent anciens francs depuis le 1er janvier 1960. Le
#: document le dit en note et ses colonnes le confirment : 142,00 F en 1959,
#: 1,52 NF en 1960 — soit la hausse de 7,04 % qu'il publie en regard.
DERNIER_ANCIEN_FRANC = 1959
#: Dernière année écrite en francs : l'euro prend la suite au 1er janvier 2002.
DERNIER_FRANC = 2001

#: Les tables d'avant la fusion : intitulé dans le document, couverture
#: attendue, et si la monnaie y est écrite en toutes lettres. Une table qui ne
#: commence ou ne finit plus où elle le devrait signale une refonte du document,
#: pas une valeur de plus : le script s'arrête alors, plutôt que d'écrire une
#: série tronquée sans le dire.
TABLES_HISTORIQUES: dict[str, tuple[str, int, int, bool]] = {
    "agirc": ("Agirc", 1947, 2018, True),
    "arrco": ("Arrco", 1999, 2018, True),
    "unirs": ("Unirs", 1961, 1998, False),
}

#: Écart toléré entre l'évolution que le document publie en regard d'une valeur
#: et celle que le script recalcule depuis les valeurs qu'il vient de lire. Un
#: dixième de point : le document arrondit ses pourcentages au centième, et
#: parfois au dixième.
ECART_EVOLUTION = 0.001

#: Rendement instantané admissible pour un régime en points — valeur de service
#: divisée par le salaire de référence. Large à dessein : il ne s'agit pas de
#: juger un barème mais d'attraper une colonne lue de travers. Les régimes des
#: années 1950 servaient couramment plus de 15 %.
RENDEMENT_PLAUSIBLE = (0.02, 0.30)

#: L'intitulé d'une table historique, tel que le document le porte : le nom de
#: la caisse, un tiret, puis le titre. C'est lui qui dit à quelle caisse une
#: page appartient — l'ordre du document ne le dit pas, la légende étant
#: imprimée après le tableau qu'elle nomme.
INTITULE = re.compile(r"^(.+?)\n-\nValeurs de point et salaires de référence", re.M)

#: Une ligne de tableau commence par son année.
LIGNE = re.compile(r"^\s*(19\d\d|20\d\d)\b(.*)$")

#: Dans les tables où la monnaie est écrite, un jeton est un montant ou un
#: pourcentage d'évolution — et leur ALTERNANCE porte le sens : chaque
#: pourcentage se rapporte au montant qui le précède.
JETON = re.compile(
    r"(?P<montant>\d{1,3}(?: \d{3})*,\d+)\s*(?:NF|F|€)"
    r"|(?P<taux>\d{1,3},\d+)\s*%"
)

#: Dans les tables des caisses, la monnaie n'est pas écrite : une ligne y est
#: une suite de cinq nombres — deux valeurs de point, leur évolution, le
#: salaire de référence, la sienne — dont les manquants sont des tirets.
NOMBRE = re.compile(r"(?<![\d,])(\d{1,3},\d+|-)(?![\d,])")


def telecharger(url: str) -> bytes:
    requete = urllib.request.Request(url, headers=ENTETES)
    with urllib.request.urlopen(requete, timeout=180) as reponse:
        return reponse.read()


def pages_du_pdf(pdf: bytes) -> list[str]:
    """Texte de chaque page, séparément.

    Les tables historiques sont à raison d'une caisse par page, et chacune
    porte son intitulé : c'est en gardant les pages séparées qu'on sait à qui
    appartient une ligne.
    """
    import io

    from pypdf import PdfReader

    return [page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages]


def texte_du_pdf(pdf: bytes) -> str:
    return re.sub(r"\s+", " ", "\n".join(pages_du_pdf(pdf)))


def annees_dune_page(page: str) -> set[int]:
    """Années qui ouvrent une ligne de tableau, sur cette page."""
    return {int(datee.group(1)) for datee in map(LIGNE.match, page.splitlines())
            if datee is not None}


def table_de(intitule: str, pages: list[str]) -> str:
    """Pages d'une caisse : celle qui porte son intitulé, et ses suites.

    Une table longue déborde sur la page suivante, qui ne porte alors aucun
    intitulé — celle de l'Agirc va de 2018 à 1990 sur sa première page et de
    1983 à 1947 sur la seconde. Une page sans intitulé continue donc la
    précédente ; une page qui en porte un autre ferme la table.

    Une page sans intitulé n'est pas pour autant une suite : après le tableau de
    l'Arrco vient sa « série reconstituée du salaire de référence », qui n'en
    porte pas et redonne les MÊMES années. C'est à cela qu'on la reconnaît — une
    suite ne revient jamais sur une année déjà lue.
    """
    morceaux: list[str] = []
    vues: set[int] = set()
    for page in pages:
        nom = INTITULE.search(page)
        if nom is not None:
            if nom.group(1).strip().casefold() != intitule.casefold():
                if morceaux:
                    break        # l'intitulé d'une autre caisse ferme la table
                continue         # avant la nôtre
        elif not morceaux:
            continue             # une page sans intitulé, avant la table
        annees = annees_dune_page(page)
        if morceaux and (not annees or annees & vues):
            break                # une année déjà lue : ce n'est pas une suite
        morceaux.append(page)
        vues |= annees
    return "\n".join(morceaux)


def en_euros(montant: float, annee: int) -> float:
    """Montant de l'année, converti à la parité irrévocable."""
    if annee <= DERNIER_ANCIEN_FRANC:
        return montant / 100 / FRANC
    if annee <= DERNIER_FRANC:
        return montant / FRANC
    return montant


def _jetons(texte: str) -> list[tuple[str, float]]:
    jetons = []
    for jeton in JETON.finditer(texte):
        if jeton.group("montant"):
            jetons.append(
                ("montant", float(jeton.group("montant").replace(" ", "").replace(",", ".")))
            )
        else:
            jetons.append(("taux", float(jeton.group("taux").replace(",", ".")) / 100))
    return jetons


def _depouiller(jetons: list[tuple[str, float]]) -> tuple[list[tuple[float, float | None]],
                                                          float, float | None]:
    """Valeurs de point avec leur évolution, salaire de référence avec la sienne.

    Le DERNIER montant d'une ligne est le salaire de référence ; ceux qui le
    précèdent sont les valeurs successives du point dans l'année — une seule
    quand le barème n'a pas bougé, deux quand il a été relevé en cours d'année.
    Le pourcentage qui suit immédiatement un montant est son évolution ; celui
    qui suit un pourcentage est l'évolution en moyenne annuelle, dont le script
    n'a rien à faire.
    """
    rangs = [rang for rang, (genre, _) in enumerate(jetons) if genre == "montant"]
    dernier = rangs[-1]
    apres = jetons[dernier + 1] if dernier + 1 < len(jetons) else None
    points = []
    for rang in rangs[:-1]:
        suivant = jetons[rang + 1]
        points.append((jetons[rang][1], suivant[1] if suivant[0] == "taux" else None))
    return points, jetons[dernier][1], apres[1] if apres and apres[0] == "taux" else None


def lignes_avec_monnaie(texte: str) -> dict[int, list[tuple[str, float]]]:
    """Jetons de chaque année, dans les tables où la monnaie est écrite.

    Une ligne SANS année qui suit une ligne datée en est la suivante dans
    l'ordre du tableau, lequel descend : c'est le cas de 1999 à l'Arrco, dont
    l'année est imprimée à part, sous le tableau. Le contrôle des évolutions
    tranche : si la ligne était mal rattachée, la hausse publiée pour l'année
    d'après ne se retrouverait pas.
    """
    lignes: dict[int, list[tuple[str, float]]] = {}
    derniere: int | None = None
    for ligne in texte.splitlines():
        datee = LIGNE.match(ligne)
        if datee is not None:
            jetons = _jetons(datee.group(2))
            if any(genre == "montant" for genre, _ in jetons):
                derniere = int(datee.group(1))
                lignes[derniere] = jetons
            continue
        jetons = _jetons(ligne)
        montants = [genre for genre, _ in jetons].count("montant")
        if derniere is not None and montants >= 2 and derniere - 1 not in lignes:
            derniere -= 1
            lignes[derniere] = jetons
    return lignes


def table_avec_monnaie(texte: str) -> tuple[dict[tuple[int, str], float], list[str]]:
    """Valeur de point et salaire de référence par année, contrôle compris.

    Deux règles de lecture, et une seule convention de date : la valeur retenue
    pour une année est celle en vigueur au 31 DÉCEMBRE, donc la dernière que la
    ligne porte. Une année dont la ligne ne porte aucune valeur de point est une
    année sans décision : la valeur de l'année précédente y reste en vigueur.
    """
    lignes = lignes_avec_monnaie(texte)
    valeurs: dict[tuple[int, str], float] = {}
    griefs: list[str] = []
    precedent_point: float | None = None
    precedent_salaire: float | None = None
    for annee in sorted(lignes):
        points, salaire, taux_salaire = _depouiller(lignes[annee])
        for montant, taux in points:
            valeur = en_euros(montant, annee)
            if taux is not None and precedent_point:
                calculee = valeur / precedent_point - 1
                if abs(calculee - taux) > ECART_EVOLUTION:
                    griefs.append(
                        f"{annee} : valeur de point {montant}, hausse publiée "
                        f"{taux:.2%}, recalculée {calculee:.2%}"
                    )
            precedent_point = valeur
        if precedent_point is None:
            griefs.append(f"{annee} : aucune valeur de point, et aucune avant elle")
            continue
        valeurs[(annee, "valeur_service")] = precedent_point
        salaire_euros = en_euros(salaire, annee)
        if taux_salaire is not None and precedent_salaire:
            calculee = salaire_euros / precedent_salaire - 1
            if abs(calculee - taux_salaire) > ECART_EVOLUTION:
                griefs.append(
                    f"{annee} : salaire de référence {salaire}, hausse publiée "
                    f"{taux_salaire:.2%}, recalculée {calculee:.2%}"
                )
        precedent_salaire = salaire_euros
        valeurs[(annee, "salaire_reference")] = salaire_euros
    return valeurs, griefs


def table_sans_monnaie(texte: str) -> tuple[dict[tuple[int, str], float], list[str]]:
    """Table d'une caisse : cinq nombres par ligne, en francs, sans monnaie écrite.

    Deux valeurs de point — celle du début d'année et celle de la décision qui
    l'a relevée —, leur évolution, le salaire de référence et la sienne. Les
    valeurs manquantes sont des tirets : une année sans relèvement n'a qu'une
    valeur, et c'est elle qui vaut au 31 décembre.

    Seule l'évolution du salaire de référence est recontrôlée. Celle du point
    ne l'est pas, et le document dit pourquoi : elle est « calculée par rapport
    aux valeurs moyennes des exercices », non d'une valeur à l'autre.
    """
    valeurs: dict[tuple[int, str], float] = {}
    publiees: dict[int, float] = {}
    griefs: list[str] = []
    for ligne in texte.splitlines():
        datee = LIGNE.match(ligne)
        if datee is None:
            continue
        annee = int(datee.group(1))
        jetons = NOMBRE.findall(datee.group(2))
        if len(jetons) != 5:
            continue
        debut, releve, _, salaire, taux_salaire = [
            None if jeton == "-" else float(jeton.replace(",", ".")) for jeton in jetons
        ]
        point = releve if releve is not None else debut
        if point is None or salaire is None:
            griefs.append(f"{annee} : ligne sans valeur de point ou sans salaire")
            continue
        valeurs[(annee, "valeur_service")] = en_euros(point, annee)
        valeurs[(annee, "salaire_reference")] = en_euros(salaire, annee)
        if taux_salaire is not None:
            publiees[annee] = taux_salaire / 100

    for annee, publiee in sorted(publiees.items()):
        precedent = valeurs.get((annee - 1, "salaire_reference"))
        if not precedent:
            continue
        calculee = valeurs[(annee, "salaire_reference")] / precedent - 1
        if abs(calculee - publiee) > ECART_EVOLUTION:
            griefs.append(
                f"{annee} : salaire de référence, hausse publiée "
                f"{publiee:.2%}, recalculée {calculee:.2%}"
            )
    return valeurs, griefs


def tables_historiques(pages: list[str]) -> tuple[dict[str, float], list[str]]:
    """Les barèmes d'avant la fusion, régime par régime, avec leurs griefs."""
    serie: dict[str, float] = {}
    griefs: list[str] = []
    for regime, (intitule, premiere, derniere, monnaie) in TABLES_HISTORIQUES.items():
        texte = table_de(intitule, pages)
        if not texte:
            griefs.append(f"{regime} : le tableau « {intitule} » est introuvable")
            continue
        valeurs, ecarts = (table_avec_monnaie(texte) if monnaie
                           else table_sans_monnaie(texte))
        griefs.extend(f"{regime} : {ecart}" for ecart in ecarts)
        annees = sorted({annee for annee, _ in valeurs})
        if not annees or (annees[0], annees[-1]) != (premiere, derniere):
            griefs.append(
                f"{regime} : la table couvre "
                f"{annees[0] if annees else '—'}-{annees[-1] if annees else '—'}, "
                f"et non {premiere}-{derniere}"
            )
            continue
        if annees != list(range(premiere, derniere + 1)):
            griefs.append(f"{regime} : la suite des années a des trous")
        for annee in annees:
            service = valeurs[(annee, "valeur_service")]
            achat = valeurs[(annee, "salaire_reference")]
            rendement = service / achat
            if not RENDEMENT_PLAUSIBLE[0] < rendement < RENDEMENT_PLAUSIBLE[1]:
                griefs.append(
                    f"{regime} {annee} : rendement de {rendement:.2%}, hors de la "
                    "plage plausible — une colonne est lue de travers"
                )
            serie[f"{regime}|{annee}|valeur_service"] = service
            serie[f"{regime}|{annee}|salaire_reference"] = achat
    return serie, griefs


def valeurs_de_service(tete: str) -> dict[int, float]:
    """Valeur de service par année, au sens du dépôt : celle du 31 décembre.

    La fédération publie par DATE D'EFFET — « à compter du 1er novembre 2024 ».
    Comme le 1er novembre précède le 31 décembre, la valeur d'une année est
    celle que sa propre décision de novembre a fixée. L'année en cours n'a donc
    de valeur que lorsque cette décision est prise.
    """
    par_annee: dict[int, float] = {}
    for mois, annee, montant in re.findall(
        r"A compter du 1er (\w+) (\d{4}) (\d,\d+)\s*€", tete
    ):
        annee = int(annee)
        valeur = float(montant.replace(",", "."))
        # Une décision de janvier est remplacée dans l'année par celle de
        # novembre : c'est cette dernière qui vaut au 31 décembre. La création
        # du régime, au 1er janvier 2019, est le seul cas où les deux coexistent.
        if mois == "novembre" or annee not in par_annee:
            par_annee[annee] = valeur
        if mois == "novembre":
            par_annee[annee] = valeur
    return par_annee


def valeurs_d_achat(tete: str) -> dict[int, float]:
    """Valeur d'achat du point, que la fédération publie par ANNÉE CIVILE."""
    depart = tete.find("Valeur d'achat du point")
    if depart < 0:
        return {}
    return {
        int(annee): float(montant.replace(",", "."))
        for annee, montant in re.findall(
            r"\b(20\d\d) (\d{1,2},\d+)\s*€", tete[depart:]
        )
    }


def controler(service: dict[int, float], achat: dict[int, float]) -> list[str]:
    """Ce que les deux barèmes doivent vérifier pour être crédibles."""
    griefs = []
    if not service or not achat:
        return ["aucun barème lu — la présentation du document a changé"]
    for nom, table in (("valeur de service", service), ("valeur d'achat", achat)):
        annees = sorted(table)
        if annees[0] != PREMIERE_ANNEE:
            griefs.append(
                f"{nom} : la série commence en {annees[0]}, or le régime unifié "
                f"naît en {PREMIERE_ANNEE}"
            )
        if annees != list(range(annees[0], annees[-1] + 1)):
            griefs.append(f"{nom} : la suite des années a des trous")
        if min(table.values()) <= 0:
            griefs.append(f"{nom} : une valeur nulle ou négative")
    # Le rendement instantané que le régime publie — valeur de service divisée
    # par le produit de la valeur d'achat et du taux d'appel de 127 % — vaut
    # 5,61 % en 2025. Un barème lu de travers le ferait sortir de sa plage.
    for annee in sorted(set(service) & set(achat)):
        rendement = service[annee] / (achat[annee] * 1.27)
        if not 0.04 < rendement < 0.07:
            griefs.append(
                f"{annee} : rendement instantané de {rendement:.2%}, hors de la "
                "plage plausible — un des deux barèmes est lu de travers"
            )
    return griefs


def main(argv: list[str] | None = None) -> int:
    try:
        import pypdf  # noqa: F401
    except ImportError:
        print(
            "pypdf n'est pas installé — la compilation est un PDF.\n"
            "    pip install pypdf\n"
            "Il n'est PAS une dépendance du dépôt : les valeurs promues dans "
            "data/reference/ sont versionnées, et le modèle s'en contente.",
            file=sys.stderr,
        )
        return 1
    try:
        pages = pages_du_pdf(telecharger(URL))
    except (urllib.error.URLError, TimeoutError) as erreur:
        print(f"échec du téléchargement : {erreur}", file=sys.stderr)
        return 1

    texte = re.sub(r"\s+", " ", "\n".join(pages))
    coupe = texte.find(FIN_DU_TABLEAU)
    tete = texte if coupe < 0 else texte[:coupe]
    service = valeurs_de_service(tete)
    achat = valeurs_d_achat(tete)
    historiques, griefs_historiques = tables_historiques(pages)
    griefs = controler(service, achat) + griefs_historiques
    if griefs:
        for grief in griefs:
            print(f"agirc_arrco : {grief}", file=sys.stderr)
        return 1

    serie = {f"agirc_arrco|{annee}|valeur_service": valeur
             for annee, valeur in sorted(service.items())}
    serie |= {f"agirc_arrco|{annee}|salaire_reference": valeur
              for annee, valeur in sorted(achat.items())}
    serie |= historiques

    # L'année qui suit la dernière décision de novembre : sa valeur de service
    # est celle-là, en vigueur depuis le 1er janvier, jusqu'à la décision de
    # novembre suivante. Publiée et opposable, mais pas encore arrêtée au
    # 31 décembre — d'où un niveau en retrait.
    en_cours = max(service) + 1
    serie_en_cours = {
        f"agirc_arrco|{en_cours}|valeur_service": service[max(service)]
    }

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(
        json.dumps(
            {
                "source": URL,
                "recupere_le": date.today().isoformat(),
                "producteur": (
                    "Fédération Agirc-Arrco, qui fixe et publie ces barèmes — "
                    "ceux du régime unifié comme ceux de l'Agirc, de l'Arrco et "
                    "des caisses d'avant la fusion. C'est le producteur de la "
                    "donnée, non une transcription."
                ),
                "regle_annuelle": (
                    "Valeur en vigueur au 31 décembre. La valeur d'achat est "
                    "publiée par année civile ; la valeur de service par date "
                    "d'effet, au 1er novembre — l'année en cours n'en a donc une "
                    "que lorsque la décision de novembre est prise."
                ),
                "serie": dict(sorted(serie.items())),
                "serie_en_cours": dict(sorted(serie_en_cours.items())),
            },
            ensure_ascii=False, indent=2, sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    couverture = ", ".join(
        f"{regime} {premiere}-{derniere}"
        for regime, (_, premiere, derniere, _) in TABLES_HISTORIQUES.items()
    )
    print(
        f"{SORTIE} : {len(serie)} valeurs arrêtées — régime unifié, service "
        f"{min(service)}-{max(service)} et achat {min(achat)}-{max(achat)} ; "
        f"tables d'avant la fusion, {couverture} ; valeur de service en vigueur "
        f"en {en_cours} reconduite à {service[max(service)]} €"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
