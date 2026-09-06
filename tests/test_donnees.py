"""Tests du socle de données : chargement, fiabilité, cohérence du catalogue."""

from __future__ import annotations

import pytest

from retraite_notionnelle.config import RACINE_DONNEES
from retraite_notionnelle.donnees.chargement import DonneeInsuffisante, Fiabilite
from retraite_notionnelle.donnees.macro import DonneesMacro
from retraite_notionnelle.donnees.mortalite import DonneesMortalite
from retraite_notionnelle.donnees.regimes import (
    CatalogueRegimes,
    ContributionsEmployeurPubliques,
)


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
    for serie in (macro.inflation, macro.salaire_moyen, macro.productivite,
                  macro.masse_salariale):
        assert serie.premiere_annee <= 1941, f"{serie.nom} commence trop tard"
        assert serie.derniere_annee >= 2070, f"{serie.nom} ne va pas assez loin"


def test_annees_projetees_sont_de_fiabilite_minimale(macro):
    """Une projection ne doit jamais se faire passer pour une observation."""
    assert macro.inflation.fiabilite(2050) == Fiabilite.ESTIMEE
    assert macro.inflation.fiabilite(2000) > Fiabilite.ESTIMEE


def test_projection_applique_le_scenario_choisi():
    """Les trois taux du COR : 0,4 % et 1,0 % en variante, 0,7 % en référence."""
    reference = DonneesMacro(RACINE_DONNEES, scenario_projection="cor_reference")
    haute = DonneesMacro(RACINE_DONNEES, scenario_projection="cor_productivite_haute")
    basse = DonneesMacro(RACINE_DONNEES, scenario_projection="cor_productivite_basse")
    assert reference.productivite(2050) == pytest.approx(0.007)
    assert haute.productivite(2050) == pytest.approx(0.010)
    assert basse.productivite(2050) == pytest.approx(0.004)


def test_derniere_annee_observee_coincide_avec_la_declaration(macro):
    """La déclaration du fichier d'hypothèses doit dire vrai.

    ``annee_derniere_observation`` est écrite à la main dans
    ``hypotheses_projection.yaml`` ; la page de résultats s'en sert pour dire au
    lecteur à partir de quelle année son chiffre repose sur un scénario. Une
    déclaration que rien ne contrôle finit par mentir — le jour où une série
    gagne une année observée sans que le fichier suive.
    """
    assert macro.derniere_annee_observee == macro.annee_derniere_observation_declaree


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
    for serie in (macro.inflation, macro.salaire_moyen, macro.productivite,
                  macro.masse_salariale):
        assert serie.fiabilite_minimale_sur(1950, 2025) == Fiabilite.CERTIFIEE, serie.nom


def test_ce_qui_precede_1950_reste_annonce_comme_estime(macro):
    """Aucune source n'existe pour l'avant-guerre : le dire, plutôt que l'oublier."""
    for serie in (macro.inflation, macro.salaire_moyen, macro.productivite,
                  macro.masse_salariale):
        assert serie.fiabilite(1935) == Fiabilite.ESTIMEE, serie.nom


def test_plafond_certifie_sur_la_periode_publiee_par_l_insee(macro):
    assert macro.plafond_securite_sociale.fiabilite(2010) == Fiabilite.CERTIFIEE


def test_plafond_ancien_vient_d_une_transcription_pas_du_producteur(macro):
    """Les années d'avant 2002 dont le décret n'a pas été lu valent « haute ».

    Elles viennent d'OpenFisca-France, transcription du Journal officiel :
    publiée, sourcée, reprise automatiquement — mais pas de la main du
    producteur : 1962 et avant, dont le décret ne nomme pas l'année qu'il
    commande ; 1982-1983 et 1989, dont le texte n'écrit pas le montant ;
    1985-1986, sans notice ; 1994-1995, dont le tableau est resté en image.
    """
    for annee in (1945, 1960, 1962, 1985, 1989, 1994):
        assert macro.plafond_securite_sociale.fiabilite(annee) == Fiabilite.HAUTE, annee


