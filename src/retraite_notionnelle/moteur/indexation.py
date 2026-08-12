"""Règle d'indexation : le « triple lock inversé ».

Le triple lock britannique retient le MAXIMUM entre l'inflation, la croissance
des salaires et un plancher de 2,5 %. La règle demandée ici en est l'exact
opposé : on retient le MINIMUM entre l'inflation, la croissance du salaire moyen
et la productivité réelle.

Deux conséquences, à garder à l'esprit en lisant les résultats :

1. **C'est une règle d'austérité structurelle.** Le minimum de trois séries est
   presque toujours inférieur à chacune d'elles. Sur 1941-2025, l'écart cumulé
   avec une indexation sur les prix se compte en ordres de grandeur.

2. **Elle mélange des taux nominaux et un taux réel.** L'inflation et le salaire
   moyen sont nominaux, la productivité est réelle. Dans les années 1940 et
   1970, la productivité réelle (1 à 5 %) est très inférieure à l'inflation
   (10 à 50 %) : c'est elle qui l'emporte, et la valeur réelle des comptes
   s'effondre. C'est bien ce que produit la règle telle qu'énoncée ;
   :data:`ModeIndexation.TRIPLE_LOCK_INVERSE_NOMINAL` permet de mesurer ce que
   coûte précisément le mélange.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import ModeIndexation, Parametres
from ..donnees.chargement import Fiabilite
from ..donnees.macro import DonneesMacro


@dataclass(frozen=True)
class TauxIndexation:
    """Taux retenu pour une année, avec le terme qui l'a emporté."""

    annee: int
    taux: float
    terme_retenu: str
    inflation: float
    salaire_moyen: float
    productivite: float
    fiabilite: Fiabilite

    @property
    def taux_reel(self) -> float:
        """Taux d'indexation net d'inflation."""
        return (1 + self.taux) / (1 + self.inflation) - 1


class Indexation:
    """Calcule et compose les taux d'indexation annuels."""

    def __init__(self, macro: DonneesMacro, parametres: Parametres) -> None:
        self.macro = macro
        self.parametres = parametres

    def taux(self, annee: int) -> TauxIndexation:
        inflation = self.macro.inflation(annee)
        salaire = self.macro.salaire_moyen(annee)
        productivite = self.macro.productivite(annee)
        mode = self.parametres.mode_indexation

        if mode is ModeIndexation.TRIPLE_LOCK_INVERSE:
            candidats = {
                "inflation": inflation,
                "salaire_moyen": salaire,
                "productivite_reelle": productivite,
            }
        elif mode is ModeIndexation.TRIPLE_LOCK_INVERSE_NOMINAL:
            candidats = {
                "inflation": inflation,
                "salaire_moyen": salaire,
                "productivite_nominale": self.macro.productivite_nominale(annee),
            }
        elif mode is ModeIndexation.PRIX:
            candidats = {"inflation": inflation}
        elif mode is ModeIndexation.SALAIRES:
            candidats = {"salaire_moyen": salaire}
        else:  # pragma: no cover - garde-fou
            raise ValueError(f"mode d'indexation non géré : {mode}")

        terme, taux = min(candidats.items(), key=lambda couple: couple[1])

        plancher = self.parametres.plancher_indexation
        if plancher is not None and taux < plancher:
            taux, terme = plancher, "plancher"

        fiabilite = min(
            self.macro.inflation.fiabilite(annee),
            self.macro.salaire_moyen.fiabilite(annee),
            self.macro.productivite.fiabilite(annee),
        )
        return TauxIndexation(
            annee=annee,
            taux=taux,
            terme_retenu=terme,
            inflation=inflation,
            salaire_moyen=salaire,
            productivite=productivite,
            fiabilite=fiabilite,
        )

    def coefficient(self, annee_depart: int, annee_arrivee: int) -> float:
        """Coefficient de revalorisation cumulée entre deux années.

        Convention : une cotisation versée en ``annee_depart`` est revalorisée
        à partir de l'année SUIVANTE. Elle n'est pas revalorisée l'année même de
        son versement, ni l'année de la liquidation — sans quoi on offrirait une
        année de rendement gratuite.
        """
        if annee_arrivee <= annee_depart:
            return 1.0
        coefficient = 1.0
        for annee in range(annee_depart + 1, annee_arrivee + 1):
            coefficient *= 1 + self.taux(annee).taux
        return coefficient

    def historique(self, debut: int, fin: int) -> list[TauxIndexation]:
        return [self.taux(annee) for annee in range(debut, fin + 1)]

    def fiabilite_sur(self, debut: int, fin: int) -> Fiabilite:
        return min((self.taux(a).fiabilite for a in range(debut, fin + 1)),
                   default=Fiabilite.ESTIMEE)
