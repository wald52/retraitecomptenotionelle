"""Tests du vérificateur de données.

Aucun de ces tests n'accède au réseau : les fichiers source sont simulés. Ce
qui est vérifié ici, ce n'est pas la valeur des séries INSEE — c'est la manière
dont le script les reconstruit, et la règle qu'il applique avant d'accorder le
niveau ``certifiee``.
"""

from __future__ import annotations

import csv
import datetime
import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _charger_script(nom: str, *parties: str):
    """Importe un script du dépôt, qui n'est pas un module installable.

    Le module est inscrit dans ``sys.modules`` avant exécution : sans cela,
    ``dataclasses`` ne retrouve pas l'espace de noms de la classe qu'il
    construit et l'import échoue.
    """
    chemin = Path(__file__).resolve().parents[1].joinpath(*parties)
    specification = importlib.util.spec_from_file_location(nom, chemin)
    module = importlib.util.module_from_spec(specification)
    sys.modules[nom] = module
    specification.loader.exec_module(module)
    return module


def _verificateur():
    return _charger_script("verifier_donnees", "scripts", "verifier_donnees.py")


@pytest.fixture(scope="module")
def verificateur():
    return _verificateur()


# -- reconstruction des séries -----------------------------------------------


def test_variations_ignorent_les_annees_non_consecutives(verificateur):
    """Un trou dans l'indice ne doit pas produire une variation sur deux ans."""
    variations = verificateur._variations({"1970": 100.0, "1971": 110.0, "1975": 200.0})
    assert set(variations) == {1971}
    assert variations[1971] == pytest.approx(0.10)


def test_inflation_chaine_les_deux_bases(verificateur, monkeypatch):
    """Le chaînage prend la base ancienne jusqu'en 1990, la récente ensuite."""
    sources = {
        "ipc_base_1980": {"1989": 100.0, "1990": 103.0, "1991": 110.0},
        "ipc_base_2015": {"1990": 50.0, "1991": 51.0, "1992": 53.0},
    }
    monkeypatch.setattr(verificateur, "_observations", lambda nom: sources[nom])
    serie = verificateur.source_inflation()
    assert serie[("1990",)] == pytest.approx(0.03)          # base 1980
    assert serie[("1991",)] == pytest.approx(51 / 50 - 1)   # base 2015
    assert serie[("1992",)] == pytest.approx(53 / 51 - 1)


def test_plafond_ecarte_une_annee_mouvante_ou_entamee(verificateur, monkeypatch):
    """Le plafond est annuel : des mois identiques DEPUIS JANVIER, ou rien.

    Il est fixé par arrêté pour l'année civile, et la dernière année à en avoir
    connu plusieurs est 1961 : exiger les douze mois revenait à refuser onze
    mois durant une valeur que le décret a déjà fixée — le plafond de 2026
    restait `estimee` alors que l'arrêté du 22 décembre 2025 le porte à 4 005 €.

    Trois garde-fous restent, et chacun a coûté quelque chose pour être trouvé :
    une année dont les mois DIVERGENT est écartée plutôt que moyennée ; une
    année vue depuis autre chose que janvier l'est aussi — la série de l'INSEE
    commence en août 2001, et retenir cette année-là sur ses cinq derniers mois
    donnait 27 348 € contre les 27 349 € du décret ; et une observation isolée
    ne certifie rien.
    """
    mensuel = {}
    mensuel.update({f"2010-{mois:02d}": 2885.0 for mois in range(1, 13)})   # complète
    mensuel.update({f"2011-{mois:02d}": 2946.0 for mois in range(1, 10)})   # entamée
    mensuel.update({f"2012-{mois:02d}": 3031.0 for mois in range(1, 12)})
    mensuel["2012-12"] = 3100.0                                             # mouvante
    mensuel.update({f"2013-{mois:02d}": 3086.0 for mois in range(8, 13)})   # sans janvier
    mensuel["2014-01"] = 3129.0                                             # isolée
    monkeypatch.setattr(verificateur, "_observations", lambda nom: mensuel)

    plafond = verificateur.source_plafond()
    assert plafond == {
        ("2010",): round(2885.0 * 12),
        ("2011",): round(2946.0 * 12),
    }


# -- règle de certification --------------------------------------------------


def _fichier_temporaire(chemin: Path, lignes: list[str]) -> None:
    chemin.write_text("# commentaire de provenance\nannee,variation,fiabilite\n"
                      + "\n".join(lignes) + "\n", encoding="utf-8")


def test_sans_fichier_source_rien_n_est_certifie(verificateur, tmp_path):
    """Sans source déposée, le contrôle est impossible — jamais réussi."""
    cible = tmp_path / "serie.csv"
    _fichier_temporaire(cible, ["1990,0.032,haute"])

    def source_absente():
        raise verificateur.SourceAbsente("fichier de test absent")

    controle = verificateur.Certification(
        nom="essai", chemin=cible, cles=("annee",), colonne="variation",
        source=source_absente, origine="test", decimales=5, tolerance=5e-4,
    )
    messages, journal = controle.confronter(appliquer=True)
    assert journal == {}
    assert messages[0].startswith("IGNORÉ")
    assert "haute" in cible.read_text(encoding="utf-8")


def test_appliquer_aligne_complete_et_certifie(verificateur, tmp_path):
    cible = tmp_path / "serie.csv"
    _fichier_temporaire(cible, ["1990,0.032,haute", "1991,0.100,estimee"])
    controle = verificateur.Certification(
        nom="essai", chemin=cible, cles=("annee",), colonne="variation",
        source=lambda: {("1990",): 0.0320, ("1991",): 0.0326, ("1992",): 0.0230},
        origine="test", decimales=5, tolerance=5e-4,
    )
    messages, journal = controle.confronter(appliquer=True)

    with cible.open(encoding="utf-8") as flux:
        lignes = {l["annee"]: l for l in csv.DictReader(
            x for x in flux if not x.startswith("#"))}

    assert [l["fiabilite"] for l in lignes.values()] == ["certifiee"] * 3
    assert float(lignes["1991"]["variation"]) == pytest.approx(0.0326)  # corrigée
    assert "1992" in lignes                                            # ajoutée
    assert journal["identiques"] == 1 and journal["corrigees"] == 1
    assert journal["ajoutees"] == 1
    assert cible.read_text(encoding="utf-8").startswith("# commentaire de provenance")


