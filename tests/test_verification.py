"""Tests du vérificateur de données.

Aucun de ces tests n'accède au réseau : les fichiers source sont simulés. Ce
qui est vérifié ici, ce n'est pas la valeur des séries INSEE — c'est la manière
dont le script les reconstruit, et la règle qu'il applique avant d'accorder le
niveau ``certifiee``.
"""

from __future__ import annotations

import csv
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


def test_plafond_ecarte_une_annee_incomplete_ou_mouvante(verificateur, monkeypatch):
    """Le plafond est annuel : douze mois identiques, ou rien.

    Une année partiellement observée donnerait un plafond faux sans que rien ne
    le signale — c'est exactement le genre de valeur qui ne doit jamais être
    certifiée.
    """
    mensuel = {}
    mensuel.update({f"2010-{mois:02d}": 2885.0 for mois in range(1, 13)})   # complète
    mensuel.update({f"2011-{mois:02d}": 2946.0 for mois in range(1, 9)})    # partielle
    mensuel.update({f"2012-{mois:02d}": 3031.0 for mois in range(1, 12)})
    mensuel["2012-12"] = 3100.0                                             # mouvante
    monkeypatch.setattr(verificateur, "_observations", lambda nom: mensuel)

    plafond = verificateur.source_plafond()
    assert plafond == {("2010",): round(2885.0 * 12)}


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


def test_plafond_ancien_s_arrete_ou_l_insee_commence(verificateur, monkeypatch):
    """Deux sources sur un même fichier ne doivent pas se marcher dessus."""
    monkeypatch.setattr(
        verificateur, "_serie_json",
        lambda *args: {"1999": 26471.2, "2001": 27349.4, "2002": 28224.0, "2010": 34620.0},
    )
    serie = verificateur.source_plafond_ancien()
    assert set(serie) == {("1999",), ("2001",)}


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
