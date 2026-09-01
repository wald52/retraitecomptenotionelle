#!/usr/bin/env python3
"""Oracle indépendant du régime général, par OpenFisca-France-Pension.

    pip install OpenFisca-France-Pension
    python scripts/fetch/openfisca_regime_general.py

À quoi il sert. Le scénario « système actuel » est l'ÉTALON du modèle : tous
les écarts affichés se mesurent par rapport à lui. Or il n'avait jusqu'ici
aucune contre-expertise. Aucun simulateur officiel n'est automatisable — M@rel
exige FranceConnect et le relevé de carrière réel, sans mode anonyme ni API —
et relire deux fois le même code ne prouve rien : une réimplémentation écrite
par la même main hérite des mêmes hypothèses.

**OpenFisca-France-Pension est une deuxième implémentation, écrite par
d'autres.** C'est le module « retraites » de l'écosystème OpenFisca, inspiré de
TiL-Pension. Ce n'est PAS une source officielle : c'est un modèle, avec ses
propres approximations et ses propres retards. Un désaccord ne désigne donc pas
d'office le coupable — la première confrontation en a produit deux, un de chaque
côté :

* **chez nous** — le modèle confondait la durée requise pour le taux plein et
  la durée maximale prise en compte par la proratisation, que l'article
  R. 351-6 fixe plus bas pour les générations d'avant 1949. Corrigé, et la
  table est désormais dans `legislation/duree_proratisation.csv` ;
* **chez lui** — sa table de durée requise ignore la réforme du 14 avril 2023 :
  il oppose 169 trimestres à la génération 1965, là où l'article L. 161-17-3
  lu dans la base LEGI en donne 172.

Ce que ce contrôle couvre, et ce qu'il ne couvre pas.

* **Le régime général seul.** L'Arrco du paquet publié est inutilisable :
  son code demande le paramètre `agirc_arrco.salaire_de_reference.
  salaire_reference_en_euros`, que les barèmes livrés ne définissent pas — ils
  portent `salaire_reference_prix_achat_valeur_nominale`. Toute liquidation
  postérieure à 2019 y lève une `ParameterNotFoundError`.
* **Les liquidations antérieures à 2025.** Les barèmes s'arrêtent : valeur du
  point Agirc-Arrco jusqu'en novembre 2024, revalorisations CNAV jusqu'en 2023.
* **Des carrières simples.** Salaire nominal constant, aucune interruption,
  aucun enfant, un seul régime de base : ce qui se décrit à l'identique des deux
  côtés, sans convention de traduction qui deviendrait l'objet du test.

UN PIÈGE, ET IL EST SILENCIEUX. Sans `simulation.max_spiral_loops`, la durée
d'assurance d'OpenFisca vaut zéro, le coefficient de proratisation vaut zéro et
la pension vaut zéro — sans qu'aucune exception ne soit levée. Un oracle
silencieusement nul valide tout. Ce script refuse donc d'écrire un profil dont
la durée d'assurance ou la pension serait nulle.

Le fichier produit, `tests/temoins/openfisca_regime_general.json`, est VERSIONNÉ
— contrairement à `data/brut/`. C'est ce qui permet à `tests/test_oracle.py` de
rejouer la confrontation sur un dépôt fraîchement cloné, sans installer
OpenFisca ni ses quatre cents mégaoctets de dépendances.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

SORTIE = Path("tests/temoins/openfisca_regime_general.json")

#: Profondeur de récursion demandée à OpenFisca. Chaque année de carrière
#: empile plusieurs appels, et une carrière de quarante ans dépasse largement
#: la limite par défaut de Python.
RECURSION = 20_000

#: Nombre de reprises autorisées à OpenFisca pour dérouler ses variables
#: récursives — celles qui lisent leur propre valeur de l'année précédente.
#: Sans cela, la durée d'assurance reste à zéro EN SILENCE.
SPIRALES = 100

#: Profils confrontés. Salaire nominal constant, carrière continue, un seul
#: régime, aucune interruption, aucun enfant : les seules situations qui se
#: décrivent à l'identique des deux côtés. Les liquidations sont toutes
#: antérieures à 2025, borne au-delà de laquelle les barèmes d'OpenFisca
#: s'arrêtent.
PROFILS: tuple[dict, ...] = (
    {"code": "carriere_complete_1948", "naissance": 1948, "debut": 1970,
     "liquidation": 2010, "salaire": 30000.0},
    {"code": "carriere_incomplete_1945", "naissance": 1945, "debut": 1968,
     "liquidation": 2007, "salaire": 25000.0},
    {"code": "carriere_complete_1950", "naissance": 1950, "debut": 1972,
     "liquidation": 2012, "salaire": 40000.0},
    {"code": "carriere_complete_1953", "naissance": 1953, "debut": 1975,
     "liquidation": 2015, "salaire": 30000.0},
    {"code": "carriere_incomplete_1955", "naissance": 1955, "debut": 1980,
     "liquidation": 2017, "salaire": 22000.0},
    {"code": "carriere_complete_1956", "naissance": 1956, "debut": 1978,
     "liquidation": 2018, "salaire": 30000.0},
    {"code": "depart_tardif_1949", "naissance": 1949, "debut": 1971,
     "liquidation": 2016, "salaire": 28000.0},
    {"code": "carriere_courte_1952", "naissance": 1952, "debut": 1990,
     "liquidation": 2014, "salaire": 35000.0},
    {"code": "bas_salaire_1947", "naissance": 1947, "debut": 1969,
     "liquidation": 2009, "salaire": 14000.0},
    {"code": "haut_salaire_1954", "naissance": 1954, "debut": 1976,
     "liquidation": 2016, "salaire": 60000.0},
)

#: Grandeurs relevées, et le nom sous lequel le témoin les porte.
GRANDEURS = {
    "duree_assurance": "regime_general_cnav_duree_assurance",
    "salaire_de_reference": "regime_general_cnav_salaire_de_reference",
    "coefficient_de_proratisation": "regime_general_cnav_coefficient_de_proratisation",
    "decote_trimestres": "regime_general_cnav_decote_trimestres",
    "taux_de_liquidation": "regime_general_cnav_taux_de_liquidation",
    "pension_brute": "regime_general_cnav_pension_brute",
}


def calculer(profil: dict, tbs) -> dict[str, float]:
    """Relève les six grandeurs du régime général pour un profil."""
    from openfisca_core.simulation_builder import SimulationBuilder

    annees = [str(a) for a in range(profil["debut"], profil["liquidation"])]
    situation = {
        "date_de_naissance": {"ETERNITY": f"{profil['naissance']}-01-01"},
        "sexe": {"ETERNITY": False},
        "nombre_enfants": {"ETERNITY": 0},
        "regime_general_cnav_liquidation_date": {
            "ETERNITY": f"{profil['liquidation']}-01-01"
        },
        "regime_general_cnav_salaire_de_base": {a: profil["salaire"] for a in annees},
        "statut_du_cotisant": {a: "emploi" for a in annees},
        "categorie_salarie": {a: "prive_non_cadre" for a in annees},
    }
    simulation = SimulationBuilder().build_from_entities(
        tbs, {"persons": {"assure": situation}}
    )
    simulation.max_spiral_loops = SPIRALES
    return {
        nom: float(simulation.calculate(variable, profil["liquidation"])[0])
        for nom, variable in GRANDEURS.items()
    }


def main(argv: list[str] | None = None) -> int:
    sys.setrecursionlimit(RECURSION)
    try:
        from openfisca_france_pension import CountryTaxBenefitSystem
    except ImportError:
        print(
            "OpenFisca-France-Pension n'est pas installé.\n"
            "    pip install OpenFisca-France-Pension\n"
            "Il n'est PAS une dépendance du dépôt : le témoin qu'il produit est "
            "versionné, et les tests s'en contentent.",
            file=sys.stderr,
        )
        return 1

    tbs = CountryTaxBenefitSystem()
    releves = {}
    for profil in PROFILS:
        mesures = calculer(profil, tbs)
        # Garde-fou : sans `max_spiral_loops`, OpenFisca rend zéro sans se
        # plaindre. Un oracle nul validerait n'importe quoi.
        if mesures["duree_assurance"] <= 0 or mesures["pension_brute"] <= 0:
            print(
                f"{profil['code']} : OpenFisca rend une durée ou une pension "
                "nulle — le déroulage récursif n'a pas eu lieu. Rien n'est écrit.",
                file=sys.stderr,
            )
            return 1
        releves[profil["code"]] = {"profil": profil, "openfisca": mesures}

    from importlib.metadata import PackageNotFoundError, version

    try:
        publiee = version("OpenFisca-France-Pension")
    except PackageNotFoundError:  # pragma: no cover - paquet posé à la main
        publiee = "inconnue"

    document = {
        "source": "OpenFisca-France-Pension",
        "version": publiee,
        "recupere_le": date.today().isoformat(),
        "avertissement": (
            "Deuxième implémentation, pas une source officielle. Un désaccord "
            "ne désigne pas d'office le coupable : la table de durée requise "
            "d'OpenFisca ignore la réforme du 14 avril 2023."
        ),
        "perimetre": (
            "Régime général seul, liquidations antérieures à 2025, carrières "
            "à salaire nominal constant sans interruption ni enfant."
        ),
        "profils": releves,
    }
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"{SORTIE} : {len(releves)} profils")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