def test_plafond_ancien_certifie_la_ou_le_decret_a_ete_lu(macro):
    """Trente et une années d'avant 2002 sont lues dans le Journal officiel.

    Le plafond n'est pas une statistique mais un décret : la base JORF de la
    DILA en est le producteur, là où l'INSEE ne commence qu'en 2002. La chaîne
    y est complète depuis 1963 — avant 1982 le titre du décret porte à lui seul
    l'année et le montant annuel.
    """
    for annee in (1963, 1969, 1981, 1984, 1987, 1988, 1990, 1993, 1996, 2001):
        assert macro.plafond_securite_sociale.fiabilite(annee) == Fiabilite.CERTIFIEE, annee


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


def _esperance_de_la_table_lue(mortalite, age, annee, sexe):
    """Espérance du moment reconstituée par le SEUL chemin que le moteur emprunte.

    ``survie_annuelle`` est le point de passage obligé : quotients observés là
    où ils existent, loi paramétrique ailleurs. Passer par lui, et non par
    ``esperance_residuelle(..., generation=False)``, est ce qui rend le contrôle
    ci-dessous réel — cette branche-là n'a longtemps consulté aucun quotient,
    si bien qu'elle comparait la calibration à sa propre cible et ne pouvait pas
    échouer.
    """
    probabilites, courante, courant = [1.0], 1.0, age
    while courant < 120 and courante > 1e-10:
        courante *= mortalite.survie_annuelle(courant, annee, sexe)
        probabilites.append(courante)
        courant += 1
    return sum(0.5 * (probabilites[t] + probabilites[t + 1])
               for t in range(len(probabilites) - 1))


