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
* régimes en points — la pension est calculée **en points** : la cotisation de
  chaque année est divisée par le prix d'achat du point de cette année-là, et le
  total est converti en rente par la valeur de service de l'année de
  liquidation (``regimes/valeurs_point.csv``). Les points d'un régime fermé sont
  convertis dans son successeur au rapport des deux valeurs de service, comme
  l'ont fait l'unification Arrco de 1999 et la fusion Agirc-Arrco de 2019. Les
  régimes dont le dépôt n'a pas les barèmes — CNAVPL, MSA, CNBF — restent
  calculés au rendement instantané (``regimes/rendements_points.csv``), de même
  que les années postérieures au dernier barème publié ;
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


class ValeursPoint:
    """Prix d'achat et valeur de service du point, régime par régime et année.

    Trois grandeurs suffisent à reconstituer exactement une pension en points :

    * le **salaire de référence**, prix d'achat du point l'année de la cotisation ;
    * le **taux d'appel**, qui dit quelle part de la cotisation ouvre des droits —
      depuis 1995, cotiser 125 € n'en acquiert que 100 ;
    * la **valeur de service**, qui convertit les points en rente à la liquidation.

    Les régimes que ce fichier ne couvre pas — CNAVPL, MSA, CNBF — retombent sur
    le rendement instantané de :class:`Rendements`, qui reste l'approximation
    d'origine, tout comme les années postérieures au dernier barème publié.
    """

    def __init__(self, racine: Path) -> None:
        self._table: dict[tuple[str, str], dict[int, tuple[float, Fiabilite]]] = {}
        chemin = racine / "reference" / "regimes" / "valeurs_point.csv"
        if not chemin.exists():
            return
        with chemin.open(encoding="utf-8") as flux:
            lignes = (l for l in flux if not l.lstrip().startswith("#"))
            for ligne in csv.DictReader(lignes):
                cle = (ligne["regime"], ligne["mesure"])
                self._table.setdefault(cle, {})[int(ligne["annee"])] = (
                    float(ligne["valeur"]),
                    Fiabilite.depuis_texte(ligne["fiabilite"]),
                )

    def _en_vigueur(self, regime: str, mesure: str,
                    annee: int) -> tuple[float, Fiabilite] | None:
        """Dernière valeur publiée à l'année demandée, ou avant elle.

        Une valeur reste en vigueur jusqu'à sa modification : c'est la règle de
        lecture d'un barème, et la seule qui ait un sens ici. Rien n'est renvoyé
        pour les années antérieures à la première publication.
        """
        valeurs = self._table.get((regime, mesure))
        if not valeurs:
            return None
        anterieures = [a for a in valeurs if a <= annee]
        return valeurs[max(anterieures)] if anterieures else None

    def achat(self, regime: str, annee: int) -> tuple[float, float, Fiabilite] | None:
        """Prix d'achat effectif d'un point : (salaire de référence, taux d'appel).

        Rien n'est renvoyé au-delà de la dernière année publiée. Prolonger le
        dernier prix connu reviendrait à supposer un barème gelé : les points
        seraient achetés trop bon marché et la pension surestimée. Ces années
        retombent sur le rendement instantané, qui, lui, s'assume approximatif.
        """
        derniere = self._table.get((regime, "salaire_reference"))
        if not derniere or annee > max(derniere):
            return None
        reference = self._en_vigueur(regime, "salaire_reference", annee)
        if reference is None or reference[0] <= 0:
            return None
        appel = self._en_vigueur(regime, "taux_appel", annee)
        taux, fiabilite_appel = appel if appel else (1.0, Fiabilite.MOYENNE)
        return reference[0], taux, min(reference[1], fiabilite_appel)

    def derniere_annee_servie(self, regime: str) -> int | None:
        valeurs = self._table.get((regime, "valeur_service"))
        return max(valeurs) if valeurs else None

    def premiere_annee_servie(self, regime: str) -> int | None:
        valeurs = self._table.get((regime, "valeur_service"))
        return min(valeurs) if valeurs else None

    def service(self, regime: str, annee: int) -> tuple[float, Fiabilite] | None:
        return self._en_vigueur(regime, "valeur_service", annee)


