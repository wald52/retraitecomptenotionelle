"""Coefficient de conversion du capital notionnel en rente viagère.

La pension annuelle vaut ``capital_notionnel / diviseur``. Le diviseur est
l'espérance de vie résiduelle actualisée :

.. math::

   G(a, L) = \\sum_{t \\ge 0} \\; {}_t p_a \\; (1 + \\nu)^{-t}

où :math:`{}_t p_a` est la probabilité, pour un liquidant d'âge :math:`a` en
année :math:`L`, d'être encore en vie :math:`t` années plus tard, lue sur une
table de **génération**, et :math:`\\nu` le taux de préfinancement.

**Pourquoi :math:`\\nu = 0` par défaut.** Dans un système notionnel, la rente
est actualisée au taux auquel elle sera ensuite revalorisée. Ici les deux sont
le même taux — le triple lock inversé — et se compensent exactement. Le diviseur
se réduit alors à l'espérance de vie résiduelle, ce qui rend le résultat
directement lisible : « votre capital notionnel divisé par le nombre d'années
que vous êtes statistiquement appelé à vivre ». Donner à :math:`\\nu` une valeur
positive revient à verser davantage au début et moins ensuite, à espérance de
coût inchangée.

**Ce que le diviseur sanctionne tout seul.** Partir cinq ans plus tôt augmente
le diviseur d'environ 4 à 5 années d'espérance de vie, soit une pension annuelle
inférieure de 15 à 20 % — avant même de compter les cinq années de cotisations
manquantes. C'est ce mécanisme qui traduit la règle « parti trop tôt, pension
réduite » sans avoir besoin d'une décote administrative.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import Parametres, TableConversion
from ..donnees.chargement import Fiabilite
from ..donnees.mortalite import DonneesMortalite


@dataclass(frozen=True)
class CoefficientConversion:
    """Diviseur annuitaire et éléments qui l'expliquent."""

    diviseur: float
    age_liquidation: float
    annee_liquidation: int
    esperance_residuelle: float
    table: str
    taux_anticipe: float
    fiabilite: Fiabilite

    @property
    def taux_de_rente(self) -> float:
        """Fraction du capital notionnel servie chaque année."""
        return 1.0 / self.diviseur if self.diviseur else 0.0


class Convertisseur:
    """Produit les coefficients de conversion."""

    def __init__(self, mortalite: DonneesMortalite, parametres: Parametres) -> None:
        self.mortalite = mortalite
        self.parametres = parametres

    def _sexe_table(self, sexe: str | None) -> str | None:
        if self.parametres.table_conversion is TableConversion.UNISEXE:
            return None
        if sexe is None:
            raise ValueError(
                "table de conversion par sexe demandée mais sexe non renseigné"
            )
        return sexe

    def coefficient(self, age_liquidation: float, annee_liquidation: int,
                    sexe: str | None = None) -> CoefficientConversion:
        sexe_table = self._sexe_table(sexe)
        generation = self.parametres.table_generation
        courbe = self.mortalite.courbe(
            age_liquidation, annee_liquidation, sexe_table, generation
        )

        nu = self.parametres.taux_anticipe_conversion
        diviseur = 0.0
        for t in range(len(courbe) - 1):
            # Rente supposée servie en continu sur l'année : on prend la survie
            # moyenne de début et de fin de période.
            survie_moyenne = 0.5 * (courbe[t] + courbe[t + 1])
            diviseur += survie_moyenne / ((1.0 + nu) ** (t + 0.5))

        if diviseur <= 0:
            raise ValueError(
                f"diviseur nul à {age_liquidation} ans en {annee_liquidation} : "
                "âge de liquidation hors des bornes de la table"
            )

        esperance = sum(
            0.5 * (courbe[t] + courbe[t + 1]) for t in range(len(courbe) - 1)
        )
        return CoefficientConversion(
            diviseur=diviseur,
            age_liquidation=age_liquidation,
            annee_liquidation=annee_liquidation,
            esperance_residuelle=esperance,
            table=("unisexe" if sexe_table is None else sexe_table)
            + ("_generation" if generation else "_moment"),
            taux_anticipe=nu,
            fiabilite=self.mortalite.fiabilite(annee_liquidation),
        )

    def effet_anticipation(self, age_anticipe: float, age_reference: float,
                           annee_liquidation: int, sexe: str | None = None) -> float:
        """Rapport des pensions à capital notionnel donné, anticipé / à l'heure.

        Isole la seule sanction due à l'allongement de la durée de service.
        L'effet total d'un départ anticipé est plus fort, puisque s'y ajoutent
        les cotisations non versées.
        """
        anticipe = self.coefficient(age_anticipe, annee_liquidation, sexe)
        reference = self.coefficient(age_reference, annee_liquidation, sexe)
        return reference.diviseur / anticipe.diviseur