def test_les_tables_observees_reproduisent_les_esperances_publiees(mortalite, esperances):
    """Deux sources indépendantes doivent décrire la même mortalité.

    Les quotients viennent d'Eurostat et de l'INED, les espérances de l'INSEE et
    de l'OCDE. La table que le moteur LIT — quotients observés puis queue
    paramétrique — doit retomber sur l'espérance publiée, faute de quoi le
    diviseur de conversion ne décrit pas la longévité que le pays mesure.

    Le raccord au-dessus du dernier âge publié a longtemps fait déborder cette
    table de 2,5 ans : les millésimes 1998-2013 s'arrêtent à 84 ans, et la loi
    prenait le relais avec une queue calibrée sur elle-même — 11,3 ans
    d'espérance résiduelle à 85 ans pour une femme en 2010, là où la cible en
    implique 7,5.
    """
    for annee in (1990, 2000, 2005, 2010, 2013, 2015, 2020, 2024):
        for sexe in ("H", "F"):
            recalculee = _esperance_de_la_table_lue(mortalite, 60, annee, sexe)
            assert recalculee == pytest.approx(
                esperances[(annee, sexe, "e60")], abs=0.1
            ), (annee, sexe)


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
        "masse_salariale": "macro/masse_salariale.csv",
        "pib_nominal": "macro/pib_nominal.csv",
        "productivite": "macro/productivite.csv",
        "plafond": "macro/plafond_securite_sociale.csv",
        "plafond_ancien": "macro/plafond_securite_sociale.csv",
        "plafond_journal_officiel": "macro/plafond_securite_sociale.csv",
        "minimum_vieillesse": "legislation/minimum_vieillesse.csv",
        "esperances_vie": "mortalite/esperances_vie.csv",
        "esperance_65_derivee": "mortalite/esperances_vie.csv",
        "esperances_projetees": "mortalite/esperances_vie.csv",
        "minimum_contributif": "legislation/minimum_contributif.csv",
        "age_ouverture_requis": "legislation/age_ouverture_requis.csv",
        "duree_assurance_requise": "legislation/duree_assurance_requise.csv",
        "duree_assurance_requise_decrets":
            "legislation/duree_assurance_requise.csv",
        "coefficient_minoration": "legislation/coefficient_minoration.csv",
        "carriere_longue": "legislation/carriere_longue.csv",
        "duree_proratisation": "legislation/duree_proratisation.csv",
        "annees_salaire_reference": "legislation/annees_salaire_reference.csv",
        "validation_trimestres": "legislation/validation_trimestres.csv",
        "smic_horaire": "macro/smic_horaire.csv",
        "decote_fonction_publique_coefficient":
            "legislation/decote_fonction_publique.csv",
        "minimum_garanti_indice": "legislation/minimum_garanti.csv",
        "minimum_garanti_part": "legislation/minimum_garanti.csv",
        "minimum_garanti_points_15_30": "legislation/minimum_garanti.csv",
        "minimum_garanti_points_30_40": "legislation/minimum_garanti.csv",
        "minimum_garanti_seuil": "legislation/minimum_garanti.csv",
        "decote_fonction_publique_trimestres":
            "legislation/decote_fonction_publique.csv",
        "point_indice_fonction_publique":
            "legislation/point_indice_fonction_publique.csv",
        "point_indice_journal_officiel":
            "legislation/point_indice_fonction_publique.csv",
        "quotients_mortalite": "mortalite/quotients_periode.csv",
        "quotients_mortalite_anciens": "mortalite/quotients_periode.csv",
        "valeurs_point": "regimes/valeurs_point.csv",
        "valeurs_point_ircantec": "regimes/valeurs_point.csv",
        "valeurs_point_cnbf": "regimes/valeurs_point.csv",
        "valeurs_point_rafp": "regimes/valeurs_point.csv",
        "valeurs_point_cnavpl": "regimes/valeurs_point.csv",
        # L'INSEE ne comble que la fin de série : depuis que la fédération
        # Agirc-Arrco est lue directement, elle n'a plus rien à ajouter, et sa
        # trace est retirée du journal plutôt que d'y affirmer une
        # certification qui n'a pas lieu. Elle y reparaîtra le jour où l'INSEE
        # publiera une année que le producteur n'a pas encore.
        "valeurs_point_agirc_arrco": "regimes/valeurs_point.csv",
        "valeurs_point_agirc_arrco_en_cours": "regimes/valeurs_point.csv",
        "valeurs_point_msa": "regimes/valeurs_point.csv",
        "valeurs_point_unirs": "regimes/valeurs_point.csv",
        "valeurs_point_texte": "regimes/valeurs_point.csv",
        "employeur_public_etat":
            "legislation/contribution_employeur_public.csv",
        "employeur_public_etat_implicite":
            "legislation/contribution_employeur_public.csv",
        "employeur_public_cnracl":
            "legislation/contribution_employeur_public.csv",
        "employeur_public_cnracl_journal_officiel":
            "legislation/contribution_employeur_public.csv",
        "employeur_public_sncf":
            "legislation/contribution_employeur_public.csv",
        "employeur_public_sncf_textes":
            "legislation/contribution_employeur_public.csv",
        "employeur_public_texte":
            "legislation/contribution_employeur_public.csv",
    }
    # Les séries d'APPOINT — celles qui ne comblent que ce que les autres ne
    # couvrent pas — peuvent n'avoir rien à dire, et sont alors absentes.
    appoint = {"valeurs_point_insee", "employeur_public_texte"}
    assert set(journal["series"]) <= set(fichiers)
    assert set(fichiers) - set(journal["series"]) <= appoint

    # Deux contrôles peuvent viser le même fichier à des niveaux différents —
    # le plafond en est le cas : INSEE certifie 2002-2025, OpenFisca renseigne
    # tout ce qui précède au niveau « haute ». On compare donc par (fichier,
    # niveau), pas contrôle par contrôle.
    #
    # Et deux contrôles peuvent viser les mêmes LIGNES par des COLONNES
    # différentes : l'article 66 de la loi de 2003 fixe, dans le même tableau,
    # le coefficient de la décote de la fonction publique et son âge
    # d'annulation. Leurs valeurs ne s'additionnent pas — c'est la colonne la
    # mieux couverte qui dit combien de lignes le fichier doit porter.
    par_colonne: dict[tuple[str, str, str], int] = collections.Counter()
    for nom, trace in journal["series"].items():
        par_colonne[(fichiers[nom], trace["niveau"], trace["colonne"])] += \
            trace["valeurs"]
    attendu: dict[tuple[str, str], int] = {}
    for (fichier, niveau, _), valeurs in par_colonne.items():
        attendu[(fichier, niveau)] = max(attendu.get((fichier, niveau), 0), valeurs)

    constate: dict[tuple[str, str], int] = collections.Counter()
    for chemin_relatif in set(fichiers.values()):
        chemin = RACINE_DONNEES / "reference" / chemin_relatif
        with chemin.open(encoding="utf-8") as flux:
            lignes = (l for l in flux if not l.lstrip().startswith("#"))
            for ligne in csv.DictReader(lignes):
                constate[(chemin_relatif, ligne["fiabilite"])] += 1

    for cle, nombre in attendu.items():
        assert constate[cle] == nombre, cle


