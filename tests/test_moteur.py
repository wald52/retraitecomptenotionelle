"""Tests du moteur : indexation, âge de référence, conversion, fusion, compte."""

from __future__ import annotations

import pytest

from retraite_notionnelle.config import (
    ModeAgeReference,
    ModeIndexation,
    Parametres,
    RACINE_DONNEES,
    TableConversion,
)
from retraite_notionnelle.donnees.macro import DonneesMacro
from retraite_notionnelle.donnees.mortalite import DonneesMortalite
from retraite_notionnelle.donnees.regimes import CatalogueRegimes
from retraite_notionnelle.moteur.age_reference import AgeReference
from retraite_notionnelle.moteur.conversion import Convertisseur
from retraite_notionnelle.moteur.fusion import CritereTaux, RegleFusion, fusionner
from retraite_notionnelle.moteur.indexation import Indexation


@pytest.fixture(scope="module")
def macro() -> DonneesMacro:
    return DonneesMacro(RACINE_DONNEES)


@pytest.fixture(scope="module")
def mortalite() -> DonneesMortalite:
    return DonneesMortalite(RACINE_DONNEES, cache_disque=False)


@pytest.fixture(scope="module")
def catalogue() -> CatalogueRegimes:
    return CatalogueRegimes(RACINE_DONNEES)


# -- indexation --------------------------------------------------------------


def test_triple_lock_inverse_retient_bien_le_minimum(macro):
    indexation = Indexation(macro, Parametres())
    for annee in (1975, 1990, 2005, 2020):
        taux = indexation.taux(annee)
        assert taux.taux == min(taux.inflation, taux.salaire_moyen, taux.productivite)


def test_triple_lock_inverse_est_domine_par_la_productivite_en_forte_inflation(macro):
    """Le mélange réel/nominal fait gagner la productivité dès que l'inflation monte."""
    indexation = Indexation(macro, Parametres())
    for annee in (1974, 1980, 1981):
        assert indexation.taux(annee).terme_retenu == "productivite_reelle"


def test_regle_litterale_detruit_le_pouvoir_d_achat_des_comptes_anciens(macro):
    """Constat central du modèle, à ne pas perdre de vue en lisant les résultats.

    Sur 1941-2025, la règle littérale revalorise les comptes d'un facteur voisin
    de 5 quand les prix sont multipliés par plus de 300 : une cotisation de
    l'immédiat après-guerre ne conserve que quelques pour cent de sa valeur
    réelle. La variante nominale, qui ramène la productivité en termes nominaux
    avant de prendre le minimum, en conserve l'essentiel.
    """
    litterale = Indexation(macro, Parametres())
    nominale = Indexation(
        macro, Parametres(mode_indexation=ModeIndexation.TRIPLE_LOCK_INVERSE_NOMINAL)
    )
    prix = macro.coefficient_prix(1941, 2025)
    cumul_litteral = litterale.coefficient(1941, 2025)
    cumul_nominal = nominale.coefficient(1941, 2025)

    assert cumul_litteral / prix < 0.05, "la règle littérale devrait tout écraser"
    assert cumul_nominal / prix > 0.50, "la variante nominale devrait préserver l'essentiel"
    assert cumul_nominal > 10 * cumul_litteral


def test_indexation_prix_reproduit_l_inflation(macro):
    indexation = Indexation(macro, Parametres(mode_indexation=ModeIndexation.PRIX))
    assert indexation.coefficient(1980, 2020) == pytest.approx(
        macro.coefficient_prix(1980, 2020)
    )


def test_plancher_d_indexation_est_respecte(macro):
    indexation = Indexation(macro, Parametres(plancher_indexation=0.0))
    for annee in range(1941, 2026):
        assert indexation.taux(annee).taux >= 0.0


def test_coefficient_ne_revalorise_pas_l_annee_du_versement(macro):
    indexation = Indexation(macro, Parametres())
    assert indexation.coefficient(2000, 2000) == 1.0
    assert indexation.coefficient(2000, 2001) == pytest.approx(
        1 + indexation.taux(2001).taux
    )


# -- âge de référence --------------------------------------------------------


def test_cliquet_ne_redescend_jamais(mortalite):
    reference = AgeReference(RACINE_DONNEES, Parametres(), mortalite)
    precedent = 0.0
    for annee in range(1945, 2031):
        courant = reference.age(annee)
        assert courant >= precedent, f"l'âge de référence recule en {annee}"
        precedent = courant


def test_abaissement_de_1982_ne_baisse_pas_la_reference(mortalite):
    """Cœur du cahier des charges : partir à 60 ans en 1990 = 5 ans d'anticipation."""
    reference = AgeReference(RACINE_DONNEES, Parametres(), mortalite)
    assert reference.age(1990) == 65.0
    ecart = reference.ecart(60.0, 1990)
    assert ecart.ecart == pytest.approx(5.0)
    assert ecart.anticipe


def test_sans_cliquet_la_reference_suit_le_droit_positif(mortalite):
    reference = AgeReference(
        RACINE_DONNEES,
        Parametres(mode_age_reference=ModeAgeReference.LEGAL_SANS_CLIQUET),
        mortalite,
    )
    assert reference.age(1990) == 60.0
    assert reference.ecart(60.0, 1990).ecart == pytest.approx(0.0)


