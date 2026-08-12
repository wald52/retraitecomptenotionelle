"""Pont entre la page HTML et le moteur, quand tout s'exécute dans le navigateur.

Le simulateur tourne dans Pyodide : c'est le même code Python que sur un poste
de travail, compilé en WebAssembly, exécuté par le navigateur du lecteur. Rien
n'est envoyé à un serveur, il n'y a rien à installer.

Le JavaScript de ``docs/index.html`` n'appelle que deux fonctions :

    demarrer("/simulateur/data")     -> prépare le simulateur
    rendre_page("/cas-types", "{}")  -> JSON {"titre": ..., "corps": ...}

Les échanges se font en chaînes JSON pour ne rien supposer de la conversion
automatique entre Python et JavaScript.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..config import Parametres
from . import gabarit as g
from .pages import Contexte, TITRES, rendre

_contexte: Contexte | None = None


def demarrer(racine_donnees: str) -> str:
    """Prépare le simulateur et renvoie l'en-tête de la page.

    Charge les séries et les tables au passage : c'est la seule opération
    coûteuse, on la fait une fois pour toutes.
    """
    global _contexte
    g.MODE = "navigateur"
    _contexte = Contexte(base=Parametres(racine_donnees=Path(racine_donnees)))
    _contexte.simulateur().macro  # force le chargement, erreurs comprises
    return g.entete("/")


def rendre_page(chemin: str, parametres_json: str = "{}") -> str:
    """Rend une page. Retourne un JSON ``{"titre", "corps", "entete", "pied"}``."""
    if _contexte is None:
        raise RuntimeError("demarrer() n'a pas été appelé")
    chemin = chemin if chemin in TITRES else "/"
    parametres = json.loads(parametres_json or "{}")
    titre, corps = rendre(_contexte, chemin, parametres)
    return json.dumps({
        "titre": titre,
        "corps": corps,
        "entete": g.entete(chemin),
        "pied": g.pied(),
    }, ensure_ascii=False)


def feuille_de_style() -> str:
    return g.FEUILLE_DE_STYLE
