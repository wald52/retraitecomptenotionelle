"""Tests des scénarios et du simulateur, au niveau du comportement attendu."""

from __future__ import annotations

import pytest

from retraite_notionnelle.carriere import AnneeCarriere, Carriere
from retraite_notionnelle.config import (
    AgeConversionDroitsAcquis,
    PartCotisation,
    ModeIndexation,
    Neutralisations,
    Parametres,
    SourceCotisations,
)
from retraite_notionnelle.simulateur import SCENARIOS_NOTIONNELS, Simulateur


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
        interruptions={annee: "sans_activite" for annee in range(1996, 2039)},
    )
    prospectif = simulateur.simuler(carriere).notionnel_prospectif
    assert prospectif.droits_acquis is not None
    assert prospectif.capital_notionnel == 0.0
    assert prospectif.pension_annuelle == 0.0


def test_le_motif_de_l_interruption_change_les_droits_ouverts(simulateur):
    """Chômage indemnisé et non indemnisé n'ouvrent pas les mêmes droits.

    Pendant un chômage indemnisé, l'UNEDIC verse de vraies cotisations aux
    régimes complémentaires : des points sont acquis. Le régime de base, lui,
    ne reçoit rien — la période y est seulement assimilée. Le modèle
    enregistrait le motif sans jamais le lire, et traitait les deux à
    l'identique.
    """
    commun = dict(annee_naissance=1975, sexe="F",
                  affiliation="salarie_prive_non_cadre",
                  age_debut=22, age_liquidation=64)
    resultats = {}
    for motif in ("chomage_indemnise", "chomage_non_indemnise", "sans_activite"):
        carriere = simulateur.carriere_simple(
            **commun,
            interruptions={annee: motif for annee in range(2000, 2005)},
        )
        resultats[motif] = simulateur.simuler(carriere)

    def complementaires(comparaison):
        return sum(p.montant for p in comparaison.actuel.pensions_par_regime
                   if p.type_calcul == "points")

    # Le chômage indemnisé préserve les points complémentaires, pas les autres.
    assert complementaires(resultats["chomage_indemnise"]) > complementaires(
        resultats["chomage_non_indemnise"]
    )
    # Et il alimente le compte notionnel, puisque des cotisations sont versées.
    assert (resultats["chomage_indemnise"].notionnel_retroactif.capital_notionnel
            > resultats["chomage_non_indemnise"].notionnel_retroactif.capital_notionnel)
    # « sans_activite » ne valide même pas de trimestre assimilé.
    assert (resultats["sans_activite"].actuel.trimestres_valides
            < resultats["chomage_non_indemnise"].actuel.trimestres_valides)


def test_un_temps_tres_partiel_ne_valide_pas_quatre_trimestres(simulateur):
    """Un trimestre s'acquiert par un montant cotisé, pas par le temps.

    150 fois le SMIC horaire depuis 2014, 200 avant. Le modèle validait quatre
    trimestres par année travaillée quelle que soit la rémunération.
    """
    trimestres = {}
    for niveau in (0.10, 0.20, 1.0):
        carriere = simulateur.carriere_simple(
            annee_naissance=1975, sexe="F",
            affiliation="salarie_prive_non_cadre", age_debut=22,
            age_liquidation=64, niveau_salaire=niveau, profil_carriere="plat",
        )
        trimestres[niveau] = carriere.trimestres_actuels
    assert trimestres[0.10] < trimestres[0.20] < trimestres[1.0]
    # Une carrière au salaire moyen valide bien quatre trimestres par an.
    assert trimestres[1.0] == 4 * 42


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


def test_a_salaire_egal_le_statut_est_compare_a_la_meme_grandeur(simulateur):
    """Un compte notionnel ne connaît que des euros cotisés.

    Les fiches publiques ne portent que la retenue de l'agent, les fiches
    privées le total salarié + employeur. Les comparer telles quelles faisait
    apparaître entre un fonctionnaire et un salarié de même rémunération un
    écart de 37 % qui ne traduisait aucune règle de retraite, mais un périmètre
    comptable.

    La `part_salariale` des fiches referme cet écart de périmètre : les deux
    scénarios comparent maintenant la même grandeur des deux côtés. Ce qui reste
    est réel — les taux salariaux ne sont pas identiques d'un régime à l'autre —
    et se compte en points, non en dizaines de points.
    """
    commun = dict(annee_naissance=1975, sexe="H", age_debut=22, age_liquidation=64)

    def pension(affiliation, scenario):
        carriere = simulateur.carriere_simple(affiliation=affiliation, **commun)
        return getattr(simulateur.simuler(carriere), scenario).pension_annuelle

    public = pension("fonctionnaire_etat", "notionnel_retroactif")
    prive = pension("salarie_prive_non_cadre", "notionnel_retroactif")
    # Quelques points d'écart, là où le périmètre comptable en faisait 37.
    assert 0.90 < public / prive < 1.10


def test_l_ancienne_convention_egalise_les_statuts(simulateur):
    """`TOTALE_ALIGNEE` prête au public le taux du privé : les deux se rejoignent."""
    aligne = Simulateur(Parametres().avec(
        part_cotisation=PartCotisation.TOTALE_ALIGNEE
    ))
    commun = dict(annee_naissance=1975, sexe="H", age_debut=22, age_liquidation=64)
    pensions = [
        aligne.simuler(
            aligne.carriere_simple(affiliation=affiliation, **commun)
        ).notionnel_retroactif.pension_annuelle
        for affiliation in ("salarie_prive_non_cadre", "fonctionnaire_etat")
    ]
    assert pensions[1] == pytest.approx(pensions[0], rel=1e-9)


def test_l_ancienne_convention_d_alignement_reste_accessible():
    """`TOTALE_ALIGNEE` prête au public la part employeur du privé.

    C'est ce que le modèle faisait par défaut avant que la répartition
    salarié/employeur soit dans les fiches. Conservée comme contrefactuel, elle
    doit rester entre la part salariale seule et la contribution publique
    réelle, qui est bien plus lourde.
    """
    profil = dict(annee_naissance=1975, sexe="H", affiliation="fonctionnaire_etat",
                  age_debut=22, age_liquidation=64)

    def pension(part):
        sim = Simulateur(Parametres().avec(part_cotisation=part))
        return sim.simuler(
            sim.carriere_simple(**profil)
        ).notionnel_retroactif.pension_annuelle

    salariale = pension(PartCotisation.SALARIALE)
    alignee = pension(PartCotisation.TOTALE_ALIGNEE)
    totale = pension(PartCotisation.TOTALE)
    assert salariale < alignee < totale


# -- scénarios 4 et 5 : les cotisations employeur du public -------------------


def test_les_cinq_scenarios_sont_calcules(simulateur, salarie_moyen):
    comparaison = simulateur.simuler(salarie_moyen)
    for cle, _, _ in SCENARIOS_NOTIONNELS:
        assert getattr(comparaison, cle).pension_annuelle > 0, cle


def test_sans_employeur_les_quatre_scenarios_se_reduisent_a_deux(simulateur):
    """Un artisan paie tout : il n'y a pas de part patronale à ajouter.

    Un non-salarié relève pourtant souvent d'un régime partagé avec des
    salariés — un artisan cotise au régime général, dont la fiche porte la
    répartition 41/59 d'un salarié. Sans le drapeau `sans_employeur` du statut,
    les scénarios 4 et 5 lui prêteraient un employeur qu'il n'a pas.
    """
    for affiliation in ("artisan", "profession_liberale", "exploitant_agricole"):
        carriere = simulateur.carriere_simple(
            annee_naissance=1975, sexe="H", affiliation=affiliation,
            age_debut=27, age_liquidation=64,
        )
        comparaison = simulateur.simuler(carriere)
        assert (comparaison.notionnel_retroactif_employeur.pension_annuelle
                == pytest.approx(comparaison.notionnel_retroactif.pension_annuelle)), affiliation
        assert (comparaison.notionnel_prospectif_employeur.pension_annuelle
                == pytest.approx(comparaison.notionnel_prospectif.pension_annuelle)), affiliation
        assert not comparaison.contribution_employeur.a_un_employeur, affiliation


def test_le_prive_aussi_a_une_part_patronale(simulateur, salarie_moyen):
    """L'axe n'est pas public/privé : il est salarial/patronal, pour tous.

    La fiche du régime général porte le total ; sa `part_salariale` dit combien
    l'employeur y met. Les scénarios 4 et 5 doivent donc déplacer un salarié du
    privé, et pas seulement un fonctionnaire.
    """
    comparaison = simulateur.simuler(salarie_moyen)
    assert (comparaison.notionnel_retroactif_employeur.pension_annuelle
            > comparaison.notionnel_retroactif.pension_annuelle * 1.5)
    employeur = comparaison.contribution_employeur
    assert employeur.a_un_employeur
    # Aucune série publique n'intervient : la fiche porte la répartition.
    assert not employeur.concerne_un_regime_public
    assert 0.5 < employeur.part < 0.65


def test_le_scenario_4_est_le_2_avec_les_cotisations_employeur(simulateur):
    """82 % de contribution employeur portés au compte, cela se voit."""
    carriere = simulateur.carriere_simple(
        annee_naissance=1975, sexe="F", affiliation="fonctionnaire_etat",
        age_debut=23, age_liquidation=64, part_primes=0.20,
    )
    comparaison = simulateur.simuler(carriere)
    assert (comparaison.notionnel_retroactif_employeur.pension_annuelle
            > comparaison.notionnel_retroactif.pension_annuelle * 1.5)