def test_depart_de_regime_special_a_50_ans(mortalite):
    """Un agent de conduite parti à 50 ans en 1990 anticipe de 15 ans."""
    reference = AgeReference(RACINE_DONNEES, Parametres(), mortalite)
    assert reference.ecart(50.0, 1990).ecart == pytest.approx(15.0)


def test_report_est_compte_negativement(mortalite):
    reference = AgeReference(RACINE_DONNEES, Parametres(), mortalite)
    ecart = reference.ecart(69.0, 2026)
    assert ecart.ecart < 0
    assert not ecart.anticipe


# -- conversion --------------------------------------------------------------


def test_diviseur_decroit_avec_l_age_de_liquidation(mortalite):
    convertisseur = Convertisseur(mortalite, Parametres())
    precedent = None
    for age in (55, 60, 62, 64, 67, 70):
        diviseur = convertisseur.coefficient(age, 2026).diviseur
        if precedent is not None:
            assert diviseur < precedent, f"le diviseur ne baisse pas à {age} ans"
        precedent = diviseur


def test_anticipation_reduit_la_pension_sans_decote_administrative(mortalite):
    """La sanction du départ anticipé est produite par le seul diviseur."""
    convertisseur = Convertisseur(mortalite, Parametres())
    rapport = convertisseur.effet_anticipation(59.0, 64.0, 2026)
    assert rapport < 1.0
    # Cinq ans d'anticipation coûtent de l'ordre de 15 % de pension annuelle,
    # avant même de compter les cotisations non versées.
    assert 0.75 < rapport < 0.92


def test_diviseur_nul_de_taux_anticipe_vaut_esperance_de_vie(mortalite):
    convertisseur = Convertisseur(mortalite, Parametres(taux_anticipe_conversion=0.0))
    coefficient = convertisseur.coefficient(64, 2026)
    assert coefficient.diviseur == pytest.approx(coefficient.esperance_residuelle, rel=1e-6)


def test_taux_anticipe_positif_reduit_le_diviseur(mortalite):
    sans = Convertisseur(mortalite, Parametres()).coefficient(64, 2026)
    avec = Convertisseur(
        mortalite, Parametres(taux_anticipe_conversion=0.015)
    ).coefficient(64, 2026)
    assert avec.diviseur < sans.diviseur


def test_table_par_sexe_penalise_les_femmes(mortalite):
    """Justification du choix unisexe par défaut : l'écart est loin d'être marginal."""
    convertisseur = Convertisseur(
        mortalite, Parametres(table_conversion=TableConversion.PAR_SEXE)
    )
    homme = convertisseur.coefficient(64, 2026, "H").diviseur
    femme = convertisseur.coefficient(64, 2026, "F").diviseur
    assert femme > homme
    assert (femme / homme - 1) > 0.05


def test_table_par_sexe_exige_le_sexe(mortalite):
    convertisseur = Convertisseur(
        mortalite, Parametres(table_conversion=TableConversion.PAR_SEXE)
    )
    with pytest.raises(ValueError, match="sexe non renseigné"):
        convertisseur.coefficient(64, 2026, None)


# -- fusion ------------------------------------------------------------------


def test_fusion_retient_les_ages_les_plus_eleves(catalogue):
    fusionne = fusionner(catalogue, 2026)
    for regime in catalogue:
        if regime.hors_repartition or not regime.vivant(2026):
            continue
        for periode in regime.periodes_actives(2026):
            assert periode.age_ouverture <= fusionne.age_ouverture
            assert periode.age_taux_plein <= fusionne.age_taux_plein


def test_fusion_supprime_tous_les_avantages_non_contributifs(catalogue):
    assert fusionner(catalogue, 2026).avantages_non_contributifs == ()


def test_fusion_retient_le_salaire_de_reference_le_moins_avantageux(catalogue):
    assert fusionner(catalogue, 2026).salaire_reference == "carriere_entiere"


def test_fusion_deplafonne_l_assiette(catalogue):
    assert fusionner(catalogue, 2026).assiette == "deplafonnee"


def test_fusion_somme_les_taux_du_statut_pivot(catalogue):
    fusionne = fusionner(catalogue, 2026)
    attendu = (
        catalogue["regime_general"].periode(2026).taux_cotisation_retraite
        + min(catalogue["agirc_arrco"].periodes_actives(2026),
              key=lambda p: p.bornes_assiette_en_pass()[0]).taux_cotisation_retraite
    )
    assert fusionne.taux_cotisation_retraite == pytest.approx(attendu)


def test_fusion_exclut_la_capitalisation(catalogue):
    assert "rafp" not in fusionner(catalogue, 2026).regimes_fusionnes


def test_fusion_variante_taux_le_plus_eleve(catalogue):
    fusionne = fusionner(
        catalogue, 2026, RegleFusion(critere_taux=CritereTaux.LE_PLUS_ELEVE)
    )
    maxima = max(
        periode.taux_cotisation_retraite
        for regime in catalogue if regime.vivant(2026) and not regime.hors_repartition
        for periode in regime.periodes_actives(2026)
    )
    assert fusionne.taux_cotisation_retraite == pytest.approx(maxima)
