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

Périmètre : le régime unifié, depuis sa création au 1er janvier 2019. Les
barèmes de l'Agirc et de l'Arrco d'avant la fusion figurent dans le même
document, mais sous une présentation différente et avec des conventions de date
qui leur sont propres ; ils restent transcrits d'OpenFisca, recoupés à l'INSEE.
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

#: Le document empile trois tableaux : le régime unifié, puis l'Agirc et l'Arrco
#: d'avant la fusion. Seul le premier est lu, et il s'arrête à cet intertitre.
FIN_DU_TABLEAU = "Agirc-Arrco - Valeurs de service"


def telecharger(url: str) -> bytes:
    requete = urllib.request.Request(url, headers=ENTETES)
    with urllib.request.urlopen(requete, timeout=180) as reponse:
        return reponse.read()


def texte_du_pdf(pdf: bytes) -> str:
    import io

    from pypdf import PdfReader

    pages = PdfReader(io.BytesIO(pdf)).pages
    return re.sub(r"\s+", " ", "\n".join(page.extract_text() or "" for page in pages))


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
        texte = texte_du_pdf(telecharger(URL))
    except (urllib.error.URLError, TimeoutError) as erreur:
        print(f"échec du téléchargement : {erreur}", file=sys.stderr)
        return 1

    coupe = texte.find(FIN_DU_TABLEAU)
    tete = texte if coupe < 0 else texte[:coupe]
    service = valeurs_de_service(tete)
    achat = valeurs_d_achat(tete)
    griefs = controler(service, achat)
    if griefs:
        for grief in griefs:
            print(f"agirc_arrco : {grief}", file=sys.stderr)
        return 1

    serie = {f"agirc_arrco|{annee}|valeur_service": valeur
             for annee, valeur in sorted(service.items())}
    serie |= {f"agirc_arrco|{annee}|salaire_reference": valeur
              for annee, valeur in sorted(achat.items())}

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
                    "Fédération Agirc-Arrco, qui fixe et publie ces deux barèmes. "
                    "C'est le producteur de la donnée, non une transcription."
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
    print(
        f"{SORTIE} : {len(serie)} valeurs arrêtées — service "
        f"{min(service)}-{max(service)}, achat {min(achat)}-{max(achat)} ; "
        f"valeur de service en vigueur en {en_cours} reconduite à "
        f"{service[max(service)]} €"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
