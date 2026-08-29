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


@pytest.fixture(scope="module")
def quotients() -> dict[tuple[int, str, int], float]:
    """Table des quotients de mortalité observés, clé (année, sexe, âge)."""
    import csv

    chemin = RACINE_DONNEES / "reference" / "mortalite" / "quotients_periode.csv"
    with chemin.open(encoding="utf-8") as flux:
        lignes = (l for l in flux if not l.lstrip().startswith("#"))
        return {
            (int(l["annee"]), l["sexe"], int(l["age"])): float(l["qx"])
            for l in csv.DictReader(lignes)
        }


@pytest.fixture(scope="module")
def esperances() -> dict[tuple[int, str, str], float]:
    """Fichier des espérances de vie relu tel quel, clé (année, sexe, mesure)."""
    import csv

    chemin = RACINE_DONNEES / "reference" / "mortalite" / "esperances_vie.csv"
    with chemin.open(encoding="utf-8") as flux:
        lignes = (l for l in flux if not l.lstrip().startswith("#"))
        return {
            (int(l["annee"]), l["sexe"], l["mesure"]): float(l["valeur"])
            for l in csv.DictReader(lignes)
        }


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
        macro.inflation(1941, fiabilite_minimale=Fiabilite.HAUTE)


# -- certification des séries ------------------------------------------------


def test_series_macro_certifiees_depuis_1950(macro):
    """Ce que les sources automatisables couvrent doit être au niveau certifiee.

    1950 est la première année où l'indice des prix, les comptes nationaux et
    l'emploi sont tous trois publiés en série continue par l'INSEE.
    """
    for serie in (macro.inflation, macro.salaire_moyen, macro.productivite):
        assert serie.fiabilite_minimale_sur(1950, 2025) == Fiabilite.CERTIFIEE, serie.nom


def test_ce_qui_precede_1950_reste_annonce_comme_estime(macro):
    """Aucune source n'existe pour l'avant-guerre : le dire, plutôt que l'oublier."""
    for serie in (macro.inflation, macro.salaire_moyen, macro.productivite):
        assert serie.fiabilite(1935) == Fiabilite.ESTIMEE, serie.nom


def test_plafond_certifie_sur_la_periode_publiee_par_l_insee(macro):
    assert macro.plafond_securite_sociale.fiabilite(2010) == Fiabilite.CERTIFIEE


def test_plafond_ancien_vient_d_une_transcription_pas_du_producteur(macro):
    """Le plafond d'avant 2002 vaut « haute », jamais « certifiee ».

    Il vient d'OpenFisca-France, transcription du Journal officiel : publiée,
    sourcée, reprise automatiquement — mais pas de la main du producteur.
    """
    for annee in (1945, 1960, 1985, 2001):
        assert macro.plafond_securite_sociale.fiabilite(annee) == Fiabilite.HAUTE, annee


def test_plafond_est_strictement_croissant(macro):
    """Un plafond qui recule trahirait une conversion de francs manquée."""
    serie = macro.plafond_securite_sociale
    annees = [a for a in serie.annees() if a <= 2026]
    for precedente, courante in zip(annees, annees[1:]):
        assert serie(courante) >= serie(precedente), courante


def test_esperances_de_vie_annuelles_sans_interpolation(esperances):
    """Une valeur observée par année : le chargeur n'a plus rien à interpoler."""
    for sexe in ("H", "F"):
        annees = {a for (a, s, m) in esperances if s == sexe and m == "e60"}
        assert set(range(1946, 2026)) <= annees


def test_esperance_a_65_ans_certifiee_depuis_1960(mortalite):
    """L'INSEE ne publie pas e65 : la certification s'arrête où l'OCDE commence."""
    assert mortalite.loi(2010, "H").fiabilite == Fiabilite.CERTIFIEE
    assert mortalite.loi(1960, "H").fiabilite == Fiabilite.CERTIFIEE
    assert mortalite.loi(1950, "H").fiabilite < Fiabilite.CERTIFIEE


def test_le_modele_utilise_les_tables_de_mortalite_observees(mortalite):
    assert mortalite.utilise_tables_reelles


def test_les_quotients_observes_priment_sur_la_calibration(mortalite, quotients):
    """Là où une table existe, c'est elle qui sort — pas la loi paramétrique."""
    assert mortalite.survie_annuelle(70, 2015, "H") == pytest.approx(
        1 - quotients[(2015, "H", 70)]
    )
    # Au-delà du dernier âge publié, la loi paramétrique reprend la main sans
    # rupture : la survie doit rester dans une plage plausible.
    assert 0.5 < mortalite.survie_annuelle(96, 2015, "H") < 0.95


