#!/usr/bin/env python3
"""Récupération des séries longues de l'INSEE par l'API SDMX de la BDM.

    python scripts/fetch/insee_bdm.py
    python scripts/fetch/insee_bdm.py --serie ipc_base_1980 --serie ipc_base_2015
    python scripts/fetch/insee_bdm.py --liste

La Banque de données macroéconomiques est interrogeable **sans clé d'accès** à
l'adresse ``https://api.insee.fr/series/BDM/V1``. Contrairement à l'API Melodi,
qui ne diffuse que les jeux récents, la BDM expose les séries chaînées depuis
1930 pour les cotisations, 1946 pour les espérances de vie et 1949 pour l'indice
des prix et les comptes nationaux.

C'est ce qui rend automatisable — donc certifiable au sens de
``scripts/verifier_donnees.py`` — l'essentiel des séries du modèle. Voir
``docs/limites.md`` §1 pour ce qui reste hors de portée.

Le fichier produit, ``data/brut/insee_bdm.json``, est le **document source** :
il n'est pas lu par le modèle, seulement par le vérificateur.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

BASE = "https://api.insee.fr/series/BDM/V1/data/SERIES_BDM"
ENTETES = {"User-Agent": "retraite-notionnelle/0.1 (recherche publique)"}
SORTIE = Path("data/brut/insee_bdm.json")

#: Séries à récupérer, sous le nom que leur donne ``verifier_donnees.py``.
#:
#: Chaque entrée dit l'identifiant BDM (« idbank »), ce que la série mesure et
#: pourquoi elle est retenue. Une série ne figure ici que si le vérificateur
#: s'en sert : ce manifeste et lui doivent rester en correspondance exacte.
SERIES: dict[str, dict[str, str]] = {
    # -- indice des prix ----------------------------------------------------
    "ipc_base_1980": {
        "idbank": "000008965",
        "role": "Indice annuel des prix, ensemble, base 100 en 1980, 1949-1992",
        "note": "seule série annuelle publiée qui couvre les Trente Glorieuses",
    },
    "ipc_base_2015": {
        "idbank": "001764363",
        "role": "Indice annuel des prix, ensemble des ménages, France, base 2015, 1990-2025",
        "note": "prend le relais de la base 1980 ; chaînage sur l'année 1990",
    },
    "coefficient_prix_1901": {
        "idbank": "010605954",
        "role": "Coefficient de transformation du franc et de l'euro, base 2015, 1901-",
        "note": "SEULE série de l'INSEE qui remonte avant 1949. Elle sert de "
                "contrôle de vraisemblance aux vingt années d'inflation "
                "reconstituées de 1930 à 1949, et non de source : publiée à "
                "deux décimales sur une base 100 en 2015, elle vaut 0,20 en "
                "1935, si bien qu'un centième y pèse cinq points de taux — "
                "assez pour valider une dérive cumulée, pas pour en tirer des "
                "variations annuelles",
    },
    # -- salaire moyen par tête --------------------------------------------
    "salaires_bruts": {
        "idbank": "011785411",
        "role": "Salaires et traitements bruts (D11), total des branches, euros courants, 1949-",
        "note": "numérateur du salaire moyen par tête",
    },
    "emploi_salarie": {
        "idbank": "011793486",
        "role": "Emploi salarié intérieur total, en personnes physiques, milliers, 1949-",
        "note": "dénominateur du salaire moyen par tête",
    },
    # -- productivité -------------------------------------------------------
    "valeur_ajoutee_volume": {
        "idbank": "011785223",
        "role": "Valeur ajoutée brute, total des branches, volume aux prix chaînés de 2020, 1949-",
        "note": "numérateur de la productivité par tête",
    },
    "emploi_total": {
        "idbank": "011793334",
        "role": "Emploi intérieur total, en personnes physiques, milliers, 1949-",
        "note": "dénominateur de la productivité par tête",
    },
    "productivite_horaire": {
        "idbank": "011793337",
        "role": "Taux de croissance de la productivité horaire, total des branches, 1950-",
        "note": "variante horaire, pour le paramètre indicateur_productivite",
    },
    # -- espérances de vie --------------------------------------------------
    "e0_H": {"idbank": "001686946", "role": "Espérance de vie à la naissance, hommes, France métropolitaine, 1946-"},
    "e0_F": {"idbank": "001686951", "role": "Espérance de vie à la naissance, femmes, France métropolitaine, 1946-"},
    "e60_H": {"idbank": "001686950", "role": "Espérance de vie à 60 ans, hommes, France métropolitaine, 1946-"},
    "e60_F": {"idbank": "001686955", "role": "Espérance de vie à 60 ans, femmes, France métropolitaine, 1946-"},
    # -- plafond de la Sécurité sociale -------------------------------------
    "plafond_mensuel": {
        "idbank": "000822494",
        "role": "Montant du plafond mensuel de la Sécurité sociale, 2001-",
        "note": "la série ne remonte pas avant 2001 : le plafond ancien reste à saisir",
    },
    # -- valeur de service du point des complémentaires du privé ------------
    # Mensuelles, et l'INSEE n'est pas le producteur de ces barèmes : elles ne
    # servent donc pas de source mais de contre-épreuve à la transcription
    # d'OpenFisca, seule à couvrir l'avant-2001. Deux transcriptions publiques
    # qui concordent valent mieux qu'une, à défaut de la caisse elle-même.
    "point_arrco": {
        "idbank": "000849395",
        "role": "Valeur du point Arrco, mensuel, 2001-2018 (série arrêtée à la fusion)",
        "note": "s'arrête en décembre 2018, quand l'Arrco disparaît dans l'Agirc-Arrco",
    },
    "point_agirc": {
        "idbank": "000822495",
        "role": "Valeur du point Agirc, mensuel, 2001-2018 (série arrêtée à la fusion)",
        "note": "même arrêt que l'Arrco, et même raison",
    },
    "point_agirc_arrco": {
        "idbank": "010593202",
        "role": "Valeur de service du point Agirc-Arrco, mensuel, 2019-",
        "note": "prend le relais des deux précédentes ; seule série à courir après 2024",
    },
}


def recuperer(idbank: str, timeout: int = 180) -> dict:
    """Télécharge une série et renvoie ses observations et ses métadonnées."""
    demande = urllib.request.Request(f"{BASE}/{idbank}", headers=ENTETES)
    with urllib.request.urlopen(demande, timeout=timeout) as reponse:
        racine = ET.fromstring(reponse.read())

    for serie in racine.iter():
        if not serie.tag.endswith("Series"):
            continue
        observations = {}
        for observation in serie:
            if not observation.tag.endswith("Obs"):
                continue
            valeur = observation.attrib.get("OBS_VALUE", "")
            if valeur in ("", "NaN"):
                continue
            observations[observation.attrib["TIME_PERIOD"]] = float(valeur)
        return {
            "idbank": idbank,
            "titre": serie.attrib.get("TITLE_FR", ""),
            "frequence": serie.attrib.get("FREQ", ""),
            "derniere_mise_a_jour": serie.attrib.get("LAST_UPDATE", ""),
            "observations": dict(sorted(observations.items())),
        }
    raise ValueError(f"aucune série dans la réponse pour l'idbank {idbank}")


def main(argv: list[str] | None = None) -> int:
    analyseur = argparse.ArgumentParser(description=__doc__,
                                        formatter_class=argparse.RawDescriptionHelpFormatter)
    analyseur.add_argument("--liste", action="store_true",
                           help="affiche le manifeste des séries et sort")
    analyseur.add_argument("--serie", action="append", default=[], metavar="NOM",
                           help="ne récupérer que cette série, répétable")
    analyseur.add_argument("--sortie", default=str(SORTIE),
                           help=f"fichier de destination (défaut : {SORTIE})")
    arguments = analyseur.parse_args(argv)

    if arguments.liste:
        for nom, fiche in SERIES.items():
            print(f"{nom:<24} {fiche['idbank']}  {fiche['role']}")
        return 0

    demandees = arguments.serie or list(SERIES)
    inconnues = [nom for nom in demandees if nom not in SERIES]
    if inconnues:
        analyseur.error(f"série inconnue : {', '.join(inconnues)}")

    recuperees: dict[str, dict] = {}
    for nom in demandees:
        fiche = SERIES[nom]
        try:
            serie = recuperer(fiche["idbank"])
        except (urllib.error.HTTPError, urllib.error.URLError) as erreur:
            print(f"ÉCHEC   {nom} ({fiche['idbank']}) : {erreur}", file=sys.stderr)
            return 1
        serie["role"] = fiche["role"]
        recuperees[nom] = serie
        periodes = list(serie["observations"])
        print(f"OK      {nom:<24} {len(periodes):>4} observations "
              f"{periodes[0]}-{periodes[-1]}")

    chemin = Path(arguments.sortie)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    charge = {"source": BASE, "recupere_le": date.today().isoformat(), "series": recuperees}
    if chemin.exists() and demandees != list(SERIES):
        # Récupération partielle : on complète le fichier au lieu de l'amputer.
        ancien = json.loads(chemin.read_text(encoding="utf-8"))
        charge["series"] = {**ancien.get("series", {}), **recuperees}
    chemin.write_text(json.dumps(charge, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{len(charge['series'])} séries écrites dans {chemin}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
