#!/usr/bin/env python3
"""Coefficients de revalorisation des salaires portés au compte, par la Cnav.

    pip install pypdf
    python scripts/fetch/cnav_revalorisation_salaires.py

À quoi ils servent. Le salaire annuel moyen du régime général est la moyenne
des N meilleures années, et « meilleures » se juge sur des salaires REVALORISÉS.
Les coefficients qui les revalorisent sont fixés chaque année par arrêté, et la
Cnav les publie en entier — une ligne par année de perception — dans sa
circulaire annuelle de revalorisation. C'est **la caisse qui les applique qui
les publie** : on ne peut pas être plus près de ce qui est réellement opposé à
l'assuré.

POURQUOI PAS OPENFISCA. Le dépôt a d'abord repris la table cumulée
d'OpenFisca-France-Pension, faute d'avoir cherché plus haut. Confrontée à la
circulaire Cnav du 9 janvier 2023, elle s'en écarte :

* de **−3 % à −5,5 %** sur toutes les perceptions postérieures à 1990, un
  déficit à peu près uniforme — c'est la revalorisation exceptionnelle de 4 %
  du 1er juillet 2022 (loi « pouvoir d'achat ») qu'elle n'a pas ;
* de **−17 % à +10 %**, sans régularité, sur les années 1949-1962.

Une seconde implémentation est une contre-expertise, pas une source. Ici la
source existe, et elle dit autre chose.

UNE SEULE COLONNE SUFFIT, ET C'EST DÉMONTRÉ. La circulaire d'une année de
liquidation donne un coefficient par année de perception ; le coefficient entre
deux années quelconques s'en déduit par simple rapport,

    coefficient(perception, liquidation) = indice[perception] / indice[liquidation]

parce que l'arrêté annuel applique UN coefficient à tous les salaires déjà
portés au compte, quelle que soit leur année de perception. Ce n'est pas un
postulat : reconstruire ainsi les colonnes publiées pour 2023 et pour 2025 à
partir de la seule circulaire de 2026 les retrouve à **0,14 %**, c'est-à-dire à
l'arrondi à trois décimales de la table publiée. Le script le revérifie à chaque
exécution contre une circulaire plus ancienne, et refuse d'écrire si l'écart
s'écarte de cette borne.

Le dépôt a un temps conclu l'inverse — « aucune formule ne reproduit les
arrêtés, une série d'ancrages fuit de 20 % ». Cette mesure portait sur la table
d'OpenFisca : ce sont ses incohérences qu'elle mesurait, pas celles du droit.

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

#: Circulaire de référence : celle qui porte la table la plus récente. C'est
#: elle qui fixe l'année de référence des indices écrits dans le CSV. À changer
#: chaque année ; l'adresse contient le numéro et la date de la circulaire, elle
#: ne se devine pas depuis l'année seule.
CIRCULAIRE = (
    2026,
    "https://legislation.lassuranceretraite.fr/Pdf/"
    "circulaire_cnav_2025_29_22122025.pdf",
)

#: Circulaire plus ancienne, gardée pour le RECOUPEMENT : sa colonne doit se
#: reconstruire depuis celle de référence par simple rapport. C'est ce contrôle
#: qui vérifie, à chaque exécution, que la table est bien multiplicative.
RECOUPEMENT = (
    2023,
    "https://legislation.lassuranceretraite.fr/Pdf/"
    "circulaire_cnav_2023_03_09012023.pdf",
)

#: Borne du recoupement. La table publiée est arrondie à trois décimales, ce qui
#: vaut déjà un pour mille sur les coefficients proches de 1 ; 0,3 % laisse la
#: marge sans laisser passer une vraie divergence.
TOLERANCE_RECOUPEMENT = 3e-3

BRUT = Path("data/brut/cnav_revalorisation_salaires.json")
SORTIE = Path("data/reference/legislation/revalorisation_salaires.csv")

#: Colonne publiée par la circulaire de recoupement, figée et VERSIONNÉE — comme
#: le témoin d'OpenFisca. Elle permet à `tests/test_donnees.py` de vérifier que
#: le modèle reproduit ce que la caisse a réellement publié cette année-là, sur
#: un dépôt fraîchement cloné, sans télécharger le PDF ni installer pypdf.
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


def coefficients(pdf: bytes) -> dict[int, float]:
    """Table « Salaires » de la circulaire, par année de perception."""
    import io

    from pypdf import PdfReader

    pages = PdfReader(io.BytesIO(pdf)).pages
    texte = re.sub(r"\s+", " ", "\n".join(page.extract_text() or "" for page in pages))
    table: dict[int, float] = {}
    for bloc in re.split(ENTETE_TABLEAU, texte)[1:]:
        # Chaque bloc s'arrête au pied de page qui annonce la page suivante.
        bloc = re.split(r"Revalorisation à compter", bloc)[0]
        for ligne in re.finditer(
            r"\b(19[3-9]\d|20[0-2]\d)(?:\s*[àa\-]\s*(19\d\d|20\d\d))? (\d{1,4},\d{1,3})\b",
            bloc,
        ):
            debut, fin = int(ligne.group(1)), ligne.group(2)
            valeur = float(ligne.group(3).replace(",", "."))
            # Une ligne peut couvrir plusieurs années — « 1930 à 1935 »,
            # « 2014-2015 » — quand l'arrêté leur oppose le même coefficient.
            for annee in range(debut, (int(fin) if fin else debut) + 1):
                table.setdefault(annee, valeur)
    return table


def controler(table: dict[int, float], annee: int) -> list[str]:
    """Ce qu'une table lue doit vérifier pour être crédible."""
    griefs = []
    annees = sorted(table)
    if not annees:
        return ["aucun coefficient lu — le format de la circulaire a changé"]
    if annees != list(range(annees[0], annees[-1] + 1)):
        griefs.append("la suite des années de perception a des trous")
    if annees[-1] != annee - 1:
        griefs.append(
            f"la dernière perception est {annees[-1]}, attendue {annee - 1}"
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


def recouper(reference: dict[int, float], annee_reference: int,
             ancienne: dict[int, float], annee_ancienne: int) -> tuple[float, int]:
    """Reconstruit la colonne d'une circulaire ancienne depuis la récente.

    Le rapport ``indice[perception] / indice[liquidation]`` doit reproduire ce
    que la caisse a publié cette année-là. C'est le contrôle qui autorise à ne
    garder qu'une colonne.
    """
    diviseur = reference[annee_ancienne]
    pire, coupable = 0.0, 0
    for perception, publie in ancienne.items():
        if perception >= annee_ancienne or perception not in reference:
            continue
        ecart = abs(reference[perception] / diviseur - publie) / publie
        if ecart > pire:
            pire, coupable = ecart, perception
    return pire, coupable


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
# années. La Cnav les publie en entier dans sa circulaire annuelle de
# revalorisation — celle du {circulaire}, pour une liquidation en {reference}.
#
# UNE SEULE COLONNE. Le coefficient entre deux années quelconques est le
# RAPPORT de leurs indices :
#
#     coefficient(perception, liquidation) = indice[perception] / indice[liquidation]
#
# parce que l'arrêté annuel applique un coefficient unique à tous les salaires
# déjà portés au compte, quelle que soit leur année de perception. Reconstruire
# ainsi les colonnes publiées pour d'autres années de liquidation les retrouve à
# {tolerance:.1%} près — l'arrondi à trois décimales de la table. Le récupérateur
# le revérifie à chaque exécution et refuse d'écrire si la borne est franchie.
#
# L'indice de l'année de référence vaut 1 : un salaire perçu l'année de la
# liquidation n'est pas revalorisé.
#
# Hors de la plage — perceptions antérieures à {premiere}, liquidations
# postérieures à {reference} — le modèle ancre sur la borne connue et prolonge
# par son approximation « les salaires jusqu'en 1986, les prix depuis ».
#
# fiabilite : `haute`. La circulaire est la publication de la caisse, non le
# Journal officiel : elle transcrit l'arrêté et l'instruction interministérielle
# qu'elle cite. Une transcription ne peut pas être `certifiee`.
annee_perception,annee_reference,coefficient,fiabilite
"""


def main(argv: list[str] | None = None) -> int:
    try:
        import pypdf  # noqa: F401
    except ImportError:
        print(
            "pypdf n'est pas installé — la circulaire est un PDF.\n"
            "    pip install pypdf\n"
            "Il n'est PAS une dépendance du dépôt : le CSV produit est versionné, "
            "et le modèle s'en contente.",
            file=sys.stderr,
        )
        return 1

    annee_reference, url_reference = CIRCULAIRE
    annee_ancienne, url_ancienne = RECOUPEMENT
    try:
        pdf_reference = telecharger(url_reference)
        pdf_ancienne = telecharger(url_ancienne)
    except (urllib.error.URLError, TimeoutError) as erreur:
        print(f"échec du téléchargement : {erreur}", file=sys.stderr)
        return 1

    table = coefficients(pdf_reference)
    ancienne = coefficients(pdf_ancienne)
    for lue, annee in ((table, annee_reference), (ancienne, annee_ancienne)):
        griefs = controler(lue, annee)
        if griefs:
            for grief in griefs:
                print(f"circulaire {annee} : {grief}", file=sys.stderr)
            return 1

    ecart, coupable = recouper(table, annee_reference, ancienne, annee_ancienne)
    if ecart > TOLERANCE_RECOUPEMENT:
        print(
            f"recoupement échoué : la colonne {annee_ancienne} reconstruite depuis "
            f"{annee_reference} s'en écarte de {ecart:.2%} sur la perception "
            f"{coupable}, au-delà de {TOLERANCE_RECOUPEMENT:.1%}. La table n'est "
            "peut-être plus multiplicative — rien n'est écrit.",
            file=sys.stderr,
        )
        return 1

    BRUT.parent.mkdir(parents=True, exist_ok=True)
    BRUT.write_text(
        json.dumps(
            {
                "source": url_reference,
                "recoupement": url_ancienne,
                "annee_reference": annee_reference,
                "recupere_le": date.today().isoformat(),
                "ecart_recoupement": ecart,
                "avertissement": (
                    "Circulaire de la caisse, non le Journal officiel : elle "
                    "transcrit l'arrêté. Fiabilité plafonnée à « haute »."
                ),
                "coefficients": {str(a): v for a, v in sorted(table.items())},
            },
            ensure_ascii=False, indent=2, sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )

    TEMOIN.parent.mkdir(parents=True, exist_ok=True)
    TEMOIN.write_text(
        json.dumps(
            {
                "source": url_ancienne,
                "annee_liquidation": annee_ancienne,
                "recupere_le": date.today().isoformat(),
                "role": (
                    "Colonne PUBLIÉE par la Cnav pour cette année de liquidation. "
                    "Le modèle la reconstruit par rapport d'indices depuis la "
                    "circulaire de référence : ce témoin lui oppose ce que la "
                    "caisse a réellement opposé aux assurés."
                ),
                "coefficients": {str(a): v for a, v in sorted(ancienne.items())},
            },
            ensure_ascii=False, indent=2, sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )

    lignes = [
        f"{annee},{annee_reference},{coefficient:.6g},haute"
        for annee, coefficient in sorted(table.items())
    ]
    # L'année de référence elle-même : un salaire perçu l'année de la
    # liquidation n'est pas revalorisé. La circulaire ne l'imprime pas, parce
    # qu'elle va de soi ; le modèle, lui, a besoin du diviseur.
    lignes.append(f"{annee_reference},{annee_reference},1,haute")
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(
        ENTETE_CSV.format(
            circulaire=url_reference.rsplit("/", 1)[-1],
            reference=annee_reference,
            premiere=min(table),
            tolerance=TOLERANCE_RECOUPEMENT,
        ) + "\n".join(lignes) + "\n",
        encoding="utf-8",
    )
    print(
        f"{SORTIE} : {len(table) + 1} indices, perceptions {min(table)}-{max(table)}, "
        f"référence {annee_reference} ; recoupement {annee_ancienne} à {ecart:.3%}\n"
        f"{TEMOIN} : colonne publiée pour {annee_ancienne}, {len(ancienne)} années"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
