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

#: Tolérance sur le salaire annuel moyen, et donc sur la pension qui en découle.
#:
#: C'est le seul poste où les deux modèles divergent, et l'écart est UNILATÉRAL :
#: nous sommes au-dessus sur les dix profils, de 0,30 % à 7,55 %. La cause est
#: unique et documentée dans `docs/limites.md` — les salaires portés au compte
#: sont revalorisés par des coefficients fixés chaque année par arrêté, qu'
#: OpenFisca porte en série (`revalorisation_salaire_cummulee`) là où nous les
#: approchons par « les salaires jusqu'en 1986, les prix depuis ».
#:
#: L'écart n'est pas monotone, et c'est normal : le salaire de référence retient
#: les N MEILLEURES années, si bien qu'un jeu de coefficients différent ne
#: déplace pas seulement le niveau de chaque année — il change lesquelles sont
#: retenues. Un écart de niveau de deux points peut donc en produire sept une
#: fois la sélection faite. Les deux modèles plafonnent bien au même plafond de
#: la Sécurité sociale, ramené en euros de part et d'autre : ce n'est pas là
#: qu'ils divergent.
#:
#: La borne est là pour que cet écart reste ce qu'il est : une approximation
#: bornée et connue, non un glissement qui s'installe. La refermer suppose de
#: reprendre la série d'OpenFisca, ce que ce récupérateur ne fait pas encore.
TOLERANCE_SALAIRE_DE_REFERENCE = 0.08


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


def test_le_salaire_de_reference_reste_dans_sa_marge(oracle, simulateur):
    """Le seul poste où les deux modèles divergent, et il doit rester borné.

    L'écart est unilatéral — nous sommes au-dessus — et sa cause est connue :
    les coefficients de revalorisation des salaires portés au compte. Le test
    vérifie les deux : que l'écart tient dans sa marge, et qu'il garde son sens,
    faute de quoi une erreur nouvelle pourrait le compenser sans se voir.
    """
    for code, entree in oracle["profils"].items():
        nous, eux = _notre_calcul(simulateur, entree["profil"]), entree["openfisca"]
        ecart = nous["salaire_de_reference"] / eux["salaire_de_reference"] - 1
        assert 0 <= ecart <= TOLERANCE_SALAIRE_DE_REFERENCE, (code, ecart)


def test_la_pension_de_base_ne_diverge_que_par_le_salaire_de_reference(
    oracle, simulateur
):
    """Tout le reste étant identique, l'écart de pension DOIT être celui du SAM.

    C'est l'invariant qui donne son prix à la confrontation : si la pension
    s'écartait autrement que par le salaire de référence, c'est qu'une règle
    aurait divergé sans que les grandeurs intermédiaires le montrent.
    """
    for code, entree in oracle["profils"].items():
        nous, eux = _notre_calcul(simulateur, entree["profil"]), entree["openfisca"]
        ecart_pension = nous["pension_brute"] / eux["pension_brute"] - 1
        ecart_salaire = nous["salaire_de_reference"] / eux["salaire_de_reference"] - 1
        assert ecart_pension == pytest.approx(ecart_salaire, abs=2e-3), code