def test_les_annees_hors_source_ne_sont_pas_touchees(verificateur, tmp_path):
    """Certifier ce qui est couvert ne doit rien dire de ce qui ne l'est pas."""
    cible = tmp_path / "serie.csv"
    _fichier_temporaire(cible, ["1935,0.050,estimee", "1990,0.032,haute"])
    controle = verificateur.Certification(
        nom="essai", chemin=cible, cles=("annee",), colonne="variation",
        source=lambda: {("1990",): 0.032}, origine="test",
        decimales=5, tolerance=5e-4,
    )
    controle.confronter(appliquer=True)

    with cible.open(encoding="utf-8") as flux:
        lignes = {l["annee"]: l for l in csv.DictReader(
            x for x in flux if not x.startswith("#"))}
    assert lignes["1935"]["fiabilite"] == "estimee"
    assert lignes["1935"]["variation"] == "0.050"
    assert lignes["1990"]["fiabilite"] == "certifiee"


def test_confrontation_seule_n_ecrit_rien(verificateur, tmp_path):
    cible = tmp_path / "serie.csv"
    avant = "# commentaire de provenance\nannee,variation,fiabilite\n1990,0.032,haute\n"
    cible.write_text(avant, encoding="utf-8")
    controle = verificateur.Certification(
        nom="essai", chemin=cible, cles=("annee",), colonne="variation",
        source=lambda: {("1990",): 0.099}, origine="test",
        decimales=5, tolerance=5e-4,
    )
    messages, _ = controle.confronter(appliquer=False)
    assert cible.read_text(encoding="utf-8") == avant
    assert any(m.startswith("ÉCART") for m in messages)


def test_transcription_tierce_ne_peut_pas_etre_certifiee(verificateur):
    """La règle de niveau est ce qui distingue une source d'une recopie.

    Le plafond ancien vient d'OpenFisca, transcription du Journal officiel : il
    doit rester au niveau « haute », quoi qu'il arrive. Rien dans le code ne
    l'empêcherait d'être promu par inadvertance ; ce test le garde.
    """
    par_nom = {c.nom: c for c in verificateur.CERTIFICATIONS}
    assert par_nom["plafond_ancien"].niveau == "haute"
    for nom in ("inflation", "salaire_moyen", "productivite", "plafond",
                "esperances_vie", "quotients_mortalite"):
        assert par_nom[nom].niveau == "certifiee", nom


def test_plafond_ancien_s_efface_devant_l_insee_et_le_journal_officiel(
        verificateur, monkeypatch):
    """Trois sources sur un même fichier ne doivent pas se marcher dessus.

    L'INSEE tient 2002 et au-delà ; le *Journal officiel* tient les années dont
    le décret a été lu ; OpenFisca ne garde que le reste. Le partage n'est pas
    cosmétique : c'est lui qui rend le journal de certification vrai.
    """
    series = {
        "openfisca_plafond.json": {
            "1999": 26471.2, "2001": 27349.4, "2002": 28224.0, "2010": 34620.0,
        },
        "jorf_plafond_securite_sociale.json": {"2001": 27349.4, "2010": 34620.0},
    }
    monkeypatch.setattr(verificateur, "_serie_json",
                        lambda nom, *args: series[nom])
    assert set(verificateur.source_plafond_ancien()) == {("1999",)}
    assert set(verificateur.source_plafond_journal_officiel()) == {("2001",)}


def test_le_plafond_ancien_survit_a_l_absence_du_journal_officiel(
        verificateur, monkeypatch):
    """Le dump JORF est long à lire : sans lui, la transcription tient tout."""
    def _serie(nom, *args):
        if nom == "jorf_plafond_securite_sociale.json":
            raise verificateur.SourceAbsente(nom)
        return {"1999": 26471.2, "2001": 27349.4, "2002": 28224.0}
    monkeypatch.setattr(verificateur, "_serie_json", _serie)
    assert set(verificateur.source_plafond_ancien()) == {("1999",), ("2001",)}


def test_prorata_du_plafond_sur_une_annee_a_deux_decrets():
    """Le plafond annuel est la somme des plafonds mensuels, pas celui de janvier."""
    module = _charger_script("openfisca_plafond", "scripts", "fetch", "openfisca_plafond.py")
    # Un décret au 1er octobre : neuf mois à l'ancien taux, trois au nouveau.
    valeurs = {"2010-01-01": 12000.0, "2010-10-01": 24000.0}
    annuel = module.annualiser(valeurs)
    assert annuel[2010] == pytest.approx(12000 * 9 / 12 + 24000 * 3 / 12)


def test_conversion_des_francs_par_epoque():
    """Anciens francs, nouveaux francs, euros : trois régimes d'unité."""
    module = _charger_script("openfisca_plafond", "scripts", "fetch", "openfisca_plafond.py")
    assert module.en_euros(120000, 1945) == pytest.approx(120000 / 100 / 6.55957)
    assert module.en_euros(14400, 1968) == pytest.approx(14400 / 6.55957)
    assert module.en_euros(28224, 2002) == pytest.approx(28224)


def test_classes_d_age_ouvertes_sont_ecartees_des_quotients():
    """« 85 ans et plus » n'est pas un quotient à 85 ans : ne pas le confondre."""
    module = _charger_script("eurostat_mortalite", "scripts", "fetch", "eurostat_mortalite.py")
    assert module._age_numerique("Y_LT1") == 0
    assert module._age_numerique("Y65") == 65
    assert module._age_numerique("Y_GE85") is None
    assert module._age_numerique("Y_GE95") is None


def test_manifeste_des_series_et_controles_se_correspondent():
    """Le récupérateur et le vérificateur doivent parler des mêmes séries."""
    module = _charger_script("insee_bdm", "scripts", "fetch", "insee_bdm.py")
    attendues = {
        "ipc_base_1980", "ipc_base_2015", "salaires_bruts", "emploi_salarie",
        "valeur_ajoutee_volume", "emploi_total", "e0_H", "e0_F", "e60_H",
        "e60_F", "plafond_mensuel",
    }
    assert attendues <= set(module.SERIES)
    for nom, fiche in module.SERIES.items():
        assert fiche["idbank"].isdigit() and len(fiche["idbank"]) == 9, nom


