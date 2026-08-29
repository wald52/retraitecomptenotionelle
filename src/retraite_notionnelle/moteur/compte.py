"""Compte notionnel : accumulation des cotisations et liquidation.

Le compte notionnel est un compte virtuel. On y inscrit chaque année les
cotisations retraite réellement versées, on le revalorise au taux d'indexation
retenu, et on divise le solde final par un coefficient de conversion actuariel.
Aucun capital n'est placé : le système reste intégralement en répartition.

Trois principes tiennent tout le reste :

1. **Seules les cotisations comptent.** Une année sans cotisation n'ajoute rien
   au compte, quelle qu'en soit la cause. Les trimestres gratuits, majorations,
   bonifications et minima n'existent pas ici.
2. **L'année du versement fixe la valeur du droit.** Une cotisation de 1975 est
   revalorisée par le produit des taux annuels de 1976 à la liquidation.
3. **L'âge de liquidation fixe le partage.** Plus on liquide tôt, moins on a
   cotisé et plus longtemps on percevra : la double sanction est automatique.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..carriere import Affiliations, Carriere
from ..config import ContributionEmployeurPublic, Parametres, SourceCotisations
from ..donnees.chargement import Fiabilite
from ..donnees.macro import DonneesMacro
from ..donnees.regimes import CatalogueRegimes
from .fusion import RegimeFusionne
from .indexation import Indexation


@dataclass(frozen=True)
class CotisationAnnuelle:
    """Détail des cotisations d'une année, régime par régime."""

    annee: int
    revenu: float
    assiette_retenue: float
    cotisation: float
    regimes: tuple[str, ...]
    taux_effectif: float
    hors_repartition: float
    fiabilite: Fiabilite

    @property
    def nulle(self) -> bool:
        return self.cotisation <= 0


@dataclass
class CompteNotionnel:
    """Résultat de l'accumulation sur une carrière."""

    capital: float
    capital_hors_repartition: float
    annee_liquidation: int
    cotisations: list[CotisationAnnuelle] = field(default_factory=list)
    fiabilite: Fiabilite = Fiabilite.ESTIMEE

    @property
    def cotisations_versees(self) -> float:
        """Somme des cotisations en euros courants, sans revalorisation."""
        return sum(c.cotisation for c in self.cotisations)

    @property
    def annees_cotisees(self) -> int:
        return sum(1 for c in self.cotisations if not c.nulle)

    @property
    def rendement_cumule(self) -> float:
        """Rapport entre capital revalorisé et cotisations versées."""
        versees = self.cotisations_versees
        return self.capital / versees if versees else 0.0


