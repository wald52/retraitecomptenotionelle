"""Tests de la page « Coût » : les dépenses observées et les cinq contrefactuels.

Deux choses distinctes s'y vérifient. D'abord que les DONNÉES tiennent : la
ventilation rend le total, les codes de systèmes du modèle sont ceux
qu'écrit le vérificateur, les couvertures annoncées sont les couvertures
réelles. Ensuite que l'AGRÉGATION dit ce qu'elle prétend dire : le coût du
système actuel est la dépense observée, sans correction, et une réforme
prospective ne déplace rien avant sa bascule.
"""

from __future__ import annotations

import csv

import pytest

from retraite_notionnelle import Parametres
from retraite_notionnelle.config import RACINE_DONNEES
from retraite_notionnelle.cout import (
    DERNIERE_GENERATION,
    PREMIERE_GENERATION,
    SCENARIOS,
    calculer_cout,
    generations,
)
from retraite_notionnelle.donnees.chargement import Fiabilite
from retraite_notionnelle.donnees.depenses import (
    CODES_SYSTEMES,
    SYSTEMES,
    DepensesRetraite,
)
from retraite_notionnelle.simulateur import Simulateur


@pytest.fixture(scope="module")
def depenses() -> DepensesRetraite:
    return DepensesRetraite(RACINE_DONNEES)


@pytest.fixture(scope="module")
def cout(depenses: DepensesRetraite):
    return calculer_cout(Simulateur(Parametres()), depenses)


# -- les données -------------------------------------------------------------


def test_le_total_couvre_1959_a_aujourd_hui(depenses: DepensesRetraite):
    assert depenses.premiere_annee == 1959
    assert depenses.derniere_annee >= 2024
    annees = list(depenses.total.annees())
    assert annees == list(range(depenses.premiere_annee, depenses.derniere_annee + 1))


def test_la_ventilation_commence_en_1990(depenses: DepensesRetraite):
    """De 1981 à 1989 la DREES publie une autre nomenclature : c'est une impasse
    assumée, et le fichier ne doit pas prétendre le contraire."""
    assert depenses.premiere_annee_ventilee == 1990
    for systeme in SYSTEMES:
        serie = depenses.systemes[systeme.code]
        assert serie.premiere_annee == 1990, systeme.code
        assert serie.derniere_annee == depenses.derniere_annee, systeme.code


def test_la_ventilation_rend_le_total(depenses: DepensesRetraite):
    """Le seul contrôle qui vaille sur un regroupement : rien d'oublié, rien de
    compté deux fois."""
    for annee in depenses.annees_ventilees():
        somme = sum(depenses.depense_systeme(s.code, annee) for s in SYSTEMES)
        # Un dixième de million d'euros par système : l'arrondi d'écriture, et
        # rien de plus.
        assert somme == pytest.approx(depenses.depense(annee),
                                      abs=0.1 * len(SYSTEMES)), annee


def test_les_systemes_couvrent_la_ventilation():
    """Les codes du modèle et ceux qu'écrit le vérificateur ne peuvent pas
    diverger : le fichier de référence serait lu à moitié, en silence."""
    chemin = RACINE_DONNEES / "reference" / "macro" / "depenses_retraite_regimes.csv"
    with chemin.open(encoding="utf-8") as flux:
        lignes = (l for l in flux if not l.lstrip().startswith("#"))
        codes = {ligne["regime"] for ligne in csv.DictReader(lignes)}
    assert codes == set(CODES_SYSTEMES)
    assert len(CODES_SYSTEMES) == len(set(CODES_SYSTEMES))


def test_la_repartition_est_le_total_moins_ce_qui_n_en_releve_pas(
        depenses: DepensesRetraite):
    derniere = depenses.derniere_annee
    hors = sum(depenses.depense_systeme(s.code, derniere)
               for s in SYSTEMES if not s.repartition)
    assert depenses.repartition(derniere) + hors == pytest.approx(
        depenses.depense(derniere), abs=0.1 * len(SYSTEMES))
    # La répartition obligatoire pèse l'essentiel du risque, mais pas tout.
    part = depenses.repartition(derniere) / depenses.depense(derniere)
    assert 0.90 < part < 0.97


