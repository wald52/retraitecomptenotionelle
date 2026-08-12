"""Scénario 1 — le système actuel, tel qu'il est.

Ce scénario sert d'étalon : c'est la pension que l'assuré perçoit ou percevra
en droit constant. Il conserve tout ce que les scénarios notionnels retirent —
minima, majorations, trimestres gratuits, décote et surcote, bonifications.

Portée et limites
-----------------
Reproduire exactement le droit positif de tous les régimes depuis 1930
supposerait un moteur législatif complet, du type de ceux de la DREES
(TRAJECTOiRE) ou de l'Institut des politiques publiques (PENSIPP). Ce module
est une **approximation documentée**, pas un simulateur officiel :

* régimes en annuités — formule ``taux × salaire de référence × durée / durée
  requise``, avec décote et surcote de la période ;
* régimes en points — la pension est reconstituée à partir du rendement
  instantané du régime (``regimes/rendements_points.csv``) plutôt qu'à partir de
  l'historique des valeurs d'achat et de service, qui n'est pas encore intégré ;
* montée en charge des réformes — les paramètres sont ceux de l'année de
  liquidation, sans le détail génération par génération de la loi Balladur ni de
  la loi Touraine.

Un écart de quelques pour cent avec la pension réelle est donc attendu.
Ce que le modèle mesure de façon robuste, ce sont les ÉCARTS ENTRE SCÉNARIOS,
tous calculés sur les mêmes carrières et les mêmes séries.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from ..carriere import Affiliations, Carriere
from ..config import Parametres
from ..donnees.chargement import Fiabilite
from ..donnees.macro import DonneesMacro
from ..donnees.regimes import CatalogueRegimes, PeriodeRegime


@dataclass(frozen=True)
class PensionRegime:
    """Pension annuelle brute servie par un régime."""

    regime: str
    montant: float
    type_calcul: str
    detail: str
    fiabilite: Fiabilite


@dataclass
class ResultatActuel:
    pension_annuelle: float
    pensions_par_regime: list[PensionRegime] = field(default_factory=list)
    trimestres_valides: int = 0
    trimestres_requis: int = 0
    taux_liquidation: float = 0.0
    minimum_applique: bool = False
    fiabilite: Fiabilite = Fiabilite.ESTIMEE

    @property
    def pension_mensuelle(self) -> float:
        return self.pension_annuelle / 12.0


class Rendements:
    """Rendements instantanés des régimes en points."""

    def __init__(self, racine: Path) -> None:
        self._table: list[tuple[str, int, int, float, Fiabilite]] = []
        chemin = racine / "reference" / "regimes" / "rendements_points.csv"
        with chemin.open(encoding="utf-8") as flux:
            lignes = (l for l in flux if not l.lstrip().startswith("#"))
            for ligne in csv.DictReader(lignes):
                self._table.append((
                    ligne["regime"], int(ligne["debut"]), int(ligne["fin"]),
                    float(ligne["rendement"]),
                    Fiabilite.depuis_texte(ligne["fiabilite"]),
                ))

    def rendement(self, regime: str, annee: int) -> tuple[float, Fiabilite]:
        for code, debut, fin, valeur, fiabilite in self._table:
            if code == regime and debut <= annee <= fin:
                return valeur, fiabilite
        return 0.0, Fiabilite.ESTIMEE


class ScenarioActuel:
    """Calcule la pension servie par le système en vigueur."""

    def __init__(self, macro: DonneesMacro, catalogue: CatalogueRegimes,
                 affiliations: Affiliations, parametres: Parametres) -> None:
        self.macro = macro
        self.catalogue = catalogue
        self.affiliations = affiliations
        self.parametres = parametres
        self.rendements = Rendements(parametres.racine_donnees)

    # -- salaire de référence ------------------------------------------------

    def salaire_de_reference(self, carriere: Carriere, periode: PeriodeRegime,
                             annee_liquidation: int, plafonner: bool) -> float:
        """Salaire de référence, exprimé en euros de l'année de liquidation.

        Les salaires portés au compte sont revalorisés sur les prix, règle en
        vigueur depuis la réforme de 1993. Avant 1993 ils l'étaient sur les
        salaires ; l'approximation retenue applique la règle des prix sur toute
        la période, ce qui minore le salaire de référence des carrières
        anciennes.
        """
        revenus: list[float] = []
        for ligne in carriere.lignes:
            if not ligne.cotise or ligne.annee >= annee_liquidation:
                continue
            revenu = ligne.revenu
            if plafonner:
                revenu = min(revenu, self.macro.plafond_securite_sociale(ligne.annee))
            revenus.append(revenu * self.macro.coefficient_prix(ligne.annee, annee_liquidation))

        if not revenus:
            return 0.0

        reference = periode.salaire_reference
        if reference == "25_meilleures_annees":
            retenus = sorted(revenus, reverse=True)[:25]
        elif reference == "10_meilleures_annees":
            retenus = sorted(revenus, reverse=True)[:10]
        elif reference in ("derniers_6_mois", "dernier_salaire"):
            return revenus[-1]
        elif reference == "carriere_entiere":
            retenus = revenus
        else:
            retenus = revenus
        return sum(retenus) / len(retenus)

    # -- calcul --------------------------------------------------------------

    def calculer(self, carriere: Carriere,
                 ignorer_penalite_age: bool = False) -> ResultatActuel:
        """Pension servie par le système en vigueur.

        ``ignorer_penalite_age`` neutralise la décote et la surcote liées à
        l'âge. On ne l'utilise que pour VALORISER DES DROITS ACQUIS à une date
        donnée — la question n'est alors pas « que toucherait cet assuré s'il
        liquidait aujourd'hui à 40 ans », qui n'a pas de sens, mais « quels
        droits sa carrière lui a-t-elle déjà ouverts ». La proratisation par la
        durée, elle, continue de s'appliquer : une carrière courte ouvre bien
        des droits proportionnellement plus faibles.
        """
        annee_liquidation = carriere.annee_liquidation
        age_liquidation = carriere.age_liquidation or 0.0

        trimestres = carriere.trimestres_actuels
        if self.parametres.neutralisations.majoration_duree_assurance is False:
            trimestres += 8 * carriere.nombre_enfants  # MDA, régime général

        pensions: list[PensionRegime] = []
        fiabilite_globale = Fiabilite.CERTIFIEE
        trimestres_requis = 0
        taux_retenu = 0.0

        # Cotisations cumulées par régime, pour les régimes en points.
        cumul_cotisations: dict[str, float] = {}
        annees_par_regime: dict[str, int] = {}

        for ligne in carriere.lignes:
            if not ligne.cotise:
                continue
            for code in self.affiliations.regimes(ligne.affiliation, ligne.annee):
                if code not in self.catalogue:
                    continue
                regime = self.catalogue[code]
                for periode in regime.periodes_actives(ligne.annee):
                    borne_basse, borne_haute = periode.bornes_assiette_en_pass()
                    pass_annuel = self.macro.plafond_securite_sociale(ligne.annee)
                    base = ligne.revenu
                    if periode.assiette == "primes_uniquement":
                        base = ligne.revenu * ligne.part_primes
                    elif periode.assiette == "hors_primes":
                        base = ligne.revenu * (1.0 - ligne.part_primes)
                    plafond = (
                        base if borne_haute is None else borne_haute * pass_annuel
                    )
                    assiette = max(0.0, min(base, plafond) - borne_basse * pass_annuel)
                    cotisation = assiette * periode.taux_cotisation_retraite
                    cumul_cotisations[code] = cumul_cotisations.get(code, 0.0) + (
                        cotisation * self.macro.coefficient_prix(ligne.annee, annee_liquidation)
                    )
                annees_par_regime[code] = annees_par_regime.get(code, 0) + 1

        for code, cumul in sorted(cumul_cotisations.items()):
            regime = self.catalogue[code]
            periode = regime.periode(min(annee_liquidation, _derniere_annee(regime)))
            if periode is None:
                continue
            fiabilite_globale = min(fiabilite_globale, regime.fiabilite)

            if periode.type_calcul in ("points", "mixte"):
                rendement, fiabilite_rendement = self.rendements.rendement(
                    code, min(annee_liquidation, _derniere_annee(regime))
                )
                fiabilite_globale = min(fiabilite_globale, fiabilite_rendement)
                montant = cumul * rendement
                if not ignorer_penalite_age:
                    montant *= _ajustement_age_points(periode, age_liquidation)
                pensions.append(PensionRegime(
                    regime=code, montant=montant, type_calcul=periode.type_calcul,
                    detail=f"cotisations revalorisées {cumul:,.0f} € × rendement {rendement:.2%}",
                    fiabilite=min(regime.fiabilite, fiabilite_rendement),
                ))
                continue

            # Régimes en annuités.
            plafonner = periode.assiette in ("plafonnee", "tranche_1", "tranche_a")
            salaire_reference = self.salaire_de_reference(
                carriere, periode, annee_liquidation, plafonner
            )
            requis = periode.duree_requise_trimestres or 160
            trimestres_requis = max(trimestres_requis, requis)
            trimestres_regime = min(annees_par_regime.get(code, 0) * 4, requis)

            taux = periode.taux_plein or 0.5
            if not ignorer_penalite_age:
                manquants = max(0, requis - trimestres)
                manquants_age = max(0.0, (periode.age_taux_plein - age_liquidation) * 4)
                # La décote retient le plus favorable des deux décomptes :
                # trimestres manquants pour la durée requise, ou trimestres
                # manquants jusqu'à l'âge d'annulation de la décote.
                trimestres_decote = min(manquants, manquants_age)
                if periode.decote_par_trimestre and trimestres_decote > 0:
                    # Les régimes sans décote (fonction publique avant 2004,
                    # régimes spéciaux avant 2008) ne subissent que la
                    # proratisation : leur `decote_par_trimestre` est nul.
                    taux *= max(0.0, 1.0 - periode.decote_par_trimestre * trimestres_decote)
                supplementaires = max(0, trimestres - requis)
                if (periode.surcote_par_trimestre and supplementaires > 0
                        and age_liquidation >= periode.age_ouverture):
                    taux *= 1.0 + periode.surcote_par_trimestre * supplementaires

            taux_retenu = max(taux_retenu, taux)
            montant = salaire_reference * taux * (trimestres_regime / requis)
            pensions.append(PensionRegime(
                regime=code, montant=montant, type_calcul="annuites",
                detail=(
                    f"SR {salaire_reference:,.0f} € × taux {taux:.2%} "
                    f"× {trimestres_regime}/{requis}"
                ),
                fiabilite=regime.fiabilite,
            ))

        total = sum(p.montant for p in pensions)

        # Avantages non contributifs du droit positif.
        minimum_applique = False
        neutralisations = self.parametres.neutralisations
        if not neutralisations.majoration_enfants and carriere.nombre_enfants >= 3:
            total *= 1.10
        if not neutralisations.minimum_contributif:
            plancher = _minimum_contributif(self.macro, annee_liquidation)
            if 0 < total < plancher and trimestres > 0:
                total = plancher * min(1.0, trimestres / max(trimestres_requis, 1))
                minimum_applique = True

        return ResultatActuel(
            pension_annuelle=total,
            pensions_par_regime=pensions,
            trimestres_valides=trimestres,
            trimestres_requis=trimestres_requis,
            taux_liquidation=taux_retenu,
            minimum_applique=minimum_applique,
            fiabilite=fiabilite_globale,
        )


def _derniere_annee(regime) -> int:
    """Dernière année pour laquelle le régime a des paramètres."""
    annees = [p.fin if p.fin is not None else 9999 for p in regime.periodes]
    return min(max(annees), 2100) if annees else 2100


def _ajustement_age_points(periode: PeriodeRegime, age_liquidation: float) -> float:
    """Abattement des régimes en points pour liquidation avant le taux plein."""
    if periode.decote_par_trimestre is None:
        return 1.0
    trimestres_manquants = max(0.0, (periode.age_taux_plein - age_liquidation) * 4)
    return max(0.0, 1.0 - periode.decote_par_trimestre * trimestres_manquants)


def _minimum_contributif(macro: DonneesMacro, annee: int) -> float:
    """Minimum contributif annuel, ancré sur sa valeur 2025 et déflaté.

    Valeur de référence : 733,03 €/mois de minimum contributif majoré au
    1er janvier 2025, soit 8 796 € par an. Grandeur indicative, utilisée
    uniquement par le scénario « système actuel ».
    """
    reference_annee, reference_valeur = 2025, 8796.0
    return reference_valeur * macro.coefficient_prix(reference_annee, annee)