def test_journal_de_certification_est_lisible():
    racine = Path(__file__).resolve().parents[1]
    journal = json.loads(
        (racine / "data" / "derive" / "certification.json").read_text(encoding="utf-8")
    )
    assert journal["certifie_le"]
    for nom, trace in journal["series"].items():
        assert trace["valeurs"] > 0, nom
        assert len(trace["empreinte"]) == 16, nom


def test_les_deux_montants_du_minimum_se_lisent_sans_verbe():
    """La rédaction change ; l'ordre des montants, non.

    L'article D. 351-2-1 porte le minimum puis sa majoration, et le verbe qui
    les introduit a changé trois fois en vingt ans — « est fixé à », « est
    porté à », « de façon à atteindre ». On relève donc tous les montants
    annuels et l'on retient le plus petit, puis le plus grand.
    """
    module = _charger_script("dila_legi_minimum_contributif", "scripts", "fetch",
                             "dila_legi_minimum_contributif.py")
    texte = (
        "Le montant minimum auquel est portée, lors de sa liquidation, la "
        "pension de vieillesse au taux plein en application de l'article "
        "L. 351-10 est fixé à 8 509,61 euros par an au 1er septembre 2023. "
        "Ce montant minimum est majoré au titre des périodes ayant donné lieu "
        "à cotisations à la charge de l'assuré, de façon à atteindre "
        "10 170,86 euros par an au 1er septembre 2023."
    )
    assert module.montants(texte) == {
        "montant_base": pytest.approx(8509.61),
        "montant_majore": pytest.approx(10170.86),
    }
    # Une rédaction antérieure, sans majoration : un seul montant.
    assert module.montants("est fixé à 6 958,21 euros par an") == {
        "montant_base": pytest.approx(6958.21)
    }
    # Le plafond est publié au MOIS : il est porté à l'année.
    assert module.plafond(
        "Le montant mensuel total des pensions personnelles de retraite "
        "mentionné au premier alinéa de l'article L. 173-2 est fixé à "
        "1 120 euros au 1er février 2014."
    ) == (2014, pytest.approx(13440.0))


def test_une_generation_coupee_en_cours_d_annee_rend_deux_segments():
    """« Nés à compter du 1er septembre 1961 » n'est pas « nés en 1961 ».

    Le récupérateur comptait les mois de chaque génération pour départager deux
    valeurs à la majorité, puis jetait le décompte : la date de la coupure était
    perdue, et le modèle opposait la valeur majoritaire à toute la génération —
    un trimestre d'âge légal d'écart pour qui naissait du mauvais côté. Il rend
    désormais un segment par valeur, la clé portant le mois.
    """
    module = _charger_script("dila_legi_parametres_retraite", "scripts", "fetch",
                             "dila_legi_parametres_retraite.py")
    # L'article D. 161-2-1-9, resserré à ce qui compte ici.
    alineas = [
        (60.0, "Soixante ans pour les assurés nés avant le 1er juillet 1951 ;"),
        (60.33, "Soixante ans et quatre mois pour les assurés nés entre le "
                "1er juillet 1951 et le 31 décembre 1951 inclus ;"),
        (60.75, "Soixante ans et neuf mois pour les assurés nés en 1952 ;"),
        (62.0, "Soixante-deux ans pour les assurés nés entre le 1er janvier "
               "1955 et le 31 août 1961 inclus ;"),
        (62.25, "Soixante-deux ans et trois mois pour les assurés nés entre le "
                "1er septembre 1961 et le 31 décembre 1961 inclus ;"),
        (64.0, "Soixante-quatre ans pour les assurés nés à compter du "
               "1er janvier 1968 ;"),
    ]
    table = module.table_par_generation(alineas)

    # Les deux générations que les textes coupent portent deux clés ; les
    # autres n'en portent qu'une, et janvier ne met pas de décimale.
    assert [c for c in table if int(c) == 1951] == [1951, 1951.5]
    assert [c for c in table if int(c) == 1961] == [1961, 1961.667]
    assert [c for c in table if int(c) == 1952] == [1952]
    assert table[1951] == 60.0 and table[1951.5] == 60.33
    assert table[1961] == 62.0 and table[1961.667] == 62.25

    # Ce sont exactement les lignes que porte le fichier de référence.
    chemin = (Path(__file__).resolve().parents[1] / "data" / "reference"
              / "legislation" / "age_ouverture_requis.csv")
    with chemin.open(encoding="utf-8") as flux:
        lignes = (l for l in flux if not l.lstrip().startswith("#"))
        fichier = {float(l["generation"]): float(l["age"])
                   for l in csv.DictReader(lignes)}
    for cle in (1951, 1951.5, 1961, 1961.667):
        assert fichier[cle] == table[cle], cle


def test_une_version_plus_recente_efface_les_coupures_qu_elle_recouvre():
    """Une version d'article REMPLACE la précédente, coupures comprises.

    Sans cela, une coupure abandonnée par un texte plus récent survivrait à son
    abrogation : la clé décimale, que la nouvelle version ne réécrit pas,
    resterait dans la table à côté de la valeur qui l'a remplacée.
    """
    module = _charger_script("dila_legi_parametres_retraite", "scripts", "fetch",
                             "dila_legi_parametres_retraite.py")

    def lire(texte):
        if texte == "avant_2023":
            return {1961: 62.0}
        return {1961: 62.0, 1961.667: 62.25}

    assert module._par_version([("2011", "avant_2023")], lire) == {1961: 62.0}
    assert module._par_version(
        [("2011", "avant_2023"), ("2023", "apres")], lire
    ) == {1961: 62.0, 1961.667: 62.25}
    # Ordre inverse : la version la plus récente est celle qui ne coupe pas.
    assert module._par_version(
        [("2023", "apres"), ("2024", "avant_2023")], lire
    ) == {1961: 62.0}


