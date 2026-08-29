"""Tests des scénarios et du simulateur, au niveau du comportement attendu."""

from __future__ import annotations

import pytest

from retraite_notionnelle.carriere import AnneeCarriere, Carriere
from retraite_notionnelle.config import (
    AgeConversionDroitsAcquis,
    ModeIndexation,
    Neutralisations,
    Parametres,
)
from retraite_notionnelle.simulateur import Simulateur


@pytest.fixture(scope="module")
def simulateur() -> Simulateur:
    return Simulateur(Parametres())


@pytest.fixture(scope="module")
def salarie_moyen(simulateur) -> Carriere:
    return simulateur.carriere_simple(
        annee_naissance=1960, sexe="H", affiliation="salarie_prive_non_cadre",
        age_debut=21, age_liquidation=62, identifiant="salarié moyen",
    )


# -- construction de carrière ------------------------------------------------


def test_carriere_couvre_les_bonnes_annees(salarie_moyen):
    assert salarie_moyen.premiere_annee == 1981
    assert salarie_moyen.derniere_annee == 2021
    assert salarie_moyen.annee_liquidation == 2022


def test_interruptions_ne_produisent_aucune_cotisation(simulateur):
    carriere = simulateur.carriere_simple(
        annee_naissance=1970, sexe="F", affiliation="salarie_prive_non_cadre",
        age_debut=22, age_liquidation=64,
        interruptions={annee: "education_enfant" for annee in range(2000, 2005)},
    )
    for annee in range(2000, 2005):
        ligne = carriere.ligne(annee)
        assert ligne is not None and not ligne.cotise and ligne.revenu == 0.0


def test_affiliation_inconnue_est_rejetee(simulateur):
    with pytest.raises(KeyError, match="affiliation inconnue"):
        simulateur.carriere_simple(1970, "H", "boulanger_lunaire", 20, 64)


def test_liquidation_avant_debut_est_rejetee(simulateur):
    with pytest.raises(ValueError, match="antérieur"):
        simulateur.carriere_simple(1970, "H", "salarie_prive_non_cadre", 40, 30)


def test_carriere_sans_age_de_liquidation_est_signalee():
    carriere = Carriere(
        annee_naissance=1960, sexe="H",
        lignes=[AnneeCarriere(1990, 20000.0, "salarie_prive_non_cadre")],
    )
    with pytest.raises(ValueError, match="âge de liquidation"):
        _ = carriere.annee_liquidation


# -- les trois scénarios -----------------------------------------------------


def test_les_trois_scenarios_sont_calcules(simulateur, salarie_moyen):
    comparaison = simulateur.simuler(salarie_moyen)
    assert comparaison.actuel.pension_annuelle > 0
    assert comparaison.notionnel_retroactif.pension_annuelle > 0
    assert comparaison.notionnel_prospectif.pension_annuelle > 0


def test_retraite_deja_liquidee_est_inchangee_dans_le_scenario_prospectif(simulateur):
    """Un retraité de 2005 ne peut pas voir ses droits recalculés en 2026."""
    carriere = simulateur.carriere_simple(
        annee_naissance=1945, sexe="H", affiliation="salarie_prive_non_cadre",
        age_debut=20, age_liquidation=60,
    )
    comparaison = simulateur.simuler(carriere)
    assert comparaison.notionnel_prospectif.pension_annuelle == pytest.approx(
        comparaison.actuel.pension_annuelle
    )
    assert comparaison.variation("notionnel_prospectif") == pytest.approx(0.0)


def test_convertir_les_droits_acquis_a_l_age_de_depart_les_preserve(simulateur):
    """La convention de conversion est le seul abattement sur des droits ouverts.

    Converti au diviseur de l'âge de référence, un droit déjà acquis perd le
    rapport des deux diviseurs dès lors que l'assuré liquide avant cet âge.
    Converti à l'âge de départ effectif, il ne perd rien : la sanction
    d'anticipation ne joue plus que sur les cotisations, comme prévu.
    """
    neutre = Simulateur(
        Parametres().avec(
            age_conversion_droits_acquis=AgeConversionDroitsAcquis.LIQUIDATION
        )
    )
    carriere = simulateur.carriere_simple(
        annee_naissance=1975, sexe="H", affiliation="salarie_prive_non_cadre",
        age_debut=20, age_liquidation=64,
    )
    reference = simulateur.simuler(carriere).notionnel_prospectif
    liquidation = neutre.simuler(carriere).notionnel_prospectif

    assert reference.droits_acquis.age_conversion == pytest.approx(67.0)
    assert liquidation.droits_acquis.age_conversion == pytest.approx(64.0)
    # Un diviseur plus élevé à 64 ans qu'à 67 : le capital d'ouverture monte.
    assert liquidation.capital_droits_acquis > reference.capital_droits_acquis
    assert liquidation.pension_annuelle > reference.pension_annuelle
    # Les cotisations postérieures à la bascule, elles, ne bougent pas.
    assert liquidation.compte.capital == pytest.approx(reference.compte.capital)