class ScenarioActuel:
    """Calcule la pension servie par le système en vigueur."""

    def __init__(self, macro: DonneesMacro, catalogue: CatalogueRegimes,
                 affiliations: Affiliations, parametres: Parametres) -> None:
        self.macro = macro
        self.catalogue = catalogue
        self.affiliations = affiliations
        self.parametres = parametres
        self.rendements = Rendements(parametres.racine_donnees)
        self.valeurs_point = ValeursPoint(parametres.racine_donnees)

    # -- valorisation des points ---------------------------------------------

    def valeur_du_point(self, code: str,
                        annee_liquidation: int) -> tuple[float, Fiabilite] | None:
        """Ce que vaut, à la liquidation, un point acquis dans ``code``.

        Un régime fermé ne sert plus ses points : ils ont été convertis dans son
        successeur, au rapport des deux valeurs de service à la date de la
        reprise — c'est ce rapport, et lui seul, qui préserve le niveau des
        pensions le jour de la fusion. La méthode remonte donc la chaîne des
        successions (UNIRS -> Arrco -> Agirc-Arrco, Agirc -> Agirc-Arrco,
        IPACTE et IGRANTE -> Ircantec) en cumulant les conversions.

        Quand la chaîne s'arrête avant l'année de liquidation — le successeur
        n'a pas de valeur du point connue — la dernière valeur publiée est
        ramenée en euros de la liquidation par l'indice des prix. C'est une
        approximation, signalée comme telle par la fiabilité renvoyée.
        """
        conversion = 1.0
        courant = code
        fiabilite = Fiabilite.CERTIFIEE
        for _ in range(len(self.catalogue) + 1):  # garde-fou : jamais de boucle
            derniere = self.valeurs_point.derniere_annee_servie(courant)
            if derniere is None:
                return None
            if annee_liquidation <= derniere:
                valeur = self.valeurs_point.service(courant, annee_liquidation)
                return conversion * valeur[0], min(fiabilite, valeur[1])

            successeur = (self.catalogue[courant].integre_dans
                          if courant in self.catalogue else None)
            premiere = (self.valeurs_point.premiere_annee_servie(successeur)
                        if successeur else None)
            if premiere is None:
                ancienne = self.valeurs_point.service(courant, derniere)
                return (
                    conversion * ancienne[0]
                    * self.macro.coefficient_prix(derniere, annee_liquidation),
                    min(fiabilite, ancienne[1], Fiabilite.MOYENNE),
                )

            avant = self.valeurs_point.service(courant, derniere)
            apres = self.valeurs_point.service(successeur, premiere)
            conversion *= avant[0] / apres[0]
            fiabilite = min(fiabilite, avant[1], apres[1])
            courant = successeur
        return None  # pragma: no cover - chaîne de successions cyclique

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

        # Cotisations cumulées par régime, pour les régimes en points dont on
        # n'a pas le prix d'achat du point ; points acquis pour les autres.
        cumul_cotisations: dict[str, float] = {}
        points_acquis: dict[str, float] = {}
        fiabilite_points: dict[str, Fiabilite] = {}
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
                    achat = (self.valeurs_point.achat(code, ligne.annee)
                             if periode.type_calcul in ("points", "mixte") else None)
                    if achat is not None:
                        reference, taux_appel, fiabilite_achat = achat
                        points_acquis[code] = points_acquis.get(code, 0.0) + (
                            cotisation / (taux_appel * reference)
                        )
                        fiabilite_points[code] = min(
                            fiabilite_points.get(code, Fiabilite.CERTIFIEE),
                            fiabilite_achat,
                        )
                    else:
                        cumul_cotisations[code] = cumul_cotisations.get(code, 0.0) + (
                            cotisation
                            * self.macro.coefficient_prix(ligne.annee, annee_liquidation)
                        )
                annees_par_regime[code] = annees_par_regime.get(code, 0) + 1

        for code in sorted(set(cumul_cotisations) | set(points_acquis)):
            cumul = cumul_cotisations.get(code, 0.0)
            regime = self.catalogue[code]
            periode = regime.periode(min(annee_liquidation, _derniere_annee(regime)))
            if periode is None:
                continue
            fiabilite_globale = min(fiabilite_globale, regime.fiabilite)

            if periode.type_calcul in ("points", "mixte"):
                montant = 0.0
                fiabilite_regime = regime.fiabilite
                details = []

                points = points_acquis.get(code, 0.0)
                if points:
                    valeur = self.valeur_du_point(code, annee_liquidation)
                    if valeur is not None:
                        service, fiabilite_service = valeur
                        montant += points * service
                        fiabilite_regime = min(
                            fiabilite_regime, fiabilite_service, fiabilite_points[code]
                        )
                        details.append(
                            f"{points:,.0f} points × valeur de service {service:.4f} €"
                        )

                # Années sans prix d'achat connu : le rendement instantané prend
                # le relais, régime par régime et année par année.
                if cumul:
                    rendement, fiabilite_rendement = self.rendements.rendement(
                        code, min(annee_liquidation, _derniere_annee(regime))
                    )
                    montant += cumul * rendement
                    fiabilite_regime = min(fiabilite_regime, fiabilite_rendement)
                    details.append(
                        f"cotisations revalorisées {cumul:,.0f} € "
                        f"× rendement {rendement:.2%}"
                    )

                fiabilite_globale = min(fiabilite_globale, fiabilite_regime)
                if not ignorer_penalite_age:
                    montant *= _ajustement_age_points(periode, age_liquidation)
                pensions.append(PensionRegime(
                    regime=code, montant=montant, type_calcul=periode.type_calcul,
                    detail=" + ".join(details) or "aucun droit",
                    fiabilite=fiabilite_regime,
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
