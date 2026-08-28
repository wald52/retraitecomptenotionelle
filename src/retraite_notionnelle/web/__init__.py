"""Interface web du simulateur, servie par un serveur local.

``retraite-notionnelle web`` sert les pages via FastAPI et expose une API JSON.
Dépendances optionnelles : ``pip install -e ".[web]"``.

Le site publié sur GitHub Pages, lui, ne passe plus par Python : il exécute un
portage JavaScript du modèle (``moteur/js/``), pour n'avoir à télécharger que le
modèle et ses données plutôt qu'un interpréteur entier. Ce module reste la
**référence** dont ce portage doit reproduire les chiffres, et
``scripts/construire_temoins.py`` fige ici même ce qu'il doit retrouver.
"""

from __future__ import annotations

__all__ = ["creer_application"]


def creer_application(parametres=None):
    """Application FastAPI. Importée à la demande : FastAPI est optionnel."""
    from .application import creer_application as fabrique

    return fabrique(parametres)