def test_les_tables_par_generation_disent_le_droit_en_vigueur():
    """Les bornes des réformes, telles que les articles du code les écrivent.

    Ces trois tables sont désormais lues dans la base LEGI et non plus saisies
    (`scripts/fetch/dila_legi_parametres_retraite.py`). Le récupérateur n'étant
    pas rejoué à chaque exécution des tests — il lit 9 Go en flux — c'est ici
    qu'on fige ce qu'il a trouvé : si un jour une passe le contredit, l'écart
    apparaîtra sur une borne connue et non au milieu d'une série.
    """
    import csv

    def table(nom, colonne):
        chemin = RACINE_DONNEES / "reference" / "legislation" / nom
        with chemin.open(encoding="utf-8") as flux:
            lignes = (l for l in flux if not l.lstrip().startswith("#"))
            return {
                float(ligne["generation"]): (float(ligne[colonne]),
                                             ligne["fiabilite"])
                for ligne in csv.DictReader(lignes)
            }

    ages = table("age_ouverture_requis.csv", "age")
    # Loi du 9 novembre 2010, puis loi du 14 avril 2023.
    assert ages[1950][0] == 60.0
    assert ages[1955][0] == 62.0
    assert ages[1968][0] == 64.0
    # LES DEUX GÉNÉRATIONS QUE LES TEXTES COUPENT EN COURS D'ANNÉE. Elles
    # portent deux lignes chacune, et la clé décimale dit le mois : `1951.5`
    # pour le 1er juillet 1951, `1961.667` pour le 1er septembre 1961.
    assert ages[1951][0] == 60.0 and ages[1951.5][0] == 60.33
    assert ages[1961][0] == 62.0 and ages[1961.667][0] == 62.25
    # Les deux fractions viennent du texte au même titre : le récupérateur rend
    # un segment par valeur, et la confrontation les a trouvées identiques.
    assert all(niveau == "certifiee" for _, niveau in ages.values())

    annulation = table("age_annulation_decote.csv", "age")
    assert annulation[1950][0] == 65.0
    assert annulation[1951][0] == 65.0 and annulation[1951.5][0] == 65.33

    durees = table("duree_assurance_requise.csv", "trimestres")
    assert durees[1943][0] == 160          # fin de la montée en charge Balladur
    assert durees[1958][0] == 167          # loi Touraine
    assert durees[1965][0] == 172          # cible atteinte, loi de 2023
    assert durees[1943][1] == "haute"      # décrets non codifiés
    assert durees[1958][1] == "certifiee"  # article L. 161-17-3
    # Même coupure au 1er septembre 1961 : 168 trimestres avant, 169 après.
    assert durees[1961][0] == 168 and durees[1961.667][0] == 169

    coefficients = table("coefficient_minoration.csv", "coefficient")
    assert coefficients[1943][0] == 0.025
    assert coefficients[1952][0] == 0.01375
    assert coefficients[1953][0] == 0.0125
    assert all(niveau == "certifiee" for _, niveau in coefficients.values())
    # Aucun texte ne coupe une génération sur ce paramètre : la table reste
    # entièrement annuelle, et on le vérifie plutôt que de le supposer.
    assert all(float(g).is_integer() for g in coefficients)

    # La table est monotone : une génération plus jeune n'est jamais mieux
    # traitée que sa devancière sur l'âge et la durée, jamais plus mal sur le
    # coefficient. Une inversion signalerait une version d'article mal ordonnée.
    for serie, croissante in ((ages, True), (durees, True), (coefficients, False)):
        valeurs = [serie[g][0] for g in sorted(serie)]
        for avant, apres in zip(valeurs, valeurs[1:]):
            assert (apres >= avant) if croissante else (apres <= avant)



