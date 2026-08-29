"""Lecteur de classeurs Excel 97 (BIFF8), sans dépendance.

Pendant de ``lecture_pdf.py``, et pour la même raison : une source publie ses
séries dans un format que la bibliothèque standard ne sait pas ouvrir, et le
dépôt s'interdit toute dépendance hors PyYAML. On écrit donc le lecteur.

Un classeur Excel 97 est un fichier composite OLE2 — un système de fichiers
miniature — dont le flux ``Workbook`` contient des enregistrements BIFF. Seuls
les NOMBRES sont extraits : quatre types d'enregistrements suffisent (NUMBER,
RK, MULRK et le résultat en cache d'une FORMULA), et c'est tout ce dont on a
besoin pour reprendre une grille de quotients de mortalité.
"""

from __future__ import annotations

import struct


def _flux(donnees: bytes, nom_cible: str) -> bytes:
    """Extrait un flux nommé d'un fichier composite OLE2."""
    if donnees[:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise ValueError("ce n'est pas un fichier composite OLE2")
    taille = 1 << struct.unpack_from("<H", donnees, 30)[0]
    taille_mini = 1 << struct.unpack_from("<H", donnees, 32)[0]
    premier_repertoire = struct.unpack_from("<i", donnees, 48)[0]
    premier_mini = struct.unpack_from("<i", donnees, 60)[0]
    premier_difat = struct.unpack_from("<i", donnees, 68)[0]
    nb_difat = struct.unpack_from("<I", donnees, 72)[0]

    def secteur(indice: int) -> bytes:
        debut = (indice + 1) * taille
        return donnees[debut:debut + taille]

    # DIFAT : 109 entrées dans l'en-tête, puis des secteurs chaînés.
    difat = list(struct.unpack_from("<109i", donnees, 76))
    suivant = premier_difat
    for _ in range(nb_difat):
        if suivant < 0:
            break
        bloc = secteur(suivant)
        entrees = struct.unpack(f"<{taille // 4}i", bloc)
        difat.extend(entrees[:-1])
        suivant = entrees[-1]

    fat: list[int] = []
    for indice in difat:
        if indice < 0:
            continue
        fat.extend(struct.unpack(f"<{taille // 4}i", secteur(indice)))

    def chaine(depart: int, longueur: int | None = None) -> bytes:
        morceaux, indice = [], depart
        while indice >= 0 and len(morceaux) * taille < (longueur or 1 << 40):
            morceaux.append(secteur(indice))
            indice = fat[indice] if indice < len(fat) else -1
        contenu = b"".join(morceaux)
        return contenu[:longueur] if longueur else contenu

    repertoire = chaine(premier_repertoire)
    entrees = []
    for debut in range(0, len(repertoire), 128):
        entree = repertoire[debut:debut + 128]
        if len(entree) < 128:
            break
        longueur_nom = struct.unpack_from("<H", entree, 64)[0]
        nom = entree[:max(0, longueur_nom - 2)].decode("utf-16-le", "replace")
        entrees.append((nom, entree[66], struct.unpack_from("<i", entree, 116)[0],
                        struct.unpack_from("<I", entree, 120)[0]))

    racine = next(e for e in entrees if e[1] == 5)
    cible = next((e for e in entrees if e[0] == nom_cible), None)
    if cible is None:
        raise LookupError(f"flux {nom_cible!r} absent : {[e[0] for e in entrees]}")
    _, _, depart, longueur = cible
    if longueur >= 4096:
        return chaine(depart, longueur)

    # Petit flux : il vit dans le mini-FAT, lui-même stocké dans le flux racine.
    mini_fat: list[int] = []
    indice = premier_mini
    while indice >= 0:
        mini_fat.extend(struct.unpack(f"<{taille // 4}i", secteur(indice)))
        indice = fat[indice] if indice < len(fat) else -1
    conteneur = chaine(racine[2])
    morceaux, indice = [], depart
    while indice >= 0 and len(morceaux) * taille_mini < longueur:
        morceaux.append(conteneur[indice * taille_mini:(indice + 1) * taille_mini])
        indice = mini_fat[indice] if indice < len(mini_fat) else -1
    return b"".join(morceaux)[:longueur]


def _rk(brut: int) -> float:
    """Décode un nombre RK : entier ou double tronqué, éventuellement centième."""
    entier = bool(brut & 0x02)
    centieme = bool(brut & 0x01)
    if entier:
        valeur = float(brut >> 2 if brut < 0x80000000 else (brut >> 2) - (1 << 30))
    else:
        valeur = struct.unpack("<d", struct.pack("<Q", (brut & 0xFFFFFFFC) << 32))[0]
    return valeur / 100 if centieme else valeur


def feuilles(donnees: bytes) -> dict[str, dict[tuple[int, int], float]]:
    """Cellules NUMÉRIQUES de chaque feuille, indexées (ligne, colonne).

    Le texte est ignoré : ce lecteur sert à extraire des grilles de nombres.
    """
    flux = _flux(donnees, "Workbook")
    noms: list[tuple[int, str]] = []
    position = 0
    while position + 4 <= len(flux):
        type_, longueur = struct.unpack_from("<HH", flux, position)
        corps = flux[position + 4:position + 4 + longueur]
        if type_ == 0x0085 and len(corps) >= 8:  # BOUNDSHEET
            debut = struct.unpack_from("<I", corps, 0)[0]
            taille_nom = corps[6]
            large = corps[7] & 0x01
            brut = corps[8:8 + taille_nom * (2 if large else 1)]
            nom = brut.decode("utf-16-le" if large else "latin-1", "replace")
            noms.append((debut, nom))
        position += 4 + longueur

    resultat: dict[str, dict[tuple[int, int], float]] = {}
    for indice, (debut, nom) in enumerate(noms):
        fin = noms[indice + 1][0] if indice + 1 < len(noms) else len(flux)
        cellules: dict[tuple[int, int], float] = {}
        position = debut
        while position + 4 <= fin:
            type_, longueur = struct.unpack_from("<HH", flux, position)
            corps = flux[position + 4:position + 4 + longueur]
            if type_ == 0x0203 and len(corps) >= 14:  # NUMBER
                ligne, colonne = struct.unpack_from("<HH", corps, 0)
                cellules[(ligne, colonne)] = struct.unpack_from("<d", corps, 6)[0]
            elif type_ == 0x027E and len(corps) >= 10:  # RK
                ligne, colonne = struct.unpack_from("<HH", corps, 0)
                cellules[(ligne, colonne)] = _rk(
                    struct.unpack_from("<I", corps, 6)[0])
            elif type_ == 0x00BD and len(corps) >= 6:  # MULRK
                ligne, premiere = struct.unpack_from("<HH", corps, 0)
                nombre = (len(corps) - 6) // 6
                for k in range(nombre):
                    brut = struct.unpack_from("<I", corps, 4 + k * 6 + 2)[0]
                    cellules[(ligne, premiere + k)] = _rk(brut)
            elif type_ == 0x0006 and len(corps) >= 20:  # FORMULA, résultat en cache
                ligne, colonne = struct.unpack_from("<HH", corps, 0)
                cache = corps[6:14]
                if cache[6:8] != b"\xff\xff":
                    cellules[(ligne, colonne)] = struct.unpack("<d", cache)[0]
            position += 4 + longueur
        resultat[nom] = cellules
    return resultat
