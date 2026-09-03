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

Le minimum n'est pas la seule statistique possible sur ces trois séries. Deux
variantes prennent les mêmes trois termes et n'en changent que l'agrégation :

* :data:`ModeIndexation.MEDIANE_TROIS_TAUX` retient celui du milieu. Le taux
  reste un taux observé, et la règle cesse d'être commandée par la série la plus
  basse : c'est la variante « sévère mais robuste ».
* :data:`ModeIndexation.MOYENNE_TROIS_TAUX` retient la moyenne arithmétique.
  Elle n'est plus austère du tout, et n'est le taux de rien : c'est la variante
  la plus fragile économiquement, fournie pour être mesurée.

Ces deux variantes gardent le mélange nominal/réel de la règle littérale — c'est
le prix à payer pour que la comparaison porte sur la seule statistique.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import ModeIndexation, Parametres
from ..donnees.chargement import Fiabilite
from ..donnees.macro import DonneesMacro


#: Modes qui comparent les trois taux tels qu'ils sont publiés — deux nominaux,
#: un réel. Ils ne diffèrent que par la statistique retenue, pas par les termes.
_MODES_TROIS_TAUX_REELS = frozenset({
    ModeIndexation.TRIPLE_LOCK_INVERSE,
    ModeIndexation.MEDIANE_TROIS_TAUX,
    ModeIndexation.MOYENNE_TROIS_TAUX,
})


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

        if mode in _MODES_TROIS_TAUX_REELS:
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
        elif mode is ModeIndexation.REVALORISATION_PORTEE_AU_COMPTE:
            # Le taux annuel des arrêtés, lu comme le scénario 1 le lit : le
            # rapport de deux années consécutives dans la colonne publiée. Le
            # produit de ces taux annuels dérive de 0,04 % sur 1941-2025 par
            # rapport au coefficient lu directement de bout en bout — la caisse
            # arrondit ses colonnes à trois décimales. C'est le prix de
            # l'uniformité : ce mode se compose comme tous les autres.
            candidats = {
                "revalorisation_legale":
                    self.macro.coefficient_revalorisation_portee_au_compte(
                        annee - 1, annee
                    ) - 1,
            }
        elif mode is ModeIndexation.PRIX:
            candidats = {"inflation": inflation}
        elif mode is ModeIndexation.SALAIRES:
            candidats = {"salaire_moyen": salaire}
        else:  # pragma: no cover - garde-fou
            raise ValueError(f"mode d'indexation non géré : {mode}")

        # Le mode choisit la STATISTIQUE appliquée aux candidats ; les candidats
        # eux-mêmes viennent d'être fixés au-dessus. Minimum par défaut — la
        # règle demandée —, médiane ou moyenne pour les variantes. Les trois
        # coïncident quand il n'y a qu'un candidat (PRIX, SALAIRES).
        if mode is ModeIndexation.MOYENNE_TROIS_TAUX:
            # La moyenne n'est le taux d'aucun des trois : elle n'a pas de terme
            # retenu, et c'est ce que le libellé dit.
            terme = "moyenne"
            taux = sum(candidats.values()) / len(candidats)
        elif mode is ModeIndexation.MEDIANE_TROIS_TAUX:
            # Nombre impair de candidats (trois, ou un) : la médiane est un
            # candidat, pas une interpolation, et le terme du milieu est nommé.
            classes = sorted(candidats.items(), key=lambda couple: couple[1])
            terme, taux = classes[len(classes) // 2]
        else:
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
        à partir de l'année SUIVANTE et **jusqu'à l'année d'arrivée incluse**.
        Elle n'est donc pas revalorisée l'année même de son versement — sans
        quoi on offrirait une année de rendement gratuite — mais elle l'est
        l'année de la liquidation, qui est celle où le compte est arrêté.

        Ce docstring annonçait l'inverse pour l'année de liquidation, alors que
        la boucle ci-dessous l'a toujours comptée. L'écart n'est pas nul : il
        vaut un an de taux d'indexation sur la totalité du capital, soit 1,0 %
        en 2029. C'est la convention du code qui est retenue — le compte est
        arrêté à la fin de l'année de liquidation, pas à son début —, et c'est
        le texte qui a été corrigé.
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