def test_la_cascade_des_droits_acquis_reconstitue_le_capital(simulateur):
    """Les étapes publiées doivent redonner le capital, sinon elles mentent."""
    carriere = simulateur.carriere_simple(
        annee_naissance=1975, sexe="H", affiliation="salarie_prive_non_cadre",
        age_debut=20, age_liquidation=64,
    )
    prospectif = simulateur.simuler(carriere).notionnel_prospectif
    acquis = prospectif.droits_acquis

    assert acquis.capital_a_la_bascule == pytest.approx(
        acquis.pension_figee * acquis.diviseur
    )
    assert acquis.capital == pytest.approx(
        acquis.capital_a_la_bascule * acquis.coefficient_revalorisation
    )
    assert prospectif.capital_notionnel == pytest.approx(
        acquis.capital + prospectif.compte.capital
    )
    assert prospectif.pension_annuelle == pytest.approx(
        prospectif.capital_notionnel / prospectif.conversion.diviseur
    )


def test_sans_carriere_avant_la_bascule_il_n_y_a_aucun_droit_acquis(simulateur):
    """Une carrière entièrement postérieure à 2026 n'a rien à convertir."""
    carriere = simulateur.carriere_simple(
        annee_naissance=2010, sexe="H", affiliation="salarie_prive_non_cadre",
        age_debut=22, age_liquidation=64,
    )
    prospectif = simulateur.simuler(carriere).notionnel_prospectif
    assert prospectif.droits_acquis is None
    assert prospectif.capital_droits_acquis == 0.0


def test_une_carriere_sans_aucune_cotisation_ne_produit_pas_de_capital(simulateur):
    """Des droits acquis existent formellement, mais ils valent zéro.

    Le cas est réel — une carrière intégralement interrompue — et la page de
    simulation doit le traverser sans diviser par le capital.
    """
    carriere = simulateur.carriere_simple(
        annee_naissance=1975, sexe="H", affiliation="salarie_prive_non_cadre",
        age_debut=21, age_liquidation=64,
        interruptions={annee: "chomage_indemnise" for annee in range(1996, 2039)},
    )
    prospectif = simulateur.simuler(carriere).notionnel_prospectif
    assert prospectif.droits_acquis is not None
    assert prospectif.capital_notionnel == 0.0
    assert prospectif.pension_annuelle == 0.0


def test_un_depart_plus_tardif_ameliore_la_pension_notionnelle(simulateur):
    """Double effet : plus de cotisations, et un diviseur plus faible."""
    pensions = []
    for age in (60, 62, 64, 67):
        carriere = simulateur.carriere_simple(
            annee_naissance=1975, sexe="H", affiliation="salarie_prive_non_cadre",
            age_debut=22, age_liquidation=age,
        )
        pensions.append(
            simulateur.simuler(carriere).notionnel_retroactif.pension_annuelle
        )
    assert pensions == sorted(pensions)


def test_carriere_interrompue_perd_davantage_en_notionnel(simulateur):
    """Les périodes non cotisées n'ouvrent aucun droit : c'est le principe."""
    commun = dict(annee_naissance=1975, sexe="F",
                  affiliation="salarie_prive_non_cadre", age_debut=22,
                  age_liquidation=64)
    complete = simulateur.simuler(simulateur.carriere_simple(**commun))
    interrompue = simulateur.simuler(simulateur.carriere_simple(
        **commun, interruptions={annee: "education_enfant" for annee in range(2005, 2013)}
    ))
    assert (interrompue.notionnel_retroactif.pension_annuelle
            < complete.notionnel_retroactif.pension_annuelle)