def test_la_depense_rapportee_au_pib_a_triple(depenses: DepensesRetraite):
    """Ordre de grandeur, pas prédiction : 5 % du PIB en 1959, 14 à 15 % depuis."""
    assert 0.04 < depenses.part_pib(1959) < 0.07
    assert 0.13 < depenses.part_pib(depenses.derniere_annee) < 0.16


def test_la_depense_est_certifiee(depenses: DepensesRetraite):
    for annee in depenses.annees():
        assert depenses.fiabilite(annee) == Fiabilite.CERTIFIEE, annee


# -- l'agrégation ------------------------------------------------------------


def test_les_generations_couvrent_la_fenetre():
    liste = generations()
    assert liste[0] == PREMIERE_GENERATION
    assert liste[-1] <= DERNIERE_GENERATION
    # Assez de générations pour que la moyenne pondérée ait un sens.
    assert len(liste) >= 15


def test_le_cout_du_systeme_actuel_est_la_depense_observee(cout):
    """L'étalon n'est pas corrigé : son rapport vaut un, année après année."""
    for ligne in cout.annees:
        assert ligne.rapports["actuel"] == 1.0
        assert ligne.cout("actuel") == ligne.observee
    assert cout.cumul("actuel") == pytest.approx(cout.cumul_observe())


def test_une_reforme_prospective_ne_deplace_rien_avant_sa_bascule(cout):
    """Les droits acquis sont conservés : aucune pension liquidée avant la
    bascule n'est modifiée, donc aucun euro n'est économisé sur le passé."""
    assert cout.derniere_annee < Parametres().annee_bascule
    assert set(cout.confondus_avec_actuel()) == {
        "notionnel_prospectif", "notionnel_prospectif_employeur",
    }
    for scenario in cout.confondus_avec_actuel():
        assert cout.cumul(scenario) == cout.cumul("actuel")


def test_la_part_patronale_coute_toujours_plus_que_la_seule_part_salariale(cout):
    """Le scénario 4 est le scénario 2 plus la cotisation de l'employeur : il ne
    peut pas coûter moins, aucune année."""
    for ligne in cout.annees:
        assert (ligne.rapports["notionnel_retroactif_employeur"]
                >= ligne.rapports["notionnel_retroactif"]), ligne.annee


def test_le_notionnel_retroactif_coute_moins_que_le_systeme_actuel(cout):
    """Résultat attendu du modèle, et non hypothèse : la part salariale seule,
    revalorisée sur la masse salariale, ne reconstitue pas les pensions servies."""
    for ligne in cout.annees:
        assert 0.0 < ligne.rapports["notionnel_retroactif"] < 1.0, ligne.annee
    assert cout.cumul("notionnel_retroactif") < cout.cumul("actuel")


def test_le_contrefactuel_ne_se_donne_jamais_pour_certifie(cout):
    """La dépense est certifiée, ce qu'on en tire ne l'est pas et ne peut
    pas l'être : aucune institution ne publie le coût d'un système qui n'a pas
    existé."""
    assert cout.fiabilite == Fiabilite.ESTIMEE


def test_les_cumuls_sont_en_euros_constants(cout):
    """Un cumul en euros courants additionnerait des unités incomparables. Le
    contrôle : le cumul dépasse largement la somme des montants nominaux, parce
    que les euros anciens valent plus que les euros récents."""
    nominal = sum(ligne.observee for ligne in cout.annees)
    assert cout.cumul_observe() > nominal * 1.5


def test_chaque_scenario_a_une_courbe_et_un_libelle(cout):
    codes = {scenario for scenario, _ in SCENARIOS}
    for ligne in cout.annees:
        assert set(ligne.rapports) == codes
    assert len(SCENARIOS) == 5