def test_la_proratisation_et_l_assiette_du_trimestre_sont_lues_dans_le_code():
    """Deux tables de plus lues dans LEGI, et une ligne qui n'y est pas.

    R. 351-6 II donne la durée maximale prise en compte par la proratisation —
    à ne pas confondre avec la durée requise — et s'arrête à la génération
    1947 : la ligne 1948 est la jonction avec `duree_assurance_requise.csv`,
    qu'aucun article n'écrit, et reste donc au niveau `haute`. R. 351-9 donne
    l'assiette d'un trimestre, en heures de SMIC.
    """
    import csv

    def lire(nom, cle, colonne):
        chemin = RACINE_DONNEES / "reference" / "legislation" / nom
        with chemin.open(encoding="utf-8") as flux:
            lignes = (l for l in flux if not l.lstrip().startswith("#"))
            return {
                float(ligne[cle]): (float(ligne[colonne]), ligne["fiabilite"])
                for ligne in csv.DictReader(lignes)
            }

    proratisation = lire("duree_proratisation.csv", "generation", "trimestres")
    assert proratisation[1900] == (150.0, "certifiee")   # « nés avant 1944 »
    assert proratisation[1945] == (154.0, "certifiee")
    assert proratisation[1947] == (158.0, "certifiee")
    assert proratisation[1948] == (160.0, "haute")       # la jonction, hors texte

    trimestre = lire("validation_trimestres.csv", "annee", "heures")
    assert trimestre[1972] == (200.0, "certifiee")
    assert trimestre[2014] == (150.0, "certifiee")

    # R. 351-29-1 : le II donne les générations 1934 à 1947, le I la cible et
    # la première génération qu'elle vise, « nés après 1947 ».
    salaire = lire("annees_salaire_reference.csv", "generation", "annees")
    assert salaire[1900] == (10.0, "certifiee")
    assert salaire[1944] == (21.0, "certifiee")   # « Vingt et une années »
    assert salaire[1948] == (25.0, "certifiee")


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
    """Là où la loi EST la table, elle doit retomber sur ses cibles.

    C'est le cas des années projetées, pour lesquelles aucun quotient n'est
    observé : la loi paramétrique y décrit seule toute la plage d'âges. Les
    cibles sont relues dans le fichier de référence plutôt que recopiées ici :
    c'est la source qui fait foi, et une recertification ne doit pas demander de
    retoucher le test.

    Pour les années OBSERVÉES, la loi ne décrit plus que la queue de la table,
    au-dessus du dernier âge publié : son espérance à 60 ans n'a plus de sens en
    propre, et c'est la table raccordée qu'il faut interroger — ce que fait
    ``test_les_tables_observees_reproduisent_les_esperances_publiees``.
    """
    for annee, sexe in [(2030, "H"), (2030, "F"), (2050, "H"), (2070, "F")]:
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


def test_e65_ancienne_derive_des_quotients_certifies(mortalite):
    """Avant 1960, l'espérance de vie à 65 ans n'est plus saisie mais calculée.

    Personne ne la publie avant l'OCDE, et le dépôt la tirait de quatre valeurs
    saisies dans les tables TD/TV, les treize autres années étant interpolées
    entre elles. Il a mieux depuis qu'il porte les quotients du moment de Vallin
    et Meslé : une espérance de vie est leur somme cumulée.

    Le contrôle qui autorise la méthode est ici : appliquée à e60, que l'INSEE
    publie et que le dépôt certifie, elle retrouve la valeur publiée à moins
    d'un dixième d'année.
    """
    import csv

    chemin = RACINE_DONNEES / "reference" / "mortalite" / "quotients_periode.csv"
    lignes = [l for l in chemin.read_text(encoding="utf-8").splitlines()
              if not l.startswith("#")]
    quotients: dict[tuple[int, str], dict[int, float]] = {}
    for ligne in csv.DictReader(lignes):
        quotients.setdefault(
            (int(ligne["annee"]), ligne["sexe"]), {}
        )[int(ligne["age"])] = float(ligne["qx"])

    def esperance(table: dict[int, float], depart: int) -> float:
        total, survie, age = 0.0, 1.0, depart
        while age in table:
            survie *= 1.0 - table[age]
            total += survie
            age += 1
        return total + 0.5

    for annee in (1946, 1950, 1955, 1960, 1970, 1980):
        for sexe in ("H", "F"):
            table = quotients[(annee, sexe)]
            # e60 est certifiée par l'INSEE : c'est l'étalon de la méthode, et
            # il vaut sur toute la période, pas seulement là où l'on dérive.
            publiee = mortalite._e60[sexe].brut(annee).valeur
            assert esperance(table, 60) == pytest.approx(publiee, abs=0.12), (annee, sexe)

            derivee = round(esperance(table, 65), 2)
            portee = mortalite._e65[sexe].brut(annee).valeur
            if annee < 1960:
                # Avant l'OCDE, le fichier porte exactement ce calcul.
                assert portee == pytest.approx(derivee, abs=0.005), (annee, sexe)
            else:
                # À partir de 1960, il porte l'OCDE — et la dérivation la
                # retrouve dans la même marge que pour e60. C'est ce second
                # recoupement qui autorise à s'en servir en deçà.
                assert portee == pytest.approx(derivee, abs=0.4), (annee, sexe)

    # Et plus aucune valeur d'avant 1960 n'est interpolée : toutes sont au
    # fichier, année par année.
    for annee in range(1946, 1960):
        for sexe in ("H", "F"):
            assert mortalite._e65[sexe].brut(annee).annee == annee, (annee, sexe)


