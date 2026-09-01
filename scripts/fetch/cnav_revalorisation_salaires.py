#!/usr/bin/env python3
"""Coefficients de revalorisation des salaires portés au compte, par la Cnav.

    pip install pypdf
    python scripts/fetch/cnav_revalorisation_salaires.py

À quoi ils servent. Le salaire annuel moyen du régime général est la moyenne
des N meilleures années, et « meilleures » se juge sur des salaires REVALORISÉS.
Les coefficients qui les revalorisent sont fixés chaque année par arrêté, et la
Cnav les publie en entier — une ligne par année de perception — dans sa
circulaire de revalorisation. C'est **la caisse qui les applique qui les
publie** : on ne peut pas être plus près de ce qui est réellement opposé à
l'assuré.

POURQUOI PAS OPENFISCA. Le dépôt a d'abord repris la table cumulée
d'OpenFisca-France-Pension, faute d'avoir cherché plus haut. Confrontée à la
circulaire du 9 janvier 2023, elle s'en écarte :

* de **−3 % à −5,5 %** sur toutes les perceptions postérieures à 1990, un
  déficit à peu près uniforme — c'est la revalorisation exceptionnelle de 4 %
  du 1er juillet 2022 (loi « pouvoir d'achat ») qu'elle n'a pas ;
* de **−17 % à +10 %**, sans régularité, sur les années 1949-1962.

Une seconde implémentation est une contre-expertise, pas une source.

POURQUOI PLUSIEURS COLONNES, ET PAS UNE SEULE. Le coefficient entre deux années
se déduit d'une colonne par simple rapport,

    coefficient(perception, liquidation) = colonne[perception] / colonne[liquidation]

parce que l'arrêté annuel applique UN coefficient à tous les salaires déjà
portés au compte, quelle que soit leur année de perception. Le dépôt n'a
d'abord gardé que la colonne la plus récente. Confrontée aux sept autres
colonnes publiées, cette reconstruction dérive avec la distance :

    liquidation 2024 (2 ans)  0,02 % médian    liquidation 2021 (5 ans)  0,13 %
    liquidation 2023 (3 ans)  0,07 %           liquidation 2020 (6 ans)  0,14 %
    liquidation 2022 (4 ans)  0,10 %           liquidation 2019 (7 ans)  0,16 %

parce que la caisse arrondit sa table publiée à trois décimales et repart
chaque année de la précédente : les arrondis s'accumulent. Garder toutes les
colonnes publiées et ancrer sur la PLUS PROCHE ramène l'écart à 0,01 % — un
ordre de grandeur.

Les colonnes dont la date d'effet n'est pas le 1er janvier — octobre 2017,
juillet 2022 — ne sont jamais servies telles quelles : le modèle raisonne à
l'année et retient l'état au 1er janvier. Elles restent d'excellents ANCRES,
parce que leur propre date s'annule dans le rapport.

UN PIÈGE, ET IL EST SILENCIEUX. La circulaire 2020-5 a été « annulée et
remplacée » par la 2020-9. Une circulaire retirée porte des chiffres qui n'ont
jamais été opposés à personne : le script refuse celles qui se déclarent
annulées.

Statut de fiabilité : `haute`, jamais `certifiee`. La circulaire est la
publication de la caisse, non le *Journal officiel* : elle transcrit l'arrêté et
l'instruction interministérielle qu'elle cite en référence. Même règle que pour
le plafond, le SMIC et les valeurs du point.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

#: Circulaires de revalorisation, par date d'effet. Les adresses portent le
#: numéro et la date de publication de la circulaire : elles ne se devinent pas
#: depuis l'année. À compléter chaque année d'une ligne, la plus récente fixant
#: l'horizon du modèle.
#:
#: Le web ne remonte pas au-delà de 2017 : les liquidations antérieures sont
#: donc reconstruites depuis la colonne d'octobre 2017, la plus proche.
CIRCULAIRES: tuple[tuple[str, str], ...] = (
    ("2017-10-01", "circulaire_cnav_2017_32_26092017.pdf"),
    ("2019-01-01", "circulaire_cnav_2019_04_09012019.pdf"),
    # 2020-9 annule et remplace 2020-5, qui portait les mêmes coefficients à un
    # détail près. Prendre la version retirée serait invisible et faux.
    ("2020-01-01", "circulaire_cnav_2020_09_04022020.pdf"),
    ("2021-01-01", "circulaire_cnav_2021_01_11012021.pdf"),
    ("2022-01-01", "circulaire_cnav_2022_03_11012022.pdf"),
    ("2022-07-01", "circulaire_cnav_2022_19_18082022.pdf"),
    ("2023-01-01", "circulaire_cnav_2023_03_09012023.pdf"),
    ("2024-01-01", "circulaire_cnav_2023_34_29122023.pdf"),
    ("2025-01-01", "circulaire_cnav_2024_39_23122024.pdf"),
    ("2026-01-01", "circulaire_cnav_2025_29_22122025.pdf"),
)

RACINE = "https://legislation.lassuranceretraite.fr/Pdf/"

#: Borne du recoupement entre colonnes. La table publiée est arrondie à trois
#: décimales, ce qui vaut déjà un pour mille sur les coefficients proches de 1 ;
#: 1 % laisse passer la dérive mesurée entre colonnes éloignées sans laisser
#: passer une colonne lue de travers.
TOLERANCE_RECOUPEMENT = 1e-2

BRUT = Path("data/brut/cnav_revalorisation_salaires.json")
SORTIE = Path("data/reference/legislation/revalorisation_salaires.csv")

#: Colonnes figées et VERSIONNÉES, comme le témoin d'OpenFisca. Elles
#: permettent à `tests/test_simulateur.py` de mesurer, sur un dépôt fraîchement
#: cloné et sans télécharger un seul PDF, l'écart entre ce que le modèle calcule
#: et ce que la caisse a publié — année de liquidation par année de liquidation.
TEMOIN = Path("tests/temoins/cnav_revalorisation_salaires.json")
ENTETES = {"User-Agent": "retraite-notionnelle/0.1 (recherche publique)"}

#: Le tableau visé porte cet intitulé. La circulaire en publie un second,
#: « Cotisations », pour les années où le compte portait des cotisations et non
#: des salaires : il ne concerne pas ce modèle, qui porte des salaires.
ENTETE_TABLEAU = r"Salaires Ann[ée]es Coefficients de revalorisation"


def telecharger(url: str) -> bytes:
    requete = urllib.request.Request(url, headers=ENTETES)
    with urllib.request.urlopen(requete, timeout=180) as reponse:
        return reponse.read()


def texte_du_pdf(pdf: bytes) -> str:
    import io

    from pypdf import PdfReader

    pages = PdfReader(io.BytesIO(pdf)).pages
    return re.sub(r"\s+", " ", "\n".join(page.extract_text() or "" for page in pages))


def est_annulee(texte: str) -> str | None:
    """La circulaire est-elle retirée sur ce qui nous intéresse ?

    Trois cas, et les confondre coûte cher dans les deux sens :

    * « Annulée et remplacée par » sans autre précision — la circulaire ENTIÈRE
      est retirée, ses chiffres n'ont jamais été opposés à personne. C'est le
      cas de la 2020-5, remplacée par la 2020-9 ;
    * « Point N annulé et remplacé par » — seul ce point tombe. La 2023-34 est
      dans ce cas, et son point 2 est le minimum contributif : ses coefficients,
      qui sont au point 1, restent en vigueur. La refuser perdrait une colonne
      pour rien ;
    * « Annule et remplace » — c'est celle qui prend la suite, la bonne.

    Rend la raison du refus, ou ``None`` si la circulaire est utilisable.
    """
    entete = texte[:1200].lower()
    clause = re.search(
        r"(?:point\s+(\d+)\s+)?annul[ée]e?s?\s+et\s+remplac[ée]e?s?\s+par", entete
    )
    if clause is None:
        return None
    point = clause.group(1)
    if point is None:
        return "la circulaire entière est annulée et remplacée"
    if point == "1":
        # Le point 1 est « Calcul des retraites » : c'est là que sont les
        # coefficients. S'il tombe, la colonne tombe avec lui.
        return "son point 1, qui porte les coefficients, est annulé et remplacé"
    return None


#: Une ligne du tableau : une année — ou une plage, « 1930 à 1935 »,
#: « 2014-2015 », quand l'arrêté leur oppose le même coefficient — puis le
#: coefficient. Celui-ci s'écrit « 9,988 », « 608 » ou « 2 221,283 » : la
#: décimale est facultative et les milliers sont séparés par une ESPACE. Ne pas
#: la prévoir coupait silencieusement les années 1930-1940 des circulaires qui
#: l'emploient — la table restait contiguë, et rien ne s'en plaignait.
LIGNE = re.compile(
    r"\b(19[3-9]\d|20[0-2]\d)(?:\s*[àa\-]\s*(19\d\d|20\d\d))? "
    r"(\d{1,3}(?: \d{3})*(?:,\d{1,3})?)\b"
)


def _lignes(bloc: str) -> list[tuple[int, int, float]]:
    """Années et coefficients d'un fragment de tableau."""
    lues = []
    for ligne in LIGNE.finditer(bloc):
        debut, fin = int(ligne.group(1)), ligne.group(2)
        brut = ligne.group(3).replace(" ", "")
        # Un entier qui ressemble à une année n'est pas un coefficient mais un
        # appariement raté : deux années de suite parce qu'une valeur manque.
        if "," not in brut and 1900 <= int(brut) <= 2100:
            continue
        lues.append((debut, int(fin) if fin else debut, float(brut.replace(",", "."))))
    return lues


