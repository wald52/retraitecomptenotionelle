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
from retraite_notionnelle.donnees.chargement import DonneeInsuffisante
from retraite_notionnelle.web.pages import (
    AGES_REFERENCE,
    INDEXATIONS,
    PROFILS,
    PROJECTIONS,
    TABLES,
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
    assert saisie.indexation == "masse_salariale"


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


@pytest.mark.parametrize("chemin", ["/", "/cas-types", "/methode"])
def test_les_ages_rendus_ne_doublent_pas_leur_unite(contexte, chemin):
    """« 64 ans ans ».

    L'âge s'écrivait « 64 » et les appelants ajoutaient « ans ». Le jour où il
    s'est mis à s'écrire « 64 ans et 7 mois », l'unité s'est retrouvée en
    double sur chaque page — et aucun test ne pouvait le voir, puisque les deux
    portages étaient d'accord et que les témoins avaient été régénérés avec la
    faute. Celui-ci regarde le texte rendu.
    """
    import re

    _, corps = rendre(contexte, chemin, {
        "naissance": "1962", "naissance_mois": "3", "debut": "22",
        "liquidation": "64", "liquidation_mois": "7",
        "statut": "salarie_prive_non_cadre",
    })
    for faute in ("ans ans", "mois mois", "ans et ans"):
        assert faute not in corps, f"{faute!r} dans {chemin}"
    # Et l'âge s'y lit bien en ans et en mois.
    if chemin == "/":
        assert re.search(r"64 ans et 7 mois", corps)


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


# -- ce que charge le site ---------------------------------------------------


def _construction():
    import importlib.util
    from pathlib import Path

    chemin = Path(__file__).resolve().parents[1] / "scripts" / "construire_donnees.py"
    specification = importlib.util.spec_from_file_location("construire_donnees", chemin)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_le_paquet_est_a_jour():
    """Le paquet et la feuille de style servis au site doivent refléter le dépôt.

    S'il échoue : ``python scripts/construire_donnees.py``.
    """
    construction = _construction()
    for chemin, contenu in construction.sorties().items():
        assert chemin.exists(), f"{chemin.name} est absent"
        assert chemin.read_bytes() == contenu, (
            f"{chemin.name} est périmé — lancer python scripts/construire_donnees.py"
        )


def test_le_paquet_contient_les_donnees_du_modele():
    import json

    construction = _construction()
    paquet = json.loads(construction.PAQUET.read_text(encoding="utf-8"))

    assert paquet["version"] == construction.VERSION
    assert {"series", "regimes", "affiliations", "quotients", "calibrations",
            "valeurs_point", "rendements_points", "hypotheses"} <= set(paquet)
    from retraite_notionnelle.donnees.regimes import CatalogueRegimes
    from retraite_notionnelle.config import RACINE_DONNEES

    assert len(paquet["regimes"]) == len(CatalogueRegimes(RACINE_DONNEES))
    assert {"inflation", "salaire_moyen", "productivite", "pass"} <= set(paquet["series"])


def test_toutes_les_calibrations_de_mortalite_sont_livrees():
    """Le navigateur lit une table, il ne recalibre rien.

    La calibration est une double bissection : la refaire dans la page coûterait
    du temps et ferait dépendre le résultat de la ``libm`` du navigateur. On
    vérifie donc que le paquet couvre tout le domaine où le modèle la consulte.
    """
    import json

    from retraite_notionnelle.config import RACINE_DONNEES
    from retraite_notionnelle.donnees.mortalite import DonneesMortalite

    paquet = json.loads(_construction().PAQUET.read_text(encoding="utf-8"))
    mortalite = DonneesMortalite(RACINE_DONNEES, cache_disque=False)
    for sexe in DonneesMortalite.SEXES:
        serie = mortalite._e60[sexe]
        for annee in range(serie.premiere_annee, serie.derniere_annee + 1):
            assert f"{annee}|{sexe}" in paquet["calibrations"]


def test_les_temoins_du_portage_sont_a_jour():
    """Les chiffres que doit retrouver le portage JavaScript.

    S'il échoue : ``python scripts/construire_temoins.py`` — et relire le diff,
    qui montre exactement quels montants le changement déplace.
    """
    import importlib.util
    from pathlib import Path

    chemin = Path(__file__).resolve().parents[1] / "scripts" / "construire_temoins.py"
    specification = importlib.util.spec_from_file_location("construire_temoins", chemin)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)

    for fichier, contenu in module.construire().items():
        assert fichier.exists(), f"{fichier.name} est absent"
        assert fichier.read_bytes() == contenu, (
            f"{fichier.name} est périmé — lancer python scripts/construire_temoins.py"
        )


