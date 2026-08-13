#!/usr/bin/env python3
"""Récupération du plafond de la Sécurité sociale ancien, depuis OpenFisca-France.

    python scripts/fetch/openfisca_plafond.py

Le plafond borne l'assiette du régime général et sépare les tranches des régimes
complémentaires : une erreur de plafond déplace mécaniquement la frontière entre
droits de base et droits complémentaires, sur toute une carrière.

L'INSEE ne publie le plafond mensuel qu'à partir de 2001 et l'Urssaf ne diffuse
aucun historique en accès ouvert. La seule série machine des plafonds anciens
est celle d'**OpenFisca-France**, le modèle socio-fiscal de référence maintenu
par l'administration française : un fichier YAML daté décret par décret, qui
remonte à juillet 1930 et cite ses références au *Journal officiel*.

Statut de fiabilité — c'est le point important. OpenFisca n'est pas le
producteur de la donnée mais une **transcription tierce** du *Journal officiel*.
Les valeurs qui en viennent sont donc versées au niveau ``haute``, jamais
``certifiee`` : elles sont publiées et reprises automatiquement, pas confrontées
à la source primaire. Deux recoupements indépendants les corroborent, et
``scripts/verifier_donnees.py`` les refait à chaque exécution :

* sur 2002-2026, elles coïncident avec le plafond mensuel publié par l'INSEE ;
* sur 1997-2001, elles coïncident avec les valeurs saisies à la main dans ce
  dépôt — décalées d'un an, erreur que ce recoupement a précisément révélée.

Unités. Les valeurs sont en anciens francs jusqu'en 1959, en nouveaux francs de
1960 à 2001, en euros ensuite. La conversion est arithmétique (÷100 puis
÷6,55957), sans revalorisation.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

URL = ("https://raw.githubusercontent.com/openfisca/openfisca-france/master/"
       "openfisca_france/parameters/prelevements_sociaux/pss/"
       "plafond_securite_sociale_annuel.yaml")
SORTIE = Path("data/brut/openfisca_plafond.json")

#: Passage aux nouveaux francs (1er janvier 1960) et à l'euro (1er janvier 2002).
ANNEE_NOUVEAU_FRANC = 1960
ANNEE_EURO = 2002
TAUX_FRANC_EURO = 6.55957


def _analyser(texte: str) -> dict[str, float]:
    """Lit le YAML sans dépendre de son ordonnancement.

    Le fichier est un dictionnaire ``values: {date: {value: montant}}``. On
    n'utilise PyYAML que pour lire, jamais pour interpréter les dates : elles
    sont converties en chaînes, l'ordre chronologique étant tout ce qui compte.
    """
    import yaml

    charge = yaml.safe_load(texte)
    valeurs = {}
    for cle, contenu in (charge.get("values") or {}).items():
        montant = (contenu or {}).get("value")
        if montant is None:
            continue
        valeurs[str(cle)] = float(montant)
    return dict(sorted(valeurs.items()))


def en_euros(montant: float, annee: int) -> float:
    if annee >= ANNEE_EURO:
        return montant
    if annee >= ANNEE_NOUVEAU_FRANC:
        return montant / TAUX_FRANC_EURO
    return montant / 100.0 / TAUX_FRANC_EURO


def annualiser(valeurs: dict[str, float]) -> dict[int, float]:
    """Plafond annuel en euros, au prorata des mois d'application.

    Le fichier date chaque revalorisation au jour près. Le plafond d'une année
    n'est donc pas la valeur de janvier lorsqu'un décret est intervenu en cours
    d'année : c'est la somme des plafonds mensuels, soit la moyenne des taux
    annuels pondérée par leur durée d'application. Une dizaine d'années sont
    concernées, toutes avant 1962.
    """
    dates = sorted(valeurs)
    if not dates:
        return {}
    premiere, derniere = int(dates[0][:4]), int(dates[-1][:4])

    resultat: dict[int, float] = {}
    for annee in range(premiere, derniere + 1):
        total = 0.0
        for mois in range(1, 13):
            debut_mois = f"{annee}-{mois:02d}-31"
            applicables = [d for d in dates if d <= debut_mois]
            if not applicables:
                break
            total += en_euros(valeurs[applicables[-1]], annee) / 12.0
        else:
            resultat[annee] = total
    return resultat


def main() -> int:
    try:
        demande = urllib.request.Request(
            URL, headers={"User-Agent": "retraite-notionnelle/0.1"}
        )
        with urllib.request.urlopen(demande, timeout=120) as reponse:
            texte = reponse.read().decode("utf-8")
    except (urllib.error.HTTPError, urllib.error.URLError) as erreur:
        print(f"OpenFisca-France indisponible : {erreur}", file=sys.stderr)
        return 1

    brut = _analyser(texte)
    annuel = annualiser(brut)
    changements = {annee: sum(1 for d in brut if int(d[:4]) == annee) for annee in annuel}
    multiples = sorted(a for a, n in changements.items() if n > 1)

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(
        json.dumps({
            "source": URL,
            "recupere_le": date.today().isoformat(),
            "unite": "euros, converti arithmétiquement depuis les francs",
            "annees_a_plusieurs_revalorisations": multiples,
            "brut": brut,
            "serie": {str(a): round(v, 2) for a, v in sorted(annuel.items())},
        }, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    annees = sorted(annuel)
    print(f"{len(brut)} dates de revalorisation, {len(annuel)} plafonds annuels")
    print(f"Couverture {annees[0]}-{annees[-1]}")
    print(f"Années à plusieurs revalorisations, calculées au prorata : "
          f"{', '.join(map(str, multiples)) or 'aucune'}")
    print(f"Écrit dans {SORTIE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