def test_lecture_d_un_classeur_excel_97():
    """Le lecteur BIFF doit rendre les nombres, et rien d'autre.

    Il n'y a pas de classeur au dépôt — data/brut/ n'est pas versionné — mais
    le décodage des nombres RK, lui, se contrôle seul : c'est le seul endroit
    du lecteur où une erreur de bit passerait pour une valeur plausible.
    """
    module = _charger_script("lecture_xls", "scripts", "fetch", "lecture_xls.py")
    # Entier codé sur 30 bits, drapeau « entier » à 1.
    assert module._rk((1234 << 2) | 0b10) == pytest.approx(1234.0)
    # Le même, avec le drapeau « centième ».
    assert module._rk((1234 << 2) | 0b11) == pytest.approx(12.34)
    # Un double tronqué : 0,5 s'écrit exactement sur les 30 bits de poids fort.
    import struct
    brut = struct.unpack("<Q", struct.pack("<d", 0.5))[0] >> 32
    assert module._rk(brut & 0xFFFFFFFC) == pytest.approx(0.5)


# -- barèmes du point, lus chez la fédération Agirc-Arrco ---------------------

#: Deux lignes de la table de l'Agirc, prises de part et d'autre du passage à
#: l'ancien franc — c'est le seul endroit du document où une conversion fautive
#: se voie, et son évolution publiée le dit : 1,52 NF après 142,00 anciens
#: francs, soit les 7,04 % imprimés en regard.
TABLE_AGIRC = """1960 0,21 NF 5,00% 0,220 NF 4,76% 10,30% 1,52 NF 7,04%
1959 19,00 F 5,56% 20,00 F 5,26% 13,00% 142,00 F 9,23%
Agirc
-
Valeurs de point et salaires de référence
"""


def test_la_valeur_du_point_retenue_est_celle_du_31_decembre():
    """Deux valeurs dans l'année : c'est la seconde qui vaut, et en euros."""
    module = _charger_script("agirc_arrco_valeurs_point", "scripts", "fetch",
                             "agirc_arrco_valeurs_point.py")
    valeurs, griefs = module.table_avec_monnaie(TABLE_AGIRC)
    assert griefs == []
    # 20,00 anciens francs de juillet 1959, et non les 19,00 de janvier.
    assert valeurs[(1959, "valeur_service")] == pytest.approx(20.0 / 100 / 6.55957)
    assert valeurs[(1959, "salaire_reference")] == pytest.approx(142.0 / 100 / 6.55957)
    # 1960 est en nouveaux francs : cent fois moins de division.
    assert valeurs[(1960, "valeur_service")] == pytest.approx(0.220 / 6.55957)
    assert valeurs[(1960, "salaire_reference")] == pytest.approx(1.52 / 6.55957)


def test_une_evolution_publiee_qui_ne_se_retrouve_pas_arrete_le_recuperateur():
    """Le document publie ses hausses : c'est lui qui contrôle sa propre lecture."""
    module = _charger_script("agirc_arrco_valeurs_point", "scripts", "fetch",
                             "agirc_arrco_valeurs_point.py")
    fausse = TABLE_AGIRC.replace("1,52 NF 7,04%", "1,62 NF 7,04%")
    _, griefs = module.table_avec_monnaie(fausse)
    assert any("salaire de référence" in grief for grief in griefs)


def test_une_annee_sans_decision_garde_la_valeur_precedente():
    """1953 et 1954 n'ont pas de valeur de point : celle de 1952 reste en vigueur."""
    module = _charger_script("agirc_arrco_valeurs_point", "scripts", "fetch",
                             "agirc_arrco_valeurs_point.py")
    valeurs, _ = module.table_avec_monnaie(
        "1953 2,00% 78,00 F 2,63%\n"
        "1952 12,00 F 9,09% 12,50 F 4,17% 22,50% 76,00 F 20,63%\n"
    )
    assert valeurs[(1953, "valeur_service")] == valeurs[(1952, "valeur_service")]
    assert valeurs[(1953, "salaire_reference")] == pytest.approx(78.0 / 100 / 6.55957)


def test_une_table_sans_intitule_qui_redonne_les_memes_annees_n_est_pas_une_suite():
    """Après l'Arrco vient sa série reconstituée, sans intitulé et sur les mêmes années.

    Une table longue déborde bien sur une page sans intitulé — c'est le cas de
    l'Agirc —, mais une page qui revient sur une année déjà lue n'est pas une
    suite : c'est une autre table.
    """
    module = _charger_script("agirc_arrco_valeurs_point", "scripts", "fetch",
                             "agirc_arrco_valeurs_point.py")
    pages = [
        "2018 1,2588 €\nArrco\n-\nValeurs de point et salaires de référence\n",
        "2018 3,30% 16,7226 €\nSérie reconstituée\n",
        "2017 1,2513 €\n",
    ]
    assert module.table_de("Arrco", pages) == pages[0]


# -- valeurs du point du RAFP, lues chez l'ERAFP -----------------------------

#: Le tableau de l'ERAFP, tel que le PDF le rend : trois lignes par tranche, et
#: une année à deux colonnes quand la valeur change en cours d'année.
TABLEAU_RAFP = """Évolution de la valeur d'acquisition depuis 2005
Année 2005 2006
En euros 1 1,017
Variation — + 1,7 %
Évolution de la valeur de service depuis 2005
Année 2015 Jusqu'au 31
mars 2016
À partir du 1er
avril 2016 2017
En euros 0,04465 0,04465 0,04474 0,04487
Variation — — + 0,2 % + 0,3%
"""


def test_l_annee_a_deux_valeurs_est_rendue_par_la_seconde():
    """2016 : la valeur de service change au 1er avril, celle du 31 décembre vaut."""
    module = _charger_script("erafp_valeurs_point", "scripts", "fetch",
                             "erafp_valeurs_point.py")
    service, griefs = module.lire_tableau(TABLEAU_RAFP,
                                          "Évolution de la valeur de service")
    assert griefs == []
    assert service[2016] == pytest.approx(0.04474)
    assert service[2017] == pytest.approx(0.04487)
    # La valeur d'acquisition de 2005 est un euro rond, sans décimale : elle se
    # lit quand même.
    acquisition, _ = module.lire_tableau(TABLEAU_RAFP,
                                         "Évolution de la valeur d'acquisition")
    assert acquisition[2005] == pytest.approx(1.0)