def test_regime_special_a_depart_precoce_est_le_plus_touche(simulateur):
    """Le cas emblématique : quinze ans d'anticipation."""
    sncf = simulateur.simuler(simulateur.carriere_simple(
        annee_naissance=1955, sexe="H", affiliation="agent_sncf",
        age_debut=20, age_liquidation=50,
    ))
    prive = simulateur.simuler(simulateur.carriere_simple(
        annee_naissance=1955, sexe="H", affiliation="salarie_prive_non_cadre",
        age_debut=20, age_liquidation=62,
    ))
    assert sncf.notionnel_retroactif.ecart_age.ecart == pytest.approx(15.0)
    assert (sncf.variation("notionnel_retroactif")
            < prive.variation("notionnel_retroactif"))


def test_sans_cotisation_aucun_droit_notionnel(simulateur):
    """Suppression des minima : peu cotisé, peu de retraite, sans plancher."""
    carriere = simulateur.carriere_simple(
        annee_naissance=1975, sexe="H", affiliation="salarie_prive_non_cadre",
        age_debut=22, age_liquidation=64, niveau_salaire=0.3,
    )
    riche = simulateur.carriere_simple(
        annee_naissance=1975, sexe="H", affiliation="salarie_prive_non_cadre",
        age_debut=22, age_liquidation=64, niveau_salaire=3.0,
    )
    faible = simulateur.simuler(carriere).notionnel_retroactif.pension_annuelle
    forte = simulateur.simuler(riche).notionnel_retroactif.pension_annuelle
    # Strictement proportionnel au salaire tant que le plafond n'est pas atteint :
    # aucun effet de seuil ne subsiste.
    assert forte > faible * 5


def test_capitalisation_reste_dans_un_compartiment_separe(simulateur):
    """Les droits RAFP ne rejoignent jamais le capital notionnel."""
    carriere = simulateur.carriere_simple(
        annee_naissance=1980, sexe="F", affiliation="fonctionnaire_etat",
        age_debut=25, age_liquidation=64, part_primes=0.20,
    )
    resultat = simulateur.simuler(carriere).notionnel_retroactif
    assert resultat.capital_capitalisation > 0
    assert resultat.rente_capitalisation_annuelle > 0
    assert resultat.rente_capitalisation_annuelle not in (resultat.pension_annuelle,)


# -- neutralisations ---------------------------------------------------------


def test_les_avantages_familiaux_ne_jouent_que_dans_le_systeme_actuel(simulateur):
    commun = dict(annee_naissance=1975, sexe="F",
                  affiliation="salarie_prive_non_cadre",
                  age_debut=22, age_liquidation=64)
    sans = simulateur.simuler(simulateur.carriere_simple(**commun, nombre_enfants=0))
    avec = simulateur.simuler(simulateur.carriere_simple(**commun, nombre_enfants=3))
    assert (avec.notionnel_retroactif.pension_annuelle
            == pytest.approx(sans.notionnel_retroactif.pension_annuelle))


def test_le_systeme_actuel_applique_ses_avantages_sans_condition(simulateur):
    """Le scénario 1 est le droit positif : ses minima s'appliquent toujours.

    Les drapeaux :class:`Neutralisations` décrivent ce que les scénarios
    notionnels RETIRENT. Les lire dans le scénario 1 amputait l'étalon de la
    majoration pour trois enfants, de la MDA et du minimum contributif —
    c'est-à-dire précisément de ce qui protège les carrières que le notionnel
    pénalise le plus, ce qui minorait l'écart mesuré.
    """
    commun = dict(annee_naissance=1975, sexe="F",
                  affiliation="salarie_prive_non_cadre",
                  age_debut=22, age_liquidation=64)
    sans = simulateur.simuler(
        simulateur.carriere_simple(**commun, nombre_enfants=0)
    ).actuel
    avec = simulateur.simuler(
        simulateur.carriere_simple(**commun, nombre_enfants=3)
    ).actuel

    # Majoration de 10 % pour trois enfants, et huit trimestres par enfant.
    assert avec.trimestres_valides == sans.trimestres_valides + 24
    assert avec.pension_annuelle > sans.pension_annuelle * 1.09

    # Les neutralisations ne doivent rien y changer : elles ne concernent que
    # les scénarios notionnels.
    neutralise = Simulateur(
        Parametres(neutralisations=Neutralisations(majoration_enfants=False))
    )
    autre = neutralise.simuler(
        neutralise.carriere_simple(**commun, nombre_enfants=3)
    ).actuel
    assert autre.pension_annuelle == pytest.approx(avec.pension_annuelle)


