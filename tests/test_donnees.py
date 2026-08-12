"""Tests du socle de données : chargement, fiabilité, cohérence du catalogue."""

from __future__ import annotations

import pytest

from retraite_notionnelle.config import RACINE_DONNEES
from retraite_notionnelle.donnees.chargement import DonneeInsuffisante, Fiabilite
from retraite_notionnelle.donnees.macro import DonneesMacro
from retraite_notionnelle.donnees.mortalite import DonneesMortalite
from retraite_notionnelle.donnees.regimes import CatalogueRegimes


@pytest.fixture(scope="module")
def macro() -> DonneesMacro:
    return DonneesMacro(RACINE_DONNEES)


@pytest.fixture(scope="module")
def catalogue() -> CatalogueRegimes:
    return CatalogueRegimes(RACINE_DONNEES)


@pytest.fixture(scope="module")
def mortalite() -> DonneesMortalite:
    return DonneesMortalite(RACINE_DONNEES, cache_disque=False)


# -- séries macro ------------------------------------------------------------


def test_series_macro_couvrent_toute_la_periode(macro):
    for serie in (macro.inflation, macro.salaire_moyen, macro.productivite):
        assert serie.premiere_annee <= 1941, f"{serie.nom} commence trop tard"
        assert serie.derniere_annee >= 2070, f"{serie.nom} ne va pas assez loin"


def test_annees_projetees_sont_de_fiabilite_minimale(macro):
    """Une projection ne doit jamais se faire passer pour une observation."""
    assert macro.inflation.fiabilite(2050) == Fiabilite.ESTIMEE
    assert macro.inflation.fiabilite(2000) > Fiabilite.ESTIMEE


def test_projection_applique_le_scenario_choisi():
    central = DonneesMacro(RACINE_DONNEES, scenario_projection="cor_central")
    defavorable = DonneesMacro(RACINE_DONNEES, scenario_projection="cor_defavorable")
    assert central.productivite(2050) == pytest.approx(0.010)
    assert defavorable.productivite(2050) == pytest.approx(0.007)


def test_scenario_de_projection_inconnu_est_rejete():
    with pytest.raises(KeyError):
        DonneesMacro(RACINE_DONNEES, scenario_projection="inexistant").productivite(2050)


def test_coefficient_prix_est_reversible(macro):
    aller = macro.coefficient_prix(1975, 2020)
    retour = macro.coefficient_prix(2020, 1975)
    assert aller * retour == pytest.approx(1.0)
    assert aller > 1.0


def test_plafond_croit_apres_la_derniere_valeur_publiee(macro):
    assert macro.plafond_securite_sociale(2040) > macro.plafond_securite_sociale(2026)


def test_serie_refuse_une_fiabilite_insuffisante(macro):
    with pytest.raises(DonneeInsuffisante):
        macro.inflation(1946, fiabilite_minimale=Fiabilite.HAUTE)


# -- catalogue des régimes ---------------------------------------------------


def test_catalogue_couvre_les_grandes_familles(catalogue):
    familles = {regime.famille for regime in catalogue}
    assert {"base_prive", "complementaire_prive", "fonction_publique",
            "special", "non_salarie", "agricole"} <= familles


def test_catalogue_contient_des_regimes_disparus(catalogue):
    """Le cahier des charges impose les régimes passés, pas seulement actuels."""
    for code in ("agirc", "arrco", "cancava", "organic", "rsi", "seita", "mines"):
        assert code in catalogue, f"régime disparu manquant : {code}"
        assert catalogue[code].fermeture is not None


def test_periodes_de_regime_sont_ordonnees_et_jointives(catalogue):
    for regime in catalogue:
        # Les régimes à tranches ont plusieurs périodes simultanées : on ne
        # teste la continuité que pour les autres.
        assiettes = {p.assiette for p in regime.periodes}
        if len(assiettes) > 1 and len(regime.periodes) > len(assiettes):
            continue
        precedente = None
        for periode in regime.periodes:
            if precedente is not None and precedente.fin is not None:
                assert periode.debut >= precedente.debut, regime.code
            precedente = periode


def test_taux_de_cotisation_plausibles(catalogue):
    for regime in catalogue:
        for periode in regime.periodes:
            assert 0.0 < periode.taux_cotisation_retraite < 0.60, (
                f"{regime.code} {periode.debut} : taux hors plage plausible"
            )


def test_ages_ouverture_inferieurs_au_taux_plein(catalogue):
    for regime in catalogue:
        for periode in regime.periodes:
            assert periode.age_ouverture <= periode.age_taux_plein, (
                f"{regime.code} {periode.debut}"
            )


def test_regimes_capitalises_sont_marques(catalogue):
    assert catalogue["rafp"].hors_repartition is True
    assert catalogue["assurances_sociales"].hors_repartition is True
    assert catalogue["regime_general"].hors_repartition is False


def test_resolution_de_succession(catalogue):
    assert catalogue.resoudre_succession("organic", 2010) == "rsi"
    assert catalogue.resoudre_succession("organic", 2020) == "regime_general"
    assert catalogue.resoudre_succession("regime_general", 2020) == "regime_general"


def test_regime_inconnu_leve_une_erreur_explicite(catalogue):
    with pytest.raises(KeyError, match="régime inconnu"):
        catalogue["nexiste_pas"]


# -- mortalité ---------------------------------------------------------------


def test_calibration_reproduit_les_esperances_publiees(mortalite):
    """La table paramétrique doit retomber sur ses cibles à 0,05 an près."""
    cas = [(2024, "H", 23.6, 19.8), (2024, "F", 27.8, 23.6),
           (1980, "H", 17.3, 13.6), (1960, "F", 19.5, 15.6)]
    for annee, sexe, e60, e65 in cas:
        loi = mortalite.loi(annee, sexe)
        assert loi.esperance(60) == pytest.approx(e60, abs=0.05)
        assert loi.esperance(65) == pytest.approx(e65, abs=0.05)


def test_esperance_decroit_avec_l_age(mortalite):
    precedente = None
    for age in (55, 60, 65, 70, 75):
        actuelle = mortalite.esperance_residuelle(age, 2026)
        if precedente is not None:
            assert actuelle < precedente
        precedente = actuelle


def test_table_de_generation_donne_plus_que_table_du_moment(mortalite):
    """La longévité progresse : ignorer la génération sous-estime la durée servie."""
    moment = mortalite.esperance_residuelle(62, 2026, generation=False)
    generation = mortalite.esperance_residuelle(62, 2026, generation=True)
    assert generation > moment


def test_esperance_progresse_dans_le_temps(mortalite):
    assert (mortalite.esperance_residuelle(65, 2020, generation=False)
            > mortalite.esperance_residuelle(65, 1960, generation=False))


def test_courbe_de_survie_est_decroissante(mortalite):
    courbe = mortalite.courbe_survie(60.0, 2020, "H")
    assert courbe[0] == pytest.approx(1.0)
    assert all(courbe[t] >= courbe[t + 1] for t in range(len(courbe) - 1))


def test_femmes_vivent_plus_longtemps_que_hommes(mortalite):
    assert (mortalite.esperance_residuelle(65, 2020, "F")
            > mortalite.esperance_residuelle(65, 2020, "H"))


def test_unisexe_est_entre_les_deux_sexes(mortalite):
    unisexe = mortalite.esperance_residuelle(65, 2020, None)
    homme = mortalite.esperance_residuelle(65, 2020, "H")
    femme = mortalite.esperance_residuelle(65, 2020, "F")
    assert homme < unisexe < femme