def test_les_tables_observees_reproduisent_les_esperances_publiees(mortalite, esperances):
    """Deux sources indépendantes doivent décrire la même mortalité.

    Les quotients viennent d'Eurostat, les espérances de l'INSEE et de l'OCDE.
    Si l'espérance recalculée à partir des quotients s'écartait nettement de
    l'espérance publiée, c'est que les deux ne portent pas sur le même champ.
    """
    for annee in (2000, 2015, 2020):
        for sexe in ("H", "F"):
            recalculee = mortalite.esperance_residuelle(60, annee, sexe, generation=False)
            assert recalculee == pytest.approx(esperances[(annee, sexe, "e60")], abs=0.4)


def test_journal_de_certification_decrit_les_series_certifiees():
    """La trace de certification doit rester en phase avec les fichiers.

    ``data/brut/`` n'est pas versionné : ce journal est la seule pièce qui
    permette, sur un dépôt fraîchement cloné, de savoir d'où viennent les
    valeurs marquées ``certifiee`` et combien elles sont.
    """
    import collections
    import csv
    import json

    journal = json.loads(
        (RACINE_DONNEES / "derive" / "certification.json").read_text(encoding="utf-8")
    )
    fichiers = {
        "inflation": "macro/ipc_annuel.csv",
        "salaire_moyen": "macro/salaire_moyen.csv",
        "productivite": "macro/productivite.csv",
        "plafond": "macro/plafond_securite_sociale.csv",
        "plafond_ancien": "macro/plafond_securite_sociale.csv",
        "esperances_vie": "mortalite/esperances_vie.csv",
        "quotients_mortalite": "mortalite/quotients_periode.csv",
        "quotients_mortalite_anciens": "mortalite/quotients_periode.csv",
        "valeurs_point": "regimes/valeurs_point.csv",
        "valeurs_point_ircantec": "regimes/valeurs_point.csv",
        "valeurs_point_cnbf": "regimes/valeurs_point.csv",
        "valeurs_point_cnavpl": "regimes/valeurs_point.csv",
        "valeurs_point_insee": "regimes/valeurs_point.csv",
        "valeurs_point_msa": "regimes/valeurs_point.csv",
        "valeurs_point_unirs": "regimes/valeurs_point.csv",
        "valeurs_point_texte": "regimes/valeurs_point.csv",
    }
    assert set(journal["series"]) == set(fichiers)

    # Deux contrôles peuvent viser le même fichier à des niveaux différents —
    # le plafond en est le cas : INSEE certifie 2002-2025, OpenFisca renseigne
    # tout ce qui précède au niveau « haute ». On compare donc par (fichier,
    # niveau), pas contrôle par contrôle.
    attendu: dict[tuple[str, str], int] = collections.Counter()
    for nom, trace in journal["series"].items():
        attendu[(fichiers[nom], trace["niveau"])] += trace["valeurs"]

    constate: dict[tuple[str, str], int] = collections.Counter()
    for chemin_relatif in set(fichiers.values()):
        chemin = RACINE_DONNEES / "reference" / chemin_relatif
        with chemin.open(encoding="utf-8") as flux:
            lignes = (l for l in flux if not l.lstrip().startswith("#"))
            for ligne in csv.DictReader(lignes):
                constate[(chemin_relatif, ligne["fiabilite"])] += 1

    for cle, nombre in attendu.items():
        assert constate[cle] == nombre, cle


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


def test_calibration_reproduit_les_esperances_publiees(mortalite, esperances):
    """La table paramétrique doit retomber sur ses cibles à 0,05 an près.

    Les cibles sont relues dans le fichier de référence plutôt que recopiées
    ici : c'est la source qui fait foi, et une recertification ne doit pas
    demander de retoucher le test.
    """
    for annee, sexe in [(2024, "H"), (2024, "F"), (1980, "H"), (1960, "F")]:
        loi = mortalite.loi(annee, sexe)
        assert loi.esperance(60) == pytest.approx(esperances[(annee, sexe, "e60")], abs=0.05)
        assert loi.esperance(65) == pytest.approx(esperances[(annee, sexe, "e65")], abs=0.05)


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
