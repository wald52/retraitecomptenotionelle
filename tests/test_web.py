"""Tests de l'interface web, dans ses deux modes.

Le contenu des pages (:mod:`retraite_notionnelle.web.pages`) ne dépend que de la
bibliothèque standard : il est testé sans condition. Les tests du serveur
FastAPI sont ignorés si les dépendances optionnelles sont absentes
(``pip install -e ".[web]"``).
"""

from __future__ import annotations

import pytest

from retraite_notionnelle.web import gabarit as g
from retraite_notionnelle.web.gabarit import (
    Cellule,
    euros,
    franciser,
    pourcentage,
    tableau,
)
from retraite_notionnelle.web.pages import (
    Contexte,
    ErreurSaisie,
    Saisie,
    rendre,
    statuts,
)


@pytest.fixture(scope="module")
def contexte() -> Contexte:
    return Contexte()


@pytest.fixture(scope="module")
def client():
    fastapi = pytest.importorskip("fastapi", reason="dépendances web absentes")
    pytest.importorskip("httpx", reason="client de test absent")
    from fastapi.testclient import TestClient

    from retraite_notionnelle.web import creer_application

    assert fastapi
    return TestClient(creer_application())


# -- pages -------------------------------------------------------------------


@pytest.mark.parametrize("chemin", ["/", "/cas-types", "/methode", "/donnees"])
def test_les_pages_repondent(client, chemin):
    reponse = client.get(chemin)
    assert reponse.status_code == 200
    assert "text/html" in reponse.headers["content-type"]
    assert "Retraite à comptes notionnels" in reponse.text


def test_accueil_sans_parametres_ne_calcule_rien(client):
    """Une visite nue montre le formulaire, pas des résultats surgis de nulle part."""
    texte = client.get("/").text
    assert "Simuler une carrière" in texte
    assert "Résultats" not in texte


def test_simulation_affiche_les_trois_scenarios(client):
    reponse = client.get(
        "/", params={"naissance": 1960, "statut": "agent_sncf",
                     "debut": 20, "liquidation": 52}
    )
    assert reponse.status_code == 200
    for attendu in ("Système actuel", "rétroactifs depuis 1941",
                    "à compter de 2026", "Résultats"):
        assert attendu in reponse.text


def test_la_saisie_est_reinjectee_dans_le_formulaire(client):
    """L'adresse porte les paramètres : la page doit être rechargeable telle quelle."""
    texte = client.get(
        "/", params={"naissance": 1955, "statut": "mineur",
                     "debut": 18, "liquidation": 55}
    ).text
    assert 'value="1955"' in texte
    assert '<option value="mineur" selected>' in texte


def test_saisie_invalide_affiche_un_message_et_pas_de_trace(client):
    reponse = client.get("/", params={"naissance": 1700})
    assert reponse.status_code == 200
    assert "Saisie refusée" in reponse.text
    assert "Traceback" not in reponse.text


def test_carriere_impossible_est_signalee_sans_planter(client):
    reponse = client.get(
        "/", params={"naissance": 1990, "statut": "salarie_prive_non_cadre",
                     "debut": 30, "liquidation": 45}
    )
    assert reponse.status_code == 200
    assert "Traceback" not in reponse.text


def test_la_decomposition_par_regle_d_indexation_est_presente(client):
    """Le point le plus contre-intuitif du modèle doit être exposé, pas caché."""
    texte = client.get(
        "/", params={"naissance": 1960, "statut": "salarie_prive_non_cadre",
                     "debut": 20, "liquidation": 62}
    ).text
    assert "D'où vient l'écart" in texte
    assert "Triple lock inversé, tout en nominal" in texte
    assert texte.count("Rendement cumulé") >= 1


def test_pas_de_decomposition_si_l_indexation_est_deja_choisie(client):
    texte = client.get(
        "/", params={"naissance": 1960, "statut": "salarie_prive_non_cadre",
                     "debut": 20, "liquidation": 62, "indexation": "prix"}
    ).text
    assert "D'où vient l'écart" not in texte


# -- API ---------------------------------------------------------------------


def test_api_statuts(client):
    donnees = client.get("/api/statuts").json()
    codes = {entree["code"] for entree in donnees}
    assert "salarie_prive_non_cadre" in codes
    assert all(entree["libelle"] for entree in donnees)