class ConstructeurCompte:
    """Construit un compte notionnel à partir d'une carrière."""

    def __init__(
        self,
        macro: DonneesMacro,
        catalogue: CatalogueRegimes,
        affiliations: Affiliations,
        indexation: Indexation,
        parametres: Parametres,
    ) -> None:
        self.macro = macro
        self.catalogue = catalogue
        self.affiliations = affiliations
        self.indexation = indexation
        self.parametres = parametres
        self._taux_pivot: dict[int, float] = {}

    # -- taux ----------------------------------------------------------------

    def taux_pivot_prive(self, annee: int) -> float:
        """Taux total salarié + employeur du statut pivot privé, cette année-là.

        Sert de référence aux régimes dont la fiche ne stocke que la retenue de
        l'agent. On somme les régimes du statut pivot dont l'assiette commence
        au premier euro, pour ne pas compter deux fois les tranches hautes.
        """
        if annee in self._taux_pivot:
            return self._taux_pivot[annee]
        total = 0.0
        codes = self.affiliations.regimes(
            self.parametres.statut_pivot_cotisations, annee
        )
        for code in codes:
            if code not in self.catalogue:
                continue
            regime = self.catalogue[code]
            if regime.hors_repartition:
                continue
            for periode in regime.periodes_actives(annee):
                borne_basse, _ = periode.bornes_assiette_en_pass()
                if borne_basse > 0:
                    continue
                total += periode.taux_cotisation_retraite
        self._taux_pivot[annee] = total
        return total

    def taux_effectif(self, periode, annee: int) -> float:
        """Taux à porter au compte notionnel pour cette période et cette année."""
        if self.parametres.source_cotisations is not SourceCotisations.TAUX_HISTORIQUES:
            return self.parametres.taux_cotisation_uniforme
        taux = periode.taux_cotisation_retraite
        aligne = (
            self.parametres.traitement_contribution_employeur_etat
            is ContributionEmployeurPublic.ALIGNEE_SUR_LE_PRIVE
        )
        if aligne and periode.perimetre_taux == "agent_seul":
            # La fiche ne porte que la retenue de l'agent : on lui substitue
            # l'effort contributif complet d'un salarié de la même année, faute
            # de quoi on comparerait un demi-effort à un effort entier.
            pivot = self.taux_pivot_prive(annee)
            if pivot > 0:
                return pivot
        return taux

    # -- assiette ------------------------------------------------------------

    def _assiette(self, revenu: float, annee: int, borne_basse: float,
                  borne_haute: float | None) -> float:
        """Part du revenu comprise entre deux bornes exprimées en plafonds."""
        pass_annuel = self.macro.plafond_securite_sociale(annee)
        plancher = borne_basse * pass_annuel
        plafond_global = self.parametres.plafond_assiette_en_pass
        if borne_haute is None:
            plafond = revenu if plafond_global is None else plafond_global * pass_annuel
        else:
            plafond = borne_haute * pass_annuel
            if plafond_global is not None:
                plafond = min(plafond, plafond_global * pass_annuel)
        return max(0.0, min(revenu, plafond) - plancher)

    # -- cotisation d'une année ---------------------------------------------

    def cotisation_annuelle(self, carriere: Carriere, annee: int,
                            regime_fusionne: RegimeFusionne | None = None) -> CotisationAnnuelle:
        ligne = carriere.ligne(annee)
        if ligne is None or not ligne.cotise:
            return CotisationAnnuelle(
                annee=annee, revenu=0.0, assiette_retenue=0.0, cotisation=0.0,
                regimes=(), taux_effectif=0.0, hors_repartition=0.0,
                fiabilite=Fiabilite.CERTIFIEE,
            )

        # Après la bascule, un seul régime : le régime fusionné.
        if regime_fusionne is not None and annee >= regime_fusionne.annee_bascule:
            assiette = self._assiette(ligne.revenu, annee, 0.0, None)
            taux = (
                regime_fusionne.taux_cotisation_retraite
                if self.parametres.source_cotisations is SourceCotisations.TAUX_HISTORIQUES
                else self.parametres.taux_cotisation_uniforme
            )
            return CotisationAnnuelle(
                annee=annee, revenu=ligne.revenu, assiette_retenue=assiette,
                cotisation=assiette * taux, regimes=("regime_unifie",),
                taux_effectif=taux, hors_repartition=0.0,
                fiabilite=regime_fusionne.fiabilite,
            )

        codes = self.affiliations.regimes(ligne.affiliation, annee)
        cotisation = 0.0
        assiette_totale = 0.0
        hors_repartition = 0.0
        fiabilite = Fiabilite.CERTIFIEE
        retenus: list[str] = []

        for code in codes:
            if code not in self.catalogue:
                continue
            regime = self.catalogue[code]
            fiabilite = min(fiabilite, regime.fiabilite)
            for periode in regime.periodes_actives(annee):
                borne_basse, borne_haute = periode.bornes_assiette_en_pass()

                if periode.assiette == "primes_uniquement":
                    base = ligne.revenu * ligne.part_primes
                elif periode.assiette == "hors_primes":
                    base = ligne.revenu * (1.0 - ligne.part_primes)
                else:
                    base = ligne.revenu

                assiette = self._assiette(base, annee, borne_basse, borne_haute)
                if assiette <= 0:
                    continue

                taux = self.taux_effectif(periode, annee)
                montant = assiette * taux

                if regime.hors_repartition and self.parametres.isoler_capitalisation:
                    # RAFP, assurances sociales d'avant-guerre : ces droits sont
                    # provisionnés, ils ne rejoignent pas le compte notionnel.
                    hors_repartition += montant
                else:
                    cotisation += montant
                    assiette_totale += assiette
                retenus.append(code)

        taux_effectif = cotisation / ligne.revenu if ligne.revenu else 0.0
        return CotisationAnnuelle(
            annee=annee,
            revenu=ligne.revenu,
            assiette_retenue=assiette_totale,
            cotisation=cotisation,
            regimes=tuple(dict.fromkeys(retenus)),
            taux_effectif=taux_effectif,
            hors_repartition=hors_repartition,
            fiabilite=fiabilite,
        )

    # -- accumulation --------------------------------------------------------

    def construire(
        self,
        carriere: Carriere,
        annee_liquidation: int,
        annee_debut: int | None = None,
        regime_fusionne: RegimeFusionne | None = None,
    ) -> CompteNotionnel:
        """Accumule les cotisations de ``annee_debut`` à la liquidation.

        ``annee_debut`` permet de n'ouvrir le compte qu'à partir d'une date —
        c'est ce qui distingue le scénario notionnel prospectif (compte ouvert à
        l'année de bascule) du scénario rétroactif (compte ouvert à l'entrée
        dans la vie active).
        """
        debut = max(
            annee_debut if annee_debut is not None else carriere.premiere_annee,
            self.parametres.annee_debut_repartition,
        )
        fin = min(annee_liquidation - 1, carriere.derniere_annee)

        capital = 0.0
        capital_hors = 0.0
        cotisations: list[CotisationAnnuelle] = []
        fiabilite = Fiabilite.CERTIFIEE

        for annee in range(debut, fin + 1):
            detail = self.cotisation_annuelle(carriere, annee, regime_fusionne)
            cotisations.append(detail)
            if detail.nulle and detail.hors_repartition == 0:
                continue
            fiabilite = min(fiabilite, detail.fiabilite)
            coefficient = self.indexation.coefficient(annee, annee_liquidation)
            capital += detail.cotisation * coefficient
            capital_hors += detail.hors_repartition * coefficient

        if cotisations:
            fiabilite = min(
                fiabilite,
                self.indexation.fiabilite_sur(debut, annee_liquidation),
            )

        return CompteNotionnel(
            capital=capital,
            capital_hors_repartition=capital_hors,
            annee_liquidation=annee_liquidation,
            cotisations=cotisations,
            fiabilite=fiabilite,
        )
