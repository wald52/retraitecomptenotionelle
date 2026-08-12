"""Scénarios 2 et 3 — les comptes notionnels.

**Scénario 2, rétroactif.** Le compte notionnel est ouvert à l'entrée dans la
vie active, ou à l'année d'origine de la répartition si la carrière a commencé
avant. Toute la carrière est recalculée : les cotisations réellement versées
alimentent le compte, la revalorisation applique le triple lock inversé année
par année depuis l'origine, et la pension est le solde divisé par le coefficient
de conversion à l'âge effectif de liquidation. Un départ à 55 ans dans un régime
spécial en 1985 est donc traité comme ce qu'il est : douze années de cotisations
en moins et douze années de rente en plus.

**Scénario 3, prospectif.** Les droits acquis jusqu'à l'année de bascule sont
figés selon les règles actuelles, convertis en capital notionnel d'ouverture,
puis le compte fonctionne en notionnel au-delà. C'est la variante qui respecte
les droits acquis — celle qu'une réforme réelle retiendrait.

La conversion des droits acquis pose une question qu'aucune convention ne
tranche seule : à quel capital notionnel correspond une pension annuelle promise
de X euros ? La réponse retenue ici est la seule cohérente avec le reste du
modèle — celle qui inverse la formule de liquidation :

.. math::  K_{\\text{ouverture}} = P_{\\text{acquise}} \\times G(a_{\\text{ref}}, L)

où :math:`P_{\\text{acquise}}` est la pension de droits figés à l'année de
bascule et :math:`G` le coefficient de conversion à l'âge de référence.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..carriere import Carriere
from ..config import Parametres
from ..donnees.chargement import Fiabilite
from ..moteur.age_reference import AgeReference, EcartAge
from ..moteur.compte import CompteNotionnel, ConstructeurCompte
from ..moteur.conversion import CoefficientConversion, Convertisseur
from ..moteur.fusion import RegimeFusionne
from .actuel import ScenarioActuel


@dataclass
class ResultatNotionnel:
    """Pension issue d'un compte notionnel, et tout ce qui l'explique."""

    pension_annuelle: float
    capital_notionnel: float
    capital_droits_acquis: float
    compte: CompteNotionnel
    conversion: CoefficientConversion
    ecart_age: EcartAge
    capital_capitalisation: float
    fiabilite: Fiabilite
    libelle: str

    @property
    def pension_mensuelle(self) -> float:
        return self.pension_annuelle / 12.0

    @property
    def rente_capitalisation_annuelle(self) -> float:
        """Rente issue du compartiment de capitalisation, servie à part.

        Le RAFP et les droits des anciennes assurances sociales ne sont pas
        convertis en capital notionnel : ils restent dans un compartiment
        distinct, converti au même coefficient actuariel.
        """
        if self.conversion.diviseur <= 0:
            return 0.0
        return self.capital_capitalisation / self.conversion.diviseur


class ScenarioNotionnel:
    """Produit les deux variantes de comptes notionnels."""

    def __init__(
        self,
        constructeur: ConstructeurCompte,
        convertisseur: Convertisseur,
        age_reference: AgeReference,
        scenario_actuel: ScenarioActuel,
        parametres: Parametres,
    ) -> None:
        self.constructeur = constructeur
        self.convertisseur = convertisseur
        self.age_reference = age_reference
        self.scenario_actuel = scenario_actuel
        self.parametres = parametres

    def _sexe(self, carriere: Carriere) -> str | None:
        from ..config import TableConversion

        if self.parametres.table_conversion is TableConversion.UNISEXE:
            return None
        return carriere.sexe

    # -- scénario 2 ----------------------------------------------------------

    def retroactif(self, carriere: Carriere,
                   regime_fusionne: RegimeFusionne | None = None) -> ResultatNotionnel:
        """Comptes notionnels appliqués depuis l'origine de la répartition."""
        annee_liquidation = carriere.annee_liquidation
        age_liquidation = carriere.age_liquidation or 0.0

        compte = self.constructeur.construire(
            carriere,
            annee_liquidation=annee_liquidation,
            annee_debut=carriere.premiere_annee,
            regime_fusionne=regime_fusionne,
        )
        conversion = self.convertisseur.coefficient(
            age_liquidation, annee_liquidation, self._sexe(carriere)
        )
        pension = compte.capital / conversion.diviseur

        return ResultatNotionnel(
            pension_annuelle=pension,
            capital_notionnel=compte.capital,
            capital_droits_acquis=0.0,
            compte=compte,
            conversion=conversion,
            ecart_age=self.age_reference.ecart(age_liquidation, annee_liquidation),
            capital_capitalisation=compte.capital_hors_repartition,
            fiabilite=min(compte.fiabilite, conversion.fiabilite),
            libelle="Comptes notionnels rétroactifs",
        )

    # -- scénario 3 ----------------------------------------------------------

    def prospectif(self, carriere: Carriere,
                   regime_fusionne: RegimeFusionne) -> ResultatNotionnel:
        """Droits figés à la bascule, comptes notionnels au-delà.

        Pour un assuré dont la retraite est déjà liquidée à la bascule, ce
        scénario ne peut rien changer : ses droits sont intégralement acquis.
        La méthode renvoie alors sa pension actuelle, de sorte que le tableau
        comparatif reste lisible — un retraité de 2005 voit bien « aucun effet »
        sur la ligne 3, et non un chiffre recalculé qui n'aurait aucun sens.
        """
        annee_liquidation = carriere.annee_liquidation
        age_liquidation = carriere.age_liquidation or 0.0
        bascule = self.parametres.annee_bascule

        if annee_liquidation <= bascule:
            return self._deja_liquide(carriere)

        capital_acquis = self._capital_droits_acquis(carriere, bascule)

        compte = self.constructeur.construire(
            carriere,
            annee_liquidation=annee_liquidation,
            annee_debut=bascule,
            regime_fusionne=regime_fusionne,
        )
        conversion = self.convertisseur.coefficient(
            age_liquidation, annee_liquidation, self._sexe(carriere)
        )
        capital_total = compte.capital + capital_acquis
        pension = capital_total / conversion.diviseur

        return ResultatNotionnel(
            pension_annuelle=pension,
            capital_notionnel=capital_total,
            capital_droits_acquis=capital_acquis,
            compte=compte,
            conversion=conversion,
            ecart_age=self.age_reference.ecart(age_liquidation, annee_liquidation),
            capital_capitalisation=compte.capital_hors_repartition,
            fiabilite=min(compte.fiabilite, conversion.fiabilite),
            libelle="Comptes notionnels à compter de la bascule",
        )

    def _deja_liquide(self, carriere: Carriere) -> ResultatNotionnel:
        """Cas d'un assuré déjà retraité à la bascule : rien ne change."""
        annee_liquidation = carriere.annee_liquidation
        age_liquidation = carriere.age_liquidation or 0.0
        actuel = self.scenario_actuel.calculer(carriere)
        conversion = self.convertisseur.coefficient(
            age_liquidation, annee_liquidation, self._sexe(carriere)
        )
        compte = self.constructeur.construire(
            carriere,
            annee_liquidation=annee_liquidation,
            annee_debut=annee_liquidation,  # aucune cotisation postérieure
        )
        return ResultatNotionnel(
            pension_annuelle=actuel.pension_annuelle,
            capital_notionnel=actuel.pension_annuelle * conversion.diviseur,
            capital_droits_acquis=actuel.pension_annuelle * conversion.diviseur,
            compte=compte,
            conversion=conversion,
            ecart_age=self.age_reference.ecart(age_liquidation, annee_liquidation),
            capital_capitalisation=0.0,
            fiabilite=actuel.fiabilite,
            libelle="Retraite déjà liquidée à la bascule — droits inchangés",
        )

    def _capital_droits_acquis(self, carriere: Carriere, bascule: int) -> float:
        """Convertit les droits figés à la bascule en capital notionnel.

        Les droits sont ceux qu'aurait produits la carrière si elle s'était
        arrêtée à la bascule, calculés selon les règles actuelles mais
        DÉBARRASSÉS des avantages non contributifs — conformément au principe
        « seules les cotisations comptent », qui vaut aussi pour le passé.

        La valorisation se fait à l'année de bascule, sans décote ni surcote :
        on mesure des droits déjà ouverts, pas une liquidation anticipée. La
        sanction d'âge s'appliquera une seule fois, à la liquidation réelle, par
        le coefficient de conversion.
        """
        lignes_avant = [l for l in carriere.lignes if l.annee < bascule]
        if not lignes_avant:
            return 0.0

        carriere_tronquee = Carriere(
            annee_naissance=carriere.annee_naissance,
            sexe=carriere.sexe,
            lignes=list(lignes_avant),
            # L'année de liquidation de cette carrière fictive doit être
            # l'année de bascule : c'est en euros de cette année-là que les
            # droits acquis sont valorisés.
            age_liquidation=float(bascule - carriere.annee_naissance),
            nombre_enfants=0,  # avantages familiaux neutralisés
            identifiant=f"{carriere.identifiant} (droits figés {bascule})",
        )
        droits = self.scenario_actuel.calculer(
            carriere_tronquee, ignorer_penalite_age=True
        )

        age_ref = self.age_reference.age(bascule)
        conversion = self.convertisseur.coefficient(age_ref, bascule, self._sexe(carriere))
        capital_a_la_bascule = droits.pension_annuelle * conversion.diviseur

        # Le capital d'ouverture se revalorise ensuite comme tout compte notionnel.
        coefficient = self.constructeur.indexation.coefficient(
            bascule, carriere.annee_liquidation
        )
        return capital_a_la_bascule * coefficient
