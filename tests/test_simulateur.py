"""Tests des scénarios et du simulateur, au niveau du comportement attendu."""

from __future__ import annotations

import pytest

from retraite_notionnelle.carriere import AnneeCarriere, Carriere
from retraite_notionnelle.config import ModeIndexation, Neutralisations, Parametres
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


def test_desactiver_une_neutralisation_change_le_systeme_actuel():
    """Contrôle : la majoration pour trois enfants existe bien dans le scénario 1."""
    avec_majoration = Parametres(
        neutralisations=Neutralisations(majoration_enfants=False)
    )
    reference = Simulateur(Parametres())
    variante = Simulateur(avec_majoration)
    commun = dict(annee_naissance=1975, sexe="F",
                  affiliation="salarie_prive_non_cadre",
                  age_debut=22, age_liquidation=64, nombre_enfants=3)
    sans = reference.simuler(reference.carriere_simple(**commun)).actuel.pension_annuelle
    avec = variante.simuler(variante.carriere_simple(**commun)).actuel.pension_annuelle
    assert avec == pytest.approx(sans * 1.10)


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