def test_la_cascade_des_avantages_est_exactement_additive(simulateur):
    """Sous-total contributif + avantages = pension. Sinon la page ment."""
    for enfants, salaire, debut in ((0, 1.0, 22), (1, 1.0, 22), (3, 2.0, 22),
                                    (3, 0.4, 37), (4, 0.8, 25)):
        carriere = simulateur.carriere_simple(
            annee_naissance=1965, sexe="F",
            affiliation="salarie_prive_non_cadre", age_debut=debut,
            age_liquidation=62, niveau_salaire=salaire, nombre_enfants=enfants,
            profil_carriere="plat",
        )
        actuel = simulateur.simuler(carriere).actuel
        somme = actuel.total_contributif + sum(
            a.montant for a in actuel.avantages_appliques
        )
        assert somme == pytest.approx(actuel.pension_annuelle), (
            f"cascade non additive pour {enfants} enfants, salaire {salaire}"
        )


def test_sans_enfant_aucun_avantage_familial_n_est_cite(simulateur):
    carriere = simulateur.carriere_simple(
        annee_naissance=1965, sexe="H", affiliation="salarie_prive_non_cadre",
        age_debut=22, age_liquidation=62,
    )
    actuel = simulateur.simuler(carriere).actuel
    codes = {a.code for a in actuel.avantages_appliques}
    assert "majoration_enfants" not in codes
    assert "majoration_duree_assurance" not in codes
    assert actuel.total_contributif == pytest.approx(actuel.pension_annuelle)


def test_la_fonction_publique_majore_de_cinq_points_par_enfant_au_dela_de_trois():
    """10 % à trois enfants, puis 5 % par enfant supplémentaire."""
    simulateur = Simulateur(Parametres())
    montants = {}
    for enfants in (3, 5):
        carriere = simulateur.carriere_simple(
            annee_naissance=1965, sexe="F", affiliation="fonctionnaire_etat",
            age_debut=22, age_liquidation=62, nombre_enfants=enfants,
        )
        actuel = simulateur.simuler(carriere).actuel
        majoration = next(
            a for a in actuel.avantages_appliques if a.code == "majoration_enfants"
        )
        montants[enfants] = majoration.montant / actuel.total_contributif
    # 20 % à cinq enfants contre 10 % à trois : le rapport doit valoir 2.
    assert montants[5] / montants[3] == pytest.approx(2.0, rel=0.02)


def test_la_surcote_suit_l_age_legal_de_la_generation():
    """Né en 1968, l'âge légal est 64 : partir à 64 ans ne surcote pas.

    Né en 1958, il est de 62 : les deux dernières années surcotent. Lire l'âge
    à l'année de liquidation donnait 64 ans à tout le monde depuis 2023.
    """
    simulateur = Simulateur(Parametres())
    taux = {}
    for naissance in (1958, 1968):
        carriere = simulateur.carriere_simple(
            annee_naissance=naissance, sexe="H",
            affiliation="salarie_prive_non_cadre", age_debut=18,
            age_liquidation=64,
        )
        taux[naissance] = simulateur.simuler(carriere).actuel.taux_liquidation
    assert taux[1958] > 0.50  # surcote de huit trimestres
    assert taux[1968] == pytest.approx(0.50)  # aucun trimestre au-delà de l'âge légal


def test_le_minimum_contributif_est_ecrete_pour_les_grosses_pensions(simulateur):
    """Un cadre à carrière complète ne doit jamais toucher le minimum."""
    carriere = simulateur.carriere_simple(
        annee_naissance=1965, sexe="H", affiliation="salarie_prive_cadre",
        age_debut=22, age_liquidation=64, niveau_salaire=3.0,
    )
    assert simulateur.simuler(carriere).actuel.minimum_applique is False


def test_le_minimum_contributif_releve_les_petites_pensions(simulateur):
    """Une carrière courte au SMIC relève du minimum : c'est son objet."""
    carriere = simulateur.carriere_simple(
        annee_naissance=1965, sexe="F", affiliation="salarie_prive_non_cadre",
        age_debut=37, age_liquidation=62, niveau_salaire=0.4,
        profil_carriere="plat",
    )
    resultat = simulateur.simuler(carriere).actuel
    assert resultat.minimum_applique is True


# -- restitution -------------------------------------------------------------


def test_le_tableau_mentionne_l_ecart_d_age(simulateur, salarie_moyen):
    texte = simulateur.simuler(salarie_moyen).tableau()
    assert "Âge de référence à cliquet" in texte
    assert "anticipation" in texte