def test_le_scenario_5_est_le_3_avec_les_cotisations_employeur(simulateur):
    """Les droits acquis sont ceux du scénario 3 ; seul le flux postérieur change.

    Le régime unique applique après la bascule un taux unique qui efface toute
    trace de l'employeur public : sans le traitement du taux unifié, ce scénario
    serait rigoureusement identique au scénario 3, et ne servirait à rien.
    """
    carriere = simulateur.carriere_simple(
        annee_naissance=1990, sexe="F", affiliation="fonctionnaire_etat",
        age_debut=23, age_liquidation=64, part_primes=0.20,
    )
    comparaison = simulateur.simuler(carriere)
    prospectif = comparaison.notionnel_prospectif
    avec_employeur = comparaison.notionnel_prospectif_employeur

    assert avec_employeur.pension_annuelle > prospectif.pension_annuelle * 1.2
    # Les droits figés à la bascule, eux, sont les mêmes des deux côtés.
    assert (avec_employeur.droits_acquis.capital
            == pytest.approx(prospectif.droits_acquis.capital))


def test_le_scenario_5_reste_inferieur_au_scenario_4(simulateur):
    """Le 5 ne compte l'employeur qu'à partir de la bascule, le 4 depuis 1995."""
    carriere = simulateur.carriere_simple(
        annee_naissance=1975, sexe="F", affiliation="fonctionnaire_etat",
        age_debut=23, age_liquidation=64, part_primes=0.20,
    )
    comparaison = simulateur.simuler(carriere)
    assert (comparaison.notionnel_prospectif_employeur.pension_annuelle
            < comparaison.notionnel_retroactif_employeur.pension_annuelle)


def test_le_regime_unique_herite_de_la_repartition_de_ses_pivots(simulateur):
    """Après la bascule, plus de fonction publique : un seul régime, un seul taux.

    Son taux est celui du statut pivot privé, et il en hérite la répartition.
    C'est elle, et non une contribution publique retrouvée décret par décret,
    qui sépare le scénario 5 du scénario 3 après la bascule.
    """
    fusionne = simulateur.regime_fusionne
    carriere = simulateur.carriere_simple(
        annee_naissance=1990, sexe="F", affiliation="fonctionnaire_etat",
        age_debut=23, age_liquidation=64, part_primes=0.25,
    )
    comparaison = simulateur.simuler(carriere)

    salariale = next(c for c in comparaison.notionnel_prospectif.compte.cotisations
                     if c.annee == 2030)
    totale = next(c for c in comparaison.notionnel_prospectif_employeur.compte.cotisations
                  if c.annee == 2030)
    assert salariale.taux_effectif == pytest.approx(fusionne.taux_cotisation_salarie)
    assert totale.taux_effectif == pytest.approx(fusionne.taux_cotisation_retraite)
    assert totale.taux_effectif > salariale.taux_effectif


def test_le_repli_est_compte_quand_aucune_serie_n_existe(simulateur):
    """Aucun taux employeur SNCF avant 2007 : le modèle estime, et il le dit.

    La part patronale est alors celle d'un salarié du privé de la même année.
    C'est une estimation, pas une somme retrouvée : elle est comptée comme telle
    dans le décompte des années, et la fiabilité du scénario retombe.
    """
    carriere = simulateur.carriere_simple(
        annee_naissance=1955, sexe="H", affiliation="agent_sncf",
        age_debut=20, age_liquidation=50,
    )
    comparaison = simulateur.simuler(carriere)
    employeur = comparaison.contribution_employeur
    assert set(employeur.annees_par_origine) == {"repli"}
    assert employeur.annees_trouvees == 0
    assert employeur.a_un_employeur
    assert (comparaison.notionnel_retroactif_employeur.fiabilite
            < comparaison.notionnel_retroactif.fiabilite)


def test_la_part_employeur_est_decomposee(simulateur):
    """Agent + employeur = total, et l'employeur pèse le plus lourd."""
    carriere = simulateur.carriere_simple(
        annee_naissance=1975, sexe="F", affiliation="fonctionnaire_etat",
        age_debut=23, age_liquidation=64, part_primes=0.20,
    )
    employeur = simulateur.simuler(carriere).contribution_employeur
    assert employeur.concerne_un_regime_public
    assert employeur.agent + employeur.employeur == pytest.approx(employeur.total)
    assert 0.7 < employeur.part < 0.95
    # Carrière 1998-2038 : taux implicite jusqu'en 2005, appelé ensuite.
    assert set(employeur.annees_par_origine) == {"implicite", "appelee"}
    assert employeur.annees_par_origine["implicite"] == 8
    assert employeur.annees_repli == 0


def test_les_scenarios_4_et_5_ne_qualifient_pas_la_fiabilite_d_ensemble(simulateur):
    """Un repli du scénario 4 ne doit pas dégrader l'étalon ni le scénario 2."""
    carriere = simulateur.carriere_simple(
        annee_naissance=1955, sexe="H", affiliation="agent_sncf",
        age_debut=20, age_liquidation=50,
    )
    comparaison = simulateur.simuler(carriere)
    assert comparaison.fiabilite == min(
        comparaison.actuel.fiabilite,
        comparaison.notionnel_retroactif.fiabilite,
        comparaison.notionnel_prospectif.fiabilite,
    )
    assert (comparaison.notionnel_retroactif_employeur.fiabilite
            <= comparaison.notionnel_retroactif.fiabilite)


# -- taux d'acquisition commun (paramètre, pas scénario) ----------------------


def test_le_taux_uniforme_ne_compte_pas_deux_fois_la_meme_tranche():
    """Régime général et Arrco découpent la même première tranche.

    Sous un taux unique, les additionner prélèverait deux fois sur les mêmes
    euros. Le compte d'un cadre ne doit donc pas dépasser ce que le taux
    prélève sur sa rémunération plafonnée.
    """
    simulateur = Simulateur(Parametres().avec(
        source_cotisations=SourceCotisations.TAUX_UNIFORME
    ))
    carriere = simulateur.carriere_simple(
        annee_naissance=1975, sexe="H", affiliation="salarie_prive_cadre",
        age_debut=23, age_liquidation=64,
    )
    compte = simulateur.simuler(carriere).notionnel_retroactif.compte
    taux = simulateur.parametres.taux_cotisation_uniforme
    for cotisation in compte.cotisations:
        if cotisation.nulle:
            continue
        assert cotisation.cotisation <= cotisation.revenu * taux + 1e-6, cotisation.annee


def test_le_taux_uniforme_est_bien_le_taux_retenu():
    """Un salarié non cadre sous le plafond doit voir exactement le taux choisi."""
    simulateur = Simulateur(Parametres().avec(
        source_cotisations=SourceCotisations.TAUX_UNIFORME,
        taux_cotisation_uniforme=0.20,
    ))
    carriere = simulateur.carriere_simple(
        annee_naissance=1975, sexe="H", affiliation="salarie_prive_non_cadre",
        age_debut=23, age_liquidation=64, niveau_salaire=0.9,
    )
    compte = simulateur.simuler(carriere).notionnel_retroactif.compte
    annee = next(c for c in compte.cotisations if c.annee == 2010)
    assert annee.cotisation == pytest.approx(annee.revenu * 0.20)


def test_le_compartiment_de_capitalisation_garde_ses_taux():
    """Le RAFP n'est pas un compte notionnel : le taux unique ne s'y applique pas."""
    reference = Simulateur(Parametres())
    uniforme = Simulateur(Parametres().avec(
        source_cotisations=SourceCotisations.TAUX_UNIFORME
    ))
    profil = dict(
        annee_naissance=1975, sexe="F", affiliation="fonctionnaire_etat",
        age_debut=23, age_liquidation=64, part_primes=0.20,
    )
    attendu = reference.simuler(
        reference.carriere_simple(**profil)
    ).notionnel_retroactif.capital_capitalisation
    obtenu = uniforme.simuler(
        uniforme.carriere_simple(**profil)
    ).notionnel_retroactif.capital_capitalisation
    assert obtenu == pytest.approx(attendu)


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
    """Une carrière courte au SMIC relève du minimum : c'est son objet.

    À condition d'être liquidée au taux plein : ici par l'âge, la génération
    1965 l'obtenant sans condition de durée à 67 ans.
    """
    carriere = simulateur.carriere_simple(
        annee_naissance=1965, sexe="F", affiliation="salarie_prive_non_cadre",
        age_debut=37, age_liquidation=67, niveau_salaire=0.4,
        profil_carriere="plat",
    )
    resultat = simulateur.simuler(carriere).actuel
    assert resultat.minimum_applique is True


def test_le_minimum_contributif_est_refuse_a_une_pension_decotee(simulateur):
    """L'article L. 351-10 réserve le minimum aux pensions au taux plein.

    La même carrière liquidée cinq ans plus tôt n'a ni la durée requise ni
    l'âge d'annulation de la décote : le droit ne la relève pas. Le modèle la
    relevait, et faisait ainsi garantir par le système actuel un départ que le
    droit sanctionne — sur le segment même où l'écart avec les comptes
    notionnels se mesure.
    """
    carriere = simulateur.carriere_simple(
        annee_naissance=1965, sexe="F", affiliation="salarie_prive_non_cadre",
        age_debut=37, age_liquidation=62, niveau_salaire=0.4,
        profil_carriere="plat",
    )
    resultat = simulateur.simuler(carriere).actuel
    assert resultat.trimestres_valides < resultat.trimestres_requis
    assert resultat.minimum_applique is False


