"""Interface web du simulateur.

Une page unique pour saisir une carrière et lire les trois scénarios, plus une
API JSON. Dépendances optionnelles : ``pip install -e ".[web]"``.

    retraite-notionnelle web
    # puis http://127.0.0.1:8000
"""

from __future__ import annotations

from .application import creer_application

__all__ = ["creer_application"]