def test_dictionnaire_est_serialisable(simulateur, salarie_moyen):
    import json

    donnees = simulateur.simuler(salarie_moyen).dictionnaire()
    json.dumps(donnees, ensure_ascii=False)
    assert set(donnees["scenarios"]) == {
        "actuel", "notionnel_retroactif", "notionnel_prospectif"
    }
    assert donnees["unite"]["euros_constants_de"] == 2026


def test_euros_constants_rendent_les_generations_comparables(simulateur):
    """Deux liquidations éloignées doivent être ramenées à la même unité."""
    ancienne = simulateur.simuler(simulateur.carriere_simple(
        annee_naissance=1940, sexe="H", affiliation="salarie_prive_non_cadre",
        age_debut=20, age_liquidation=62,
    ))
    recente = simulateur.simuler(simulateur.carriere_simple(
        annee_naissance=1990, sexe="H", affiliation="salarie_prive_non_cadre",
        age_debut=20, age_liquidation=62,
    ))
    assert ancienne.coefficient_euros_constants > 1.0   # euros de 2002 -> 2026
    assert recente.coefficient_euros_constants < 1.0    # euros de 2052 -> 2026


def test_l_ecart_entre_regles_d_indexation_croit_avec_l_anciennete_de_la_carriere():
    """L'effet du mélange réel/nominal se concentre sur les décennies inflationnistes.

    Pour une carrière liquidée dans les années 2010, l'essentiel du capital a
    été constitué après 1990, période où les deux règles se rejoignent : l'écart
    reste modeste. Pour une carrière des années 1950-1980, il devient massif.
    C'est pourquoi le choix de la règle pèse surtout sur le scénario rétroactif
    appliqué aux générations anciennes.
    """
    litteral = Simulateur(Parametres())
    nominal = Simulateur(Parametres(
        mode_indexation=ModeIndexation.TRIPLE_LOCK_INVERSE_NOMINAL
    ))

    def rapport(annee_naissance: int) -> float:
        commun = dict(annee_naissance=annee_naissance, sexe="H",
                      affiliation="salarie_prive_non_cadre",
                      age_debut=20, age_liquidation=62)
        a = litteral.simuler(litteral.carriere_simple(**commun))
        b = nominal.simuler(nominal.carriere_simple(**commun))
        return (b.notionnel_retroactif.pension_annuelle
                / a.notionnel_retroactif.pension_annuelle)

    ancienne = rapport(1925)   # carrière 1945-1986
    recente = rapport(1970)    # carrière 1990-2031
    assert ancienne > recente > 1.0


# -- régimes en points -------------------------------------------------------


def test_les_complementaires_sont_calculees_en_points(simulateur, salarie_moyen):
    """La retraite complémentaire ne passe plus par un rendement estimé.

    Depuis l'intégration des valeurs d'achat et de service du point, la pension
    Arrco est le produit de points réellement acquis par la valeur de service
    de l'année de liquidation. Le libellé le dit, et c'est ce libellé qui
    distingue les deux modes de calcul.
    """
    pensions = {p.regime: p for p in simulateur.simuler(salarie_moyen).actuel.pensions_par_regime}
    assert "arrco" in pensions
    assert "points × valeur de service" in pensions["arrco"].detail
    assert pensions["arrco"].montant > 0


def test_les_points_d_un_regime_fusionne_sont_convertis(simulateur):
    """Un régime fermé ne sert plus ses points : son successeur les sert.

    Arrco a fermé en 2018, Agirc-Arrco a repris ses points au rapport des deux
    valeurs de service. Une pension Arrco liquidée après 2019 doit donc être
    valorisée au-dessus de la dernière valeur du point Arrco — sans quoi la
    conversion a été oubliée.
    """
    from retraite_notionnelle.scenarios.actuel import ValeursPoint

    valeurs = ValeursPoint(simulateur.parametres.racine_donnees)
    scenario = simulateur.scenario_actuel
    derniere_arrco = valeurs.derniere_annee_servie("arrco")
    assert derniere_arrco == 2018

    avant, _ = valeurs.service("arrco", derniere_arrco)
    apres, _ = scenario.valeur_du_point("arrco", 2022)
    assert apres > avant, "les points Arrco n'ont pas suivi la fusion de 2019"

    # La conversion doit être exactement le rapport des valeurs de service au
    # moment de la reprise : c'est elle qui laisse les pensions inchangées.
    service_2019, _ = valeurs.service("agirc_arrco", 2019)
    service_2022, _ = valeurs.service("agirc_arrco", 2022)
    assert apres == pytest.approx(avant / service_2019 * service_2022)


