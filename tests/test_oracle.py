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

#: Tolérance sur la durée, la décote, le taux et la proratisation : ce sont des
#: comptages et des tables, ils doivent tomber juste à l'unité près.
TOLERANCE_EXACTE = 1e-4

#: Tolérance sur le salaire annuel moyen et sur la pension, qui en découle.
#:
#: Elle valait 8 % : le modèle approchait les coefficients de revalorisation des
#: salaires portés au compte par « les salaires jusqu'en 1986, les prix depuis »,
#: une approximation qui sur-revalorise les salaires anciens de 12 à 14 % sur
#: quarante ans.
#:
#: Le modèle lit désormais les coefficients dans la circulaire annuelle de la
#: Cnav, et **c'est OpenFisca qui s'en écarte** : sa table cumulée est de 3 à
#: 5,5 % en dessous de ce que la caisse publie pour toutes les perceptions
#: postérieures à 1990 — il lui manque la revalorisation exceptionnelle de 4 %
#: du 1er juillet 2022 — et jusqu'à 17 % à côté sur les années 1950. La
#: confrontation vaut toujours, mais elle ne peut plus être une égalité sur ce
#: poste : le désaccord résiduel, de 0,16 % à 2,22 %, est celui d'OpenFisca avec
#: la source. `tests/test_simulateur.py` vérifie, lui, que le modèle reproduit
#: la colonne que la caisse a publiée.
TOLERANCE_SALAIRE = 0.03


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
            eux["taux_de_liquidation"], abs=TOLERANCE_EXACTE
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
            eux["coefficient_de_proratisation"], abs=TOLERANCE_EXACTE
        ), code


def test_le_salaire_de_reference_reste_proche(oracle, simulateur):
    """Le salaire annuel moyen : le seul poste où les deux modèles diffèrent.

    Il divergeait de 0,30 % à 7,55 % quand le modèle APPROCHAIT les coefficients
    de revalorisation. Il les lit maintenant dans la circulaire de la Cnav, et
    ce qui reste — de 0,16 % à 2,22 % — n'est plus notre écart mais celui
    d'OpenFisca avec la source : il manque à sa table la revalorisation
    exceptionnelle de 4 % du 1er juillet 2022.

    Le test garde donc une borne large, et ce n'est pas un relâchement : le
    contrôle serré de cette grandeur est ailleurs, dans
    `test_les_coefficients_de_revalorisation_reproduisent_la_circulaire`, qui
    oppose au modèle la colonne que la caisse a publiée.
    """
    for code, entree in oracle["profils"].items():
        nous, eux = _notre_calcul(simulateur, entree["profil"]), entree["openfisca"]
        assert nous["salaire_de_reference"] == pytest.approx(
            eux["salaire_de_reference"], rel=TOLERANCE_SALAIRE
        ), code
        # Et toujours en dessous : l'écart a un sens, il n'est pas du bruit.
        assert nous["salaire_de_reference"] <= eux["salaire_de_reference"], code


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
            eux["pension_brute"], rel=TOLERANCE_SALAIRE
        ), code
