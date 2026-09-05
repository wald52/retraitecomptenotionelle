#!/usr/bin/env python3
"""Valeurs du point du RAFP, publiées par l'ERAFP qui les fixe.

    pip install pypdf
    python scripts/fetch/erafp_valeurs_point.py

À quoi elles servent. Le RAFP est le seul compartiment CAPITALISÉ du modèle :
il est servi à part, à l'identique dans les cinq scénarios, et c'est pourquoi
il ne pèse pas sur les écarts. Il pèse en revanche sur le montant affiché à un
fonctionnaire, et il se calcule en points — cotisation divisée par la valeur
d'acquisition, points multipliés par la valeur de service.

POURQUOI CETTE SOURCE. Ces valeurs venaient d'OpenFisca-France-Pension,
c'est-à-dire d'une transcription, plafonnée à ``haute``. Or l'ERAFP publie
lui-même le tableau complet depuis la création du régime, et c'est LUI qui fixe
ces deux valeurs : « La valeur d'acquisition et la valeur de service du point
RAFP sont fixées chaque année par le conseil d'administration de l'ERAFP. » Le
producteur, donc, au sens du dépôt — même règle que pour l'Ircantec, dont les
barèmes viennent de la Caisse des dépôts qui le gère, et que pour l'Agirc-Arrco.

CE QUE LA CONFRONTATION A TROUVÉ, et ce n'est pas rien : la transcription
répétait en 2021 la valeur d'acquisition de 2020 — 1,2452 € au lieu de
1,2502 €. Une valeur d'acquisition trop basse achète trop de points : l'erreur
majorait de 0,4 % les droits acquis en 2021. Elle s'est vue toute seule, parce
que le document publie en regard de chaque valeur son évolution, et que
+ 0,4 % ne mène pas de 1,2452 à 1,2452.

ET SIX ANNÉES DE PLUS. La transcription s'arrêtait à 2021 ; l'ERAFP publie
jusqu'en 2026. Les années manquantes étaient prolongées par les prix, alors que
le RAFP a été revalorisé bien plus vite — + 5,7 % en 2023, + 6,8 % en 2024 sur
la valeur de service.

UNE ANNÉE À DEUX VALEURS. En 2016, la valeur de service change au 1er avril :
le tableau porte deux colonnes, « jusqu'au 31 mars » et « à partir du 1er
avril ». La règle du dépôt retient la valeur en vigueur au 31 décembre, donc la
seconde — et le script l'obtient sans cas particulier, en laissant la dernière
colonne d'une même année l'emporter sur les précédentes.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

#: Tableau publié par l'établissement, une page, deux tableaux.
URL = "https://media.rafp.fr/s3fs-public/2024-02/RAFP-Evolution-valeurs-point.pdf"

SORTIE = Path("data/brut/erafp_valeurs_point.json")
ENTETES = {"User-Agent": "retraite-notionnelle/0.1 (recherche publique)"}

#: Le régime naît de la loi du 21 août 2003 et cotise à compter du 1er janvier
#: 2005 : aucune valeur ne le précède.
PREMIERE_ANNEE = 2005

#: Les deux tableaux, et la grandeur du dépôt qui leur correspond. La « valeur
#: d'acquisition » du RAFP est ce que le dépôt appelle salaire de référence :
#: le prix d'un point.
TABLEAUX = {
    "salaire_reference": "Évolution de la valeur d'acquisition",
    "valeur_service": "Évolution de la valeur de service",
}

#: Écart toléré entre l'évolution publiée et celle recalculée depuis les
#: valeurs lues. Le document arrondit au dixième de point ; on en tolère deux
#: fois plus, sans quoi + 0,3 % sur quatre décimales ferait crier au loup.
ECART_EVOLUTION = 0.002

#: Rendement instantané du régime — valeur de service divisée par valeur
#: d'acquisition. Il est resté entre 3,8 % et 4,1 % depuis 2005 ; la plage est
#: large à dessein, il ne s'agit que d'attraper deux colonnes interverties.
RENDEMENT_PLAUSIBLE = (0.030, 0.050)

ANNEE = re.compile(r"\b(20\d\d)\b")
#: « 1 », « 1,017 », « 0,04465 » — la première valeur d'acquisition est un euro
#: rond, et s'écrit sans décimale.
MONTANT = re.compile(r"\b\d+(?:,\d+)?\b")
EVOLUTION = re.compile(r"[+-]\s*\d+(?:,\d+)?\s*%|—|-{1,2}(?=\s|$)")


def telecharger(url: str) -> bytes:
    requete = urllib.request.Request(url, headers=ENTETES)
    with urllib.request.urlopen(requete, timeout=180) as reponse:
        return reponse.read()


def texte_du_pdf(pdf: bytes) -> str:
    import io

    from pypdf import PdfReader

    texte = "\n".join(page.extract_text() or ""
                      for page in PdfReader(io.BytesIO(pdf)).pages)
    # L'apostrophe typographique du document contre l'apostrophe droite du
    # code : la même lettre pour un lecteur, deux caractères pour une
    # recherche.
    return texte.replace("\u2019", "'")


def _blocs(texte: str) -> list[tuple[list[int], list[float], list[float | None]]]:
    """Découpe un tableau en ses blocs de sept colonnes.

    Le tableau ne tient pas dans la largeur de la page : il est imprimé en
    tranches, chacune faite de trois lignes — les années, les montants, les
    évolutions. C'est cette structure, et non l'ordre des nombres, qui dit ce
    qui va avec quoi.
    """
    blocs = []
    lignes = [l.strip() for l in texte.splitlines()]
    for rang, ligne in enumerate(lignes):
        if not ligne.startswith("Année"):
            continue
        # Une tranche peut déborder sur la ligne suivante — « Jusqu'au 31
        # mars 2016 » y tient sur deux lignes —, jusqu'aux montants.
        entete, montants, evolutions = [ligne], None, None
        for suite in lignes[rang + 1:]:
            if suite.startswith("En euros"):
                montants = suite
            elif montants is not None and suite.startswith("Variation"):
                evolutions = suite
                break
            elif montants is None:
                entete.append(suite)
        if montants is None or evolutions is None:
            continue
        annees = [int(a) for a in ANNEE.findall(" ".join(entete))]
        valeurs = [float(m.replace(",", ".")) for m in MONTANT.findall(montants)]
        taux = [None if not m[0] in "+-" else
                float(m.strip("%").replace(" ", "").replace(",", ".")) / 100
                for m in EVOLUTION.findall(evolutions)]
        blocs.append((annees, valeurs, taux))
    return blocs


def lire_tableau(texte: str, intitule: str) -> tuple[dict[int, float], list[str]]:
    """Une grandeur, année par année, et ce que son contrôle a trouvé.

    Deux colonnes peuvent porter la même année — 2016, dont la valeur de
    service change au 1er avril. La dernière l'emporte : c'est celle qui est en
    vigueur au 31 décembre, la convention du dépôt.
    """
    debut = texte.find(intitule)
    if debut < 0:
        return {}, [f"tableau « {intitule} » introuvable"]
    fin = min((texte.find(autre, debut + 1) for autre in TABLEAUX.values()
               if texte.find(autre, debut + 1) > 0), default=len(texte))

    valeurs: dict[int, float] = {}
    griefs: list[str] = []
    precedente: float | None = None
    for annees, montants, taux in _blocs(texte[debut:fin]):
        if not (len(annees) == len(montants) == len(taux)):
            griefs.append(
                f"{intitule} : une tranche porte {len(annees)} années, "
                f"{len(montants)} montants et {len(taux)} évolutions"
            )
            continue
        for annee, montant, evolution in zip(annees, montants, taux):
            if evolution is not None and precedente:
                calculee = montant / precedente - 1
                if abs(calculee - evolution) > ECART_EVOLUTION:
                    griefs.append(
                        f"{intitule} {annee} : {montant}, hausse publiée "
                        f"{evolution:.2%}, recalculée {calculee:.2%}"
                    )
            precedente = montant
            valeurs[annee] = montant
    return valeurs, griefs


def controler(acquisition: dict[int, float], service: dict[int, float]) -> list[str]:
    """Ce que les deux barèmes doivent vérifier pour être crédibles."""
    griefs = []
    for nom, table in (("valeur d'acquisition", acquisition),
                       ("valeur de service", service)):
        if not table:
            griefs.append(f"{nom} : tableau vide — la présentation a changé")
            continue
        annees = sorted(table)
        if annees[0] != PREMIERE_ANNEE:
            griefs.append(
                f"{nom} : la série commence en {annees[0]}, or le régime cotise "
                f"depuis {PREMIERE_ANNEE}"
            )
        if annees != list(range(annees[0], annees[-1] + 1)):
            griefs.append(f"{nom} : la suite des années a des trous")
        if min(table.values()) <= 0:
            griefs.append(f"{nom} : une valeur nulle ou négative")
    for annee in sorted(set(acquisition) & set(service)):
        rendement = service[annee] / acquisition[annee]
        if not RENDEMENT_PLAUSIBLE[0] < rendement < RENDEMENT_PLAUSIBLE[1]:
            griefs.append(
                f"{annee} : rendement de {rendement:.2%}, hors de la plage "
                "plausible — un des deux tableaux est lu de travers"
            )
    return griefs


def main(argv: list[str] | None = None) -> int:
    try:
        import pypdf  # noqa: F401
    except ImportError:
        print(
            "pypdf n'est pas installé — le tableau de l'ERAFP est un PDF.\n"
            "    pip install pypdf\n"
            "Il n'est PAS une dépendance du dépôt : les valeurs promues dans "
            "data/reference/ sont versionnées, et le modèle s'en contente.",
            file=sys.stderr,
        )
        return 1
    try:
        texte = texte_du_pdf(telecharger(URL))
    except (urllib.error.URLError, TimeoutError) as erreur:
        print(f"échec du téléchargement : {erreur}", file=sys.stderr)
        return 1

    tables: dict[str, dict[int, float]] = {}
    griefs: list[str] = []
    for mesure, intitule in TABLEAUX.items():
        tables[mesure], ecarts = lire_tableau(texte, intitule)
        griefs.extend(ecarts)
    griefs.extend(controler(tables["salaire_reference"], tables["valeur_service"]))
    if griefs:
        for grief in griefs:
            print(f"rafp : {grief}", file=sys.stderr)
        return 1

    serie = {
        f"rafp|{annee}|{mesure}": valeur
        for mesure, table in tables.items()
        for annee, valeur in sorted(table.items())
    }

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(
        json.dumps(
            {
                "source": URL,
                "recupere_le": date.today().isoformat(),
                "producteur": (
                    "ERAFP, dont le conseil d'administration fixe chaque année "
                    "les deux valeurs. C'est le producteur de la donnée, non "
                    "une transcription."
                ),
                "regle_annuelle": (
                    "Valeur en vigueur au 31 décembre. Une année à deux "
                    "valeurs — 2016, dont la valeur de service change au "
                    "1er avril — est donc rendue par la seconde."
                ),
                "serie": dict(sorted(serie.items())),
            },
            ensure_ascii=False, indent=2, sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    acquisition = tables["salaire_reference"]
    service = tables["valeur_service"]
    print(
        f"{SORTIE} : {len(serie)} valeurs — acquisition "
        f"{min(acquisition)}-{max(acquisition)}, service "
        f"{min(service)}-{max(service)} ; rendement "
        f"{service[max(service)] / acquisition[max(service)]:.2%} en "
        f"{max(service)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