def test_rendement_instantane_reproduit_le_repere_publie(simulateur):
    """Agirc-Arrco 2025 : le régime publie un rendement de 5,61 %.

    C'est le seul chiffre que la caisse communique directement, et il enchaîne
    les trois grandeurs du fichier. S'il tombe juste, elles sont cohérentes.
    """
    from retraite_notionnelle.scenarios.actuel import ValeursPoint

    valeurs = ValeursPoint(simulateur.parametres.racine_donnees)
    reference, taux_appel, _ = valeurs.achat("agirc_arrco", 2025)
    service, _ = valeurs.service("agirc_arrco", 2025)
    assert service / (reference * taux_appel) == pytest.approx(0.0561, abs=0.0002)


def test_un_regime_sans_valeur_de_point_garde_le_rendement(simulateur):
    """La bascule est régime par régime, pas globale.

    La CNAVPL, la MSA ou la CNBF n'ont pas de série de valeurs du point dans le
    dépôt : elles doivent continuer d'être calculées au rendement instantané,
    sans que rien ne casse.
    """
    carriere = simulateur.carriere_simple(
        annee_naissance=1960, sexe="F", affiliation="profession_liberale",
        age_debut=25, age_liquidation=64,
    )
    pensions = {p.regime: p for p in simulateur.simuler(carriere).actuel.pensions_par_regime}
    assert "cnavpl" in pensions
    assert "rendement" in pensions["cnavpl"].detail
    assert pensions["cnavpl"].montant > 0


def test_le_prix_du_point_n_est_pas_prolonge_au_dela_du_publie(simulateur):
    """Un barème inconnu ne doit pas être supposé gelé.

    Prolonger le dernier prix d'achat connu ferait acheter les points trop bon
    marché et gonflerait la pension sans que rien ne le signale. Ces années
    doivent retomber sur le rendement instantané, qui, lui, s'annonce approximatif.
    """
    from retraite_notionnelle.scenarios.actuel import ValeursPoint

    valeurs = ValeursPoint(simulateur.parametres.racine_donnees)
    assert valeurs.achat("agirc", 2018) is not None
    assert valeurs.achat("agirc", 2019) is None, "barème Agirc prolongé après sa fermeture"
    assert valeurs.achat("rafp", 2005) is not None


def test_rafp_et_rci_sont_calcules_en_points(simulateur):
    """Les deux régimes que la recherche de sources a permis d'ajouter."""
    fonctionnaire = simulateur.carriere_simple(
        annee_naissance=1965, sexe="H", affiliation="fonctionnaire_etat",
        age_debut=23, age_liquidation=64, part_primes=0.20,
    )
    artisan = simulateur.carriere_simple(
        annee_naissance=1965, sexe="F", affiliation="artisan",
        age_debut=25, age_liquidation=64,
    )
    for carriere, code in ((fonctionnaire, "rafp"), (artisan, "rci")):
        pensions = {p.regime: p for p in simulateur.simuler(carriere).actuel.pensions_par_regime}
        assert code in pensions, code
        assert "points × valeur de service" in pensions[code].detail, code


def test_le_producteur_prime_sur_la_transcription(simulateur):
    """L'Ircantec est le seul régime dont on ait les deux sources.

    Ses barèmes viennent de la Caisse des dépôts, qui gère le régime, et non
    d'OpenFisca qui les transcrit. Là où le producteur publie, ses valeurs
    doivent être certifiées ; ailleurs, la transcription reprend au niveau
    « haute ».
    """
    import csv

    from retraite_notionnelle.donnees.chargement import Fiabilite

    chemin = (simulateur.parametres.racine_donnees / "reference" / "regimes"
              / "valeurs_point.csv")
    with chemin.open(encoding="utf-8") as flux:
        lignes = [l for l in csv.DictReader(
            x for x in flux if not x.lstrip().startswith("#"))
            if l["regime"] == "ircantec"]

    niveaux = {int(l["annee"]): l["fiabilite"] for l in lignes}
    assert niveaux[1971] == "certifiee"
    assert niveaux[2021] == "certifiee"
    assert niveaux[2022] == "haute", "hors couverture du producteur, la transcription"
    assert Fiabilite.depuis_texte("certifiee") > Fiabilite.depuis_texte("haute")