def test_une_valeur_du_rafp_recopiee_ne_passe_pas_le_controle():
    """C'est ainsi que l'erreur de 2021 s'est vue : + 0,4 % ne mène pas de x à x."""
    module = _charger_script("erafp_valeurs_point", "scripts", "fetch",
                             "erafp_valeurs_point.py")
    recopiee = TABLEAU_RAFP.replace("En euros 1 1,017", "En euros 1 1")
    _, griefs = module.lire_tableau(recopiee, "Évolution de la valeur d'acquisition")
    assert any("hausse publiée" in grief for grief in griefs)


# -- deux tables de plus, lues dans le code de la sécurité sociale ------------


def test_la_duree_de_proratisation_se_lit_dans_l_article():
    """R. 351-6 II écrit sa table en toutes lettres, génération par génération."""
    module = _charger_script("dila_legi_parametres_retraite", "scripts", "fetch",
                             "dila_legi_parametres_retraite.py")
    texte = (
        "II.-Pour les pensions prenant effet après le 31 décembre 2003, la durée "
        "maximum d'assurance est fixée à : 150 trimestres pour les assurés nés "
        "avant 1944 ; 152 trimestres pour les assurés nés en 1944 ; 154 "
        "trimestres pour les assurés nés en 1945."
    )
    assert module.duree_proratisation([("2007-04-27", texte)]) == {
        1900: 150.0, 1944: 152.0, 1945: 154.0,
    }


def test_l_assiette_du_trimestre_se_lit_dans_l_article():
    """R. 351-9 date ses périodes de deux façons, et l'une commence l'année d'après."""
    module = _charger_script("dila_legi_parametres_retraite", "scripts", "fetch",
                             "dila_legi_parametres_retraite.py")
    texte = (
        "Pour la période comprise entre le 1er janvier 1972 et le 31 décembre "
        "2013, il y a lieu de retenir autant de trimestres que le salaire annuel "
        "représente de fois le montant du salaire minimum de croissance calculé "
        "sur la base de 200 heures. "
        "Pour la période postérieure au 31 décembre 2013, il y a lieu de retenir "
        "autant de trimestres que ce salaire calculé sur la base de 150 heures."
    )
    assert module.heures_par_trimestre([("2014-03-21", texte)]) == {
        1972: 200.0, 2014: 150.0,
    }


# -- le Journal officiel, là où il porte lui-même la valeur ------------------


def test_le_smic_se_lit_dans_le_decret_qui_le_releve():
    """Date d'EFFET, monnaie, métropole : trois pièges dans une phrase."""
    module = _charger_script("dila_legi_smic", "scripts", "fetch",
                             "dila_legi_smic.py")
    metropole = (
        "Décret n° 96-571 du 26 juin 1996 portant relèvement du salaire minimum "
        "de croissance A compter du 1er juillet 1996, pour les catégories de "
        "travailleurs intéressées par l'article L. 131-2 du code du travail, le "
        "montant du salaire minimum de croissance est porté à 37,91 F de l'heure "
        "en métropole, dans les départements d'outre-mer."
    )
    mayotte = (
        "Décret du 20 décembre 2016 A compter du 1er janvier 2017, le montant du "
        "salaire minimum de croissance est porté à 7,44 € de l'heure à Mayotte."
    )
    par_date = module.relevements([("1996-06-28", metropole), ("2016-12-22", mayotte)])
    # La date du décret — 26 juin — ne doit pas prendre la place de son effet.
    assert list(par_date) == [__import__("datetime").date(1996, 7, 1)]
    assert par_date[__import__("datetime").date(1996, 7, 1)] == pytest.approx(
        37.91 / 6.55957)


def test_l_annee_de_la_bascule_a_l_euro_n_est_pas_certifiee():
    """6,67 € au 1er janvier 2002 : un arrondi, pas une conversion.

    Le dernier décret en vigueur est en francs — 43,72 F, soit 6,6651 € — quand
    le SMIC opposable en 2002 est de 6,67 €. Le texte qui fixe cet arrondi n'est
    pas dans le dump : l'année n'est pas rendue.
    """
    from datetime import date

    module = _charger_script("dila_legi_smic", "scripts", "fetch",
                             "dila_legi_smic.py")
    serie = module.serie_annuelle({
        date(2000, 7, 1): 6.405908,
        date(2001, 7, 1): 6.665071,
        date(2002, 7, 1): 6.83,
    })
    assert 2002 not in serie
    assert serie[2003] == pytest.approx(6.83)


def test_le_point_d_indice_gele_reconduit_sa_derniere_version():
    """Une année sans version n'est pas un trou : le point a été gelé six ans."""
    from datetime import date

    module = _charger_script("dila_legi_point_indice", "scripts", "fetch",
                             "dila_legi_point_indice.py")
    serie = module.serie_annuelle({
        date(2010, 7, 9): 5556.35,
        date(2016, 7, 1): 5589.69,
    })
    assert serie[2011] == pytest.approx(55.5635)
    assert serie[2016] == pytest.approx(55.5635)   # gel de 2010 à 2016
    assert serie[2017] == pytest.approx(55.8969)


def test_le_traitement_de_l_indice_100_se_lit_en_francs_puis_en_euros():
    """« 33 990 F » puis « 5 181,75 » : le Journal officiel aère ses milliers."""
    from datetime import date

    module = _charger_script("dila_legi_point_indice", "scripts", "fetch",
                             "dila_legi_point_indice.py")
    versions = module.versions_datees([
        ("2001-09-29", "Décret n° 85-1148 du 24 octobre 1985 La valeur annuelle "
                       "du traitement afférent à l'indice 100 majoré est fixée à "
                       "33 990 F"),
        ("2002-01-01", "Décret n° 85-1148 du 24 octobre 1985 La valeur annuelle "
                       "du traitement afférent à l'indice 100 majoré est fixée à "
                       "5 181,75 "),
    ])
    assert versions[date(2001, 9, 29)] == pytest.approx(33990 / 6.55957)
    assert versions[date(2002, 1, 1)] == pytest.approx(5181.75)


