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
    """Et la cotisation DÉPLAFONNÉE en fait partie.

    L'assiette du régime unifié est déplafonnée : les 2,41 % que le régime
    général prélève sur la totalité du salaire y portent donc sur la même base
    que la part plafonnée, et s'y ajoutent. Les omettre faisait perdre au compte
    notionnel, après la bascule, exactement ce que la séparation des deux taux
    venait d'y porter avant elle.
    """
    fusionne = fusionner(catalogue, 2026)
    base = catalogue["regime_general"].periode(2026)
    complementaire = min(catalogue["agirc_arrco"].periodes_actives(2026),
                         key=lambda p: p.bornes_assiette_en_pass()[0])
    attendu = (
        base.taux_cotisation_retraite + base.taux_cotisation_deplafonnee
        + complementaire.taux_cotisation_retraite
        + complementaire.taux_cotisation_deplafonnee
    )
    assert fusionne.taux_cotisation_retraite == pytest.approx(attendu)
    assert base.taux_cotisation_deplafonnee > 0, (
        "sans déplafonnée au régime général, ce test ne prouve plus rien"
    )


def test_fusion_exclut_la_capitalisation(catalogue):
    assert "rafp" not in fusionner(catalogue, 2026).regimes_fusionnes


def test_fusion_variante_taux_le_plus_eleve(catalogue):
    fusionne = fusionner(
        catalogue, 2026, RegleFusion(critere_taux=CritereTaux.LE_PLUS_ELEVE)
    )
    maxima = max(
        periode.taux_cotisation_retraite + periode.taux_cotisation_deplafonnee
        for regime in catalogue if regime.vivant(2026) and not regime.hors_repartition
        for periode in regime.periodes_actives(2026)
    )
    assert fusionne.taux_cotisation_retraite == pytest.approx(maxima)


# -- le mois -----------------------------------------------------------------


def test_la_liquidation_est_datee_au_mois_et_non_arrondie_a_l_annee():
    """« Soixante-quatre ans et six mois » n'est pas « soixante-cinq ans ».

    Le modèle arrondissait ``naissance + âge`` à l'année civile la plus proche,
    et Python arrondit les demis AU PAIR : deux assurés déclarant le même âge
    étaient traités différemment selon la parité de leur millésime. La date se
    lit désormais en mois depuis la date de naissance.
    """
    from retraite_notionnelle.carriere import Carriere

    def date(naissance, mois, age):
        carriere = Carriere(annee_naissance=naissance, sexe="H",
                            mois_naissance=mois, age_liquidation=age,
                            lignes=[])
        return (carriere.date_liquidation.annee, carriere.date_liquidation.mois)

    # Né en mars 1962, parti à 64 ans et 6 mois : septembre 2026, et rien d'autre.
    assert date(1962, 3, 64.5) == (2026, 9)
    assert date(1962, 1, 64.5) == (2026, 7)
    # La parité du millésime ne décide plus de rien : deux générations
    # consécutives, même âge, même mois de départ dans l'année.
    assert date(1961, 1, 64.5)[1] == date(1962, 1, 64.5)[1] == 7
    # Un âge entier et une naissance en janvier tombent au 1er janvier, comme
    # avant : c'est la convention qui laisse les cas types inchangés.
    assert date(1975, 1, 64) == (2039, 1)


def test_l_annee_de_liquidation_est_portee_au_compte_au_prorata(macro):
    """Partir en décembre, ce n'est pas travailler onze mois pour rien.

    L'accumulation s'arrêtait à l'année PRÉCÉDANT la liquidation : les mois
    cotisés de l'année du départ n'allaient nulle part. Ils y vont, à
    proportion, et le compte croît donc de mois en mois.
    """
    from retraite_notionnelle.carriere import Carriere

    capitaux = []
    for mois in range(12):
        carriere = Carriere.depuis_profil(
            1962, "H", "salarie_prive_non_cadre", 22, 64 + mois / 12, macro,
        )
        ligne = carriere.ligne(carriere.annee_liquidation)
        if mois == 0:
            # Départ au 1er janvier : aucun mois de l'année n'est travaillé.
            assert ligne is None or carriere.part_retenue(2026) == 0
        else:
            assert ligne.fraction_annee == pytest.approx(mois / 12)
            assert ligne.revenu > 0
        capitaux.append(sum(l.revenu for l in carriere.lignes))
    assert capitaux == sorted(capitaux)
    assert capitaux[-1] > capitaux[0]