def coefficients(texte: str) -> dict[int, float]:
    """Table « Salaires » de la circulaire, par année de perception.

    La circulaire publie DEUX tableaux : « Cotisations », pour les années où le
    compte portait des cotisations, et « Salaires ». Seul le second concerne ce
    modèle. On découpe donc sur l'en-tête du second — et on regarde AVANT lui,
    parce que l'extraction du PDF place parfois la fin d'un tableau devant son
    propre en-tête : la circulaire du 29 décembre 2023 y perdait 2010 et 2011,
    silencieusement.
    """
    table: dict[int, float] = {}
    morceaux = re.split(ENTETE_TABLEAU, texte)
    for rang, bloc in enumerate(morceaux[1:], start=1):
        # Chaque bloc s'arrête au pied de page qui annonce la page suivante.
        for debut, fin, valeur in _lignes(re.split(r"Revalorisation à compter", bloc)[0]):
            for annee in range(debut, fin + 1):
                table.setdefault(annee, valeur)
        # La queue du morceau précédent peut porter des lignes égarées. On n'y
        # retient que les années postérieures à 1946 : le tableau
        # « Cotisations » ne va pas plus loin, donc rien ne peut s'y confondre.
        for debut, fin, valeur in _lignes(morceaux[rang - 1][-400:]):
            if debut < 1947:
                continue
            for annee in range(debut, fin + 1):
                table.setdefault(annee, valeur)
    return table