def test_la_majoration_du_minimum_suit_la_seule_duree_cotisee(simulateur):
    """Deux durées proratisent le minimum, et ce ne sont pas les mêmes.

    Le montant de base suit la durée d'ASSURANCE acquise dans le régime, sa
    majoration la seule durée COTISÉE (D. 351-2-2). Deux carrières de même
    durée d'assurance, dont l'une est pour moitié du chômage indemnisé, ne
    reçoivent donc pas le même plancher.
    """
    commun = dict(
        annee_naissance=1965, sexe="F", affiliation="salarie_prive_non_cadre",
        age_debut=42, age_liquidation=67, niveau_salaire=0.4,
        profil_carriere="plat",
    )
    entierement_cotisee = simulateur.simuler(
        simulateur.carriere_simple(**commun)
    ).actuel
    moitie_chomee = simulateur.simuler(simulateur.carriere_simple(
        interruptions={annee: "chomage_indemnise"
                       for annee in range(1965 + 42, 1965 + 54)},
        **commun,
    )).actuel

    # Même durée d'assurance — le chômage indemnisé valide ses trimestres.
    assert entierement_cotisee.trimestres_valides == moitie_chomee.trimestres_valides
    assert entierement_cotisee.minimum_applique
    assert moitie_chomee.minimum_applique
    minimum = {r.code: r.montant for r in entierement_cotisee.avantages_appliques}
    minimum_chome = {r.code: r.montant for r in moitie_chomee.avantages_appliques}
    assert (minimum["minimum_contributif"]
            > minimum_chome["minimum_contributif"])


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
        "actuel", "notionnel_retroactif", "notionnel_prospectif",
        "notionnel_retroactif_employeur", "notionnel_prospectif_employeur",
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

    Et il les sert au coefficient que l'accord de fusion a fixé, non au rapport
    de deux valeurs de service prises où les séries s'arrêtent. L'accord national
    interprofessionnel du 17 novembre 2017 convertit les points Arrco UN POUR UN
    et les points Agirc au coefficient 0,347798289 — celui qui figure sur les
    relevés de carrière.

    Ce test opposait auparavant le rapport `arrco(2018) / agirc_arrco(2019)`,
    qui vaut 0,990 : la valeur du régime unifié y était prise au 31 décembre
    2019, après la revalorisation de novembre, quand la conversion s'opère au
    1er janvier. Un pour cent de moins sur tous les points d'avant 2019.
    """
    from retraite_notionnelle.scenarios.actuel import ValeursPoint

    valeurs = ValeursPoint(simulateur.parametres.racine_donnees)
    scenario = simulateur.scenario_actuel
    derniere_arrco = valeurs.derniere_annee_servie("arrco")
    assert derniere_arrco == 2018

    avant, _ = valeurs.service("arrco", derniere_arrco)
    apres, _ = scenario.valeur_du_point("arrco", 2022)
    assert apres > avant, "les points Arrco n'ont pas suivi la fusion de 2019"

    service_2022, _ = valeurs.service("agirc_arrco", 2022)
    assert apres == pytest.approx(service_2022), "un point Arrco vaut un point Agirc-Arrco"

    agirc, _ = scenario.valeur_du_point("agirc", 2022)
    assert agirc / service_2022 == pytest.approx(0.347798289, rel=1e-6)


def test_un_regime_ferme_ne_vaut_jamais_plus_que_son_successeur(simulateur):
    """Une conversion aux fusions préserve les droits : elle ne les multiplie pas.

    Ce test attrape d'un coup les trois défauts de la chaîne de succession, tous
    dus à une date de reprise mal choisie : le point UNIRS valorisé quinze fois
    trop cher pour toute liquidation postérieure à 1998, les points IPACTE et
    IGRANTE cinquante-quatre fois trop chers au-delà de 2022, et le pour cent
    perdu à la fusion de 2019 parce que la valeur du régime unifié était prise au
    31 décembre et non au 1er janvier.
    """
    scenario = simulateur.scenario_actuel
    chaines = (
        ("unirs", "arrco"), ("ipacte", "ircantec"), ("igrante", "ircantec"),
        ("agirc", "agirc_arrco"), ("arrco", "agirc_arrco"),
    )
    for code, successeur in chaines:
        reprise = scenario.conversions_points.fusion(code, successeur)
        assert reprise is not None, f"aucun coefficient déclaré : {code} -> {successeur}"
        assert 0 < reprise.coefficient <= 1.0, (code, reprise.coefficient)
        # La comparaison n'a de sens qu'à compter de la reprise : avant elle, le
        # successeur n'existe pas et sa « valeur » n'est qu'un repli sur les prix.
        for annee in range(reprise.annee_effet, 2061):
            valeur = scenario.valeur_du_point(code, annee)
            reference = scenario.valeur_du_point(successeur, annee)
            if valeur is None or reference is None:
                continue
            assert valeur[0] <= reference[0] * 1.001, (code, annee, valeur[0], reference[0])


def test_le_rendement_du_point_ne_saute_pas_d_une_annee_sur_l_autre(simulateur):
    """Cent euros cotisés une année ou la suivante donnent des pensions voisines.

    Une rupture signale un changement d'ÉCHELLE que le moteur n'a pas traité.
    C'était le cas de l'Arrco en 1999 : les valeurs d'avant sont celles de
    l'UNIRS, celles d'après celles du régime unifié, et le moteur accumulait des
    points dans la première unité pour les liquider dans la seconde. Cent euros
    cotisés en 1998 produisaient 30,31 € de pension annuelle, les mêmes cent
    euros de 1999 n'en produisaient que 11,15 — un facteur 2,7 en une année,
    pour une unification qui, par construction, ne changeait aucun droit.
    """
    scenario = simulateur.scenario_actuel
    liquidation = 2029
    # La borne est large à dessein : elle vise les changements d'UNITÉ, qui se
    # comptent en facteurs, et non les mouvements de barème, qui peuvent être
    # brusques sans être faux — le taux d'appel de l'Ircantec passe de 0,60 à
    # 0,80 en 1983, et c'est le droit.
    for code in ("arrco", "agirc", "ircantec"):
        valeur_service = scenario.valeur_du_point(code, liquidation)
        assert valeur_service is not None
        precedent = None
        for annee in range(1962, 2019):
            achat = scenario.valeurs_point.achat(code, annee)
            if achat is None:
                continue
            reference, appel, _ = achat
            echelle, _ = scenario.conversions_points.echelle(code, annee, liquidation)
            rendu = 100.0 / (appel * reference) * echelle * valeur_service[0]
            if precedent is not None:
                assert 0.5 < rendu / precedent < 2.0, (code, annee, precedent, rendu)
            precedent = rendu


def test_les_trimestres_de_decote_sont_des_entiers(simulateur):
    """Article R. 351-27 : le nombre de trimestres est arrondi à l'entier supérieur.

    Les âges d'annulation de la décote des générations 1951 à 1954 valent 65,33,
    65,75, 66,17 et 66,58 ans. Sans arrondi, on opposait 13,32 trimestres à un
    assuré né en 1951 parti à 62 ans, quand le droit lui en oppose 14 : un taux
    de 40,01 % au lieu de 39,50 %.
    """
    scenario = simulateur.scenario_actuel
    periode = simulateur.catalogue["regime_general"].periode(2015)
    for generation in range(1945, 1976):
        for age_depart in (60.0, 61.0, 62.0, 63.0, 64.0, 65.0):
            carriere = simulateur.carriere_simple(
                annee_naissance=generation, sexe="H",
                affiliation="salarie_prive_non_cadre",
                age_debut=30, age_liquidation=age_depart,
            )
            _, age_annulation, _ = scenario._decote(
                periode, carriere, carriere.annee_liquidation
            )
            retenus = scenario._trimestres_de_decote(
                periode, carriere.trimestres_actuels, 168, age_depart, age_annulation
            )
            assert retenus == int(retenus), (generation, age_depart, retenus)


def test_les_neutralisations_ne_commandent_rien(simulateur):
    """Elles DÉCLARENT ce que les scénarios notionnels retirent, sans le piloter.

    La suppression n'est pas une option qu'on active : elle est la conséquence
    mécanique de la règle d'accumulation. Ce test fige la propriété, pour qu'on
    ne redonne pas à ces drapeaux un pouvoir qu'ils n'ont pas — et pour que la
    documentation cesse de le laisser croire.
    """
    carriere = dict(
        annee_naissance=1975, sexe="F", affiliation="salarie_prive_non_cadre",
        age_debut=22, age_liquidation=64, niveau_salaire=0.45, nombre_enfants=3,
    )
    tous_actifs = Simulateur(Parametres()).simuler(
        Simulateur(Parametres()).carriere_simple(**carriere)
    )
    aucun = Simulateur(
        Parametres(neutralisations=Neutralisations(
            minimum_contributif=False, majoration_enfants=False,
            majoration_duree_assurance=False, minimum_vieillesse_aspa=False,
        ))
    )
    resultat = aucun.simuler(aucun.carriere_simple(**carriere))
    for cle, _, _ in SCENARIOS_NOTIONNELS:
        assert (getattr(resultat, cle).pension_annuelle
                == pytest.approx(getattr(tous_actifs, cle).pension_annuelle))
    assert resultat.actuel.pension_annuelle == pytest.approx(
        tous_actifs.actuel.pension_annuelle
    )


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

    Elles sont rangées sous ``cnbf_complementaire``, et **le moteur s'en sert
    depuis que la fiche est scindée** : le régime de base des avocats est
    forfaitaire, le complémentaire est en points, et les agréger en un seul taux
    au rendement instantané effaçait les deux règles à la fois.
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

    # Le catalogue porte ce code, et le prix d'achat lui est attaché — pas au
    # régime de base, qui n'a pas de point.
    assert "cnbf_complementaire" in simulateur.catalogue
    valeurs_point = ValeursPoint(simulateur.parametres.racine_donnees)
    assert valeurs_point.achat("cnbf", 2026) is None
    assert valeurs_point.achat("cnbf_complementaire", 2026) is not None


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

    Les valeurs sont rangées sous ``msa_rco``, code qui a désormais sa propre
    fiche : la RCO a été scindée du régime de base, faute de quoi tout verser
    dans le complémentaire aurait fait disparaître la base. Ce test garde cette
    séparation autant que les valeurs.
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

    # La fiche est désormais scindée : la RCO a la sienne, et c'est elle qui
    # porte le barème en points ; la base garde la sienne, et son étage
    # proportionnel reste au rendement instantané faute de barème publié.
    catalogue = CatalogueRegimes(simulateur.parametres.racine_donnees)
    assert "msa_rco" in catalogue
    assert "msa_non_salaries" in catalogue
    rco = catalogue["msa_rco"].periode(2020)
    assert rco.type_calcul == "points"
    # Le barème est en POINTS : 100 points pour 1 820 SMIC, et le nombre de
    # points ne dépend donc pas du taux de cotisation — ce qui est heureux,
    # puisque c'est le barème qui est publié, pas le prix d'achat.
    assert rco.points_maximum == 100
    assert rco.assiette_repere_smic == 1820
    assert rco.assiette_plancher is True


# -- montée en charge des réformes, lue à la génération ----------------------


def test_les_salaires_anciens_sont_revalorises_sur_les_salaires(simulateur):
    """Le compte n'a pas toujours été revalorisé sur les prix.

    Les arrêtés annuels de revalorisation ont suivi les SALAIRES jusqu'en 1986
    avant de suivre les prix. Sur les Trente Glorieuses, les salaires ont crû
    nettement plus vite que les prix : appliquer la règle des prix à ces
    années-là ramenait au compte des salaires très en dessous de ce que le
    droit y a inscrit, et minorait le salaire de référence d'autant.
    """
    macro = simulateur.macro
    salaires = macro.coefficient_revalorisation_salaires(1960, 2025)
    prix = macro.coefficient_prix(1960, 2025)
    assert salaires > prix

    # À partir de 1987, les deux règles ne font plus qu'une.
    assert macro.coefficient_revalorisation_salaires(1990, 2025) == pytest.approx(
        macro.coefficient_prix(1990, 2025)
    )
    # Et le coefficient reste réversible, comme celui des prix.
    assert macro.coefficient_revalorisation_salaires(2025, 1960) == pytest.approx(
        1.0 / salaires
    )


def test_le_nombre_d_annees_du_salaire_de_reference_suit_la_generation(simulateur):
    """Dix à vingt-cinq années, à raison d'une par génération, de 1934 à 1948.

    Lu à l'année de liquidation, le paramètre opposait vingt-cinq années à des
    assurés auxquels la loi n'en a jamais demandé plus de dix — et étendre la
    moyenne aux années les plus faibles ne peut que l'abaisser.
    """
    from retraite_notionnelle.scenarios.actuel import AnneesSalaireReference

    table = AnneesSalaireReference(simulateur.parametres.racine_donnees)
    assert table.annees(1930)[0] == 10
    assert table.annees(1938)[0] == 15
    assert table.annees(1948)[0] == 25
    assert table.annees(1975)[0] == 25

    # Deux générations qui liquident à trente ans d'écart, même carrière type :
    # la plus ancienne relève de dix années, la plus récente de vingt-cinq.
    scenario = simulateur.scenario_actuel
    ancien = simulateur.carriere_simple(
        annee_naissance=1930, sexe="H", affiliation="salarie_prive_non_cadre",
        age_debut=20, age_liquidation=64, profil_carriere="ascendant",
    )
    recent = simulateur.carriere_simple(
        annee_naissance=1975, sexe="H", affiliation="salarie_prive_non_cadre",
        age_debut=20, age_liquidation=64, profil_carriere="ascendant",
    )
    catalogue = simulateur.catalogue
    periode_ancienne = catalogue["regime_general"].periode(
        ancien.annee_liquidation)
    periode_recente = catalogue["regime_general"].periode(recent.annee_liquidation)
    dix = scenario.salaire_de_reference(
        "regime_general", ancien, periode_ancienne,
        ancien.annee_liquidation, True, 1930)
    vingt_cinq = scenario.salaire_de_reference(
        "regime_general", ancien, periode_ancienne,
        ancien.annee_liquidation, True, 1975)
    assert dix > vingt_cinq
    assert periode_recente.salaire_reference_par_generation


def test_le_coefficient_de_minoration_suit_la_generation(simulateur):
    """2,5 % par trimestre avant 1944, 1,25 % à partir de 1953.

    La table de l'article R. 351-27 vaut aussi bien pour l'ancien droit —
    1,25 point retiré au taux de 50 %, soit 2,5 % de ce taux — que pour la
    montée en charge de la loi Fillon.
    """
    from retraite_notionnelle.scenarios.actuel import CoefficientsMinoration

    table = CoefficientsMinoration(simulateur.parametres.racine_donnees)
    assert table.coefficient(1940)[0] == pytest.approx(0.025)
    assert table.coefficient(1944)[0] == pytest.approx(0.02375)
    assert table.coefficient(1952)[0] == pytest.approx(0.01375)
    assert table.coefficient(1953)[0] == pytest.approx(0.0125)
    assert table.coefficient(1990)[0] == pytest.approx(0.0125)


def test_la_decote_est_plafonnee_a_vingt_trimestres(simulateur):
    """Le taux ne descend pas sous 37,5 %, quelle que soit l'anticipation.

    Sans ce plafond, un départ dix ans avant l'heure retirait la moitié de la
    pension de base là où le droit n'en retire que le quart.
    """
    resultats = {}
    for age in (52, 57, 62):
        carriere = simulateur.carriere_simple(
            annee_naissance=1965, sexe="H", affiliation="salarie_prive_non_cadre",
            age_debut=25, age_liquidation=age,
        )
        resultats[age] = simulateur.scenario_actuel.calculer(carriere)

    # 50 % × (1 − 1,25 % × 20) = 37,5 %, et pas moins.
    assert resultats[52].taux_liquidation == pytest.approx(0.375)
    assert resultats[57].taux_liquidation == pytest.approx(0.375)
    assert resultats[62].taux_liquidation == pytest.approx(0.375)


def test_l_age_d_annulation_de_la_decote_suit_la_generation(simulateur):
    """65 ans jusqu'à la génération 1950, 67 à partir de 1955.

    Les fiches portaient l'âge CIBLE de la loi de 2010 dès son entrée en
    vigueur, opposant 67 ans à des générations auxquelles la loi n'a jamais
    demandé plus de 65.
    """
    from retraite_notionnelle.scenarios.actuel import AgesAnnulationDecote

    table = AgesAnnulationDecote(simulateur.parametres.racine_donnees)
    assert table.age(1940)[0] == pytest.approx(65.0)
    assert table.age(1953)[0] == pytest.approx(66.17)
    assert table.age(1960)[0] == pytest.approx(67.0)

    # Une carrière courte liquidée à 65 ans : la génération 1945 y est au taux
    # plein d'office, la génération 1960 non.
    taux = {}
    for generation in (1945, 1960):
        carriere = simulateur.carriere_simple(
            annee_naissance=generation, sexe="H",
            affiliation="salarie_prive_non_cadre",
            age_debut=40, age_liquidation=65,
        )
        taux[generation] = simulateur.scenario_actuel.calculer(carriere).taux_liquidation
    assert taux[1945] == pytest.approx(0.50)
    assert taux[1960] < 0.50


# -- abattement propre aux complémentaires -----------------------------------


def test_les_coefficients_d_anticipation_sont_ceux_de_l_agirc_arrco():
    """Le barème du régime, et non la décote du régime de base.

    Deux tables — trimestres manquants, et âge — dont la plus avantageuse est
    retenue. L'exemple que la caisse publie elle-même : un participant né en
    1959 qui demande sa retraite à 63 ans et 2 mois (0,83 par l'âge) et totalise
    155 trimestres sur 167 requis (0,88 pour douze trimestres manquants) se voit
    appliquer 0,88.
    """
    from retraite_notionnelle.scenarios.actuel import _coefficient_anticipation

    # Table des trimestres manquants : un point par trimestre jusqu'à douze,
    # un point et quart ensuite, et rien au-delà de vingt.
    assert _coefficient_anticipation(0, 20) == pytest.approx(1.0)
    assert _coefficient_anticipation(1, 20) == pytest.approx(0.99)
    assert _coefficient_anticipation(12, 20) == pytest.approx(0.88)
    assert _coefficient_anticipation(20, 20) == pytest.approx(0.78)
    assert _coefficient_anticipation(21, 20) is None

    # Table des âges : elle descend un palier plus bas, jusqu'à 0,43.
    assert _coefficient_anticipation(40, 40) == pytest.approx(0.43)

    # Les trimestres sont arrondis AU SUPÉRIEUR : trois ans et dix mois
    # d'anticipation valent seize trimestres, pas quinze.
    assert _coefficient_anticipation(15 + 1 / 3, 40) == pytest.approx(0.83)


def test_l_abattement_de_la_complementaire_n_est_pas_celui_de_la_base(simulateur):
    """À dix ans d'anticipation, 0,43 chez l'Agirc-Arrco, 0,75 à la base.

    Les deux barèmes ne se recoupent pas : le régime complémentaire est plus
    doux sur les carrières courtes et beaucoup plus dur sur l'âge. Retenir la
    décote de la base, comme le faisait le modèle, était faux dans les deux
    sens.
    """
    carriere = simulateur.carriere_simple(
        annee_naissance=1965, sexe="H", affiliation="salarie_prive_non_cadre",
        age_debut=25, age_liquidation=57,
    )
    scenario = simulateur.scenario_actuel
    periode = simulateur.catalogue["agirc_arrco"].periode(2019)
    requis = scenario.durees_requises.trimestres(1965)[0]
    abattement = scenario._abattement_points(
        periode, carriere, 100, requis, 57.0, 2022)
    assert abattement == pytest.approx(0.43)

    # Au taux plein, aucun abattement, quel que soit l'âge.
    assert scenario._abattement_points(
        periode, carriere, requis, requis, 57.0, 2022) == pytest.approx(1.0)


def test_la_majoration_pour_enfants_de_la_complementaire_est_plafonnee(simulateur):
    """10 % à la base, mais au plus 2 367 € par an à l'Agirc-Arrco.

    Sans ce plafond, les familles très nombreuses de salariés du privé étaient
    surestimées : le cadre qui touche 30 000 € de complémentaire s'en voyait
    majorer de 3 000 € au lieu des 2 367 € que le régime sert au maximum.
    """
    carriere = simulateur.carriere_simple(
        annee_naissance=1965, sexe="F", affiliation="salarie_prive_cadre",
        age_debut=23, age_liquidation=64, niveau_salaire=3.0,
        profil_carriere="fortement_ascendant", nombre_enfants=4,
    )
    resultat = simulateur.scenario_actuel.calculer(carriere)
    majoration = next(a for a in resultat.avantages_appliques
                      if a.code == "majoration_enfants")
    complementaire = sum(
        p.montant for p in resultat.pensions_par_regime
        if p.regime in ("agirc", "arrco", "agirc_arrco")
    )
    assert "plafonnée" in majoration.detail
    assert majoration.montant < 0.10 * (
        complementaire + sum(p.montant for p in resultat.pensions_par_regime
                             if p.regime == "regime_general")
    )


def test_la_mda_compte_dans_la_proratisation_du_regime_qui_la_porte(simulateur):
    """Le droit attribue les trimestres DANS un régime, pas au-dessus d'eux.

    Ils jouaient sur la décote tous régimes confondus mais restaient hors du
    rapport durée acquise / durée requise du régime qui les accorde, ce qui
    amputait la mère de famille de la part que la MDA est censée lui rendre.
    """
    commun = dict(annee_naissance=1975, sexe="F",
                  affiliation="salarie_prive_non_cadre",
                  age_debut=30, age_liquidation=64)
    sans = simulateur.scenario_actuel.calculer(
        simulateur.carriere_simple(**commun, nombre_enfants=0))
    avec = simulateur.scenario_actuel.calculer(
        simulateur.carriere_simple(**commun, nombre_enfants=2))

    base_sans = next(p for p in sans.pensions_par_regime
                     if p.regime == "regime_general")
    base_avec = next(p for p in avec.pensions_par_regime
                     if p.regime == "regime_general")
    assert avec.trimestres_valides == sans.trimestres_valides + 16
    # La carrière est trop courte pour le taux plein : les seize trimestres
    # relèvent le taux ET la proratisation, et la pension de base monte plus
    # que du seul effet de décote.
    assert base_avec.montant > base_sans.montant
    assert "/" in base_avec.detail


def test_les_trimestres_pour_enfants_suivent_la_date_le_sexe_et_le_regime(simulateur):
    """Huit trimestres par enfant, à tout le monde et de tout temps : c'est ce
    que le module servait, et le droit n'en a jamais servi autant.

    La majoration de durée d'assurance naît en 1972 à un an par enfant, passe à
    deux ans en 1975, et va à la mère. La fonction publique ne l'applique pas :
    elle a sa bonification, un an par enfant né avant 2004 et deux trimestres
    pour les enfants nés depuis. Un père de trois enfants recevait douze
    trimestres — trois ans de durée d'assurance — que la loi ne lui a jamais
    donnés.
    """
    def trimestres(**kw):
        reglages = dict(affiliation="salarie_prive_non_cadre", age_debut=30,
                        age_liquidation=60, nombre_enfants=2, sexe="F")
        reglages.update(kw)
        carriere = simulateur.carriere_simple(**reglages)
        resultat = simulateur.scenario_actuel.calculer(carriere)
        sans = simulateur.scenario_actuel.calculer(
            simulateur.carriere_simple(**{**reglages, "nombre_enfants": 0})
        )
        return resultat.trimestres_valides - sans.trimestres_valides

    # La MDA se lit à l'ANNÉE DE LIQUIDATION : rien avant la loi Boulin, un an
    # par enfant jusqu'en 1974, deux ans ensuite.
    assert trimestres(annee_naissance=1910) == 0     # liquidation en 1970
    assert trimestres(annee_naissance=1913) == 8     # en 1973, 4 par enfant
    assert trimestres(annee_naissance=1920) == 16    # en 1980, 8 par enfant
    assert trimestres(annee_naissance=1960) == 16

    # Elle va à la mère : l'attribution par défaut des quatre trimestres
    # d'éducation ouverts en 2010 est la sienne, faute d'accord des parents.
    assert trimestres(annee_naissance=1960, sexe="H") == 0

    # La fonction publique sert sa propre bonification, lue à l'année de
    # naissance de l'enfant — présumé né aux trente ans de sa mère.
    fonctionnaire = dict(affiliation="fonctionnaire_etat")
    assert trimestres(annee_naissance=1960, **fonctionnaire) == 8   # nés en 1990
    assert trimestres(annee_naissance=1985, **fonctionnaire) == 4   # nés en 2015

    # Les régimes alignés appliquent les règles familiales du régime général
    # (article L. 634-2), ce que leur fiche ne disait pas.
    assert trimestres(annee_naissance=1950, affiliation="artisan") == 16


def test_les_trimestres_pour_enfants_nomment_le_dispositif_qui_les_accorde(simulateur):
    """La cascade doit dire ce qu'elle applique : la fonction publique ne sert
    pas une MDA, mais une bonification, et le montant n'est pas le même."""
    commun = dict(annee_naissance=1960, sexe="F", age_debut=30,
                  age_liquidation=62, nombre_enfants=3)
    privee = simulateur.scenario_actuel.calculer(
        simulateur.carriere_simple(affiliation="salarie_prive_non_cadre", **commun))
    publique = simulateur.scenario_actuel.calculer(
        simulateur.carriere_simple(affiliation="fonctionnaire_etat", **commun))

    def avantage(resultat):
        return next(a for a in resultat.avantages_appliques
                    if a.code == "majoration_duree_assurance")

    assert avantage(privee).libelle == "Majoration de durée d'assurance"
    assert "24 trimestres" in avantage(privee).detail
    assert avantage(publique).libelle == "Bonification pour enfants"
    assert "12 trimestres" in avantage(publique).detail


def test_la_loi_boulin_ne_visait_que_les_meres_de_deux_enfants(simulateur):
    """Le seuil de trois enfants du projet a été abaissé à deux au débat, pas à
    un : jusqu'en 1974, une mère d'un enfant unique n'avait droit à rien."""
    def trimestres(nombre_enfants, annee_naissance):
        commun = dict(annee_naissance=annee_naissance, sexe="F",
                      affiliation="salarie_prive_non_cadre",
                      age_debut=30, age_liquidation=60)
        avec = simulateur.scenario_actuel.calculer(
            simulateur.carriere_simple(**commun, nombre_enfants=nombre_enfants))
        sans = simulateur.scenario_actuel.calculer(
            simulateur.carriere_simple(**commun, nombre_enfants=0))
        return avec.trimestres_valides - sans.trimestres_valides

    # Liquidation en 1973, sous la loi Boulin.
    assert trimestres(1, 1913) == 0
    assert trimestres(2, 1913) == 8
    # Liquidation en 1980 : la loi du 3 janvier 1975 sert dès le premier enfant.
    assert trimestres(1, 1920) == 8


def test_la_surcote_parentale_recompense_l_annee_imposee_par_la_reforme_de_2023(
        simulateur):
    """L'avantage familial le plus récent, et le modèle l'ignorait.

    La loi du 14 avril 2023 a reculé l'âge légal à 64 ans : qui avait sa durée
    requise à 63 ans s'est vu imposer une année de travail de plus qui ne lui
    rapportait rien, la surcote ordinaire ne comptant qu'au-delà de l'âge légal.
    L'article L. 351-1-2-1 la paie 1,25 % par trimestre, quatre au plus, à qui
    détient un trimestre de majoration de durée d'assurance pour enfants.
    """
    def surcote(**kw):
        reglages = dict(annee_naissance=1968, sexe="F",
                        affiliation="salarie_prive_non_cadre",
                        age_debut=18, age_liquidation=64, nombre_enfants=2)
        reglages.update(kw)
        resultat = simulateur.scenario_actuel.calculer(
            simulateur.carriere_simple(**reglages))
        return next((a for a in resultat.avantages_appliques
                     if a.code == "surcote_parentale"), None)

    # Génération 1968 : âge légal 64 ans, donc quatre trimestres entre 63 et 64.
    acquise = surcote()
    assert acquise is not None
    assert "4 trimestres" in acquise.detail and "5.00%" in acquise.detail

    # Sans trimestre pour enfants, pas de surcote parentale : c'est ce trimestre
    # qui ouvre le droit, et il va par défaut à la mère.
    assert surcote(sexe="H") is None
    assert surcote(nombre_enfants=0) is None

    # Sans la durée requise à 63 ans, pas de surcote parentale non plus.
    assert surcote(age_debut=30) is None

    # Avant le 1er septembre 2023, le dispositif n'existe pas.
    assert surcote(annee_naissance=1955) is None

    # Génération 1958 : l'âge légal est de 62 ans, la fenêtre 63 → âge légal est
    # vide, et la surcote ordinaire prend seule le relais.
    assert surcote(annee_naissance=1958) is None


def test_la_surcote_est_passee_a_1_25_pour_cent_au_1er_janvier_2009(simulateur):
    """La fiche servait 0,75 % jusqu'en 2010, la loi 1,25 % depuis 2009.

    Le taux de la loi Fillon a été relevé par la loi de financement de la
    sécurité sociale pour 2009 : deux années de liquidations recevaient ici une
    surcote deux tiers trop faible.
    """
    def taux(annee_liquidation):
        carriere = simulateur.carriere_simple(
            annee_naissance=annee_liquidation - 62, sexe="H",
            affiliation="salarie_prive_non_cadre", age_debut=18,
            age_liquidation=62,
        )
        resultat = simulateur.scenario_actuel.calculer(carriere)
        return next(p.detail for p in resultat.pensions_par_regime
                    if p.regime == "regime_general")

    # Huit trimestres cotisés au-delà de l'âge légal et de la durée requise :
    # 50 % × (1 + 8 × 0,75 %) en 2008, 50 % × (1 + 8 × 1,25 %) en 2009.
    assert "taux 53.00%" in taux(2008)
    assert "taux 55.00%" in taux(2009)


def test_la_surcote_parentale_se_cumule_avec_la_surcote_ordinaire(simulateur):
    """Les deux ne comptent pas les mêmes trimestres : l'une entre 63 ans et
    l'âge légal, l'autre au-delà. Elles s'ajoutent sans se recouvrir."""
    commun = dict(annee_naissance=1968, sexe="F",
                  affiliation="salarie_prive_non_cadre",
                  age_debut=18, nombre_enfants=2)
    tardive = simulateur.scenario_actuel.calculer(
        simulateur.carriere_simple(**commun, age_liquidation=67))
    base = next(p for p in tardive.pensions_par_regime
                if p.regime == "regime_general")
    # Taux plein majoré de la surcote ordinaire (douze trimestres au-delà de
    # 64 ans), puis surcote parentale de 5 % par-dessus.
    assert "taux 57.50%" in base.detail
    assert "surcote parentale 5.00%" in base.detail


# -- régimes que le barème en points fait sortir du rendement instantané -----


def test_le_regime_de_base_des_liberaux_est_calcule_en_points(simulateur):
    """525 points au plafond, 25 sur la seconde tranche : c'est un barème.

    Le régime n'attribue pas un nombre de points proportionnel à la cotisation
    mais un nombre PLAFONNÉ de points par tranche. C'est cette règle — et non
    un prix d'achat, que la caisse ne publie pas — qui convertit le revenu en
    droits, et c'est elle qui manquait au moteur.
    """
    tranches = simulateur.catalogue["cnavpl"].periodes_actives(2020)
    assert [p.points_maximum for p in tranches] == [525.0, 25.0]
    assert [p.assiette for p in tranches] == ["plafonnee", "plafonnee_5_pass"]

    carriere = simulateur.carriere_simple(
        annee_naissance=1960, sexe="H", affiliation="profession_liberale",
        age_debut=27, age_liquidation=66, niveau_salaire=2.5,
    )
    pension = next(p for p in simulateur.scenario_actuel.calculer(
        carriere).pensions_par_regime if p.regime == "cnavpl")
    assert "points × valeur de service" in pension.detail

    # Un revenu au-dessus du plafond n'ouvre pas plus de 525 points par an sur
    # la première tranche : c'est tout l'objet du plafonnement.
    riche = simulateur.carriere_simple(
        annee_naissance=1960, sexe="H", affiliation="profession_liberale",
        age_debut=27, age_liquidation=66, niveau_salaire=8.0,
    )
    points_riche = float(next(p for p in simulateur.scenario_actuel.calculer(
        riche).pensions_par_regime if p.regime == "cnavpl"
    ).detail.split(" points")[0].replace(",", ""))
    annees = 66 - 27
    assert points_riche < 550 * annees


def test_la_complementaire_agricole_ouvre_cent_points_a_l_assiette_minimale(simulateur):
    """1 820 SMIC cotisés valent 100 points, et l'assiette ne descend pas plus bas.

    Le nombre de points ne dépend pas du taux de cotisation : c'est le barème
    qui est publié, pas le prix d'achat — et c'est ce qui débloque le calcul,
    la valeur d'achat du point de RCO restant introuvable.
    """
    carriere = simulateur.carriere_simple(
        annee_naissance=1960, sexe="H", affiliation="exploitant_agricole",
        age_debut=20, age_liquidation=64, niveau_salaire=0.2,
    )
    pension = next(p for p in simulateur.scenario_actuel.calculer(
        carriere).pensions_par_regime if p.regime == "msa_rco")
    points = float(pension.detail.split(" points")[0].replace(",", ""))
    # 2003 à 2023 inclus, cent points par an au minimum.
    assert points == pytest.approx(100 * 21, rel=0.01)
    assert pension.montant > 0


# -- minimum contributif, désormais sourcé dans le code ----------------------


def test_le_minimum_contributif_distingue_le_montant_majore(simulateur):
    """Deux montants, pas un : le majoré vaut près d'un cinquième de plus.

    Le majoré ne récompense que les périodes COTISÉES. Le modèle servait le
    montant de base à tout le monde — c'est-à-dire le plus faible des deux, et
    précisément pas celui qui s'applique à la carrière complète que le minimum
    est fait de protéger.
    """
    minimum = simulateur.scenario_actuel.minimum_contributif
    base, majore, plafond, _ = minimum.valeurs(2025)

    assert majore > base * 1.15

    # Les montants publiés par les caisses pour 2025 : 8 972 € et 10 721 €
    # par an. L'ancre du code, revalorisée sur le SMIC, doit les retrouver.
    assert base == pytest.approx(8972.28, rel=0.01)
    assert majore == pytest.approx(10720.68, rel=0.01)
    assert plafond == pytest.approx(16738.32, rel=0.01)


def test_le_minimum_contributif_est_revalorise_sur_le_smic(simulateur):
    """Le SMIC, et non les prix : c'est ce que la loi dit depuis 2014 et 2023.

    L'index ne dépend pas de l'ancre mais de l'ANNÉE TRAVERSÉE. Prendre celui
    de l'ancre appliquerait à quinze ans de revalorisations une règle que la
    loi n'a introduite qu'en 2023.
    """
    minimum = simulateur.scenario_actuel.minimum_contributif
    macro = simulateur.macro

    # Le plafond bascule sur le SMIC en 2014. Une année qui n'a pas de montant
    # connu se projette donc sur le SMIC depuis cette ancre — et le SMIC monte
    # plus vite que les prix.
    ancre, _ = minimum._revalorise("plafond_ecretement", 2014)
    porte, _ = minimum._revalorise("plafond_ecretement", 2018)
    assert porte == pytest.approx(ancre * macro.coefficient_smic(2014, 2018))
    assert porte > ancre * macro.coefficient_prix(2014, 2018)

    # 2025, lui, a un montant connu : aucune projection ne s'y applique.
    assert minimum._revalorise("plafond_ecretement", 2025)[0] == pytest.approx(
        1394.86 * 12
    )

    # Les deux minima ne basculent qu'en 2023. Une année antérieure se
    # revalorise donc sur les prix, depuis l'ancre de 2007.
    depuis_2007, _ = minimum._revalorise("montant_base", 2007)
    en_2012, _ = minimum._revalorise("montant_base", 2012)
    assert en_2012 == pytest.approx(depuis_2007 * macro.coefficient_prix(2007, 2012))


def test_les_montants_reellement_servis_priment_sur_toute_projection(simulateur):
    """Ce que les caisses ont payé passe avant ce que le modèle calcule.

    Le fichier porte deux sortes de valeurs : les ancres du code, certifiées,
    et les montants réellement servis, transcrits de leur publication. Les
    secondes ne sont que `haute` — ce sont des transcriptions — et elles
    l'emportent pourtant, parce qu'une valeur transcrite qui dit vrai vaut
    mieux qu'une valeur calculée qui dit faux.
    """
    minimum = simulateur.scenario_actuel.minimum_contributif

    # Réponse du ministère à la question écrite n° 32630 (Assemblée nationale) :
    # 642,93 €/mois en 2020, majoré à 702,55 €, plafond 1 191,57 €.
    servis = {
        2020: (642.93 * 12, 702.55 * 12, 1191.57 * 12),
        2024: (733.03 * 12, 876.13 * 12, 1394.86 * 12),
        2025: (747.69 * 12, 893.39 * 12, 1394.86 * 12),
    }
    for annee, (base, majore, plafond) in servis.items():
        assert minimum.valeurs(annee)[0] == pytest.approx(base), annee
        assert minimum.valeurs(annee)[1] == pytest.approx(majore), annee
        assert minimum.valeurs(annee)[2] == pytest.approx(plafond), annee


def test_une_reforme_ne_glisse_pas_dans_le_passe(simulateur):
    """La projection part de la valeur EN VIGUEUR, jamais d'une postérieure.

    La réforme du 14 avril 2023 a relevé le minimum majoré de plus de 30 %.
    Ramener cette valeur en arrière, comme le faisait la règle de l'ancre la
    plus proche, surestimait de 7,6 % le montant de 2020 — celui-là même que
    l'État a rappelé dans sa réponse à une question écrite.
    """
    minimum = simulateur.scenario_actuel.minimum_contributif
    ancres = sorted(a for (mesure, a) in minimum._table if mesure == "montant_majore")
    assert ancres[0] == 2007 and 2023 in ancres

    # 2015 n'est pas au fichier : il est projeté depuis l'ancre de 2007, donc
    # reste très en dessous du montant d'après réforme.
    projete, _ = minimum._revalorise("montant_majore", 2015)
    avant_reforme = minimum._table[("montant_majore", 2007)][0]
    apres_reforme = minimum._table[("montant_majore", 2023)][0]
    assert avant_reforme < projete < apres_reforme * 0.9

    # Et une année antérieure à toute ancre se projette depuis la première.
    ancien, _ = minimum._revalorise("montant_majore", 1990)
    assert ancien < avant_reforme


# -- mortalité observée avant 1986 -------------------------------------------


def test_les_quotients_observes_remontent_avant_eurostat(simulateur):
    """Eurostat s'arrête à 1986 ; l'INED, lui, remonte au XIXe siècle.

    `docs/limites.md` tenait la Human Mortality Database pour la seule source à
    remonter plus haut, et donc la série pour hors de portée puisqu'elle exige
    une inscription. Les tables de Vallin et Meslé, que l'INED sert librement,
    la remplacent : le modèle a désormais de vrais quotients là où il n'avait
    que sa loi de Gompertz-Makeham.
    """
    quotients = simulateur.mortalite._quotients_observes
    assert quotients is not None

    annees = sorted({annee for annee, _ in quotients})
    assert annees[0] <= 1899
    assert 1950 in annees and 1985 in annees and 2020 in annees

    # Avant 1986, les âges vont jusqu'à 104 ans : le raccord paramétrique ne
    # sert plus sur ces années-là.
    ages_1950 = quotients[(1950, "H")]
    assert max(ages_1950) >= 104
    # Un quotient reste une probabilité, et croît en tendance avec l'âge.
    assert all(0 < q <= 1 for q in ages_1950.values())
    assert ages_1950[90] > ages_1950[60] > ages_1950[30]

    # Et le moteur les emploie : la survie d'une année couverte ne passe plus
    # par la loi paramétrique.
    attendu = 1.0 - ages_1950[70]
    assert simulateur.mortalite.survie_annuelle(70, 1950, "H") == pytest.approx(attendu)


# -- ce que le droit positif fait, et que l'étalon ne faisait pas -------------


def test_le_salaire_de_reference_ne_retient_que_les_annees_du_regime(simulateur):
    """Un régime ne liquide que ce qui lui a été déclaré.

    Le salaire de référence portait sur TOUTE la carrière, régime par régime
    confondu : un polypensionné passé de la fonction publique au privé
    liquidait sa pension civile sur son dernier salaire privé — pendant que le
    prorata de durée, lui, restait celui du régime. Le modèle rapportait donc
    une part de carrière publique à une assiette qui ne l'était pas.
    """
    from retraite_notionnelle.carriere import AnneeCarriere, Carriere

    publiques = [AnneeCarriere(annee=a, revenu=20_000.0,
                               affiliation="fonctionnaire_etat")
                 for a in range(1980, 2000)]
    privees = [AnneeCarriere(annee=a, revenu=60_000.0,
                             affiliation="salarie_prive_cadre")
               for a in range(2000, 2022)]

    melangee = simulateur.scenario_actuel.calculer(Carriere(
        annee_naissance=1960, sexe="H", lignes=publiques + privees,
        age_liquidation=62,
    ))
    publique_seule = simulateur.scenario_actuel.calculer(Carriere(
        annee_naissance=1960, sexe="H", lignes=list(publiques), age_liquidation=62,
    ))

    pension = {p.regime: p for p in melangee.pensions_par_regime}
    seule = {p.regime: p for p in publique_seule.pensions_par_regime}
    # Même assiette des deux côtés : la pension civile ne connaît que le
    # traitement des années passées dans la fonction publique.
    assert "SR 28,501 €" in pension["fonction_publique_etat"].detail
    assert "SR 28,501 €" in seule["fonction_publique_etat"].detail
    # Et le salaire annuel moyen du régime général ne connaît que les années
    # privées : y verser les années publiques, plus faibles, l'abaissait.
    privee_seule = simulateur.scenario_actuel.calculer(Carriere(
        annee_naissance=1960, sexe="H", lignes=list(privees), age_liquidation=62,
    ))
    reference = {p.regime: p for p in privee_seule.pensions_par_regime}
    assert (pension["regime_general"].detail.split("×")[0]
            == reference["regime_general"].detail.split("×")[0])


def test_les_annees_posterieures_a_la_liquidation_n_ouvrent_rien(simulateur):
    """On ne cotise pas après être parti.

    La boucle d'acquisition ne bornait pas à l'année de liquidation : des
    années postérieures achetaient des points et validaient des trimestres,
    ce qui annulait jusqu'à la décote de qui, précisément, part tôt.
    """
    from retraite_notionnelle.carriere import AnneeCarriere, Carriere

    avant = [AnneeCarriere(annee=a, revenu=40_000.0,
                           affiliation="salarie_prive_non_cadre")
             for a in range(1985, 2022)]
    apres = [AnneeCarriere(annee=a, revenu=40_000.0,
                           affiliation="salarie_prive_non_cadre")
             for a in range(2022, 2030)]

    borne = simulateur.scenario_actuel.calculer(Carriere(
        annee_naissance=1960, sexe="H", lignes=list(avant), age_liquidation=62))
    prolongee = simulateur.scenario_actuel.calculer(Carriere(
        annee_naissance=1960, sexe="H", lignes=avant + apres, age_liquidation=62))

    assert borne.pension_annuelle == pytest.approx(prolongee.pension_annuelle)
    assert borne.trimestres_valides == prolongee.trimestres_valides


def test_la_decote_de_la_fonction_publique_est_celle_de_l_article_l14(simulateur):
    """Ni le coefficient du privé, ni son âge d'annulation.

    Trois écarts, tous dans le même sens. La décote n'existe qu'à compter de
    2006 ; son coefficient monte d'un huitième de point par an, de 0,125 % en
    2006 à 1,25 % en 2015 ; et son âge d'annulation n'est pas un âge en propre
    mais la LIMITE D'ÂGE du grade, diminuée d'un nombre décroissant de
    trimestres jusqu'en 2020.
    """
    scenario = simulateur.scenario_actuel

    # 2005 : la décote n'existe pas encore dans la fonction publique.
    carriere = simulateur.carriere_simple(
        annee_naissance=1945, sexe="H", affiliation="fonctionnaire_etat",
        age_debut=25, age_liquidation=60, niveau_salaire=1.2,
    )
    resultat = scenario.calculer(carriere)
    assert resultat.trimestres_valides < resultat.trimestres_requis
    assert resultat.taux_liquidation == pytest.approx(0.75)

    # 2012 : coefficient de 0,875 %, âge d'annulation à la limite d'âge moins
    # huit trimestres — 63 ans et neuf mois pour la génération 1952, dont la
    # limite d'âge est de 65 ans et neuf mois.
    periode = simulateur.catalogue["fonction_publique_etat"].periode(2012)
    carriere = simulateur.carriere_simple(
        annee_naissance=1952, sexe="H", affiliation="fonctionnaire_etat",
        age_debut=25, age_liquidation=60, niveau_salaire=1.2,
    )
    coefficient, age_annulation, _ = scenario._decote(periode, carriere, 2012)
    assert coefficient == pytest.approx(0.00875)
    assert age_annulation == pytest.approx(65.75 - 2.0)

    # 2020 : la montée en charge est finie, l'âge d'annulation EST la limite
    # d'âge et le coefficient vaut 1,25 %.
    periode = simulateur.catalogue["fonction_publique_etat"].periode(2020)
    carriere = simulateur.carriere_simple(
        annee_naissance=1960, sexe="H", affiliation="fonctionnaire_etat",
        age_debut=25, age_liquidation=60, niveau_salaire=1.2,
    )
    coefficient, age_annulation, _ = scenario._decote(periode, carriere, 2020)
    assert coefficient == pytest.approx(0.0125)
    assert age_annulation == pytest.approx(67.0)


def test_le_taux_d_avant_1983_ne_depend_que_de_l_age(simulateur):
    """Le taux plein par la durée est une création de 1982.

    Le régime général servait 20 % à 60 ans, majorés de quatre points par année
    différée jusqu'à 40 % à 65 ans ; la loi Boulin a porté ces bornes à 25 % et
    50 %. Aucune durée, si longue fût-elle, n'ouvrait le taux plein avant
    l'âge — et le modèle servait pourtant le taux plein à tout âge.
    """
    scenario = simulateur.scenario_actuel

    def taux(naissance, age):
        return scenario.calculer(simulateur.carriere_simple(
            annee_naissance=naissance, sexe="H",
            affiliation="salarie_prive_non_cadre",
            age_debut=20, age_liquidation=age,
        )).taux_liquidation

    # Ordonnances de 1945 : 20 % à 60 ans, 40 % à 65.
    assert taux(1905, 60) == pytest.approx(0.20)
    assert taux(1905, 65) == pytest.approx(0.40)
    # Loi Boulin : 25 % à 60 ans, 50 % à 65 — malgré quarante ans de carrière.
    assert taux(1915, 60) == pytest.approx(0.25)
    assert taux(1915, 65) == pytest.approx(0.50)


def test_le_minimum_garanti_de_la_fonction_publique_est_servi(simulateur):
    """Le plancher de la fonction publique, déclaré mais jamais appliqué.

    Barème de l'article L. 17 : 57,5 % de la référence à quinze ans de
    services, 95 % à trente, la totalité à quarante. La référence est le
    traitement de l'indice majoré 227 au 1er janvier 2004 — 997,96 € par mois,
    soit exactement 227 fois le point d'indice de cette année-là — revalorisé
    comme les pensions depuis.
    """
    minimum = simulateur.scenario_actuel.minimum_garanti

    # 997,96 € est la valeur du traitement à l'indice majoré 227, celle que
    # l'article désigne comme référence. En 2004 le barème n'en était encore
    # qu'à l'indice 217 : la montée en charge court jusqu'en 2013.
    assert minimum.reference(2004)[0] / 12 == pytest.approx(
        997.96 * 217 / 227, rel=0.001)
    assert minimum.reference(2013)[0] / 12 > minimum.reference(2004)[0] / 12
    assert minimum.reference(2024)[0] / 12 == pytest.approx(1325.01, rel=0.001)
    assert minimum.reference(2025)[0] / 12 == pytest.approx(1354.16, rel=0.001)

    plein = minimum.reference(2025)[0]
    assert minimum.montant(2025, 15 * 4)[0] == pytest.approx(plein * 0.575)
    assert minimum.montant(2025, 30 * 4)[0] == pytest.approx(plein * 0.95)
    assert minimum.montant(2025, 40 * 4)[0] == pytest.approx(plein)
    assert minimum.montant(2025, 45 * 4)[0] == pytest.approx(plein)

    # Et il relève réellement une petite pension publique liquidée au taux
    # plein — ici par l'âge, la décote étant nulle à 67 ans.
    carriere = simulateur.carriere_simple(
        annee_naissance=1962, sexe="F", affiliation="fonctionnaire_etat",
        age_debut=40, age_liquidation=67, niveau_salaire=0.5, part_primes=0.15,
    )
    resultat = simulateur.scenario_actuel.calculer(carriere)
    applique = {a.code: a.montant for a in resultat.avantages_appliques}
    assert applique["minimum_garanti"] > 0


def test_le_minimum_garanti_suppose_le_taux_plein_depuis_2011(simulateur):
    """La loi du 9 novembre 2010 l'a conditionné, et le modèle l'ignorait."""
    commun = dict(
        annee_naissance=1962, sexe="F", affiliation="fonctionnaire_etat",
        age_debut=40, niveau_salaire=0.5, part_primes=0.15,
    )
    decotee = simulateur.scenario_actuel.calculer(
        simulateur.carriere_simple(age_liquidation=64, **commun))
    taux_plein = simulateur.scenario_actuel.calculer(
        simulateur.carriere_simple(age_liquidation=67, **commun))

    assert all(a.code != "minimum_garanti" for a in decotee.avantages_appliques)
    assert any(a.code == "minimum_garanti" for a in taux_plein.avantages_appliques)


def test_le_droit_dit_si_la_liquidation_est_ouverte(simulateur):
    """Le modèle servait une pension à un âge où la loi n'en sert aucune.

    Un salarié du privé né en 1965 n'a pas le droit de liquider à 58 ans, sauf
    carrière longue — et la carrière longue exige d'avoir commencé tôt ET
    d'avoir la durée cotisée requise. Le montant reste calculé, parce qu'il
    faut comparer les trois scénarios sur la même carrière, mais le résultat
    dit désormais qu'il ne décrit aucune pension servie.
    """
    scenario = simulateur.scenario_actuel

    def ouverture(age_debut, age_liquidation):
        return scenario.calculer(simulateur.carriere_simple(
            annee_naissance=1965, sexe="H",
            affiliation="salarie_prive_non_cadre",
            age_debut=age_debut, age_liquidation=age_liquidation,
        ))

    tardif = ouverture(23, 60)
    assert tardif.liquidation_ouverte is False
    assert tardif.motif_ouverture == "non_ouverte"
    assert tardif.age_ouverture_opposable == pytest.approx(63.25)

    # À l'âge légal de sa génération, elle l'est.
    legal = ouverture(23, 64)
    assert legal.liquidation_ouverte is True
    assert legal.motif_ouverture == "age_legal"

    # Entré à seize ans et fort de plus de trimestres cotisés que la durée
    # requise, le même assuré part à 60 ans : c'est la carrière longue.
    precoce = ouverture(16, 60)
    assert precoce.liquidation_ouverte is True
    assert precoce.motif_ouverture == "carriere_longue"
    assert precoce.age_ouverture_opposable == pytest.approx(60.0)

    # Mais pas à 58 ans : la durée cotisée n'y est pas encore.
    assert ouverture(16, 58).liquidation_ouverte is False


def test_l_avpf_porte_un_salaire_au_compte(simulateur):
    """Une période assimilée ne porte aucun salaire ; l'AVPF, si.

    C'est toute la différence, et le modèle ne la faisait pas : les années
    d'éducation d'un enfant validaient des trimestres sans jamais ajouter de
    salaire au compte, alors que la CNAF y cotise sur une assiette forfaitaire
    égale au SMIC. Le cas type « carrière interrompue » annonçait cette
    compensation sans que rien ne la calcule.
    """
    from retraite_notionnelle.donnees.chargement import (
        charger_periodes_non_travaillees,
    )

    motifs = charger_periodes_non_travaillees(
        simulateur.parametres.racine_donnees
    )
    assert motifs["education_enfant"].avpf is True
    assert motifs["chomage_indemnise"].avpf is False

    carriere = simulateur.carriere_simple(
        annee_naissance=1970, sexe="F", affiliation="salarie_prive_non_cadre",
        age_debut=42, age_liquidation=64, niveau_salaire=1.2,
        profil_carriere="plat", nombre_enfants=2,
        interruptions={a: "education_enfant" for a in range(2014, 2019)},
    )
    interrompues = [l for l in carriere.lignes if l.revenu_avpf > 0]
    assert len(interrompues) == 5
    # L'assiette est le SMIC annuel : 1 820 heures au SMIC horaire de l'année.
    attendu = 1820.0 * simulateur.macro.smic_horaire(2014)
    assert interrompues[0].revenu_avpf == pytest.approx(attendu)

    # Sur une carrière de moins de vingt-cinq années portées au compte, ces
    # années au SMIC entrent dans la moyenne au lieu de la remplacer : le
    # salaire annuel moyen BAISSE. C'est la règle, et le modèle la montre.
    resultat = simulateur.scenario_actuel.calculer(carriere)
    applique = {a.code: a.montant for a in resultat.avantages_appliques}
    assert applique["avpf"] < 0


def test_le_minimum_vieillesse_complete_les_toutes_petites_pensions(simulateur):
    """L'ASPA, dernier plancher du système actuel, jamais servie jusqu'ici.

    Allocation différentielle : elle porte les ressources au barème d'une
    personne seule, 1 034,28 € par mois en 2025. Et elle ne s'ouvre qu'à
    65 ans, ce que le modèle respecte — il ne suit pas l'assuré au-delà de sa
    liquidation.
    """
    plafond = simulateur.scenario_actuel.minimum_vieillesse.plafond(2025)
    assert plafond[0] / 12 == pytest.approx(1034.28, rel=0.001)

    commun = dict(
        annee_naissance=1960, sexe="F", affiliation="salarie_prive_non_cadre",
        age_debut=50, niveau_salaire=0.5,
    )
    avant = simulateur.scenario_actuel.calculer(
        simulateur.carriere_simple(age_liquidation=64, **commun))
    apres = simulateur.scenario_actuel.calculer(
        simulateur.carriere_simple(age_liquidation=65, **commun))

    assert all(a.code != "minimum_vieillesse" for a in avant.avantages_appliques)
    applique = {a.code: a.montant for a in apres.avantages_appliques}
    assert applique["minimum_vieillesse"] > 0
    assert apres.pension_annuelle == pytest.approx(
        simulateur.scenario_actuel.minimum_vieillesse.plafond(2025)[0]
    )

    # Et le paramètre la retire d'un seul geste : ce n'est pas une pension.
    from retraite_notionnelle.simulateur import SCENARIOS_NOTIONNELS, Simulateur

    sans = Simulateur(simulateur.parametres.avec(
        minimum_vieillesse_dans_le_scenario_actuel=False
    ))
    depouillee = sans.scenario_actuel.calculer(
        sans.carriere_simple(age_liquidation=65, **commun))
    assert depouillee.pension_annuelle < apres.pension_annuelle


def test_la_garantie_minimale_de_points_agirc_est_servie(simulateur):
    """120 points par an, même quand la tranche B est nulle.

    Un cadre payé sous le plafond de la Sécurité sociale n'acquérait aucun
    point à l'Agirc, quand l'accord du 9 février 1988 lui en donnait 120 par
    an. La fiche du régime le déclarait ; le moteur ne le servait pas.
    """
    commun = dict(
        annee_naissance=1958, sexe="H", affiliation="salarie_prive_cadre",
        age_debut=32, age_liquidation=64, profil_carriere="plat",
    )
    sous_plafond = simulateur.scenario_actuel.calculer(
        simulateur.carriere_simple(niveau_salaire=0.8, **commun))
    agirc = {p.regime: p for p in sous_plafond.pensions_par_regime}["agirc"]

    # Vingt-neuf années cotisées de 1990 à 2018, toutes garanties.
    assert agirc.montant > 0
    assert "3,480 points" in agirc.detail


def test_le_regime_de_base_des_avocats_est_forfaitaire(simulateur):
    """La pension de base d'un avocat ne dépend pas de son revenu.

    C'est la particularité du régime, et c'est ce qu'un compte notionnel
    supprime le plus radicalement. La fiche agrégeait pourtant la base et le
    complémentaire en un seul taux calculé au rendement instantané : la pension
    y était intégralement proportionnelle au revenu, exactement l'inverse de la
    règle. Depuis la scission, seul le complémentaire l'est.
    """
    commun = dict(
        annee_naissance=1975, sexe="H", affiliation="avocat",
        age_debut=25, age_liquidation=64, profil_carriere="fortement_ascendant",
    )
    modeste = simulateur.scenario_actuel.calculer(
        simulateur.carriere_simple(niveau_salaire=0.8, **commun))
    aise = simulateur.scenario_actuel.calculer(
        simulateur.carriere_simple(niveau_salaire=4.0, **commun))

    base = {r.regime: r for r in modeste.pensions_par_regime}
    base_aise = {r.regime: r for r in aise.pensions_par_regime}
    assert base["cnbf"].montant == pytest.approx(base_aise["cnbf"].montant)
    assert "forfait" in base["cnbf"].detail
    # Le complémentaire, lui, suit le revenu.
    assert (base_aise["cnbf_complementaire"].montant
            > 4 * base["cnbf_complementaire"].montant)


def test_les_tranches_des_avocats_sont_en_euros_non_en_plafonds(simulateur):
    """La CNBF fixe ses tranches en euros et ne les indexe pas.

    42 507 € en 2023, en 2025 et en 2026, quand le plafond de la Sécurité
    sociale passait de 43 992 à 48 060 €. Les exprimer en plafonds, comme le
    fait le reste du catalogue, les ferait dériver d'année en année — d'où un
    champ écrit pour ce cas, et utilisable par tout régime qui ferait de même.
    """
    regime = simulateur.catalogue["cnbf_complementaire"]
    tranches = [p for p in regime.periodes_actives(2026)
                if p.borne_haute_euros is not None]
    assert len(tranches) == 5
    assert [p.borne_haute_euros for p in tranches] == [
        42507, 85014, 127521, 170028, 212535]
    assert [p.taux_cotisation_retraite for p in tranches] == [
        pytest.approx(t) for t in (0.07, 0.104, 0.122, 0.14, 0.158)]

    # Et les bornes restent en euros quel que soit le plafond de l'année.
    premiere = tranches[0]
    assert premiere.bornes_assiette_en_euros(48_060) == (0.0, 42507)
    assert premiere.bornes_assiette_en_euros(30_000) == (0.0, 42507)

    # Un régime ordinaire, lui, garde des bornes en plafonds.
    tranche_2 = next(p for p in simulateur.catalogue["agirc_arrco"]
                     .periodes_actives(2026) if p.assiette == "tranche_2")
    assert tranche_2.bornes_assiette_en_euros(48_060) == (48_060.0, 8 * 48_060.0)