def test_les_annees_du_salaire_de_reference_se_lisent_en_toutes_lettres():
    """« Vingt et une années » : le féminin, et la cible dans un autre alinéa."""
    module = _charger_script("dila_legi_parametres_retraite", "scripts", "fetch",
                             "dila_legi_parametres_retraite.py")
    texte = (
        "I.-Les durées de vingt-cinq années fixées aux premier et troisième "
        "alinéas de l'article R. 351-29 sont applicables aux assurés nés après "
        "1947, quelle que soit la date d'effet de leur pension. "
        "II.-Le nombre d'années mentionné aux premier et troisième alinéas de "
        "l'article R. 351-29 est de : Dix années pour l'assuré né avant le "
        "1er janvier 1934 ; Vingt et une années pour l'assuré né en 1944 ; "
        "Vingt-quatre années pour l'assuré né en 1947."
    )
    assert module.annees_salaire_reference([("2007-04-27", texte)]) == {
        1900: 10.0, 1944: 21.0, 1947: 24.0, 1948: 25.0,
    }


def test_la_decote_de_la_fonction_publique_se_lit_dans_le_tableau_de_la_loi():
    """Le tableau est rendu à plat, et sa dernière ligne perd ses repères."""
    module = _charger_script("dila_legi_decote_fonction_publique", "scripts", "fetch",
                             "dila_legi_decote_fonction_publique.py")
    texte = (
        "III. - Jusqu'au 31 décembre 2019, sont fixés comme indiqué dans le "
        "tableau suivant : I : 2006 II : 0,125 % III : Limite d'âge moins 16 "
        "trimestres I : 2007 II : 0,25 % III : Limite d'âge moins 14 trimestres "
        "2019 1,25 % Limite d'âge moins 1 trimestre"
    )
    table = module.montee_en_charge([("2004-01-01", texte)])
    assert table[2006] == {"coefficient": 0.00125, "trimestres_avant_limite": 16.0}
    assert table[2007] == {"coefficient": 0.0025, "trimestres_avant_limite": 14.0}
    # La dernière ligne du tableau n'a plus ses « I : », « II : », « III : ».
    assert table[2019] == {"coefficient": 0.0125, "trimestres_avant_limite": 1.0}


def test_l_age_d_annulation_suit_l_age_d_ouverture(verificateur):
    """La règle de L. 351-8 : l'âge d'ouverture majoré de cinq ans, plafonné à 67."""
    messages = verificateur.controle_vraisemblance_age_annulation()
    assert messages[0].startswith("OK")
    assert not [m for m in messages if m.startswith("SUSPECT")]


def test_le_bareme_du_minimum_garanti_se_lit_en_six_colonnes():
    """Les points sont par ANNÉE dans la loi, par TRIMESTRE dans le dépôt."""
    module = _charger_script("dila_legi_minimum_garanti", "scripts", "fetch",
                             "dila_legi_minimum_garanti.py")
    texte = (
        "Jusqu'au 31 décembre 2013, les dispositions présentées dans le tableau "
        "suivant sont applicables, par dérogation aux a et b de l'article L. 17 : "
        "I : 2003 II : 60 % III : 216 IV : 4 points V : Vingt-cinq ans VI : Sans objet "
        "I : 2004 II : 59,7 % III : 217 IV : 3,8 points V : Vingt-cinq ans et demi "
        "VI : 0,04 point "
        "I : 2013 II : 57,5 % III : 227 IV : 2,5 points V : Trente ans VI : 0,5 point"
    )
    table = module.bareme([("2004-01-01", texte)])
    # La ligne 2003 décrit le droit antérieur : le dépôt la date de 1976 et le
    # récupérateur ne la lit pas.
    assert sorted(table) == [2004, 2013]
    assert table[2004] == {
        "part_15_ans": pytest.approx(0.597),
        "indice_majore": 217.0,
        "points_15_30": pytest.approx(0.0095),   # 3,8 points par an
        "points_30_40": pytest.approx(0.0001),   # 0,04 point par an
        "trimestres_seuil": 102.0,               # vingt-cinq ans et demi
    }
    assert table[2013]["trimestres_seuil"] == 120.0


def test_les_bornes_en_toutes_lettres_du_minimum_garanti():
    module = _charger_script("dila_legi_minimum_garanti", "scripts", "fetch",
                             "dila_legi_minimum_garanti.py")
    assert module.annees_en_lettres("Vingt-cinq ans") == 25.0
    assert module.annees_en_lettres("Vingt-huit ans et demi") == 28.5
    assert module.annees_en_lettres("Trente ans") == 30.0
    assert module.annees_en_lettres("Sans objet") is None


def test_la_reference_du_minimum_garanti_se_recoupe_au_point_d_indice(verificateur):
    """227 × 52,7558 = 11 975,57 : deux chemins indépendants, même chiffre."""
    messages = verificateur.controle_vraisemblance_minimum_garanti()
    assert messages[0].startswith("OK")
    assert not [m for m in messages if m.startswith("SUSPECT")]


def _plafond():
    return _charger_script("jorf_plafond_securite_sociale", "scripts", "fetch",
                           "jorf_plafond_securite_sociale.py")


def test_la_notice_ancienne_du_plafond_porte_ses_deux_semestres():
    """« POUR LA PERIODE DU 01-01-1991 AU 30-06-1991 A 11340FRS ET […] »"""
    module = _plafond()
    notice = (
        "TAUX D'AUGMENTATION DE 5% AU 01-01-1991. LE PLAFOND AU 01-07-1991,EST "
        "FIXE EN APPLIQUANT AU PLAFOND EN VIGUEUR AU 01-01-1991,UN TAUX DE "
        "REVALORISATION EGAL A LA MOITIE DU TAUX RETENU A CETTE DERNIERE "
        "DATE,SOIT 2,5%. LES NOUVELLES VALEURS DU PLAFOND S'ETABLISSENT DONC "
        "POUR LA PERIODE DU 01-01-1991 AU 30-06-1991 A 11340FRS ET POUR LA "
        "PERIODE DU 01-07-1991 AU 31-12-1991 A 11620FRS PAR MOIS."
    )
    par_date, _, griefs = module.montants_dates([notice])
    assert griefs == []
    assert par_date[datetime.date(1991, 1, 1)] == pytest.approx(11340 / 6.55957)
    assert par_date[datetime.date(1991, 7, 1)] == pytest.approx(11620 / 6.55957)


