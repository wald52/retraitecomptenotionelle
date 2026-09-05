"""Lecteur de classeurs Excel 2007+ (.xlsx), sans dépendance.

Pendant de ``lecture_xls.py``, qui lit le format Excel 97, et écrit pour la même
raison : une source publie ses séries dans un format que la bibliothèque
standard ne sait pas ouvrir, et le dépôt s'interdit toute dépendance hors PyYAML.

La tâche est ici beaucoup plus courte que pour le BIFF8, parce qu'un ``.xlsx``
n'est qu'une archive ZIP de fichiers XML — deux formats que la bibliothèque
standard couvre entièrement. Il ne reste qu'à connaître trois conventions :

* ``xl/workbook.xml`` nomme les feuilles ; le chemin de chacune se lit dans
  ``xl/_rels/workbook.xml.rels``, par l'identifiant de relation ``r:id`` ;
* le texte des cellules n'est pas dans la feuille mais dans une table commune,
  ``xl/sharedStrings.xml``, à laquelle une cellule de type ``s`` renvoie par son
  indice ;
* une cellule porte sa référence en notation A1 (``B7``) et non un couple
  d'indices : la colonne se lit en base 26, sur les lettres.

Seules les cellules qui portent une valeur sont rendues, les vides étant
absentes de la feuille : un lecteur doit donc interroger la grille par
``.get()``, jamais par index.
"""

from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree as ET

#: Espace de noms du format SpreadsheetML, préfixant chaque balise.
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

_REFERENCE = re.compile(r"([A-Z]+)(\d+)")


def _colonne(lettres: str) -> int:
    """Indice zéro d'une colonne depuis ses lettres : A -> 0, Z -> 25, AA -> 26."""
    indice = 0
    for lettre in lettres:
        indice = indice * 26 + (ord(lettre) - ord("A") + 1)
    return indice - 1


def feuilles(donnees: bytes) -> dict[str, dict[tuple[int, int], float | str]]:
    """Grilles du classeur, par nom de feuille.

    Chaque grille associe un couple ``(ligne, colonne)``, en indices commençant
    à zéro, à la valeur de la cellule — un ``float`` pour un nombre, une ``str``
    pour un texte. Les cellules vides sont absentes.
    """
    with zipfile.ZipFile(io.BytesIO(donnees)) as archive:
        noms = archive.namelist()
        if "xl/workbook.xml" not in noms:
            raise ValueError("ce n'est pas un classeur Excel 2007+")

        relations = dict(re.findall(
            r'Id="(rId\d+)"[^>]*Target="([^"]+)"',
            archive.read("xl/_rels/workbook.xml.rels").decode("utf-8"),
        ))
        chemins = {
            nom: "xl/" + relations[identifiant].lstrip("/")
            for nom, identifiant in re.findall(
                r'<sheet name="([^"]+)"[^>]*r:id="(rId\d+)"',
                archive.read("xl/workbook.xml").decode("utf-8"),
            )
        }

        chaines: list[str] = []
        if "xl/sharedStrings.xml" in noms:
            for si in ET.fromstring(archive.read("xl/sharedStrings.xml")):
                chaines.append("".join(t.text or "" for t in si.iter(NS + "t")))

        grilles: dict[str, dict[tuple[int, int], float | str]] = {}
        for nom, chemin in chemins.items():
            if chemin not in noms:
                continue
            grille: dict[tuple[int, int], float | str] = {}
            for cellule in ET.fromstring(archive.read(chemin)).iter(NS + "c"):
                reference = _REFERENCE.match(cellule.get("r") or "")
                valeur = cellule.find(NS + "v")
                if reference is None or valeur is None or valeur.text is None:
                    continue
                position = (int(reference.group(2)) - 1, _colonne(reference.group(1)))
                if cellule.get("t") == "s":
                    grille[position] = chaines[int(valeur.text)]
                elif cellule.get("t") in (None, "n"):
                    grille[position] = float(valeur.text)
            grilles[nom] = grille
    return grilles

