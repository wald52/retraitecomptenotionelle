#!/usr/bin/env python3
"""Recontrôle des données de référence contre les sources téléchargées.

    python scripts/verifier_donnees.py
    python scripts/verifier_donnees.py --appliquer

C'est ce script — et lui seul — qui a le droit de faire passer une valeur au
niveau ``certifiee``. Une valeur n'est certifiée que si elle a été confrontée
avec succès à un fichier source présent dans ``data/brut/``. Sans fichier
source, le contrôle est signalé comme impossible, jamais comme réussi.

Contrôles actuellement implémentés :

* cohérence interne : continuité des séries, absence de trous, plages plausibles ;
* **vraisemblance** de l'inflation 1996-2025 face à l'IPCH d'Eurostat.

Ce second contrôle ne certifie rien, et c'est délibéré. L'IPCH harmonisé et
l'IPC national ne mesurent pas la même chose : traitement des remboursements de
santé, pondérations, champ des ménages. L'écart atteint couramment 0,5 à 0,8
point (2022 : 5,2 % pour l'IPC, 5,9 % pour l'IPCH), sans qu'aucune des deux
valeurs soit fausse. Confronter l'une à l'autre détecte une erreur de saisie
grossière ; cela ne remplace pas la source. Le seuil d'alerte est donc fixé à
1,5 point, et aucune valeur ne passe au niveau ``certifiee`` par ce biais.

**La certification reste à faire**, et suppose de déposer dans ``data/brut/``
les exports INSEE eux-mêmes. Aucune source automatisable n'existe à ce jour pour
l'inflation avant 1996, le salaire moyen, la productivité, le plafond et les
tables de mortalité. Voir docs/limites.md §1.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
DONNEES = RACINE / "data"

#: Seuil d'alerte du contrôle de vraisemblance IPC / IPCH, en points de taux.
#: Fixé à 1,5 point : au-dessous, l'écart s'explique par la différence de
#: méthode entre indice national et indice harmonisé ; au-dessus, il y a
#: vraisemblablement une erreur de saisie.
SEUIL_VRAISEMBLANCE = 0.015


def charger_csv(chemin: Path) -> list[dict[str, str]]:
    import csv

    with chemin.open(encoding="utf-8") as flux:
        lignes = (l for l in flux if not l.lstrip().startswith("#"))
        return list(csv.DictReader(lignes))


def controle_vraisemblance_inflation() -> list[str]:
    """Confronte la série d'inflation saisie à l'IPCH d'Eurostat.

    Contrôle de vraisemblance uniquement : les deux indices divergent
    légitimement, seul un écart important trahit une erreur de saisie.
    """
    source = DONNEES / "brut" / "eurostat_hicp.json"
    if not source.exists():
        return [
            f"IGNORÉ  vraisemblance inflation : {source} absent "
            "(lancer scripts/fetch/eurostat_hicp.py)"
        ]

    reference = {
        int(annee): valeur
        for annee, valeur in json.loads(source.read_text(encoding="utf-8"))["serie"].items()
    }
    saisi = {
        int(ligne["annee"]): float(ligne["variation"])
        for ligne in charger_csv(DONNEES / "reference" / "macro" / "ipc_annuel.csv")
    }

    communes = sorted(set(reference) & set(saisi))
    anomalies = []
    ecart_moyen = 0.0
    for annee in communes:
        ecart = reference[annee] - saisi[annee]
        ecart_moyen += ecart
        if abs(ecart) > SEUIL_VRAISEMBLANCE:
            anomalies.append(
                f"SUSPECT inflation {annee} : saisi {saisi[annee]:.2%}, "
                f"IPCH {reference[annee]:.2%} — écart de {abs(ecart):.2%}, "
                "trop élevé pour la seule différence IPC/IPCH"
            )
    if communes:
        ecart_moyen /= len(communes)

    messages = [
        f"OK      vraisemblance inflation : {len(communes)} années comparées à l'IPCH, "
        f"{len(anomalies)} au-delà du seuil de {SEUIL_VRAISEMBLANCE:.1%}",
        f"        écart moyen IPCH − IPC : {ecart_moyen:+.2%} "
        "(positif attendu, l'IPCH est structurellement au-dessus)",
    ]
    return messages + anomalies


def controle_coherence_interne() -> list[str]:
    """Vérifications qui ne dépendent d'aucune source externe."""
    messages: list[str] = []

    fichiers = {
        "ipc_annuel.csv": ("variation", -0.15, 0.70),
        "salaire_moyen.csv": ("variation_nominale", -0.15, 0.70),
        "productivite.csv": ("variation_reelle", -0.15, 0.20),
    }
    for nom, (colonne, mini, maxi) in fichiers.items():
        lignes = charger_csv(DONNEES / "reference" / "macro" / nom)
        annees = [int(l["annee"]) for l in lignes]
        trous = set(range(min(annees), max(annees) + 1)) - set(annees)
        if trous:
            messages.append(f"TROU    {nom} : années manquantes {sorted(trous)}")
        for ligne in lignes:
            valeur = float(ligne[colonne])
            if not mini <= valeur <= maxi:
                messages.append(
                    f"SUSPECT {nom} {ligne['annee']} : {valeur:.3%} hors plage plausible"
                )
        messages.append(f"OK      {nom} : {len(lignes)} années, {min(annees)}-{max(annees)}")

    plafond = charger_csv(DONNEES / "reference" / "macro" / "plafond_securite_sociale.csv")
    precedent = None
    for ligne in plafond:
        valeur = float(ligne["pass_eur"])
        if precedent is not None and valeur < precedent:
            messages.append(
                f"SUSPECT plafond {ligne['annee']} : recul de {precedent:.0f} à {valeur:.0f} €"
            )
        precedent = valeur
    messages.append(f"OK      plafond : {len(plafond)} années")

    return messages


def main(argv: list[str] | None = None) -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    arguments = analyseur.parse_args(argv)

    messages = controle_coherence_interne()
    messages.extend(controle_vraisemblance_inflation())

    for message in messages:
        print(message)

    anomalies = [m for m in messages if m.startswith(("ÉCART", "TROU", "SUSPECT"))]

    print(
        "\nAucune valeur n'a été certifiée : la certification exige un export de "
        "la source elle-même dans data/brut/, que les portails de diffusion ne "
        "permettent pas encore d'automatiser pour les séries longues. "
        "Voir docs/limites.md §1."
    )

    if anomalies:
        print(f"\n{len(anomalies)} anomalie(s) à examiner", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