def test_le_plafond_annuel_est_la_somme_de_ses_douze_mois():
    """Le plafond a été semestriel : douze fois janvier serait faux."""
    module = _plafond()
    par_date = {
        datetime.date(1991, 1, 1): 1728.77,
        datetime.date(1991, 7, 1): 1771.46,
    }
    serie = module.serie_annuelle(par_date, set())
    assert serie[1991] == pytest.approx(6 * 1728.77 + 6 * 1771.46)


def test_une_annee_sans_texte_n_est_pas_reconduite():
    """Le plafond a monté chaque année : un report écrirait un gel inexistant."""
    module = _plafond()
    serie = module.serie_annuelle({datetime.date(1984, 7, 1): 1294.29}, set())
    assert serie == {}


def test_le_taux_annonce_par_la_notice_est_refait():
    """La notice écrit sa hausse : un montant qui ne la respecte pas est refusé."""
    module = _plafond()
    faux = (
        "SOIT 2,5%. LES NOUVELLES VALEURS DU PLAFOND S'ETABLISSENT DONC POUR LA "
        "PERIODE DU 01-01-1991 AU 30-06-1991 A 11340FRS ET POUR LA PERIODE DU "
        "01-07-1991 AU 31-12-1991 A 12500FRS PAR MOIS."
    )
    _, _, griefs = module.montants_dates([faux])
    assert [g for g in griefs if "taux annoncé" in g]


def test_les_autres_plafonds_du_journal_officiel_sont_ecartes():
    """« LE PLAFOND DE LA PARTICIPATION FORFAITAIRE […] EST FIXE A 933FRS »."""
    module = _plafond()
    intrus = (
        "SECURITE SOCIALE. A COMPTER DU 01-01-1991,LE PLAFOND DE LA "
        "PARTICIPATION FORFAITAIRE SUSVISEE EST FIXE A 933FRS."
    )
    par_date, _, griefs = module.montants_dates([intrus])
    assert par_date == {} and griefs == []


def test_l_article_premier_du_plafond_se_date_lui_meme():
    """« 14 090 F […] versés du 1er janvier au 31 décembre 1998 »."""
    module = _plafond()
    article = (
        "Art. 1er. - Les cotisations dues dans la limite du plafond de la "
        "sécurité sociale sont calculées jusqu'à concurrence des sommes "
        "suivantes : 42 270 F si les rémunérations ou gains sont versés par "
        "trimestre ; 14 090 F si les rémunérations ou gains sont versés par "
        "mois ; 650 F si les rémunérations ou gains sont versés par jour, pour "
        "les rémunérations ou gains versés du 1er janvier au 31 décembre 1998."
    )
    par_date, _, griefs = module.montants_dates([article])
    assert griefs == []
    assert par_date == {datetime.date(1998, 1, 1): pytest.approx(14090 / 6.55957)}


def test_l_arrete_moderne_du_plafond_porte_son_annee_dans_son_titre():
    module = _plafond()
    arrete = (
        "Arrêté du 19 décembre 2023 portant fixation du plafond de la sécurité "
        "sociale pour 2024 Les valeurs mensuelle et journalière du plafond de "
        "la sécurité sociale sont les suivantes : - valeur mensuelle : "
        "3 864 euros ; - valeur journalière : 213 euros."
    )
    par_date, _, griefs = module.montants_dates([arrete])
    assert griefs == []
    assert par_date == {datetime.date(2024, 1, 1): 3864.0}
    assert module.serie_annuelle(par_date, {2024})[2024] == pytest.approx(46368.0)


def test_les_anciens_francs_du_plafond_passent_par_la_division_par_cent():
    """Avant 1960, le Journal officiel compte en anciens francs."""
    module = _plafond()
    assert module._en_euros(600000, datetime.date(1957, 1, 1)) == pytest.approx(
        600000 / 100 / 6.55957)
    assert module._en_euros(11340, datetime.date(1991, 1, 1)) == pytest.approx(
        11340 / 6.55957)
    assert module._en_euros(3864, datetime.date(2024, 1, 1)) == 3864.0


def test_la_notice_des_annees_1980_rappelle_janvier_entre_parentheses():
    """« EST FIXE A 8490FRS […] DEPUIS LE 01-01-1984 (8110FRS PAR MOIS) »."""
    module = _plafond()
    notice = (
        "PORTANT FIXATION,A COMPTER DU 01-07-1984,DU PLAFOND DES COTISATIONS DE "
        "SECURITE SOCIALE. LE PLAFOND DE SECURITE SOCIALE APPLICABLE AUX "
        "REMUNERATIONS OU GAINS VERSES A PARTIR DU 01-07-1984 EST FIXE A "
        "8490FRS PAR MOIS ,SOIT UNE AUGMENTATION DE 4,69% PAR RAPPORT AU "
        "PLAFOND EN VIGUEUR DEPUIS LE 01-01-1984 (8110FRS PAR MOIS)."
    )
    par_date, _, griefs = module.montants_dates([notice])
    assert griefs == []
    assert par_date[datetime.date(1984, 1, 1)] == pytest.approx(8110 / 6.55957)
    assert par_date[datetime.date(1984, 7, 1)] == pytest.approx(8490 / 6.55957)