def test_api_simuler(client):
    donnees = client.get(
        "/api/simuler",
        params={"naissance": 1975, "statut": "fonctionnaire_etat",
                "debut": 23, "liquidation": 64, "primes": 0.2},
    ).json()
    assert donnees["assure"]["annee_naissance"] == 1975
    scenarios = donnees["scenarios"]
    assert scenarios["actuel"]["pension_annuelle"] > 0
    assert scenarios["notionnel_retroactif"]["pension_annuelle"] > 0
    assert donnees["fiabilite"]


def test_api_refuse_une_saisie_invalide(client):
    reponse = client.get("/api/simuler", params={"naissance": 1700})
    assert reponse.status_code == 422
    assert "erreur" in reponse.json()


def test_api_refuse_un_statut_inconnu(client):
    reponse = client.get(
        "/api/simuler",
        params={"naissance": 1975, "statut": "astronaute",
                "debut": 23, "liquidation": 64},
    )
    assert reponse.status_code == 422


# -- saisie ------------------------------------------------------------------


def test_saisie_par_defaut_est_valide():
    Saisie().verifier()


@pytest.mark.parametrize("champs", [
    {"naissance": "1700"},
    {"debut": "12"},
    {"liquidation": "90"},
    {"naissance": "1980", "debut": "30", "liquidation": "25"},
    {"salaire": "50"},
])
def test_saisies_refusees(champs):
    with pytest.raises(ErreurSaisie):
        Saisie.depuis_requete(champs)


def test_valeur_non_numerique_est_refusee_proprement():
    with pytest.raises(ErreurSaisie):
        Saisie.depuis_requete({"naissance": "mille-neuf-cent"})


def test_virgule_decimale_acceptee():
    assert Saisie.depuis_requete({"salaire": "1,5"}).salaire == 1.5


def test_option_inconnue_retombe_sur_le_defaut():
    saisie = Saisie.depuis_requete({"indexation": "au_doigt_mouille"})
    assert saisie.indexation == "triple_lock_inverse"


def test_interruptions_analysees():
    saisie = Saisie(interruptions="1995:1997:education_enfant, 2001:2001:maladie")
    plages = saisie.interruptions_analysees()
    assert plages[1995] == "education_enfant"
    assert plages[1997] == "education_enfant"
    assert plages[2001] == "maladie"
    assert 1998 not in plages


def test_interruption_mal_formee_est_refusee():
    with pytest.raises(ErreurSaisie):
        Saisie(interruptions="1995-1997").interruptions_analysees()


def test_requete_reconstruit_les_parametres():
    requete = Saisie(naissance=1960, statut="mineur").requete()
    assert "naissance=1960" in requete
    assert "statut=mineur" in requete


# -- rendu -------------------------------------------------------------------


def test_les_nombres_sont_a_la_francaise():
    assert euros(1234567) == "1 234 567 €"
    assert pourcentage(-0.937, signe=True) == "-93,7 %"
    assert pourcentage(0.5, signe=True) == "+50,0 %"


def test_franciser_les_libelles_du_moteur():
    assert franciser("SR 17,542 € × taux 63.75%") == (
        "SR 17 542 € × taux 63,75 %"
    )


def test_l_echappement_protege_des_injections(client):
    texte = client.get("/", params={"interruptions": "<script>alert(1)</script>"}).text
    assert "<script>alert(1)</script>" not in texte
    assert "&lt;script&gt;" in texte


def test_cellule_teintee_selon_la_valeur():
    assert "background" in Cellule("-90 %", intensite=-0.9).style()
    assert Cellule("+0 %", intensite=0.0).style() == ""
    rendu = tableau(["a"], [[Cellule("x", intensite=-0.5)]], ["nombre"])
    assert "rgba(162, 71, 46" in rendu


# -- rendu commun aux deux modes ---------------------------------------------


@pytest.mark.parametrize("chemin", ["/", "/cas-types", "/methode", "/donnees"])
def test_rendre_produit_un_corps_pour_chaque_page(contexte, chemin):
    titre, corps = rendre(contexte, chemin)
    assert titre
    assert len(corps) > 500


def test_rendre_ignore_un_chemin_inconnu(contexte):
    titre, _ = rendre(contexte, "/n-importe-quoi")
    assert titre == "Simuler"


def test_rendre_ne_leve_jamais_sur_une_saisie_invalide(contexte):
    _, corps = rendre(contexte, "/", {"naissance": "1700"})
    assert "Saisie refusée" in corps


