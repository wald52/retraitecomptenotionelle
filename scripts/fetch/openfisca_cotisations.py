#!/usr/bin/env python3
"""Récupération des taux de cotisation vieillesse du régime général.

    python scripts/fetch/openfisca_cotisations.py

Le taux de cotisation est ce qui alimente le compte notionnel : c'est, avec le
salaire, la seule grandeur qui détermine le capital accumulé. Une erreur de deux
points sur quarante ans déplace la pension d'autant.

Les taux historiques ne sont publiés dans aucune série statistique : ils vivent
dans des décrets. La seule transcription machine complète est celle
d'**OpenFisca-France**, le modèle socio-fiscal de référence maintenu par
l'administration, qui date chaque taux au jour de son entrée en vigueur depuis
octobre 1967 et cite ses références.

Quatre taux sont récupérés, dont la somme donne le taux total pesant sur le
salaire — c'est cette somme que le modèle appelle ``taux_cotisation_retraite`` :

* part salariale et part patronale **sous plafond** (depuis 1967) ;
* part salariale et part patronale **déplafonnées** (depuis 1991).

Statut de fiabilité. OpenFisca est une transcription tierce, pas le producteur :
ces taux ne sont pas versés automatiquement dans les fiches de régime et ne
peuvent pas y porter le niveau ``certifiee``. ``scripts/verifier_donnees.py`` les
confronte aux valeurs saisies et signale les écarts ; la correction d'une fiche
reste une décision, prise à la main, tracée dans ses notes.

Avant octobre 1967, rien : les taux de 1930 à 1967 restent saisis depuis les
ordonnances de 1945 et leurs modificatifs.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

RACINE = ("https://raw.githubusercontent.com/openfisca/openfisca-france/master/"
          "openfisca_france/parameters/prelevements_sociaux/"
          "cotisations_securite_sociale_regime_general/cnav")
COMPOSANTES = {
    "salarie_plafonnee": "salarie/vieillesse_plafonnee.yaml",
    "employeur_plafonnee": "employeur/vieillesse_plafonnee.yaml",
    "salarie_deplafonnee": "salarie/vieillesse_deplafonnee.yaml",
    "employeur_deplafonnee": "employeur/vieillesse_deplafonnee.yaml",
}
SORTIE = Path("data/brut/openfisca_cotisations.json")
PREMIERE_ANNEE = 1967


def _taux(texte: str) -> dict[str, float]:
    """Extrait le barème d'un fichier OpenFisca : date d'effet -> taux.

    Les fichiers décrivent un barème à une seule tranche ; seul son taux nous
    intéresse, le seuil valant zéro. Une valeur nulle signifie « cotisation non
    encore instituée » et vaut donc zéro.
    """
    import yaml

    charge = yaml.safe_load(texte)
    bareme = charge["brackets"][0]["rate"]
    return {
        str(cle): float(contenu["value"] or 0.0)
        for cle, contenu in bareme.items()
    }


def _en_vigueur(bareme: dict[str, float], annee: int) -> float:
    """Taux applicable au 1er janvier de l'année.

    Les revalorisations de milieu d'année sont ignorées : le modèle raisonne en
    années pleines, et retenir le taux du 1er janvier est le choix le plus
    lisible — il est explicité ici plutôt que caché dans un calcul.
    """
    anterieures = [cle for cle in sorted(bareme) if cle[:4] <= str(annee)]
    return bareme[anterieures[-1]] if anterieures else 0.0


def main() -> int:
    baremes: dict[str, dict[str, float]] = {}
    for nom, chemin in COMPOSANTES.items():
        try:
            demande = urllib.request.Request(
                f"{RACINE}/{chemin}", headers={"User-Agent": "retraite-notionnelle/0.1"}
            )
            with urllib.request.urlopen(demande, timeout=120) as reponse:
                baremes[nom] = _taux(reponse.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError) as erreur:
            print(f"ÉCHEC   {nom} : {erreur}", file=sys.stderr)
            return 1
        print(f"OK      {nom:<24} {len(baremes[nom])} dates d'effet")

    derniere = max(int(cle[:4]) for bareme in baremes.values() for cle in bareme)
    serie = {}
    for annee in range(PREMIERE_ANNEE, derniere + 1):
        parts = {nom: _en_vigueur(bareme, annee) for nom, bareme in baremes.items()}
        serie[str(annee)] = {
            **{nom: round(valeur, 5) for nom, valeur in parts.items()},
            "total": round(sum(parts.values()), 5),
        }

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(
        json.dumps({
            "source": RACINE,
            "recupere_le": date.today().isoformat(),
            "regime": "regime_general",
            "note": "taux au 1er janvier ; total = salarié + employeur, plafonné "
                    "et déplafonné",
            "baremes": baremes,
            "serie": serie,
        }, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"\n{len(serie)} années écrites dans {SORTIE} "
          f"({PREMIERE_ANNEE}-{derniere})")
    print(f"Taux total {PREMIERE_ANNEE} : {serie[str(PREMIERE_ANNEE)]['total']:.2%} ; "
          f"{derniere} : {serie[str(derniere)]['total']:.2%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
