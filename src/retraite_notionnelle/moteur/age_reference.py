"""Âge de référence à cliquet et écart d'anticipation.

Règle demandée : *chaque fois que l'âge de départ a été abaissé, la pension doit
être calculée comme si l'assuré était parti trop tôt*. Concrètement :

* l'âge de référence ne redescend jamais — c'est un **cliquet** sur l'âge du
  taux plein du régime général ;
* l'abaissement de 65 à 60 ans par l'ordonnance du 26 mars 1982 ne fait donc
  pas baisser l'âge de référence : une liquidation à 60 ans en 1990 est traitée
  comme une anticipation de 5 ans ;
* un régime spécial ouvrant à 50 ou 55 ans est mesuré au même étalon : un
  départ d'agent de conduite SNCF à 50 ans en 1990 est une anticipation de
  15 ans.

**Comment cet écart pèse sur la pension.** Dans un système en comptes
notionnels, il n'est pas nécessaire — et il serait faux — d'ajouter une décote
forfaitaire par-dessus. L'anticipation est déjà sanctionnée deux fois,
mécaniquement :

1. les années non travaillées n'ont pas produit de cotisations, donc pas de
   capital notionnel ;
2. la rente est servie plus longtemps, donc le coefficient de conversion est
   plus élevé et la pension annuelle plus faible.

Le mode :data:`ModeCoefficientEcart.ACTUARIEL` (défaut) s'en tient à cette
double sanction. Le mode ``EXPLICITE`` ajoute une décote supplémentaire par
année d'écart, pour qui veut une pénalité affichée en plus de la pénalité
actuarielle ; c'est alors une double peine assumée, et le rapport de simulation
le signale.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from ..config import ModeAgeReference, Parametres
from ..donnees.chargement import Fiabilite, SerieAnnuelle, charger_serie_annuelle
from ..donnees.mortalite import DonneesMortalite


class ModeCoefficientEcart(str, Enum):
    #: L'écart n'est pas sanctionné en plus : le diviseur actuariel et
    #: l'absence de cotisations font déjà tout le travail.
    ACTUARIEL = "actuariel"
    #: Décote explicite supplémentaire par année d'anticipation.
    EXPLICITE = "explicite"


@dataclass(frozen=True)
class EcartAge:
    """Position d'une liquidation par rapport à l'âge de référence."""

    age_liquidation: float
    age_reference: float
    annee_liquidation: int

    @property
    def ecart(self) -> float:
        """Positif = départ anticipé, négatif = départ différé."""
        return self.age_reference - self.age_liquidation

    @property
    def anticipe(self) -> bool:
        return self.ecart > 0

    def __str__(self) -> str:  # pragma: no cover - affichage
        if abs(self.ecart) < 1e-9:
            return f"liquidation à l'âge de référence ({self.age_reference:.2f} ans)"
        sens = "anticipation" if self.anticipe else "report"
        return (
            f"{sens} de {abs(self.ecart):.2f} an(s) "
            f"(liquidation à {self.age_liquidation:.2f}, référence {self.age_reference:.2f})"
        )


class AgeReference:
    """Série d'âges de référence, construite à cliquet."""

    def __init__(self, racine: Path, parametres: Parametres,
                 mortalite: DonneesMortalite | None = None) -> None:
        self.parametres = parametres
        self.mortalite = mortalite
        chemin = racine / "reference" / "legislation" / "ages_reference.csv"
        self._legal = _charger_ages(chemin, "age_taux_plein_legal")
        self._cliquet = _charger_ages(chemin, "age_reference")

    def age(self, annee: int) -> float:
        """Âge de référence applicable à une liquidation de l'année ``annee``."""
        mode = self.parametres.mode_age_reference

        if mode is ModeAgeReference.LEGAL_SANS_CLIQUET:
            return self._legal(annee)

        base = self._applique_cliquet(annee)

        if mode is ModeAgeReference.CLIQUET_PUIS_ESPERANCE_VIE and annee > self.parametres.annee_bascule:
            return max(base, self._age_indexe_esperance_vie(annee))
        return base

    def _applique_cliquet(self, annee: int) -> float:
        """Maximum des âges de taux plein observés jusqu'à l'année considérée.

        On ne se contente pas de lire la colonne pré-calculée : on la recalcule,
        de sorte qu'une correction du fichier législatif se propage sans risque
        d'incohérence entre les deux colonnes.
        """
        debut = min(self._legal.premiere_annee, annee)
        return max(self._legal(a) for a in range(debut, annee + 1))

    def _age_indexe_esperance_vie(self, annee: int) -> float:
        """Âge stabilisant le ratio durée de retraite / durée de carrière.

        Recherche le plus petit âge ``a`` tel que l'espérance de vie résiduelle
        à ``a``, rapportée à la durée de carrière depuis 22 ans, ne dépasse pas
        le ratio cible.
        """
        if self.mortalite is None:
            return self._applique_cliquet(annee)
        ancrage = self._applique_cliquet(self.parametres.annee_bascule)
        cible = self.parametres.ratio_cible_retraite_carriere
        age = ancrage
        while age < 75:
            esperance = self.mortalite.esperance_residuelle(age, annee)
            carriere = age - 22.0
            if carriere > 0 and esperance / carriere <= cible:
                return age
            age += 0.25
        return 75.0

    def ecart(self, age_liquidation: float, annee_liquidation: int) -> EcartAge:
        return EcartAge(
            age_liquidation=age_liquidation,
            age_reference=self.age(annee_liquidation),
            annee_liquidation=annee_liquidation,
        )

    def fiabilite(self, annee: int) -> Fiabilite:
        return self._legal.fiabilite(annee)


def _charger_ages(chemin: Path, colonne: str) -> SerieAnnuelle:
    """Charge une colonne d'âges du fichier législatif.

    Le fichier ne comporte pas de colonne ``fiabilite`` : les âges légaux sont
    des données de droit, lues dans les textes. On les qualifie donc de
    ``haute`` — « certifiée » reste réservé à ce qui a été recontrôlé
    automatiquement contre la source.
    """
    import csv

    valeurs = {}
    with chemin.open(encoding="utf-8") as flux:
        lignes = (l for l in flux if not l.lstrip().startswith("#"))
        for ligne in csv.DictReader(lignes):
            annee = int(ligne["annee"])
            valeurs[annee] = _valeur(annee, float(ligne[colonne]))
    return SerieAnnuelle(valeurs, f"{colonne}", interpolation="escalier")


def _valeur(annee: int, valeur: float):
    from ..donnees.chargement import ValeurAnnuelle

    return ValeurAnnuelle(annee=annee, valeur=valeur, fiabilite=Fiabilite.HAUTE)
