"""Le contenu des pages du site, écrit en Python.

Le site publié sur GitHub Pages ne passe pas par Python : il exécute un portage
JavaScript du modèle (``moteur/js/``), pour n'avoir à télécharger que le modèle
et ses données plutôt qu'un interpréteur entier. Ce module reste la
**référence** dont ce portage doit reproduire les chiffres et le rendu, et
``scripts/construire_temoins.py`` fige ici même ce qu'il doit retrouver.
"""

from __future__ import annotations