def test_la_loi_parametrique_sous_estime_la_mortalite_des_grands_ages(mortalite):
    """Ce que vaut le raccord au-delà du dernier âge observé, mesuré.

    Eurostat s'arrête à 84 puis 94 ans ; au-delà, le modèle reprend sa loi de
    Gompertz-Makeham. Les tables de Vallin et Meslé couvrent 1986-1997 jusqu'à
    104 ans : ces douze années sont le seul endroit où l'on puisse confronter la
    loi à l'observation aux grands âges.

    Le verdict était net, et toujours dans le même sens : la loi faisait mourir
    les très vieux trop lentement, d'environ un cinquième. Elle était calibrée
    sur elle-même — e60 et e65 de la loi PURE — et rien ne l'obligeait à rendre
    la queue que la cible implique. Le niveau de cette queue est désormais recalé
    pour que la table RACCORDÉE reproduise l'espérance publiée, et le biais
    tombe de vingt-deux pour cent à moins de trois.

    Ce test ne corrige rien : il FIGE l'écart résiduel, pour qu'il ne dérive pas
    en silence et que le chiffre cité dans `docs/limites.md` reste vrai.
    """
    import statistics

    ecarts = []
    for annee in range(1986, 1998):
        for sexe in ("H", "F"):
            for age in range(95, 105):
                observe = 1.0 - mortalite.survie_annuelle(age, annee, sexe)
                loi = 1.0 - mortalite.loi(annee, sexe).survie(age, 1.0)
                ecarts.append((loi - observe) / observe)

    assert len(ecarts) == 240
    biais = statistics.mean(ecarts)
    # Ce qui restait un biais d'un cinquième n'est plus qu'un résidu.
    assert -0.05 < biais < 0.05, biais
    # Et jamais dans l'autre sens sur la médiane.
    assert statistics.median(ecarts) < 0


# -- contribution employeur des régimes publics -------------------------------


@pytest.fixture(scope="module")
def employeurs() -> ContributionsEmployeurPubliques:
    return ContributionsEmployeurPubliques(RACINE_DONNEES)


def test_les_trois_regimes_publies_sont_charges(employeurs):
    assert employeurs.regimes == ("cnracl", "fonction_publique_etat", "sncf")


def test_les_taux_appeles_par_l_etat_sont_ceux_des_decrets(employeurs):
    """Repères tirés de la fiche du Service des retraites de l'État."""
    for annee, attendu in ((2006, 0.4990), (2013, 0.7428), (2024, 0.7428),
                           (2025, 0.7828), (2026, 0.8228)):
        contribution = employeurs.taux("fonction_publique_etat", annee)
        assert contribution.taux == pytest.approx(attendu), annee
        assert contribution.nature == "appelee"
        assert contribution.fiabilite is Fiabilite.CERTIFIEE


def test_le_taux_de_l_etat_d_avant_2006_est_annonce_comme_implicite(employeurs):
    """Reconstitution budgétaire, pas cotisation appelée : elle doit le dire."""
    contribution = employeurs.taux("fonction_publique_etat", 2005)
    assert contribution.taux == pytest.approx(0.594)
    assert contribution.nature == "implicite"
    assert contribution.fiabilite is Fiabilite.HAUTE


def test_avant_la_premiere_annee_rien_n_est_invente(employeurs):
    """L'État ne versait aucune cotisation en 1960 : ne pas lui en prêter une."""
    assert employeurs.taux("fonction_publique_etat", 1994) is None
    assert employeurs.taux("cnracl", 1947) is None
    assert employeurs.taux("sncf", 2006) is None
    assert employeurs.taux("ratp", 2020) is None


