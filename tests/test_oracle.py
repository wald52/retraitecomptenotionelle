"""Confrontation du scénario 1 à une SECONDE IMPLÉMENTATION, écrite par d'autres.

Le scénario « système actuel » est l'étalon du modèle : tous les écarts affichés
se mesurent par rapport à lui. Le vérifier en le relisant ne prouve rien — une
réimplémentation écrite par la même main hérite des mêmes hypothèses. Et aucun
simulateur officiel n'est automatisable : M@rel exige FranceConnect et le relevé
de carrière réel, sans mode anonyme ni API.

Reste OpenFisca-France-Pension, le module « retraites » de l'écosystème
OpenFisca. Ce n'est pas une source officielle, c'est un autre modèle — mais il
est écrit par d'autres, à partir des mêmes textes, et c'est exactement ce qui
manquait. La première confrontation a produit deux désaccords, un de chaque
côté : la durée de proratisation, que nous confondions avec la durée requise
(corrigé), et sa table de durée requise, qui ignore la réforme du 14 avril 2023.

**Ce test n'installe pas OpenFisca.** Il rejoue le témoin versionné que
`scripts/fetch/openfisca_regime_general.py` a figé, ce qui le rend exécutable
sur un dépôt fraîchement cloné, sans les quatre cents mégaoctets de numpy,
pandas et numba.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from retraite_notionnelle.carriere import AnneeCarriere, Carriere
from retraite_notionnelle.config import Parametres
from retraite_notionnelle.simulateur import Simulateur

TEMOIN = Path(__file__).resolve().parent / "temoins" / "openfisca_regime_general.json"

#: Tolérance sur les grandeurs comparées.
#:
#: Elle valait 8 % : le salaire annuel moyen était le seul poste où les deux
#: modèles divergeaient, de 0,30 % à 7,55 %, et toujours dans le même sens.
#: La cause en était les coefficients de revalorisation des salaires portés au
#: compte, que le modèle approchait par « les salaires jusqu'en 1986, les prix
#: depuis » — une approximation qui SUR-REVALORISE les salaires anciens de 12 à
#: 14 % sur quarante ans.
#:
#: Les coefficients des arrêtés sont désormais dans le dépôt
#: (`legislation/revalorisation_salaires.csv`), et l'écart tombe à 4·10⁻⁶ : ce
#: qui restait est l'arrondi à six chiffres significatifs de la table. La
#: tolérance n'est donc plus une marge d'approximation mais une marge de
#: précision numérique, et le test devient un vrai contrôle d'égalité.
TOLERANCE = 1e-4


@pytest.fixture(scope="module")
def oracle() -> dict:
    return json.loads(TEMOIN.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def simulateur() -> Simulateur:
    return Simulateur(Parametres())


def _notre_calcul(simulateur: Simulateur, profil: dict) -> dict[str, float]:
    """Le régime général du scénario 1, sur la carrière exacte du témoin."""
    lignes = [
        AnneeCarriere(
            annee=annee, revenu=profil["salaire"],
            affiliation="salarie_prive_non_cadre", trimestres_valides=4,
        )
        for annee in range(profil["debut"], profil["liquidation"])
    ]
    carriere = Carriere(
        annee_naissance=profil["naissance"], sexe="H", lignes=lignes,
        age_liquidation=float(profil["liquidation"] - profil["naissance"]),
        identifiant=profil["code"],
    )
    scenario = simulateur.scenario_actuel
    resultat = scenario.calculer(carriere)
    periode = simulateur.catalogue["regime_general"].periode(profil["liquidation"])
    requis, _ = scenario._duree_requise(periode, carriere)
    proratisation, _ = scenario._duree_proratisation(periode, carriere, requis)
    _, age_annulation, _ = scenario._decote(
        periode, carriere, profil["liquidation"]
    )
    base = next(
        p for p in resultat.pensions_par_regime if p.regime == "regime_general"
    )
    return {
        "duree_assurance": float(resultat.trimestres_valides),
        "salaire_de_reference": scenario.salaire_de_reference(
            "regime_general", carriere, periode, profil["liquidation"],
            True, profil["naissance"], True,
        ),
        "coefficient_de_proratisation": (
            min(resultat.trimestres_valides, proratisation) / proratisation
        ),
        "decote_trimestres": float(scenario._trimestres_de_decote(
            periode, resultat.trimestres_valides, requis,
            profil["liquidation"] - profil["naissance"], age_annulation,
        )),
        "taux_de_liquidation": resultat.taux_liquidation,
        "pension_brute": base.montant,
    }


def test_le_temoin_couvre_le_perimetre_annonce(oracle):
    """Le témoin doit dire d'où il vient, et rester dans ce qu'OpenFisca sait faire.

    Ses barèmes s'arrêtent en 2024 — valeur du point Agirc-Arrco en novembre
    2024, revalorisations CNAV en 2023 — et son Arrco est cassé dans la version
    publiée. Un profil qui déborderait ces bornes produirait une comparaison
    sans valeur, ou pas de comparaison du tout.
    """
    assert oracle["source"] == "OpenFisca-France-Pension"
    assert oracle["version"]
    assert len(oracle["profils"]) >= 8
    for code, entree in oracle["profils"].items():
        assert entree["profil"]["liquidation"] < 2025, code
        # Le garde-fou du récupérateur : un oracle silencieusement nul
        # validerait n'importe quoi.
        assert entree["openfisca"]["duree_assurance"] > 0, code
        assert entree["openfisca"]["pension_brute"] > 0, code


def test_la_duree_dassurance_concorde(oracle, simulateur):
    """Trimestres validés : les deux modèles doivent compter pareil."""
    for code, entree in oracle["profils"].items():
        nous = _notre_calcul(simulateur, entree["profil"])
        assert nous["duree_assurance"] == entree["openfisca"]["duree_assurance"], code


def test_la_decote_concorde_trimestre_par_trimestre(oracle, simulateur):
    """Le décompte des trimestres de décote, et le taux qui en découle.

    C'est le contrôle le plus exigeant du lot : il met en jeu la durée requise
    par génération, l'âge d'annulation de la décote par génération, la règle du
    minimum entre les deux décomptes, le plafond de vingt trimestres et
    l'arrondi à l'entier supérieur. Cinq tables et trois règles doivent tomber
    juste ensemble.
    """
    for code, entree in oracle["profils"].items():
        nous, eux = _notre_calcul(simulateur, entree["profil"]), entree["openfisca"]
        assert nous["decote_trimestres"] == eux["decote_trimestres"], code
        assert nous["taux_de_liquidation"] == pytest.approx(
            eux["taux_de_liquidation"], abs=1e-4
        ), code


def test_la_proratisation_concorde(oracle, simulateur):
    """Le coefficient de proratisation, et son dénominateur.

    C'est ce contrôle qui a révélé que le modèle confondait la durée requise
    pour le taux plein et la durée maximale prise en compte par la
    proratisation, que l'article R. 351-6 fixe plus bas pour les générations
    d'avant 1949. Un assuré né en 1945 avec 156 trimestres y perdait 2,5 % de
    pension de base que le droit ne lui retire pas.
    """
    for code, entree in oracle["profils"].items():
        nous, eux = _notre_calcul(simulateur, entree["profil"]), entree["openfisca"]
        assert nous["coefficient_de_proratisation"] == pytest.approx(
            eux["coefficient_de_proratisation"], abs=1e-4
        ), code


def test_le_salaire_de_reference_concorde(oracle, simulateur):
    """Le salaire annuel moyen, dernier poste à avoir divergé.

    Il divergeait de 0,30 % à 7,55 %, toujours dans le même sens, parce que le
    modèle approchait les coefficients de revalorisation des salaires portés au
    compte au lieu de les lire. Ils sont maintenant dans le dépôt, et les deux
    modèles tombent sur le même salaire de référence à l'arrondi près.
    """
    for code, entree in oracle["profils"].items():
        nous, eux = _notre_calcul(simulateur, entree["profil"]), entree["openfisca"]
        assert nous["salaire_de_reference"] == pytest.approx(
            eux["salaire_de_reference"], rel=TOLERANCE
        ), code


def test_la_pension_de_base_concorde(oracle, simulateur):
    """Le bout de la chaîne : deux implémentations, une pension.

    C'est le contrôle qui donne son prix à la confrontation. Salaire de
    référence, taux, coefficient de proratisation : chacun a été vérifié
    séparément, et leur produit doit tomber juste — un écart qui n'apparaîtrait
    qu'ici signalerait une règle appliquée dans le mauvais ordre.
    """
    for code, entree in oracle["profils"].items():
        nous, eux = _notre_calcul(simulateur, entree["profil"]), entree["openfisca"]
        assert nous["pension_brute"] == pytest.approx(
            eux["pension_brute"], rel=TOLERANCE
        ), code