def test_le_portage_javascript_retrouve_les_chiffres_du_modele():
    """Lance ``node --test`` : le site doit calculer comme la référence Python."""
    import shutil
    import subprocess
    from pathlib import Path

    if shutil.which("node") is None:
        pytest.skip("node absent : le portage JavaScript n'est pas vérifiable ici")

    racine = Path(__file__).resolve().parents[1]
    execution = subprocess.run(
        ["node", "--test", "tests/js/moteur.test.js"],
        cwd=racine, capture_output=True, text=True, check=False,
    )
    assert execution.returncode == 0, execution.stdout + execution.stderr


def test_le_portage_javascript_concorde_sur_des_carrieres_tirees_au_hasard():
    """Les témoins figés couvrent des cas choisis ; celui-ci, des cas non prévus.

    Un portage se trompe rarement là où on l'a regardé. On tire donc des
    carrières au hasard — graine fixe, donc reproductible —, on les calcule ici,
    et ``tests/js/comparer.mjs`` vérifie que le site retrouve chaque valeur.
    """
    import json
    import random
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path

    if shutil.which("node") is None:
        pytest.skip("node absent : le portage JavaScript n'est pas vérifiable ici")

    contexte = Contexte()
    alea = random.Random(20260828)
    statuts = list(contexte.simulateur().affiliations.codes)
    cas = []
    for numero in range(60):
        # Les âges sont tirés EN MOIS, et le mois de naissance avec : c'est là
        # que le portage a le plus de chances de diverger, puisque le mois
        # commande la date de liquidation, les mois cotisés de l'année du
        # départ, les trimestres civils qu'ils valident et le diviseur.
        debut = alea.randint(14 * 12, 30 * 12)
        liquidation = alea.randint(max(41 * 12, debut + 12), 75 * 12)
        requete = {
            "naissance": str(alea.randint(1900, 2005)),
            "naissance_mois": str(alea.randint(1, 12)),
            "sexe": alea.choice(["H", "F"]),
            "statut": alea.choice(statuts),
            "debut": str(debut // 12),
            "debut_mois": str(debut % 12),
            "liquidation": str(liquidation // 12),
            "liquidation_mois": str(liquidation % 12),
            "salaire": f"{alea.uniform(0.1, 9):.3f}",
            "profil": alea.choice([code for code, _ in PROFILS]),
            "primes": f"{alea.uniform(0, 0.6):.3f}",
            "enfants": str(alea.randint(0, 6)),
            "indexation": alea.choice([code for code, _ in INDEXATIONS]),
            "age_reference": alea.choice([code for code, _ in AGES_REFERENCE]),
            "table": alea.choice([code for code, _ in TABLES]),
            "projection": alea.choice([code for code, _ in PROJECTIONS]),
            "bascule": str(alea.randint(1945, 2065)),
            "euros": str(alea.randint(1945, 2065)),
            "interruptions": alea.choice(["", f"{alea.randint(1985, 2005)}:"
                                          f"{alea.randint(2006, 2015)}:education_enfant"]),
        }
        nom = f"aleatoire_{numero}"
        try:
            resultat = contexte.simuler(Saisie.depuis_requete(requete)).dictionnaire()
        except (ErreurSaisie, DonneeInsuffisante, KeyError, ValueError) as erreur:
            cas.append({"nom": nom, "requete": requete, "erreur": str(erreur)})
            continue
        cas.append({"nom": nom, "requete": requete, "resultat": _sans_nan(resultat)})

    racine = Path(__file__).resolve().parents[1]
    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8",
                                     delete=False) as fichier:
        json.dump(cas, fichier, ensure_ascii=False)
        chemin = fichier.name
    try:
        execution = subprocess.run(
            ["node", "tests/js/comparer.mjs", chemin],
            cwd=racine, capture_output=True, text=True, check=False,
        )
    finally:
        Path(chemin).unlink(missing_ok=True)
    assert execution.returncode == 0, execution.stdout + execution.stderr


def _sans_nan(valeur):
    """NaN et infinis en ``null`` : la norme JSON ne connaît qu'eux."""
    if isinstance(valeur, float) and (valeur != valeur or valeur in (
            float("inf"), float("-inf"))):
        return None
    if isinstance(valeur, dict):
        return {cle: _sans_nan(v) for cle, v in valeur.items()}
    if isinstance(valeur, list):
        return [_sans_nan(v) for v in valeur]
    return valeur


def test_la_page_ne_depend_d_aucun_service_exterieur():
    """« Tout doit déjà être là » : aucune requête vers un tiers au chargement."""
    from pathlib import Path

    page = (Path(__file__).resolve().parents[1] / "index.html").read_text()
    assert 'href="moteur/style.css"' in page
    assert 'from "./moteur/js/pages.js"' in page
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


def test_le_prechargement_du_paquet_correspond_a_la_requete():
    """Un préchargement qui ne correspond pas au ``fetch`` est pire qu'inutile.

    Le navigateur ne réutilise le ``<link rel="preload">`` que si la requête a
    exactement le même mode et les mêmes identifiants. Sinon il télécharge le
    paquet **deux fois** — 186 Ko en trop à chaque première visite — en n'émettant
    qu'un avertissement de console que personne ne lit. Les deux déclarations sont
    donc verrouillées ensemble ici : ``crossorigin`` sur le lien, et un ``fetch``
    nu, sans ``mode`` ni ``credentials`` qui s'en écarteraient.
    """
    import re
    from pathlib import Path

    page = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")

    prechargement = re.search(r"<link rel=\"preload\"[^>]*donnees\.json[^>]*>", page)
    appel = re.search(r"fetch\(\"moteur/donnees\.json\",\s*(\{[^}]*\})\)", page)
    assert prechargement and appel, "préchargement ou requête introuvables dans index.html"

    assert "crossorigin" in prechargement.group(0), (
        "le préchargement doit porter crossorigin, sinon il ne correspond pas au fetch"
    )
    options = appel.group(1)
    assert "credentials" not in options and "mode" not in options, (
        f"la requête s'écarte du préchargement ({options}) : le paquet serait "
        "téléchargé deux fois"
    )


def test_le_style_d_amorcage_ne_vise_que_des_elements_existants():
    """Pas de règle orpheline dans la page : ce qui ne sert plus s'enlève.

    L'écran d'attente a déjà survécu à un moteur entier ; ses règles lui
    survivaient à leur tour. Chaque classe et chaque identifiant stylés doivent
    donc se retrouver dans le corps de la page ou dans le script qui le remplace.
    """
    import re
    from pathlib import Path

    page = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")
    style = re.search(r"<style>(.*?)</style>", page, re.S).group(1)
    reste = page.replace(style, "")

    selecteurs = " ".join(re.findall(r"^([^{}@]+)\{", style, re.M))
    for nom in set(re.findall(r"[#.]([\w-]+)", selecteurs)):
        assert nom in reste, (
            f"« {nom} » est stylé dans index.html mais n'existe nulle part dans la page"
        )

    balises = set(re.findall(r"\b(\w+)(?=\s*[.#{]|\s+[\w.#])", selecteurs))
    for balise in balises & {"code", "table", "img", "button", "input", "ul", "li"}:
        assert f"<{balise}" in reste, (
            f"la règle visant <{balise}> ne correspond à aucun élément de la page"
        )


def test_le_moteur_javascript_est_versionne():
    """Le site n'a aucune étape de construction : tout ce qu'il charge est là."""
    from pathlib import Path

    moteur = Path(__file__).resolve().parents[1] / "moteur"
    assert (moteur / "donnees.json").exists()
    assert (moteur / "style.css").exists()

    modules = {chemin.name for chemin in (moteur / "js").iterdir()}
    attendus = {
        "format.js", "serie.js", "config.js", "macro.js", "mortalite.js",
        "regimes.js", "indexation.js", "conversion.js", "fusion.js",
        "age-reference.js", "carriere.js", "compte.js", "scenario-actuel.js",
        "scenario-notionnel.js", "simulateur.js", "castypes.js", "gabarit.js",
        "pages.js",
    }
    assert attendus <= modules, f"manquant : {attendus - modules}"

    #: Le portage ne tire aucune bibliothèque : il ne doit rien importer
    #: d'autre que lui-même.
    for chemin in (moteur / "js").iterdir():
        for ligne in chemin.read_text(encoding="utf-8").splitlines():
            if ligne.startswith("import ") and " from " in ligne:
                origine = ligne.rsplit(" from ", 1)[1].strip(' ;"')
                assert origine.startswith("./"), (
                    f"{chemin.name} importe depuis l'extérieur : {origine}"
                )