def test_au_dela_de_la_serie_le_dernier_taux_est_prolonge(employeurs):
    """Une carrière qui court jusqu'en 2060 ne doit pas changer de convention
    au milieu — mais la prolongation ne se fait pas passer pour une observation."""
    contribution = employeurs.taux("fonction_publique_etat", 2050)
    assert contribution.taux == pytest.approx(0.8228)
    assert contribution.projetee
    assert contribution.fiabilite is Fiabilite.ESTIMEE


def test_la_cnracl_remonte_a_1948(employeurs):
    """La fonction publique territoriale n'a jamais eu le problème de l'État."""
    debut, fin = employeurs.couverture("cnracl")
    assert debut == 1948
    assert fin >= 2025
    assert employeurs.taux("cnracl", 1948).taux == pytest.approx(0.12)


def test_les_taux_employeur_publics_restent_plausibles(employeurs):
    """Aucune erreur de virgule : entre 5 % et 100 % du traitement."""
    for regime in employeurs.regimes:
        debut, fin = employeurs.couverture(regime)
        for annee in range(debut, fin + 1):
            taux = employeurs.taux(regime, annee).taux
            assert 0.05 < taux < 1.0, (regime, annee, taux)


# -- répartition salarié / employeur ------------------------------------------


def test_toute_periode_de_salaries_porte_sa_part_salariale(catalogue):
    """Le défaut 1.0 dit « cotisation intégralement personnelle ».

    Vrai d'un artisan et d'une période `agent_seul`, dont le taux est déjà la
    seule retenue de l'agent. Faux de toute période dont le taux est un total
    employeur compris : l'oublier ferait porter au compte, sous les scénarios 2
    et 3, une part patronale qui n'a rien à y faire.
    """
    familles = {"base_prive", "complementaire_prive", "additionnel_capitalise"}
    oublies = [
        f"{regime.code} {periode.debut}-{periode.fin}"
        for regime in catalogue
        for periode in regime.periodes
        if (regime.famille in familles or regime.code == "msa_salaries")
        and periode.perimetre_taux != "agent_seul"
        and periode.part_salariale >= 1.0
    ]
    assert oublies == []


def test_la_retenue_de_l_agent_est_deja_la_part_salariale(catalogue):
    """Une période `agent_seul` ne porte que ce que l'agent verse."""
    for regime in catalogue:
        for periode in regime.periodes:
            if periode.perimetre_taux == "agent_seul":
                assert periode.part_salariale == 1.0, regime.code
                assert (periode.taux_cotisation_salarie
                        == periode.taux_cotisation_retraite), regime.code


def test_les_non_salaries_cotisent_seuls(catalogue):
    """Sans employeur, la cotisation est intégralement personnelle."""
    for regime in catalogue:
        if regime.famille in ("non_salarie", "liberal"):
            for periode in regime.periodes:
                assert periode.part_salariale == 1.0, regime.code


def test_les_parts_salariales_sont_plausibles(catalogue):
    """Entre un quart et la totalité : aucune erreur de virgule ni d'inversion."""
    for regime in catalogue:
        for periode in regime.periodes:
            assert 0.25 <= periode.part_salariale <= 1.0, (
                f"{regime.code} {periode.debut}: {periode.part_salariale}"
            )
            assert (periode.taux_cotisation_salarie
                    <= periode.taux_cotisation_retraite + 1e-12), regime.code


def test_les_statuts_sans_employeur_sont_marques():
    """Un artisan cotise au régime général, dont la fiche porte 41/59.

    Le taux y est le bon, la répartition ne l'est pas : c'est le STATUT qui dit
    qu'il n'a pas d'employeur, pas le régime.
    """
    from retraite_notionnelle.carriere import Affiliations

    affiliations = Affiliations(RACINE_DONNEES)
    sans = {code for code in affiliations.codes
            if affiliations.sans_employeur(code)}
    assert sans == {"artisan", "commercant", "profession_liberale", "avocat",
                    "exploitant_agricole"}
    assert not affiliations.sans_employeur("salarie_prive_non_cadre")
    assert not affiliations.sans_employeur("fonctionnaire_etat")
