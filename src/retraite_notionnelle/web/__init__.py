"""Interface web du simulateur, servie de deux façons.

* **Dans le navigateur, sans rien installer** — ``docs/index.html`` exécute le
  moteur Python dans la page elle-même (Pyodide). C'est la version publiée sur
  GitHub Pages : une adresse à ouvrir, rien d'autre.
* **En local, avec un serveur** — ``retraite-notionnelle web`` sert les mêmes
  pages via FastAPI et expose en plus une API JSON. Dépendances optionnelles :
  ``pip install -e ".[web]"``.

Les deux affichent exactement la même chose : le contenu est produit par
:mod:`.pages`, qui ne dépend que de la bibliothèque standard.
"""

from __future__ import annotations

__all__ = ["creer_application"]


def creer_application(parametres=None):
    """Application FastAPI. Importée à la demande : FastAPI est optionnel."""
    from .application import creer_application as fabrique

    return fabrique(parametres)