def test_valeurs_du_point_des_avocats_sont_sourcees(simulateur):
    """Les barèmes de la CNBF, seule source qui porte la valeur du point des avocats.

    Elles sont rangées sous ``cnbf_complementaire``, un code que le catalogue ne
    connaît pas : le régime complémentaire des avocats n'est pas encore séparé
    de leur régime de base dans les fiches, et le moteur ne doit donc pas s'en
    servir tant que la scission n'est pas faite. Le test garde les deux moitiés
    de cette décision — les données sont là, le moteur ne les utilise pas.
    """
    import csv

    from retraite_notionnelle.scenarios.actuel import ValeursPoint

    chemin = (simulateur.parametres.racine_donnees / "reference" / "regimes"
              / "valeurs_point.csv")
    with chemin.open(encoding="utf-8") as flux:
        lignes = [l for l in csv.DictReader(
            x for x in flux if not x.lstrip().startswith("#"))
            if l["regime"] == "cnbf_complementaire"]

    valeurs = {(int(l["annee"]), l["mesure"]): float(l["valeur"]) for l in lignes}
    assert {l["fiabilite"] for l in lignes} == {"certifiee"}
    assert valeurs[(2026, "salaire_reference")] == pytest.approx(12.5229)
    assert valeurs[(2026, "valeur_service")] == pytest.approx(1.0262)

    # Le rendement d'un régime complémentaire décroît : c'est ce qui permet de
    # détecter une lecture de travers dans le PDF du barème.
    annees = sorted({a for a, _ in valeurs})
    rendements = [valeurs[(a, "valeur_service")] / valeurs[(a, "salaire_reference")]
                  for a in annees]
    assert all(apres < avant for avant, apres in zip(rendements, rendements[1:]))
    assert 0.08 < rendements[-1] < 0.11

    # Le catalogue ignore ce code : le moteur ne peut pas s'en servir par mégarde.
    assert "cnbf_complementaire" not in simulateur.catalogue
    assert ValeursPoint(simulateur.parametres.racine_donnees).achat("cnbf", 2026) is None


def test_valeur_du_point_des_liberaux_est_sourcee(simulateur):
    """La CNAVPL publie sa valeur du point dans ses recueils, et nulle part ailleurs.

    Le décret annuel ne fixe qu'un coefficient de revalorisation : ni le
    Journal officiel ni la législation consolidée ne portent le montant, ce que
    quatre dépouillements ont établi. Ces valeurs viennent donc de la caisse.

    Le moteur ne s'en sert pas encore : le prix d'acquisition d'un point se
    déduit du taux de tranche et d'un plafond de points que le recueil ne
    livre pas sous une forme relisible. Tant qu'il manque, la CNAVPL reste au
    rendement instantané.
    """
    import csv

    from retraite_notionnelle.scenarios.actuel import ValeursPoint

    chemin = (simulateur.parametres.racine_donnees / "reference" / "regimes"
              / "valeurs_point.csv")
    with chemin.open(encoding="utf-8") as flux:
        lignes = [l for l in csv.DictReader(
            x for x in flux if not x.lstrip().startswith("#"))
            if l["regime"] == "cnavpl"]

    valeurs = {(int(l["annee"]), l["mesure"]): float(l["valeur"]) for l in lignes}
    assert {l["fiabilite"] for l in lignes} == {"certifiee"}
    assert valeurs[(2025, "valeur_service")] == pytest.approx(0.6540)
    assert valeurs[(2025, "taux_t1")] == pytest.approx(0.0823)
    assert valeurs[(2025, "taux_t2")] == pytest.approx(0.0187)

    services = [valeurs[(a, "valeur_service")]
                for a in sorted({a for a, m in valeurs if m == "valeur_service"})]
    assert all(apres > avant for avant, apres in zip(services, services[1:]))

    # Faute de prix d'acquisition, le moteur doit rester sur le rendement.
    assert ValeursPoint(simulateur.parametres.racine_donnees).achat("cnavpl", 2025) is None