def test_les_trimestres_de_l_annee_du_depart_sont_bornes_aux_trimestres_civils(macro):
    """On ne valide pas quatre trimestres en sept mois.

    Le montant cotisé commande le nombre de trimestres, les mois en commandent
    le plafond : c'est la règle de l'article R. 351-9 pour l'année du point de
    départ, et elle vaut aussi pour l'année d'entrée dans la vie active.
    """
    from retraite_notionnelle.carriere import Carriere

    attendus = [0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 3]
    for mois, attendu in enumerate(attendus):
        carriere = Carriere.depuis_profil(
            1962, "H", "salarie_prive_non_cadre", 22, 64 + mois / 12, macro,
            niveau_salaire=3.0,
        )
        ligne = carriere.ligne(carriere.annee_liquidation)
        obtenu = 0 if ligne is None else carriere.trimestres_retenus(ligne)
        assert obtenu == attendu, mois


def test_un_releve_declarant_douze_mois_est_tronque_au_point_de_depart(macro):
    """Une ligne de carrière dit l'année ; la liquidation dit jusqu'où.

    Un relevé de carrière déclare des années pleines. Qui liquide au 1er juillet
    n'a pourtant travaillé que six mois de son année de départ, et c'est la plus
    courte des deux durées qui compte — sans quoi l'année du départ vaudrait
    douze mois de cotisations à qui n'en a fait aucun.
    """
    from retraite_notionnelle.carriere import AnneeCarriere, Carriere

    lignes = [AnneeCarriere(annee=a, revenu=40_000.0,
                            affiliation="salarie_prive_non_cadre")
              for a in range(1985, 2027)]
    carriere = Carriere(annee_naissance=1962, sexe="H", lignes=lignes,
                        age_liquidation=64.5)
    assert carriere.annee_liquidation == 2026
    assert carriere.part_retenue(2026) == pytest.approx(0.5)
    assert carriere.trimestres_retenus(carriere.ligne(2026)) == 2
    # Une année postérieure au départ ne compte pas, pleine ou non.
    assert carriere.part_retenue(2027) == 0.0

    # Départ au 1er janvier : l'année du départ ne compte pour rien.
    janvier = Carriere(annee_naissance=1962, sexe="H", lignes=list(lignes),
                       age_liquidation=64.0)
    assert janvier.part_retenue(2026) == 0.0


def test_le_diviseur_ne_fait_plus_de_marche_a_l_anniversaire(mortalite):
    """Le mois de départ déplace le diviseur, et régulièrement.

    ``survie_annuelle`` lisait ``quotients[int(age)]`` : la part OBSERVÉE de la
    table était aveugle aux mois, et le diviseur d'un départ à 60 ans et onze
    mois était celui d'un départ à 60 ans tout rond — puis tombait d'un coup à
    l'anniversaire. La force de mortalité étant supposée constante entre deux
    âges entiers, la décroissance est désormais lisse.
    """
    parametres = Parametres(racine_donnees=RACINE_DONNEES)
    convertisseur = Convertisseur(mortalite, parametres)
    # 2005 : les quotients observés couvrent la première moitié de la courbe,
    # et c'est là que la marche se produisait.
    diviseurs = [convertisseur.coefficient(60 + m / 12, 2005, "H").diviseur
                 for m in range(13)]
    ecarts = [avant - apres for avant, apres in zip(diviseurs, diviseurs[1:])]

    assert diviseurs == sorted(diviseurs, reverse=True)
    # Aucun pas ne pèse plus du double du plus petit : la marche d'un an valait
    # près de la moitié de la baisse annuelle à elle seule.
    assert max(ecarts) < 2 * min(ecarts)
    # Et le douzième mois retombe exactement sur l'âge entier suivant.
    assert diviseurs[12] == pytest.approx(
        convertisseur.coefficient(61.0, 2005, "H").diviseur
    )