def controler(table: dict[int, float], effet: str) -> list[str]:
    """Ce qu'une colonne lue doit vérifier pour être crédible."""
    griefs = []
    annees = sorted(table)
    if not annees:
        return ["aucun coefficient lu — le format de la circulaire a changé"]
    if annees != list(range(annees[0], annees[-1] + 1)):
        griefs.append("la suite des années de perception a des trous")
    if annees[-1] != int(effet[:4]) - (1 if effet.endswith("-01-01") else 0):
        griefs.append(
            f"la dernière perception est {annees[-1]}, incohérente avec un effet "
            f"au {effet}"
        )
    for precedente, suivante in zip(annees, annees[1:]):
        if table[suivante] > table[precedente] + 1e-9:
            griefs.append(
                f"le coefficient remonte de {precedente} à {suivante} "
                f"({table[precedente]} → {table[suivante]}) : un salaire plus "
                "récent ne peut pas être plus revalorisé qu'un salaire plus ancien"
            )
    if min(table.values()) < 1.0:
        griefs.append("un coefficient est inférieur à 1 : la revalorisation ne retire pas")
    return griefs


def au_1er_janvier(effet: str) -> bool:
    """Cette colonne décrit-elle l'état du compte au 1er janvier de son année ?"""
    return effet.endswith("-01-01")


