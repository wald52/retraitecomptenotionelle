#!/usr/bin/env python3
"""Coefficients de revalorisation des salaires portés au compte, 1949-2023.

    python scripts/fetch/openfisca_revalorisation_salaires.py

À quoi ils servent. Le salaire annuel moyen du régime général est la moyenne
des N meilleures années, et « meilleures » se juge sur des salaires REVALORISÉS.
Les coefficients qui les revalorisent sont fixés chaque année par arrêté, et ils
n'ont pas suivi une règle unique : les salaires jusqu'au milieu des années 1980,
les prix depuis, avec des revalorisations semestrielles, des gels, des
revalorisations exceptionnelles, et des changements du DÉLAI d'application — la
revalorisation portait tantôt jusqu'à l'année n−1, tantôt jusqu'à n−2.

Le modèle les approchait par « les salaires jusqu'en 1986, les prix depuis ».
La confrontation à OpenFisca-France-Pension a mesuré ce que cette approximation
coûte : **elle sur-revalorise les salaires anciens de 12 à 14 %** sur un
horizon 1970-2018 ou 1980-2018, ce qui gonflait le salaire de référence de
toutes les carrières comportant des années anciennes, et donc l'étalon
lui-même.

POURQUOI UNE TABLE À DEUX ENTRÉES, ET PAS UNE SÉRIE ANNUELLE

Parce qu'aucune formule ne reproduit les arrêtés. J'ai essayé, et mesuré :

* une série d'ancrages, avec `coefficient(t, L) = ancre[t] / ancre[L]` : écart
  jusqu'à 20 % — les changements de délai la font fuir ;
* la même, restreinte aux liquidations récentes ou aux écarts d'au moins trois
  ans : elle fuit encore, jusqu'à 2,8 % en 1985 ;
* une série d'ancrages plus une série d'entrée : 16,7 % d'écart sur les
  perceptions du début des années 1950 ;
* un retard par année de liquidation : 697 couples sur 2 628 restent
  inexpliqués.

La table à deux entrées est donc la seule forme exacte, et c'est la doctrine du
dépôt : préférer ce qui a été réellement appliqué à toute reconstitution
élégante. Elle pèse une soixantaine de kilo-octets.

Statut de fiabilité. OpenFisca n'est pas le producteur : c'est une
**transcription** des arrêtés et des circulaires CNAV, chaque valeur portant sa
date de *Journal officiel* ou sa référence de circulaire dans les métadonnées du
fichier amont. Les valeurs sont donc versées au niveau ``haute``, jamais
``certifiee`` — même règle que pour le plafond, le SMIC et les valeurs du point.

Ce que la table ne couvre pas : les salaires perçus après 2021 et les
liquidations postérieures à 2023. Pour ces dernières, les arrêtés servent quand
même — le modèle ancre sur le dernier publié et n'approche que le bout du
chemin, ce qu'autorise leur structure : chaque arrêté applique un coefficient
unique à tous les salaires déjà portés au compte, et la table le confirme, la
dispersion d'une perception à l'autre y valant 1,6·10⁻⁵. L'approximation
d'origine ne reprend toute la main que pour les salaires perçus hors table.
`docs/limites.md` dit dans quel sens elle joue.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

import yaml

URL = ("https://raw.githubusercontent.com/openfisca/openfisca-france-pension/"
       "master/openfisca_france_pension/parameters/retraites/secteur_prive/"
       "regime_general_cnav/revalorisation_salaire_cummulee.yaml")
BRUT = Path("data/brut/openfisca_revalorisation_salaires.json")
SORTIE = Path("data/reference/legislation/revalorisation_salaires.csv")
ENTETES = {"User-Agent": "retraite-notionnelle/0.1 (recherche publique)"}

#: Dernière année de liquidation retenue. Au-delà, la table amont ne dit plus
#: rien et le modèle reprend son approximation.
DERNIERE_LIQUIDATION = 2023


def telecharger() -> dict:
    requete = urllib.request.Request(URL, headers=ENTETES)
    with urllib.request.urlopen(requete, timeout=120) as reponse:
        return yaml.safe_load(reponse.read().decode("utf-8"))


def table(document: dict) -> dict[tuple[int, int], float]:
    """Coefficient cumulé, par (année de perception, année de liquidation).

    La valeur retenue pour une année de liquidation est celle en vigueur au
    1er janvier : c'est la convention de tout le dépôt, et celle qu'oppose la
    caisse pour l'année entière.
    """
    perceptions = sorted(k for k in document if isinstance(k, int))
    resultat: dict[tuple[int, int], float] = {}
    for perception in perceptions:
        paliers = sorted(
            (str(cle)[:10], valeur.get("value") if isinstance(valeur, dict) else valeur)
            for cle, valeur in document[perception]["values"].items()
        )
        for liquidation in range(perception + 1, DERNIERE_LIQUIDATION + 1):
            applicables = [
                v for date_effet, v in paliers
                if date_effet <= f"{liquidation}-01-01" and v is not None
            ]
            if applicables:
                resultat[(perception, liquidation)] = applicables[-1]
    return resultat


ENTETE_CSV = """\
# Coefficients de revalorisation des salaires portés au compte
# ------------------------------------------------------------
# source_id: openfisca_revalorisation_salaires
#
# Fichier écrit par scripts/fetch/openfisca_revalorisation_salaires.py :
# ne pas modifier à la main.
#
# Le salaire annuel moyen du régime général est la moyenne des N MEILLEURES
# années, et « meilleures » se juge sur des salaires revalorisés. Les
# coefficients qui les revalorisent sont fixés chaque année par arrêté, et ils
# n'ont jamais suivi une règle unique : les salaires jusqu'au milieu des années
# 1980, les prix depuis, avec des revalorisations semestrielles, des gels, des
# revalorisations exceptionnelles, et des changements du DÉLAI d'application —
# la revalorisation portait tantôt jusqu'à l'année n−1, tantôt jusqu'à n−2.
#
# Le modèle les approchait par « les salaires jusqu'en 1986, les prix depuis ».
# Cette approximation SUR-REVALORISE les salaires anciens de 12 à 14 % sur un
# horizon de quarante ans, et gonflait donc le salaire de référence de toutes
# les carrières comportant des années anciennes.
#
# POURQUOI DEUX ENTRÉES. Aucune formule ne reproduit les arrêtés : une série
# d'ancrages fuit de 20 %, la même restreinte aux liquidations récentes fuit
# encore de 2,8 %, un retard par année de liquidation laisse 697 couples sur
# 2 628 inexpliqués. La table est donc donnée telle quelle. Le coefficient est
# celui en vigueur au 1er janvier de l'année de liquidation.
#
# Hors de la plage couverte — salaires perçus avant 1949 ou après 2021,
# liquidations postérieures à {derniere} — le modèle reprend son approximation.
#
# fiabilite : `haute`. OpenFisca n'est pas le producteur mais une transcription
# des arrêtés et des circulaires CNAV, chacune datée dans les métadonnées du
# fichier amont. Une transcription tierce ne peut pas être `certifiee`.
annee_perception,annee_liquidation,coefficient
"""


def main(argv: list[str] | None = None) -> int:
    try:
        document = telecharger()
    except (urllib.error.URLError, TimeoutError) as erreur:
        print(f"échec du téléchargement : {erreur}", file=sys.stderr)
        return 1

    valeurs = table(document)
    if not valeurs:
        print("aucun coefficient lu — le format amont a changé", file=sys.stderr)
        return 1

    BRUT.parent.mkdir(parents=True, exist_ok=True)
    BRUT.write_text(
        json.dumps(
            {
                "source": URL,
                "recupere_le": date.today().isoformat(),
                "avertissement": (
                    "Transcription tierce des arrêtés et circulaires CNAV : "
                    "fiabilité plafonnée à « haute », jamais « certifiee »."
                ),
                "valeurs": {
                    f"{p}|{liq}": v for (p, liq), v in sorted(valeurs.items())
                },
            },
            ensure_ascii=False, indent=2, sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )

    lignes = [
        f"{perception},{liquidation},{coefficient:.6g}"
        for (perception, liquidation), coefficient in sorted(valeurs.items())
    ]
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(
        ENTETE_CSV.format(derniere=DERNIERE_LIQUIDATION) + "\n".join(lignes) + "\n",
        encoding="utf-8",
    )
    perceptions = {p for p, _ in valeurs}
    print(
        f"{SORTIE} : {len(valeurs)} coefficients, "
        f"perceptions {min(perceptions)}-{max(perceptions)}, "
        f"liquidations jusqu'à {DERNIERE_LIQUIDATION}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