def test_statuts(contexte):
    codes = {entree["code"] for entree in statuts(contexte)}
    assert "salarie_prive_non_cadre" in codes


# -- mode navigateur ---------------------------------------------------------


@pytest.fixture
def mode_navigateur():
    """Bascule le rendu en mode navigateur, et le remet en place ensuite."""
    precedent = g.MODE
    g.MODE = "navigateur"
    yield
    g.MODE = precedent


def test_les_liens_passent_par_l_ancre_dans_le_navigateur(mode_navigateur, contexte):
    """Sur GitHub Pages le site est servi dans un sous-chemin : pas de lien absolu."""
    _, corps = rendre(contexte, "/")
    entete = g.entete("/")
    assert 'href="#/cas-types"' in entete
    assert 'href="/cas-types"' not in entete
    assert 'action="#/"' in corps


def test_pas_de_renvoi_vers_l_api_dans_le_navigateur(mode_navigateur, contexte):
    """Il n'y a pas de serveur : proposer une adresse d'API serait un lien mort."""
    _, corps = rendre(contexte, "/", {"naissance": "1960",
                                      "statut": "salarie_prive_non_cadre",
                                      "debut": "20", "liquidation": "62"})
    assert "/api/simuler" not in corps
    assert "Les résultats complets en JSON" in corps


def test_le_pont_du_navigateur_rend_du_json(mode_navigateur):
    import json

    from retraite_notionnelle.config import RACINE_DONNEES
    from retraite_notionnelle.web import navigateur

    navigateur.demarrer(str(RACINE_DONNEES))
    page = json.loads(navigateur.rendre_page("/cas-types", "{}"))
    assert page["titre"] == "Cas types"
    assert "Le cas général" in page["corps"]
    assert 'href="#/"' in page["entete"]
    assert navigateur.feuille_de_style().startswith("\n:root")


# -- paquet embarqué dans la page --------------------------------------------


def _construction():
    import importlib.util
    from pathlib import Path

    chemin = Path(__file__).resolve().parents[1] / "scripts" / "construire_site.py"
    specification = importlib.util.spec_from_file_location("construire_site", chemin)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_le_paquet_est_a_jour():
    """Le paquet servi au navigateur doit refléter le code du dépôt.

    S'il échoue : ``python scripts/construire_site.py``.
    """
    construction = _construction()
    assert construction.PAQUET.exists(), "docs/simulateur.zip est absent"
    assert construction.PAQUET.read_bytes() == construction.construire(), (
        "docs/simulateur.zip est périmé — lancer python scripts/construire_site.py"
    )


def test_le_paquet_contient_le_moteur_et_les_donnees():
    import zipfile

    construction = _construction()
    with zipfile.ZipFile(construction.PAQUET) as archive:
        noms = set(archive.namelist())
    assert "retraite_notionnelle/simulateur.py" in noms
    assert "retraite_notionnelle/web/navigateur.py" in noms
    assert "data/sources.yaml" in noms
    assert any(nom.startswith("data/reference/macro/") for nom in noms)


def test_la_page_ne_depend_d_aucun_service_exterieur():
    """« Tout doit déjà être là » : aucune requête vers un tiers au chargement."""
    from pathlib import Path

    page = (Path(__file__).resolve().parents[1] / "docs" / "index.html").read_text()
    assert 'src="pyodide/pyodide.js"' in page
    assert "cdn.jsdelivr.net" not in page

    #: Seules adresses tolérées : le dépôt lui-même (liens que le lecteur suit
    #: s'il le veut) et l'espace de noms SVG, qui n'est jamais requêté.
    autorisees = ("https://github.com/wald52/", "http://www.w3.org/2000/svg")
    for hote in ("http://", "https://"):
        for morceau in page.split(hote)[1:]:
            adresse = hote + morceau.split('"')[0]
            assert adresse.startswith(autorisees), (
                f"adresse extérieure dans la page : {adresse}"
            )


def test_le_moteur_pyodide_est_versionne():
    from pathlib import Path

    pyodide = Path(__file__).resolve().parents[1] / "docs" / "pyodide"
    attendus = {"pyodide.js", "pyodide.asm.mjs", "pyodide.asm.wasm",
                "python_stdlib.zip", "pyodide-lock.json"}
    presents = {chemin.name for chemin in pyodide.iterdir()}
    assert attendus <= presents, f"manquant : {attendus - presents}"
    assert any(nom.startswith("pyyaml-") for nom in presents)