def recouper(colonnes: dict[str, dict[int, float]]) -> tuple[float, str, str, int]:
    """Chaque colonne du 1er janvier doit se reconstruire depuis chacune des autres.

    C'est le contrôle qui vérifie que la table est bien multiplicative — sans
    quoi le modèle n'aurait pas le droit d'ancrer sur la colonne la plus proche
    pour les années de liquidation qui n'en ont pas.

    Deux exclusions, et elles ne sont pas des commodités. Une colonne dont la
    date d'effet tombe en cours d'année n'est jamais une CIBLE : son année de
    référence porte déjà la revalorisation de ce millésime, quand une colonne du
    1er janvier ne la porte pas encore — reconstruire celle de juillet 2022
    depuis celle de 2026 manque exactement les 4 % de la loi « pouvoir d'achat »,
    ce qui ne prouve rien sur la table et tout sur la date. Et une colonne
    n'ancre jamais sa propre année, pour la même raison.
    """
    pire = (0.0, "", "", 0)
    for effet_cible, cible in colonnes.items():
        if not au_1er_janvier(effet_cible):
            continue
        annee_cible = int(effet_cible[:4])
        for effet_ancre, ancre in colonnes.items():
            if (effet_ancre == effet_cible or annee_cible not in ancre
                    or int(effet_ancre[:4]) == annee_cible):
                continue
            diviseur = ancre[annee_cible]
            for perception, publie in cible.items():
                if perception >= annee_cible or perception not in ancre:
                    continue
                ecart = abs(ancre[perception] / diviseur - publie) / publie
                if ecart > pire[0]:
                    pire = (ecart, effet_cible, effet_ancre, perception)
    return pire


ENTETE_CSV = """\
# Coefficients de revalorisation des salaires portés au compte
# ----------------------------------------------------------
# source_id: cnav_revalorisation_salaires
#
# Fichier écrit par scripts/fetch/cnav_revalorisation_salaires.py :
# ne pas modifier à la main.
#
# Le salaire annuel moyen du régime général est la moyenne des N MEILLEURES
# années, et « meilleures » se juge sur des salaires revalorisés : ces
# coefficients commandent donc à la fois le montant retenu et le CHOIX des
# années. La Cnav les publie en entier dans ses circulaires de revalorisation.
#
# UNE COLONNE PAR DATE D'EFFET. Le coefficient entre deux années quelconques est
# le RAPPORT de deux valeurs d'une même colonne :
#
#     coefficient(perception, liquidation) = colonne[perception] / colonne[liquidation]
#
# parce que l'arrêté annuel applique un coefficient unique à tous les salaires
# déjà portés au compte. Une seule colonne suffirait donc en théorie ; en
# pratique la caisse arrondit sa table à trois décimales et repart chaque année
# de la précédente, si bien que reconstruire une colonne depuis une autre dérive
# avec la distance — 0,02 % à deux ans, 0,16 % à sept. Le modèle sert donc la
# colonne publiée quand elle existe, et ancre sinon sur la PLUS PROCHE.
#
# LES COLONNES HORS 1er JANVIER ne sont jamais servies telles quelles : le modèle
# raisonne à l'année et retient l'état au 1er janvier. Elles restent des ancres,
# leur date s'annulant dans le rapport.
#
# Hors de la plage — perceptions antérieures à la première année publiée,
# liquidations postérieures à la dernière date d'effet — le modèle ancre sur la
# borne connue et prolonge par son approximation « les salaires jusqu'en 1986,
# les prix depuis ».
#
# fiabilite : `haute`. La circulaire est la publication de la caisse, non le
# Journal officiel : elle transcrit l'arrêté et l'instruction interministérielle
# qu'elle cite. Une transcription ne peut pas être `certifiee`.
date_effet,annee_perception,coefficient,fiabilite
"""


