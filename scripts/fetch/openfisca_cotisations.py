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

#: Racine des barèmes des régimes COMPLÉMENTAIRES du privé.
RACINE_COMPLEMENTAIRES = (
    "https://raw.githubusercontent.com/openfisca/openfisca-france/master/"
    "openfisca_france/parameters/prelevements_sociaux/"
    "regimes_complementaires_retraite_secteur_prive"
)

#: Barèmes à tranches des complémentaires : régime -> (fichier, première année).
#:
#: Ce sont les TAUX EFFECTIFS, c'est-à-dire ce qui est prélevé — taux d'appel
#: compris. Les fiches du dépôt portent la même grandeur, si bien que les deux
#: se comparent directement. L'Arrco distingue les entreprises créées avant et
#: après 1997, l'Agirc avant et après 1981 : on retient dans les deux cas le
#: barème de droit commun, celui des entreprises les plus récentes.
COMPLEMENTAIRES = {
    "arrco": ("arrco/taux_effectifs/entreprises_apres_01_01_1997/arrco.yaml", 1962),
    "agirc": ("agirc/taux_effectifs/entreprises_apres_01_01_1981/agirc.yaml", 1947),
    "agirc_arrco": ("agirc_arrco/tx_total.yaml", 2019),
}


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


def _tranches(texte: str) -> list[dict[str, float]]:
    """Barème à plusieurs tranches : une table date -> taux par tranche.

    Les complémentaires cotisent par tranche de salaire, et le taux de chacune
    a sa propre histoire — 2,5 % en 1962 sur la première tranche de l'Arrco,
    7,75 % en 2015 ; rien sur la seconde avant 1997, 20,25 % ensuite. Une
    valeur nulle signifie « tranche non cotisée cette année-là ».
    """
    import yaml

    charge = yaml.safe_load(texte)
    tranches = []
    for tranche in charge["brackets"]:
        tranches.append({
            str(cle): float((contenu or {}).get("value") or 0.0)
            for cle, contenu in tranche["rate"].items()
        })
    return tranches


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

    complementaires: dict[str, dict[str, dict[str, float]]] = {}
    for regime, (chemin, premiere) in COMPLEMENTAIRES.items():
        try:
            demande = urllib.request.Request(
                f"{RACINE_COMPLEMENTAIRES}/{chemin}",
                headers={"User-Agent": "retraite-notionnelle/0.1"},
            )
            with urllib.request.urlopen(demande, timeout=120) as reponse:
                tranches = _tranches(reponse.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError) as erreur:
            print(f"ÉCHEC   {regime} : {erreur}", file=sys.stderr)
            return 1
        annuel: dict[str, dict[str, float]] = {}
        for annee in range(premiere, derniere + 1):
            valeurs = {f"tranche_{i + 1}": round(_en_vigueur(t, annee), 5)
                       for i, t in enumerate(tranches)}
            if any(valeurs.values()):
                annuel[str(annee)] = valeurs
        complementaires[regime] = annuel
        print(f"OK      {regime:<24} {len(tranches)} tranches, "
              f"{len(annuel)} années")

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(
        json.dumps({
            "source": RACINE,
            "source_complementaires": RACINE_COMPLEMENTAIRES,
            "recupere_le": date.today().isoformat(),
            "regime": "regime_general",
            "note": "taux au 1er janvier ; total = salarié + employeur, plafonné "
                    "et déplafonné. Les complémentaires portent leurs TAUX "
                    "EFFECTIFS, taux d'appel compris, tranche par tranche : "
                    "c'est la même grandeur que celle des fiches du dépôt.",
            "baremes": baremes,
            "serie": serie,
            "complementaires": complementaires,
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