def test_valeur_du_point_agirc_arrco_est_recoupee_par_l_insee(simulateur):
    """Deux transcriptions publiques indépendantes, et elles concordent.

    Les barèmes de l'Agirc et de l'Arrco pèsent plus lourd que tous les autres
    réunis dans la pension d'un salarié du privé, et leur seule source était
    jusqu'ici OpenFisca — invérifiable, la caisse ne publiant pas de série.
    L'INSEE en diffuse la valeur de service depuis 2001 sous trois idbanks ;
    ``controle_vraisemblance_point_insee`` compare les deux à chaque exécution.

    Ce test garde ce que ce recoupement a rapporté : l'année 2025, que seule
    la série INSEE couvre, la transcription s'arrêtant à 2024. Sans elle une
    liquidation de 2025 convertissait ses points au barème de 2024.
    """
    import csv

    chemin = (simulateur.parametres.racine_donnees / "reference" / "regimes"
              / "valeurs_point.csv")
    with chemin.open(encoding="utf-8") as flux:
        lignes = [l for l in csv.DictReader(
            x for x in flux if not x.lstrip().startswith("#"))
            if l["mesure"] == "valeur_service"]

    par_regime: dict[str, dict[int, float]] = {}
    for ligne in lignes:
        par_regime.setdefault(ligne["regime"], {})[int(ligne["annee"])] = float(
            ligne["valeur"])

    # Les valeurs de part et d'autre de la fusion, au 31 décembre — la
    # convention du fichier. La dernière de l'Arrco, 1,2588 €, est celle que
    # l'Agirc-Arrco reprend au 1er janvier 2019 avant de la revaloriser en
    # novembre : la continuité du point est vérifiable, l'Agirc restant à part
    # puisque ses points ont été convertis dans le rapport des deux valeurs.
    assert par_regime["arrco"][2018] == pytest.approx(1.2588, abs=1e-4)
    assert par_regime["agirc"][2018] == pytest.approx(0.4378, abs=1e-4)
    assert par_regime["agirc_arrco"][2019] == pytest.approx(1.2714, abs=1e-4)

    # Ce que le recoupement a ajouté : la dernière année, absente d'OpenFisca.
    assert par_regime["agirc_arrco"][2025] == pytest.approx(1.4386, abs=1e-4)

    # La valeur de service ne recule jamais : elle est gelée, jamais rabotée.
    for regime in ("arrco", "agirc", "agirc_arrco"):
        annees = sorted(a for a in par_regime[regime] if a >= 2001)
        valeurs = [par_regime[regime][a] for a in annees]
        assert all(apres >= avant for avant, apres in zip(valeurs, valeurs[1:]))


def test_valeur_du_point_de_la_complementaire_agricole_est_sourcee(simulateur):
    """La dernière caisse en points sans série a fini par en avoir une.

    Elle ne vient ni de la MSA ni de son service statistique — les « Chiffres
    utiles » sont un annuaire d'effectifs — mais du code rural lui-même, dont
    l'article D. 732-166 fixe la valeur chaque année depuis 2005. La base LEGI
    de la DILA en garde toutes les versions datées ; c'est la publication
    officielle, d'où le niveau du producteur.

    Les valeurs sont rangées sous ``msa_rco``, un code que le catalogue ignore :
    la fiche ``msa_non_salaries`` agrège le régime de base et son étage
    complémentaire, et tout verser dans le second ferait disparaître le premier.
    Ce test garde cette séparation autant que les valeurs.
    """
    import csv

    from retraite_notionnelle.donnees import CatalogueRegimes

    chemin = (simulateur.parametres.racine_donnees / "reference" / "regimes"
              / "valeurs_point.csv")
    with chemin.open(encoding="utf-8") as flux:
        lignes = [l for l in csv.DictReader(
            x for x in flux if not x.lstrip().startswith("#"))
            if l["regime"] == "msa_rco"]

    valeurs = {int(l["annee"]): float(l["valeur"]) for l in lignes}
    assert {l["fiabilite"] for l in lignes} == {"certifiee"}
    assert {l["mesure"] for l in lignes} == {"valeur_service"}

    # Bornes de la série, et l'année 2019 — que seul un décret fixant deux
    # années d'un coup fait entrer : aucun texte ne lui est propre.
    assert valeurs[2005] == pytest.approx(0.2972)
    assert valeurs[2019] == pytest.approx(0.3392)
    assert valeurs[2024] == pytest.approx(0.3835)

    annees = sorted(valeurs)
    assert annees == list(range(annees[0], annees[-1] + 1)), "la série a un trou"
    assert all(valeurs[b] >= valeurs[a] for a, b in zip(annees, annees[1:]))

    # Le code reste hors catalogue tant que la fiche n'est pas scindée.
    catalogue = CatalogueRegimes(simulateur.parametres.racine_donnees)
    assert "msa_rco" not in catalogue
    assert "msa_non_salaries" in catalogue