def main(argv: list[str] | None = None) -> int:
    try:
        import pypdf  # noqa: F401
    except ImportError:
        print(
            "pypdf n'est pas installé — les circulaires sont des PDF.\n"
            "    pip install pypdf\n"
            "Il n'est PAS une dépendance du dépôt : le CSV produit est versionné, "
            "et le modèle s'en contente.",
            file=sys.stderr,
        )
        return 1

    colonnes: dict[str, dict[int, float]] = {}
    adresses: dict[str, str] = {}
    for effet, fichier in CIRCULAIRES:
        url = RACINE + fichier
        try:
            texte = texte_du_pdf(telecharger(url))
        except (urllib.error.URLError, TimeoutError) as erreur:
            print(f"échec du téléchargement de {fichier} : {erreur}", file=sys.stderr)
            return 1
        refus = est_annulee(texte)
        if refus:
            print(
                f"{fichier} : {refus}. Ses coefficients n'ont été opposés à "
                "personne. Rien n'est écrit.",
                file=sys.stderr,
            )
            return 1
        table = coefficients(texte)
        griefs = controler(table, effet)
        if griefs:
            for grief in griefs:
                print(f"{fichier} (effet {effet}) : {grief}", file=sys.stderr)
            return 1
        colonnes[effet] = table
        adresses[effet] = url

    ecart, cible, ancre, perception = recouper(colonnes)
    if ecart > TOLERANCE_RECOUPEMENT:
        print(
            f"recoupement échoué : la colonne {cible} reconstruite depuis {ancre} "
            f"s'en écarte de {ecart:.2%} sur la perception {perception}, au-delà "
            f"de {TOLERANCE_RECOUPEMENT:.1%}. Une colonne est peut-être lue de "
            "travers — rien n'est écrit.",
            file=sys.stderr,
        )
        return 1

    BRUT.parent.mkdir(parents=True, exist_ok=True)
    BRUT.write_text(
        json.dumps(
            {
                "sources": adresses,
                "recupere_le": date.today().isoformat(),
                "ecart_maximal_entre_colonnes": ecart,
                "avertissement": (
                    "Circulaires de la caisse, non le Journal officiel : elles "
                    "transcrivent l'arrêté. Fiabilité plafonnée à « haute »."
                ),
                "colonnes": {
                    effet: {str(a): v for a, v in sorted(table.items())}
                    for effet, table in sorted(colonnes.items())
                },
            },
            ensure_ascii=False, indent=2, sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )

    TEMOIN.parent.mkdir(parents=True, exist_ok=True)
    TEMOIN.write_text(
        json.dumps(
            {
                "sources": adresses,
                "recupere_le": date.today().isoformat(),
                "role": (
                    "Colonnes PUBLIÉES par la Cnav, une par date d'effet. Le "
                    "modèle sert la colonne de l'année quand elle existe et "
                    "reconstruit les autres par rapport d'indices : ce témoin "
                    "lui oppose ce que la caisse a réellement opposé aux "
                    "assurés, et mesure la dérive de la reconstruction."
                ),
                "colonnes": {
                    effet: {str(a): v for a, v in sorted(table.items())}
                    for effet, table in sorted(colonnes.items())
                },
            },
            ensure_ascii=False, indent=2, sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )

    lignes = [
        # Dix chiffres significatifs : les coefficients des années 1930 en
        # comptent huit — « 64 227,700 » — et six les auraient tronqués, ce qui
        # aurait empêché le modèle de rendre EXACTEMENT la valeur publiée.
        f"{effet},{annee},{coefficient:.10g},haute"
        for effet, table in sorted(colonnes.items())
        for annee, coefficient in sorted(table.items())
    ]
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(ENTETE_CSV + "\n".join(lignes) + "\n", encoding="utf-8")
    print(
        f"{SORTIE} : {len(colonnes)} colonnes, {len(lignes)} coefficients, "
        f"effets {min(colonnes)} à {max(colonnes)} ; "
        f"recoupement maximal entre colonnes {ecart:.3%}"
    )
    print(f"{TEMOIN} : les mêmes colonnes, figées pour les tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