def test_le_titre_date_la_parenthese_quand_le_corps_ne_le_fait_pas():
    """« FIXATION A COMPTER DU 01-01-1988 ET DU 01-07-1988 […] (PLAFOND: 9950FRS) »."""
    module = _plafond()
    notice = (
        "PORTANT FIXATION A COMPTER DU 01-01-1988 ET DU 01-07-1988 DU PLAFOND "
        "DE LA SECURITE SOCIALE. LE TAUX D'AUGMENTATION DE 3,32% CORRESPOND A "
        "L'EVOLUTION DU SALAIRE MOYEN (3,3%) (PLAFOND: 9950FRS PAR MOIS). "
        "A COMPTER DU 01-07-1988,LE PLAFOND EST FIXE A 10110FRS PAR MOIS,"
        "VALEUR OBTENUE PAR MAJORATION DE 1,60% DE LA VALEUR AU 01-01-1988."
    )
    par_date, _, griefs = module.montants_dates([notice])
    # Le contrôle doit retenir 1,60 %, le taux de juillet, et non les 3,32 %
    # de janvier, qui se rapportent à l'année précédente.
    assert griefs == []
    assert par_date[datetime.date(1988, 1, 1)] == pytest.approx(9950 / 6.55957)
    assert par_date[datetime.date(1988, 7, 1)] == pytest.approx(10110 / 6.55957)


def test_le_titre_d_avant_1982_porte_l_annee_et_le_montant_annuel():
    """« POUR L'ANNEE 1969 DU PLAFOND […] A 16 320 FRS » — trois séparateurs."""
    module = _plafond()
    titres = [
        "Décret n°68-1186 du 30 décembre 1968 PORTANT FIXATION POUR L'ANNEE "
        "1969 DU PLAFOND DES COTISATIONS DE SECURITE SOCIALE A 16 320 FRS",
        "Décret n°71-1109 PORTANT FIXATION POUR L'ANNEE 1972 DU PLAFOND DES "
        "COTISATIONS DE SECURITE SOCIALE (21 960 FRS)",
        "Décret n°79-1136 FIXATION POUR L'ANNEE 1980 DU PLAFOND DES COTISATIONS "
        "DE SECURITE SOCIALE : 60 120 FRS",
    ]
    annuels, griefs = module.annuels_du_titre(titres)
    assert griefs == []
    assert annuels[1969] == pytest.approx(16320 / 6.55957)
    assert annuels[1972] == pytest.approx(21960 / 6.55957)
    assert annuels[1980] == pytest.approx(60120 / 6.55957)


def test_a_compter_du_1er_janvier_n_est_pas_pour_l_annee():
    """Le piège de 1982 : le décret de décembre 1981 ne commande pas l'année.

    Un décret de juin 1982 a relevé le plafond au 1er juillet ; lire le montant
    annuel du 1er janvier comme celui de l'année donnerait 1982 à −3,6 %.
    """
    module = _plafond()
    titre = (
        "Décret n°81-1164 du 30 décembre 1981 PORTANT FIXATION A COMPTER DU "
        "01-01-1982, DU PLAFOND DES COTISATIONS DE SECURITE SOCIALE "
        "(GAIN OU REMUNERATION ANNUEL : 79 080 FRS)"
    )
    assert module.annuels_du_titre([titre]) == ({}, [])


def test_un_titre_annuel_cede_devant_un_relevement_en_cours_d_annee():
    """La règle ne repose pas sur une date charnière supposée, mais sur ce qui est lu."""
    module = _plafond()
    serie, griefs = module.fusionner(
        {}, {1982: 12055.0}, {datetime.date(1982, 7, 1): 1100.0})
    assert serie == {}
    assert [g for g in griefs if "titre annuel écarté" in g]


def test_les_deux_lectures_se_contredisent_sans_se_recouvrir():
    """Si le titre et les mois disaient deux choses, l'année serait refusée."""
    module = _plafond()
    serie, griefs = module.fusionner({1969: 2487.9}, {1969: 2999.0}, {})
    assert serie == {1969: 2487.9}
    assert [g for g in griefs if "le titre annuel dit" in g]


def test_la_notice_de_1987_ecrit_janvier_en_toutes_lettres():
    """« LA VALEUR DU NOUVEAU PLAFOND EST DE 9630FRS PAR MOIS », sans parenthèse."""
    module = _plafond()
    notice = (
        "PORTANT FIXATION A COMPTER DU 01-01-1987 ET DU 01-07-1987 DU PLAFOND "
        "DE LA SECURITE SOCIALE. LE TAUX D'AUGMENTATION DE 4,4% CORRESPOND A "
        "L'EVOLUTION DU SALAIRE MOYEN (4,5%). LA VALEUR DU NOUVEAU PLAFOND EST "
        "DE 9630FRS PAR MOIS. A COMPTER DU 01-07-1987 IL SERA DE 9840FRS PAR "
        "MOIS,VALEUR OBTENUE PAR MAJORATION DE 2,18% DE LA VALEUR AU 01-01-1987."
    )
    par_date, _, griefs = module.montants_dates([notice])
    assert griefs == []
    assert par_date[datetime.date(1987, 1, 1)] == pytest.approx(9630 / 6.55957)
    assert par_date[datetime.date(1987, 7, 1)] == pytest.approx(9840 / 6.55957)


def test_janvier_seul_ne_fait_pas_une_annee_sans_mention_expresse():
    """1989 : janvier est lisible, juillet n'annonce qu'un taux.

    De 1982 à 1996 un second décret relevait le plafond au 1er juillet. Étendre
    janvier aux douze mois sous-estimerait l'année de tout ce relèvement — sauf
    si le texte déclare lui-même couvrir l'année entière.
    """
    module = _plafond()
    janvier = {datetime.date(1989, 1, 1): 1576.32}
    assert module.serie_annuelle(janvier, set()) == {}
    assert module.serie_annuelle(janvier, {1989})[1989] == pytest.approx(12 * 1576.32)


def test_l_annee_entiere_se_lit_dans_le_texte_qui_la_declare():
    """« POUR LA PERIODE DU 01-01-1997 AU 31-12-1997 », « du 1er janvier au 31 décembre 1998 »."""
    module = _plafond()
    _, entieres, _ = module.montants_dates([
        "LES NOUVELLES VALEURS DU PLAFOND POUR LA PERIODE DU 01-01-1997 AU "
        "31-12-1997, EN APPLIQUANT AU PLAFOND MENSUEL MOYEN DE 1996 LE TAUX.",
        "pour les rémunérations ou gains versés du 1er janvier au 31 décembre 1998.",
    ])
    assert entieres == {1997, 1998}
