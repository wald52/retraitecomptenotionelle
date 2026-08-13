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