def test_le_diviseur_decroit_aussi_au_passage_du_1er_janvier(mortalite):
    """Le millésime de la table ne doit pas sauter quand l'âge, lui, glisse.

    L'âge avançait mois par mois et l'année civile d'un bloc au 1er janvier :
    le diviseur REMONTAIT à cette date, et partir un mois plus tard rallongeait
    la durée de service attendue. Le trajet d'une année de rente est désormais
    découpé à ses deux franchissements — l'anniversaire, puis le 1er janvier —,
    chaque tronçon recevant la force de mortalité de la cellule qu'il traverse.
    """
    parametres = Parametres(racine_donnees=RACINE_DONNEES)
    convertisseur = Convertisseur(mortalite, parametres)

    # Vingt-quatre mois consécutifs, à cheval sur deux 1er janvier.
    diviseurs = []
    for k in range(25):
        annee, mois = 2037 + k // 12, k % 12 + 1
        diviseurs.append(
            convertisseur.coefficient(62 + k / 12, annee, "H", mois).diviseur
        )
    ecarts = [avant - apres for avant, apres in zip(diviseurs, diviseurs[1:])]

    assert all(ecart > 0 for ecart in ecarts), diviseurs
    # Le pas de janvier ne se distingue pas des autres : c'était le symptôme.
    assert max(ecarts) < 2 * min(ecarts), ecarts

    # Et douze mois de mois valent exactement un an d'âge, au même mois.
    assert diviseurs[12] == pytest.approx(
        convertisseur.coefficient(63.0, 2038, "H", 1).diviseur
    )


def test_le_taux_de_remplacement_rapporte_un_revenu_annualise(macro):
    """L'année du départ ne porte que ses mois ; le taux compare des années.

    Le dernier revenu servait de dénominateur tel quel. L'année du départ étant
    devenue incomplète, six mois de salaire y répondaient d'une pension
    annuelle : le taux de remplacement doublait pour qui liquidait en juillet.
    """
    from retraite_notionnelle.simulateur import Simulateur
    from retraite_notionnelle.carriere import Carriere

    simulateur = Simulateur(Parametres(racine_donnees=RACINE_DONNEES))
    taux = []
    for mois in range(12):
        carriere = Carriere.depuis_profil(
            1962, "H", "salarie_prive_non_cadre", 22, 64 + mois / 12,
            simulateur.macro, profil_carriere="plat",
        )
        taux.append(simulateur.simuler(carriere).taux_remplacement_actuel)

    # Aucun mois ne fait bondir le taux : il suit la pension, pas la troncature
    # de la dernière année.
    for avant, apres in zip(taux, taux[1:]):
        assert abs(apres / avant - 1) < 0.03, taux
    assert all(0.2 < t < 1.2 for t in taux), taux


def test_le_mois_de_liquidation_designe_la_circulaire_de_revalorisation(macro):
    """Deux circulaires portent l'année 2022, et elles diffèrent de 3,9 %.

    La revalorisation exceptionnelle du 1er juillet 2022 n'était opposée à
    personne : le modèle ne retenait que les colonnes prenant effet au
    1er janvier, si bien qu'une liquidation de septembre 2022 lisait celle de
    janvier et sous-revalorisait tout son salaire annuel moyen.
    """
    lu = macro.coefficient_revalorisation_portee_au_compte
    janvier = lu(2015, 2022, 1)
    juillet = lu(2015, 2022, 7)
    assert juillet > janvier
    assert juillet / janvier == pytest.approx(1.039, abs=0.002)
    # La colonne ne s'applique qu'à compter de sa date d'effet.
    assert lu(2015, 2022, 6) == pytest.approx(janvier)
    assert lu(2015, 2022, 12) == pytest.approx(juillet)
