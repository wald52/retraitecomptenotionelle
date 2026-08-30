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
from ..config import Parametres, PartCotisation, SourceCotisations
from ..donnees.chargement import Fiabilite
from ..donnees.macro import DonneesMacro
from ..donnees.regimes import CatalogueRegimes, ContributionsEmployeurPubliques
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
    #: D'où vient la part employeur PUBLIQUE, cette année-là — celle des
    #: régimes à ``perimetre_taux: agent_seul``, qu'aucune fiche ne porte. Vide
    #: si l'année n'en compte aucun ;
    #: ``appelee`` ou ``implicite`` si la contribution réellement versée a été
    #: trouvée ; ``repli`` si elle ne l'a pas été et que le taux du statut pivot
    #: privé lui a été substitué. Ne vaut que dans les scénarios 4 et 5 —
    #: ailleurs, la question ne se pose pas.
    origine_part_employeur: str = ""
    #: Part de ``cotisation`` versée par l'employeur, en euros. Nulle sous
    #: ``SALARIALE``, qui ne porte rien de lui au compte, et pour un
    #: non-salarié, qui n'en a pas.
    part_employeur: float = 0.0

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

    @property
    def cotisations_employeur(self) -> float:
        """Part des cotisations versée par l'employeur, en euros courants."""
        return sum(c.part_employeur for c in self.cotisations)

    @property
    def annees_part_employeur(self) -> dict[str, int]:
        """Nombre d'années par origine de la part employeur publique.

        Ce que les scénarios 4 et 5 doivent dire d'eux-mêmes : sur combien
        d'années la contribution réellement versée a été trouvée, et sur combien
        il a fallu retomber sur l'alignement du scénario 2 faute de série.
        """
        decompte: dict[str, int] = {}
        for cotisation in self.cotisations:
            if cotisation.origine_part_employeur and not cotisation.nulle:
                origine = cotisation.origine_part_employeur
                decompte[origine] = decompte.get(origine, 0) + 1
        return decompte


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
        self.contributions_publiques = ContributionsEmployeurPubliques(
            parametres.racine_donnees
        )

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

    def taux_effectif(self, regime: str, periode, annee: int,
                      sans_employeur: bool = False
                      ) -> tuple[float, float, str, Fiabilite]:
        """Taux à porter au compte, sa part employeur, d'où elle vient et ce
        qu'elle vaut.

        Le deuxième terme est la part employeur EN POINTS DE TAUX, nulle sous
        ``SALARIALE`` et pour un non-salarié. Le troisième ne concerne que les
        régimes dont la fiche s'arrête à la retenue de l'agent : il dit si la
        contribution réellement versée par l'employeur public a été trouvée pour
        cette année-là (``appelee``, ``implicite``) ou s'il a fallu lui
        substituer le taux du statut pivot privé (``repli``). Le quatrième
        qualifie le résultat : la fiabilité de la série employeur quand elle a
        servi, ``estimee`` quand il a fallu s'en passer.
        """
        part = self.parametres.part_cotisation
        taux = periode.taux_cotisation_retraite

        if sans_employeur:
            # Un non-salarié paie tout : la répartition de la fiche est celle
            # d'un salarié du même régime, elle ne le concerne pas.
            return taux, 0.0, "", Fiabilite.CERTIFIEE

        if part is PartCotisation.SALARIALE:
            # La même grandeur des deux côtés : ce que l'assuré supporte. Pour
            # une période `agent_seul`, la retenue de l'agent est déjà cela, et
            # `part_salariale` y vaut un.
            return periode.taux_cotisation_salarie, 0.0, "", Fiabilite.CERTIFIEE

        if periode.perimetre_taux != "agent_seul":
            # Le privé : la fiche porte le total, et sa part salariale dit
            # combien l'employeur y met.
            return (taux, taux - periode.taux_cotisation_salarie, "",
                    Fiabilite.CERTIFIEE)

        if part is PartCotisation.TOTALE:
            # La retenue de l'agent, plus ce que l'employeur public a versé.
            contribution = self.contributions_publiques.taux(regime, annee)
            if contribution is not None:
                return (taux + contribution.taux, contribution.taux,
                        contribution.nature, contribution.fiabilite)
            # Aucune série pour ce régime cette année-là : plutôt que de laisser
            # le taux à la seule retenue de l'agent — ce qui ferait retomber les
            # scénarios 4 et 5 sur les scénarios 2 et 3 sans le dire — on
            # retombe sur l'effort total d'un salarié du privé de la même année.
            # L'écart avec la retenue est alors porté à la part employeur : c'est
            # une ESTIMATION de ce que l'employeur public aurait versé, pas une
            # somme retrouvée, et le résultat le dit — `repli`, fiabilité
            # `estimee`, et le décompte des années affiché sous la simulation.
            pivot = self.taux_pivot_prive(annee)
            if pivot <= taux:
                return taux, 0.0, "repli", Fiabilite.ESTIMEE
            return pivot, pivot - taux, "repli", Fiabilite.ESTIMEE

        # TOTALE_ALIGNEE : l'ancienne convention, conservée comme contrefactuel.
        pivot = self.taux_pivot_prive(annee)
        if pivot > 0:
            return pivot, 0.0, "", Fiabilite.CERTIFIEE
        return taux, 0.0, "", Fiabilite.CERTIFIEE

    def a_un_employeur(self, ligne, annee: int) -> bool:
        """Un employeur verse-t-il quelque chose pour cet assuré, cette année-là ?

        Non pour un artisan, un commerçant, un libéral, un exploitant agricole :
        ils cotisent seuls, et leur cotisation est intégralement personnelle.
        Oui pour un salarié, dont la fiche porte une part salariale inférieure à
        un, et pour un agent public, dont la fiche s'arrête à sa retenue.
        """
        if self.affiliations.sans_employeur(ligne.affiliation):
            return False
        for code in self.affiliations.regimes(ligne.affiliation, annee):
            if code not in self.catalogue:
                continue
            regime = self.catalogue[code]
            if regime.hors_repartition:
                continue
            for periode in regime.periodes_actives(annee):
                if periode.perimetre_taux == "agent_seul":
                    return True
                if periode.part_salariale < 1.0:
                    return True
        return False

    def taux_unifie(self, ligne, annee: int,
                    regime_fusionne: RegimeFusionne
                    ) -> tuple[float, float, str, Fiabilite]:
        """Taux du régime unique, après la bascule — et ce que l'employeur y met.

        Le régime unique remplace tous les régimes : il n'y a plus, après la
        bascule, ni fonction publique ni régimes spéciaux, donc plus de
        contribution d'un employeur public à retrouver décret par décret. Son
        taux est celui du statut pivot privé, et il en hérite la répartition
        salarié/employeur — c'est elle qui sépare ici les scénarios 2 et 3 des
        scénarios 4 et 5.

        Une exception, et une seule : un assuré qui n'avait pas d'employeur
        n'en gagne pas un en changeant de régime. Un artisan cotise seul avant
        la bascule ; il cotise seul après, à un taux plus élevé — c'est déjà ce
        que dit le modèle, et la répartition doit le suivre.
        """
        if self.parametres.source_cotisations is not SourceCotisations.TAUX_HISTORIQUES:
            return self.parametres.taux_cotisation_uniforme, 0.0, "", Fiabilite.CERTIFIEE

        unifie = regime_fusionne.taux_cotisation_retraite
        salarie = (regime_fusionne.taux_cotisation_salarie
                   if self.a_un_employeur(ligne, annee) else unifie)

        if self.parametres.part_cotisation is PartCotisation.SALARIALE:
            return salarie, 0.0, "", Fiabilite.CERTIFIEE
        return unifie, unifie - salarie, "", Fiabilite.CERTIFIEE

    # -- assiette ------------------------------------------------------------

    def _assiette(self, revenu: float, annee: int, plancher: float,
                  plafond_periode: float | None) -> float:
        """Part du revenu comprise entre deux bornes, exprimées EN EUROS.

        Le plafond global du modèle, lui, reste en plafonds de la Sécurité
        sociale : c'est un paramètre de simulation, pas une règle de régime.
        """
        pass_annuel = self.macro.plafond_securite_sociale(annee)
        plafond_global = self.parametres.plafond_assiette_en_pass
        if plafond_periode is None:
            plafond = revenu if plafond_global is None else plafond_global * pass_annuel
        else:
            plafond = plafond_periode
            if plafond_global is not None:
                plafond = min(plafond, plafond_global * pass_annuel)
        return max(0.0, min(revenu, plafond) - plancher)

    @staticmethod
    def _fusionner(bornes: list[tuple[float, float | None]]
                   ) -> list[tuple[float, float | None]]:
        """Réunion d'intervalles d'assiette, sans recouvrement.

        Un taux d'acquisition COMMUN s'applique une fois à la rémunération, et
        non une fois par régime. Or les régimes se recouvrent : un cadre cotise
        au régime général et à l'Arrco sur la même première tranche, puis à
        l'Agirc sur la seconde. Sommer leurs assiettes conviendrait à des taux
        distincts, chacun n'ouvrant droit que dans son régime ; appliquer un taux
        unique à cette somme le compterait deux fois. On réunit donc les
        intervalles avant de prélever. ``None`` en borne haute vaut « sans
        plafond de régime » — le plafond global du modèle s'applique ensuite.
        """
        ordonnees = sorted(bornes, key=lambda b: (b[0], b[1] is None, b[1] or 0.0))
        fusionnees: list[tuple[float, float | None]] = []
        for basse, haute in ordonnees:
            if not fusionnees:
                fusionnees.append((basse, haute))
                continue
            precedente_basse, precedente_haute = fusionnees[-1]
            if precedente_haute is not None and basse > precedente_haute:
                fusionnees.append((basse, haute))
                continue
            if precedente_haute is None or haute is None:
                fusionnees[-1] = (precedente_basse, None)
            else:
                fusionnees[-1] = (precedente_basse, max(precedente_haute, haute))
        return fusionnees

    def _base_selon_assiette(self, assiette: str, base_ligne: float,
                             part_primes: float) -> float:
        if assiette == "primes_uniquement":
            return base_ligne * part_primes
        if assiette == "hors_primes":
            return base_ligne * (1.0 - part_primes)
        return base_ligne

    # -- cotisation d'une année ---------------------------------------------

    def cotisation_annuelle(self, carriere: Carriere, annee: int,
                            regime_fusionne: RegimeFusionne | None = None) -> CotisationAnnuelle:
        ligne = carriere.ligne(annee)
        if ligne is None or (not ligne.cotise and not ligne.familles_cotisantes):
            return CotisationAnnuelle(
                annee=annee, revenu=0.0, assiette_retenue=0.0, cotisation=0.0,
                regimes=(), taux_effectif=0.0, hors_repartition=0.0,
                fiabilite=Fiabilite.CERTIFIEE,
            )

        # Après la bascule, un seul régime : le régime fusionné.
        if regime_fusionne is not None and annee >= regime_fusionne.annee_bascule:
            assiette = self._assiette(ligne.revenu, annee, 0.0, None)
            taux, taux_employeur, origine, fiabilite_taux = self.taux_unifie(
                ligne, annee, regime_fusionne
            )
            fiabilite = regime_fusionne.fiabilite
            if origine:
                fiabilite = min(fiabilite, fiabilite_taux)
            return CotisationAnnuelle(
                annee=annee, revenu=ligne.revenu, assiette_retenue=assiette,
                cotisation=assiette * taux, regimes=("regime_unifie",),
                taux_effectif=taux, hors_repartition=0.0,
                fiabilite=fiabilite,
                origine_part_employeur=origine,
                part_employeur=assiette * taux_employeur,
            )

        # Pendant une période indemnisée, seuls les régimes complémentaires
        # encaissent, et sur le salaire d'avant l'interruption.
        base_ligne = ligne.revenu if ligne.cotise else ligne.revenu_reference
        familles_admises = None if ligne.cotise else set(ligne.familles_cotisantes)

        codes = self.affiliations.regimes(ligne.affiliation, annee)
        sans_employeur = self.affiliations.sans_employeur(ligne.affiliation)
        cotisation = 0.0
        assiette_totale = 0.0
        hors_repartition = 0.0
        fiabilite = Fiabilite.CERTIFIEE
        retenus: list[str] = []
        origines: list[str] = []
        part_employeur = 0.0

        # Taux d'acquisition commun (``source_cotisations = taux_uniforme``) :
        # un seul taux, prélevé une fois sur la rémunération. Les régimes en
        # répartition n'y servent plus qu'à délimiter l'assiette, qu'on réunit
        # avant de prélever. Le compartiment de capitalisation, lui, garde ses
        # taux propres : il n'est pas un compte notionnel.
        acquisition_commune = (
            self.parametres.source_cotisations is SourceCotisations.TAUX_UNIFORME
        )
        intervalles: dict[str, list[tuple[float, float | None]]] = {}

        for code in codes:
            if code not in self.catalogue:
                continue
            regime = self.catalogue[code]
            if familles_admises is not None and regime.famille not in familles_admises:
                continue
            fiabilite = min(fiabilite, regime.fiabilite)
            en_repartition = not (
                regime.hors_repartition and self.parametres.isoler_capitalisation
            )
            for periode in regime.periodes_actives(annee):
                borne_basse, borne_haute = periode.bornes_assiette_en_euros(
                    self.macro.plafond_securite_sociale(annee)
                )

                base = self._base_selon_assiette(
                    periode.assiette, base_ligne, ligne.part_primes
                )

                if acquisition_commune and en_repartition:
                    # Regroupées par ASSIETTE DE DÉPART — traitement indiciaire,
                    # primes, rémunération entière — et non par régime : c'est
                    # la même rémunération qu'on découpe, et deux régimes qui la
                    # découpent différemment doivent se réunir, pas s'ajouter.
                    # Les planchers d'assiette propres à un régime — les 1 820
                    # SMIC de la complémentaire agricole — ne survivent pas non
                    # plus : un taux unique porte sur la rémunération réelle.
                    if self._assiette(base, annee, borne_basse, borne_haute) > 0:
                        groupe = (
                            periode.assiette
                            if periode.assiette in ("primes_uniquement", "hors_primes")
                            else "total"
                        )
                        intervalles.setdefault(groupe, []).append(
                            (borne_basse, borne_haute)
                        )
                        retenus.append(code)
                    continue

                assiette = self._assiette(base, annee, borne_basse, borne_haute)
                repere = periode.repere_assiette(
                    self.macro.plafond_securite_sociale(annee),
                    self.macro.smic_horaire(annee),
                )
                if periode.assiette_plancher and assiette < repere:
                    # Assiette minimale : la complémentaire agricole prélève sur
                    # 1 820 SMIC même quand le revenu est en dessous. Ce qui a
                    # été prélevé ouvre des droits, ici comme dans le scénario 1.
                    assiette = repere
                if assiette <= 0:
                    continue

                taux, taux_employeur, origine, fiabilite_taux = self.taux_effectif(
                    code, periode, annee, sans_employeur
                )
                if origine:
                    origines.append(origine)
                    fiabilite = min(fiabilite, fiabilite_taux)
                montant = assiette * taux

                if regime.hors_repartition and self.parametres.isoler_capitalisation:
                    # RAFP, assurances sociales d'avant-guerre : ces droits sont
                    # provisionnés, ils ne rejoignent pas le compte notionnel.
                    hors_repartition += montant
                else:
                    cotisation += montant
                    assiette_totale += assiette
                    part_employeur += assiette * taux_employeur
                retenus.append(code)

        if acquisition_commune:
            taux_commun = self.parametres.taux_cotisation_uniforme
            for groupe, bornes in intervalles.items():
                base = self._base_selon_assiette(groupe, base_ligne, ligne.part_primes)
                for borne_basse, borne_haute in self._fusionner(bornes):
                    assiette = self._assiette(base, annee, borne_basse, borne_haute)
                    if assiette <= 0:
                        continue
                    assiette_totale += assiette
                    cotisation += assiette * taux_commun

        taux_effectif = cotisation / base_ligne if base_ligne else 0.0
        return CotisationAnnuelle(
            annee=annee,
            revenu=base_ligne,
            assiette_retenue=assiette_totale,
            cotisation=cotisation,
            regimes=tuple(dict.fromkeys(retenus)),
            taux_effectif=taux_effectif,
            hors_repartition=hors_repartition,
            fiabilite=fiabilite,
            # Un même agent ne relève que d'un régime en répartition à la fois ;
            # si deux périodes se recouvraient, le repli l'emporte, parce que
            # c'est lui qui qualifie le résultat.
            origine_part_employeur=(
                "repli" if "repli" in origines else (origines[0] if origines else "")
            ),
            part_employeur=part_employeur,
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
