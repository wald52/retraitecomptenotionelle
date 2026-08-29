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
* régimes en points — la pension est calculée **en points**. Deux façons de les
  acquérir, selon ce que la caisse publie : par un PRIX D'ACHAT, la cotisation
  de l'année étant divisée par le salaire de référence de cette année-là
  (``regimes/valeurs_point.csv``) ; ou par un BARÈME EN POINTS, le régime
  annonçant combien de points ouvre une assiette donnée — 525 points au plafond
  au régime de base des libéraux, 100 points pour 1 820 SMIC à la complémentaire
  agricole. Le total est converti en rente par la valeur de service de l'année
  de liquidation. Les points d'un régime fermé sont convertis dans son
  successeur au rapport des deux valeurs de service, comme l'ont fait
  l'unification Arrco de 1999 et la fusion Agirc-Arrco de 2019. Restent au
  rendement instantané (``regimes/rendements_points.csv``) la CNBF, le RCI et le
  RAFP, et les années postérieures au dernier barème publié ;
* montée en charge des réformes — cinq paramètres sont lus à la GÉNÉRATION :
  durée requise, âge d'ouverture, âge d'annulation de la décote, coefficient de
  minoration et nombre d'années retenues au salaire de référence. Les taux de
  cotisation, eux, restent ceux de l'année de liquidation.

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


@dataclass(frozen=True)
class AvantageApplique:
    """Effet en euros d'un avantage non contributif du droit positif.

    Les trois avantages s'appliquent dans cet ordre, et l'ordre compte : la
    MDA ajoute des trimestres, donc modifie la décote et la proratisation AVANT
    que la majoration ne multiplie, et le minimum ne comble qu'ensuite. Leurs
    effets s'additionnent exactement au total : c'est ce qui rend la cascade
    vérifiable ligne à ligne.
    """

    code: str
    libelle: str
    montant: float
    detail: str = ""


@dataclass
class ResultatActuel:
    pension_annuelle: float
    pensions_par_regime: list[PensionRegime] = field(default_factory=list)
    #: Avantages non contributifs effectivement appliqués, et leur effet.
    avantages_appliques: list[AvantageApplique] = field(default_factory=list)
    #: Total des pensions de régime avant tout avantage non contributif.
    total_contributif: float = 0.0
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


class TableParGeneration:
    """Paramètre législatif indexé sur l'ANNÉE DE NAISSANCE.

    Depuis la loi du 22 juillet 1993 pour la durée d'assurance, et la loi du
    9 novembre 2010 pour l'âge d'ouverture, les deux paramètres qui commandent
    le taux plein dépendent de la génération et non de l'année de liquidation :
    deux assurés qui liquident le même jour ne se voient pas opposer la même
    exigence. Les lire à l'année de liquidation, comme le faisait ce module,
    opposait aux générations anciennes des règles que la loi ne leur a jamais
    appliquées.

    Lecture en escalier : la valeur d'une génération non renseignée est celle
    de la dernière génération renseignée avant elle, et la dernière valeur du
    fichier vaut pour toutes les générations suivantes — une cible atteinte ne
    bouge plus. En deçà de la première, le paramètre ne dépendait pas encore de
    la génération : on renvoie ``None`` pour que la fiche du régime reprenne la
    main.
    """

    def __init__(self, racine: Path, fichier: str, colonne: str) -> None:
        self._table: dict[int, tuple[float, Fiabilite]] = {}
        chemin = racine / "reference" / "legislation" / fichier
        if not chemin.exists():
            return
        with chemin.open(encoding="utf-8") as flux:
            lignes = (l for l in flux if not l.lstrip().startswith("#"))
            for ligne in csv.DictReader(lignes):
                self._table[int(ligne["generation"])] = (
                    float(ligne[colonne]),
                    Fiabilite.depuis_texte(ligne["fiabilite"]),
                )
        self._generations = sorted(self._table)

    def valeur(self, generation: int) -> tuple[float, Fiabilite] | None:
        if not self._table or generation < self._generations[0]:
            return None
        applicable = self._generations[0]
        for candidate in self._generations:
            if candidate > generation:
                break
            applicable = candidate
        return self._table[applicable]


class DureesRequises(TableParGeneration):
    """Durée d'assurance requise pour le taux plein, par génération."""

    def __init__(self, racine: Path) -> None:
        super().__init__(racine, "duree_assurance_requise.csv", "trimestres")

    def trimestres(self, generation: int) -> tuple[int, Fiabilite] | None:
        valeur = self.valeur(generation)
        return None if valeur is None else (int(valeur[0]), valeur[1])


class AgesOuverture(TableParGeneration):
    """Âge légal d'ouverture des droits, par génération.

    C'est lui qui commande la surcote : seuls les trimestres cotisés au-delà de
    cet âge la déclenchent.
    """

    def __init__(self, racine: Path) -> None:
        super().__init__(racine, "age_ouverture_requis.csv", "age")

    def age(self, generation: int) -> tuple[float, Fiabilite] | None:
        return self.valeur(generation)


class AgesAnnulationDecote(TableParGeneration):
    """Âge d'annulation de la décote, par génération.

    C'est lui qui commande la décote de l'assuré parti tôt : 65 ans jusqu'à la
    génération 1950, 67 à partir de 1955. Les fiches de régime portaient l'âge
    CIBLE de la loi de 2010 dès son entrée en vigueur, opposant 67 ans à des
    générations auxquelles la loi n'a jamais demandé plus de 65.
    """

    def __init__(self, racine: Path) -> None:
        super().__init__(racine, "age_annulation_decote.csv", "age")

    def age(self, generation: int) -> tuple[float, Fiabilite] | None:
        return self.valeur(generation)


class CoefficientsMinoration(TableParGeneration):
    """Coefficient de minoration du taux plein par trimestre manquant."""

    def __init__(self, racine: Path) -> None:
        super().__init__(racine, "coefficient_minoration.csv", "coefficient")

    def coefficient(self, generation: int) -> tuple[float, Fiabilite] | None:
        return self.valeur(generation)


class AnneesSalaireReference(TableParGeneration):
    """Nombre d'années retenues au salaire annuel moyen, par génération."""

    def __init__(self, racine: Path) -> None:
        super().__init__(racine, "annees_salaire_reference.csv", "annees")

    def annees(self, generation: int) -> tuple[int, Fiabilite] | None:
        valeur = self.valeur(generation)
        return None if valeur is None else (int(valeur[0]), valeur[1])


#: Coefficients d'anticipation de l'Agirc-Arrco, sous leur forme de barème.
#: Le régime n'applique pas la décote du régime de base : il a ses propres
#: coefficients, publiés en deux tables — l'une indexée sur les trimestres
#: manquants, l'autre sur l'âge — dont il retient la plus favorable.
#:
#: Les deux tables descendent par paliers réguliers, et c'est cette régularité
#: qu'on écrit ici plutôt que quarante lignes de barème : un point de
#: pourcentage par trimestre jusqu'à douze, un point et quart jusqu'à vingt,
#: un point trois quarts au-delà — ce dernier palier n'existant que dans la
#: table des âges, qui descend jusqu'à 0,43 pour dix ans d'anticipation.
_PALIERS_ANTICIPATION: tuple[tuple[int, float], ...] = (
    (12, 0.01), (20, 0.0125), (40, 0.0175),
)

#: Dernière ligne de la table des âges : dix ans d'anticipation. Au-delà, le
#: barème ne descend plus.
_COEFFICIENT_ANTICIPATION_PLANCHER = 0.43


def _coefficient_anticipation(trimestres_manquants: float,
                              maximum: int) -> float | None:
    """Coefficient d'anticipation Agirc-Arrco pour un nombre de trimestres.

    ``maximum`` est la dernière ligne du barème : vingt trimestres pour la
    table des trimestres manquants, quarante pour celle des âges. Au-delà, la
    table ne dit rien et ``None`` est renvoyé — la prolonger reviendrait à
    inventer un coefficient plus favorable que celui de l'autre table, alors
    que le régime retient la plus avantageuse des deux.

    Les trimestres sont comptés en ENTIERS ARRONDIS AU SUPÉRIEUR : le barème
    est un escalier, et un assuré à qui il manque trois ans et dix mois se voit
    opposer seize trimestres, pas quinze. C'est la lecture que la caisse
    illustre elle-même dans son exemple.
    """
    manquants = max(0, -(-int(round(trimestres_manquants * 1000)) // 1000))
    if manquants <= 0:
        return 1.0
    if manquants > maximum:
        return None
    coefficient = 1.0
    precedent = 0
    for borne, pas in _PALIERS_ANTICIPATION:
        tranche = min(manquants, borne) - precedent
        if tranche > 0:
            coefficient -= tranche * pas
        precedent = borne
        if manquants <= borne:
            break
    return max(0.0, coefficient)


class ValeursPoint:
    """Prix d'achat et valeur de service du point, régime par régime et année.

    Trois grandeurs suffisent à reconstituer exactement une pension en points :

    * le **salaire de référence**, prix d'achat du point l'année de la cotisation ;
    * le **taux d'appel**, qui dit quelle part de la cotisation ouvre des droits —
      depuis 1995, cotiser 125 € n'en acquiert que 100 ;
    * la **valeur de service**, qui convertit les points en rente à la liquidation.

    Les régimes que ce fichier ne couvre pas retombent sur le rendement
    instantané de :class:`Rendements`, qui reste l'approximation d'origine, tout
    comme les années postérieures au dernier barème publié. Ceux dont la caisse
    publie un barème EN POINTS plutôt qu'un prix d'achat — le régime de base des
    libéraux, la complémentaire agricole — n'en ont pas besoin : leur fiche
    porte ``points_maximum``, et seule la valeur de service est lue ici.
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
        self.durees_requises = DureesRequises(parametres.racine_donnees)
        self.ages_ouverture = AgesOuverture(parametres.racine_donnees)
        self.ages_annulation_decote = AgesAnnulationDecote(parametres.racine_donnees)
        self.coefficients_minoration = CoefficientsMinoration(parametres.racine_donnees)
        self.annees_salaire_reference = AnneesSalaireReference(parametres.racine_donnees)
        self.minimum_contributif = MinimumContributif(parametres.racine_donnees, macro)

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
                if valeur is None:
                    # Liquidation antérieure au premier barème publié. Symétrique
                    # du cas ci-dessous : la première valeur connue est ramenée
                    # en euros de la liquidation par l'indice des prix, et la
                    # fiabilité tombe pour le dire.
                    premiere_connue = self.valeurs_point.premiere_annee_servie(courant)
                    ancienne = self.valeurs_point.service(courant, premiere_connue)
                    return (
                        conversion * ancienne[0]
                        * self.macro.coefficient_prix(premiere_connue, annee_liquidation),
                        min(fiabilite, ancienne[1], Fiabilite.MOYENNE),
                    )
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
                             annee_liquidation: int, plafonner: bool,
                             generation: int | None = None) -> float:
        """Salaire de référence, exprimé en euros de l'année de liquidation.

        Deux règles de droit commandent ce calcul, et le modèle les applique
        maintenant l'une et l'autre.

        La première est la **revalorisation des salaires portés au compte** :
        les salaires anciens sont réévalués par les coefficients annuels que
        fixe l'arrêté, lesquels ont suivi les salaires jusqu'en 1986 et suivent
        les prix depuis 1987. Appliquer la règle des prix à toute la période,
        comme le faisait ce module, ramenait au compte les salaires des Trente
        Glorieuses très en dessous de ce que le droit y a inscrit.

        La seconde est le **nombre d'années retenues**, que la loi du 22 juillet
        1993 fait passer de dix à vingt-cinq à raison d'une par génération. Le
        lire à l'année de liquidation opposait vingt-cinq années à des assurés
        auxquels la loi n'en a jamais demandé plus de dix — et étendre la
        moyenne aux années les plus faibles ne peut que l'abaisser.

        Le salaire retenu est celui de l'assiette du régime, et pas la
        rémunération entière : la pension civile porte sur le seul traitement
        indiciaire, primes exclues. C'est le paramètre qui commande le taux de
        remplacement d'un fonctionnaire, puisque les primes n'ouvrent de droit
        qu'au RAFP.
        """
        revenus: list[float] = []
        for ligne in carriere.lignes:
            if not ligne.cotise or ligne.annee >= annee_liquidation:
                continue
            revenu = _assiette_de_reference(periode, ligne)
            if plafonner:
                revenu = min(revenu, self.macro.plafond_securite_sociale(ligne.annee))
            revenus.append(revenu * self.macro.coefficient_revalorisation_salaires(
                ligne.annee, annee_liquidation))

        if not revenus:
            return 0.0

        reference = periode.salaire_reference
        if reference in ("25_meilleures_annees", "10_meilleures_annees"):
            annees = 25 if reference == "25_meilleures_annees" else 10
            if periode.salaire_reference_par_generation and generation is not None:
                par_generation = self.annees_salaire_reference.annees(generation)
                if par_generation is not None:
                    annees = par_generation[0]
            retenus = sorted(revenus, reverse=True)[:annees]
        elif reference in ("derniers_6_mois", "dernier_salaire"):
            return revenus[-1]
        elif reference == "carriere_entiere":
            retenus = revenus
        else:
            retenus = revenus
        return sum(retenus) / len(retenus)

    def _duree_requise(self, periode: PeriodeRegime,
                       carriere: Carriere) -> tuple[int, Fiabilite | None]:
        """Durée requise opposable à cet assuré dans ce régime."""
        requis = periode.duree_requise_trimestres or 160
        if periode.duree_requise_par_generation:
            par_generation = self.durees_requises.trimestres(carriere.annee_naissance)
            if par_generation is not None:
                return par_generation
        return requis, None

    def _age_ouverture(self, periode: PeriodeRegime, carriere: Carriere) -> float:
        """Âge légal opposable à cet assuré dans ce régime."""
        if periode.age_ouverture_par_generation:
            par_generation = self.ages_ouverture.age(carriere.annee_naissance)
            if par_generation is not None:
                return par_generation[0]
        return periode.age_ouverture

    def _age_taux_plein(self, periode: PeriodeRegime, carriere: Carriere) -> float:
        """Âge d'annulation de la décote opposable à cet assuré."""
        if periode.age_taux_plein_par_generation:
            par_generation = self.ages_annulation_decote.age(carriere.annee_naissance)
            if par_generation is not None:
                return par_generation[0]
        return periode.age_taux_plein

    def _decote(self, periode: PeriodeRegime,
                carriere: Carriere) -> tuple[float | None, Fiabilite | None]:
        """Coefficient de minoration opposable à cet assuré dans ce régime.

        Un régime sans décote — fonction publique avant 2004, régimes spéciaux
        avant 2008 — n'en acquiert pas une parce que la table en porte une :
        ``None`` dans la fiche reste ``None`` ici.
        """
        if periode.decote_par_trimestre is None:
            return None, None
        if periode.decote_par_generation:
            par_generation = self.coefficients_minoration.coefficient(
                carriere.annee_naissance
            )
            if par_generation is not None:
                return par_generation
        return periode.decote_par_trimestre, None

    def _trimestres_de_decote(self, periode: PeriodeRegime, carriere: Carriere,
                              trimestres: int, requis: int,
                              age_liquidation: float) -> float:
        """Trimestres de décote opposables, plafond compris.

        Le décompte retient le plus favorable des deux : trimestres manquants
        pour la durée requise, ou trimestres manquants jusqu'à l'âge
        d'annulation de la décote. Et il est PLAFONNÉ — vingt trimestres dans
        tous les régimes qui appliquent une décote. Sans ce plafond, un départ
        dix ans avant l'heure retirait la moitié de la pension là où le droit
        n'en retire que le quart.
        """
        manquants = max(0, requis - trimestres)
        manquants_age = max(
            0.0, (self._age_taux_plein(periode, carriere) - age_liquidation) * 4
        )
        trimestres_decote = min(manquants, manquants_age)
        if periode.decote_trimestres_maximum is not None:
            trimestres_decote = min(trimestres_decote, periode.decote_trimestres_maximum)
        return trimestres_decote

    def _abattement_points(self, periode: PeriodeRegime, carriere: Carriere,
                           trimestres: int, requis: int,
                           age_liquidation: float) -> float:
        """Abattement d'un régime en points liquidé avant le taux plein.

        « Avant le taux plein » est une condition de DURÉE autant que d'âge :
        une complémentaire est servie sans abattement dès que l'assuré a le
        taux plein au régime de base, même s'il liquide avant l'âge d'annulation
        de la décote.

        L'Agirc-Arrco ne reprend pas la décote du régime de base : elle publie
        ses propres COEFFICIENTS D'ANTICIPATION, en deux tables — l'une indexée
        sur les trimestres manquants, l'autre sur l'âge — et retient la plus
        avantageuse pour l'assuré. Les deux ne se recoupent pas : douze
        trimestres manquants valent 0,88, quand la décote du régime de base
        n'en donnerait que 0,85 ; mais dix ans d'anticipation valent 0,43, là
        où elle en donnerait 0,50.
        """
        if periode.abattement_points == "agirc_arrco":
            if trimestres >= requis:
                return 1.0
            par_duree = _coefficient_anticipation(requis - trimestres, 20)
            ecart_age = max(
                0.0, (self._age_taux_plein(periode, carriere) - age_liquidation) * 4
            )
            par_age = _coefficient_anticipation(ecart_age, 40)
            if par_age is None:
                par_age = _COEFFICIENT_ANTICIPATION_PLANCHER
            candidats = [c for c in (par_duree, par_age) if c is not None]
            return max(candidats) if candidats else 1.0

        if periode.decote_par_trimestre is None:
            return 1.0
        decote, _ = self._decote(periode, carriere)
        trimestres_decote = self._trimestres_de_decote(
            periode, carriere, trimestres, requis, age_liquidation
        )
        return max(0.0, 1.0 - (decote or 0.0) * trimestres_decote)

    def _plafond_majoration(self, code: str, periode: PeriodeRegime,
                            carriere: Carriere,
                            annee_liquidation: int) -> float | None:
        """Plafond en euros de la majoration pour enfants, ou ``None``.

        Les régimes de base servent 10 % sans plafond ; l'Agirc-Arrco, elle,
        borne la majoration en euros — 2 367 € par an pour les pensions servies
        depuis le 1er novembre 2025 — et le plafond est revalorisé comme la
        valeur de service du point, à laquelle il est donc rapporté ici. Sans
        lui, les familles très nombreuses de salariés du privé étaient
        surestimées.

        Le plafond ne s'oppose qu'aux assurés nés à compter du 2 août 1951 : le
        modèle ne connaît que l'année de naissance et retient les générations à
        partir de 1952, comme il le fait des autres bornes coupées en cours
        d'année.
        """
        if periode.plafond_majoration_enfants is None:
            return None
        if carriere.annee_naissance < 1952:
            return None
        plafond = periode.plafond_majoration_enfants
        annee_reference = periode.plafond_majoration_annee
        if annee_reference is None or annee_reference == annee_liquidation:
            return plafond
        servie = self.valeur_du_point(code, annee_liquidation)
        publiee = self.valeur_du_point(code, annee_reference)
        if servie is None or publiee is None or publiee[0] <= 0:
            return plafond * self.macro.coefficient_prix(
                annee_reference, annee_liquidation
            )
        return plafond * servie[0] / publiee[0]

    def _regime_porteur_mda(self, trimestres_par_regime: dict[str, int],
                            annee_liquidation: int) -> str | None:
        """Régime auquel sont attribués les trimestres de la MDA.

        Celui, parmi les régimes en annuités dont la fiche porte l'avantage
        ``mda``, où l'assuré a validé le plus de trimestres. Départage par le
        code, pour que le résultat ne dépende pas de l'ordre d'un dictionnaire.
        """
        candidats = []
        for code, valides in trimestres_par_regime.items():
            if code not in self.catalogue:
                continue
            regime = self.catalogue[code]
            periode = regime.periode(min(annee_liquidation, _derniere_annee(regime)))
            if periode is None or periode.type_calcul != "annuites":
                continue
            if "mda" not in periode.avantages_non_contributifs:
                continue
            candidats.append((valides, code))
        return max(candidats, key=lambda c: (c[0], c[1]))[1] if candidats else None

    # -- calcul --------------------------------------------------------------

    def calculer(self, carriere: Carriere,
                 ignorer_penalite_age: bool = False,
                 avantages_non_contributifs: bool = True) -> ResultatActuel:
        """Pension servie par le système en vigueur.

        ``ignorer_penalite_age`` neutralise la décote et la surcote liées à
        l'âge. On ne l'utilise que pour VALORISER DES DROITS ACQUIS à une date
        donnée — la question n'est alors pas « que toucherait cet assuré s'il
        liquidait aujourd'hui à 40 ans », qui n'a pas de sens, mais « quels
        droits sa carrière lui a-t-elle déjà ouverts ». La proratisation par la
        durée, elle, continue de s'appliquer : une carrière courte ouvre bien
        des droits proportionnellement plus faibles.

        ``avantages_non_contributifs`` commande le minimum contributif, la
        majoration pour trois enfants et la majoration de durée d'assurance.
        Il vaut VRAI par défaut, et il doit le rester : ce scénario décrit le
        droit positif, il sert d'étalon, et un étalon amputé de ses minima
        sous-estime le système actuel là où il protège le plus — petites
        pensions et carrières de mères de famille. Seule la valorisation des
        droits acquis du scénario prospectif le met à faux, parce qu'elle
        mesure du contributif pur.

        Les drapeaux :class:`Neutralisations` ne sont PAS lus ici : ils
        décrivent ce que les scénarios notionnels retirent, pas ce que le droit
        en vigueur accorde.
        """
        annee_liquidation = carriere.annee_liquidation
        age_liquidation = carriere.age_liquidation or 0.0

        trimestres = carriere.trimestres_actuels
        trimestres_mda = (
            8 * carriere.nombre_enfants if avantages_non_contributifs else 0
        )
        trimestres += trimestres_mda

        pensions: list[PensionRegime] = []
        fiabilite_globale = Fiabilite.CERTIFIEE
        trimestres_requis = 0
        taux_retenu = 0.0

        #: Indice dans ``pensions`` et prorata de durée des régimes de base qui
        #: portent le minimum contributif.
        eligibles_minimum: list[tuple[int, float]] = []

        # Cotisations cumulées par régime, pour les régimes en points dont on
        # n'a pas le prix d'achat du point ; points acquis pour les autres.
        cumul_cotisations: dict[str, float] = {}
        points_acquis: dict[str, float] = {}
        fiabilite_points: dict[str, Fiabilite] = {}
        # Durée d'assurance validée dans chaque régime, PÉRIODES ASSIMILÉES
        # COMPRISES : le coefficient de proratisation du régime général porte
        # sur la durée d'assurance, pas sur les seules années cotisées. Une
        # année de chômage indemnisé ne verse rien au compte mais compte bien
        # dans le rapport durée acquise / durée requise.
        trimestres_par_regime: dict[str, int] = {}

        for ligne in carriere.lignes:
            if ligne.annee >= annee_liquidation:
                continue
            for code in self.affiliations.regimes(ligne.affiliation, ligne.annee):
                if code not in self.catalogue:
                    continue
                trimestres_par_regime[code] = (
                    trimestres_par_regime.get(code, 0) + ligne.trimestres_valides
                )

        # Les trimestres de la majoration de durée d'assurance ne flottent pas
        # au-dessus des régimes : le droit les attribue DANS un régime, et ils
        # comptent donc aussi dans sa proratisation, pas seulement dans la
        # décote tous régimes confondus. Les ignorer là amputait la pension
        # d'une mère de famille de la part que la MDA est censée lui rendre.
        # Faute de connaître l'année de naissance des enfants, ils vont au
        # régime de base où l'assuré a validé le plus de trimestres parmi ceux
        # qui portent la MDA — exact pour une carrière mono-affiliée, qui est
        # le cas ordinaire, approché pour un polypensionné.
        if trimestres_mda:
            regime_mda = self._regime_porteur_mda(
                trimestres_par_regime, annee_liquidation
            )
            if regime_mda is not None:
                trimestres_par_regime[regime_mda] += trimestres_mda

        for ligne in carriere.lignes:
            if not ligne.cotise and not ligne.familles_cotisantes:
                continue
            # Pendant une période indemnisée, seuls les régimes complémentaires
            # encaissent, et sur le salaire d'avant l'interruption.
            base_ligne = ligne.revenu if ligne.cotise else ligne.revenu_reference
            familles_admises = (
                None if ligne.cotise else set(ligne.familles_cotisantes)
            )
            for code in self.affiliations.regimes(ligne.affiliation, ligne.annee):
                if code not in self.catalogue:
                    continue
                regime = self.catalogue[code]
                if (familles_admises is not None
                        and regime.famille not in familles_admises):
                    continue
                for periode in regime.periodes_actives(ligne.annee):
                    borne_basse, borne_haute = periode.bornes_assiette_en_pass()
                    pass_annuel = self.macro.plafond_securite_sociale(ligne.annee)
                    base = base_ligne
                    if periode.assiette == "primes_uniquement":
                        base = base_ligne * ligne.part_primes
                    elif periode.assiette == "hors_primes":
                        base = base_ligne * (1.0 - ligne.part_primes)
                    plafond = (
                        base if borne_haute is None else borne_haute * pass_annuel
                    )
                    assiette = max(0.0, min(base, plafond) - borne_basse * pass_annuel)
                    repere = periode.repere_assiette(
                        pass_annuel, self.macro.smic_horaire(ligne.annee)
                    )
                    if periode.assiette_plancher and assiette < repere:
                        # Assiette minimale : la complémentaire agricole cotise
                        # sur 1 820 SMIC même quand le revenu est en dessous,
                        # et ouvre donc ses cent points malgré tout.
                        assiette = repere
                    cotisation = assiette * periode.taux_cotisation_retraite
                    if periode.points_maximum is not None and repere > 0:
                        # Barème écrit en POINTS et non en prix d'achat : le
                        # régime annonce combien de points ouvre une assiette
                        # donnée — 525 points au plafond pour le régime de base
                        # des libéraux, 100 points pour 1 820 SMIC à la
                        # complémentaire agricole. Le nombre de points ne
                        # dépend alors pas du taux de cotisation, et c'est
                        # heureux : ce sont les barèmes qui sont publiés, pas
                        # les prix d'achat.
                        points_acquis[code] = points_acquis.get(code, 0.0) + (
                            periode.points_maximum * assiette / repere
                        )
                        fiabilite_points[code] = min(
                            fiabilite_points.get(code, Fiabilite.CERTIFIEE),
                            regime.fiabilite,
                        )
                        continue
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

        # Durée requise de référence : celle du régime de base. C'est elle qui
        # commande le taux plein, donc aussi l'abattement des complémentaires —
        # un assuré au taux plein liquide sa complémentaire sans abattement,
        # quel que soit son âge.
        requis_reference = 0
        for code in sorted(set(cumul_cotisations) | set(points_acquis)):
            regime = self.catalogue[code]
            periode = regime.periode(min(annee_liquidation, _derniere_annee(regime)))
            if periode is None or periode.type_calcul != "annuites":
                continue
            requis_reference = max(
                requis_reference, self._duree_requise(periode, carriere)[0]
            )
        requis_reference = requis_reference or 160

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
                    montant *= self._abattement_points(
                        periode, carriere, trimestres, requis_reference,
                        age_liquidation,
                    )
                pensions.append(PensionRegime(
                    regime=code, montant=montant, type_calcul=periode.type_calcul,
                    detail=" + ".join(details) or "aucun droit",
                    fiabilite=fiabilite_regime,
                ))
                continue

            # Régimes en annuités.
            plafonner = periode.assiette in ("plafonnee", "tranche_1", "tranche_a")
            salaire_reference = self.salaire_de_reference(
                carriere, periode, annee_liquidation, plafonner,
                carriere.annee_naissance,
            )
            requis, fiabilite_duree = self._duree_requise(periode, carriere)
            if fiabilite_duree is not None:
                fiabilite_globale = min(fiabilite_globale, fiabilite_duree)
            trimestres_requis = max(trimestres_requis, requis)
            trimestres_regime = min(trimestres_par_regime.get(code, 0), requis)

            taux = periode.taux_plein or 0.5
            if not ignorer_penalite_age:
                decote, fiabilite_decote = self._decote(periode, carriere)
                trimestres_decote = self._trimestres_de_decote(
                    periode, carriere, trimestres, requis, age_liquidation
                )
                if decote and trimestres_decote > 0:
                    # Les régimes sans décote (fonction publique avant 2004,
                    # régimes spéciaux avant 2008) ne subissent que la
                    # proratisation : leur `decote_par_trimestre` est nul.
                    if fiabilite_decote is not None:
                        fiabilite_globale = min(fiabilite_globale, fiabilite_decote)
                    taux *= max(0.0, 1.0 - decote * trimestres_decote)
                # La surcote ne récompense que les trimestres COTISÉS APRÈS
                # l'âge légal ET au-delà de la durée requise. Les compter tous
                # majorait la pension de qui a commencé tôt sans jamais
                # travailler au-delà de l'âge d'ouverture.
                supplementaires = max(0, trimestres - requis)
                age_ouverture = self._age_ouverture(periode, carriere)
                if (periode.surcote_par_trimestre and supplementaires > 0
                        and age_liquidation >= age_ouverture):
                    supplementaires = min(
                        supplementaires,
                        _trimestres_cotises_apres(
                            carriere, age_ouverture, annee_liquidation
                        ),
                    )
                    if supplementaires > 0:
                        taux *= 1.0 + periode.surcote_par_trimestre * supplementaires

            taux_retenu = max(taux_retenu, taux)
            montant = salaire_reference * taux * (trimestres_regime / requis)
            if "minimum_contributif" in periode.avantages_non_contributifs:
                # Le minimum ne relève que les régimes de base qui le portent,
                # et au prorata de la durée acquise DANS CE régime.
                eligibles_minimum.append((len(pensions), trimestres_regime / requis))
            pensions.append(PensionRegime(
                regime=code, montant=montant, type_calcul="annuites",
                detail=(
                    f"SR {salaire_reference:,.0f} € × taux {taux:.2%} "
                    f"× {trimestres_regime}/{requis}"
                ),
                fiabilite=regime.fiabilite,
            ))

        total = sum(p.montant for p in pensions)
        total_contributif = total
        avantages: list[AvantageApplique] = []

        # Avantages non contributifs du droit positif, dans l'ordre où le droit
        # les applique : durée d'assurance, puis majoration, puis minimum.
        minimum_applique = False

        if avantages_non_contributifs and carriere.nombre_enfants > 0:
            # Effet de la MDA : la même carrière sans les huit trimestres par
            # enfant, tout le reste égal. C'est la seule façon d'isoler un
            # avantage qui agit sur la décote et sur la proratisation.
            sans_mda = self.calculer(
                carriere, ignorer_penalite_age, avantages_non_contributifs=False
            )
            effet = total - sans_mda.total_contributif
            # La MDA est déjà incorporée aux pensions de régime : la base
            # contributive de la cascade est celle d'AVANT, sans quoi son effet
            # serait compté deux fois.
            total_contributif = sans_mda.total_contributif
            if abs(effet) > 1e-9:
                avantages.append(AvantageApplique(
                    code="majoration_duree_assurance",
                    libelle="Majoration de durée d'assurance",
                    montant=effet,
                    detail=f"{8 * carriere.nombre_enfants} trimestres pour "
                           f"{carriere.nombre_enfants} enfant"
                           f"{'s' if carriere.nombre_enfants > 1 else ''}",
                ))

        if avantages_non_contributifs and carriere.nombre_enfants >= 3:
            majoration = 0.0
            taux_cite = 0.0
            # Le plafond de l'Agirc-Arrco s'oppose à la majoration de LA
            # complémentaire, pas à celle de chacune de ses fiches : les points
            # d'un salarié du privé sont répartis entre l'Agirc, l'Arrco et le
            # régime unifié, et plafonner chacun séparément reviendrait à
            # tripler le plafond. On les met donc dans un même seau.
            majoration_plafonnee = 0.0
            plafond_commun: float | None = None
            for pension in pensions:
                regime = self.catalogue[pension.regime]
                periode = regime.periode(min(annee_liquidation, _derniere_annee(regime)))
                if periode is None:
                    continue
                if "majoration_enfants" not in periode.avantages_non_contributifs:
                    continue
                taux = _taux_majoration_enfants(regime, carriere.nombre_enfants)
                part = pension.montant * taux
                plafond = self._plafond_majoration(
                    pension.regime, periode, carriere, annee_liquidation
                )
                if plafond is None:
                    majoration += part
                else:
                    majoration_plafonnee += part
                    plafond_commun = (plafond if plafond_commun is None
                                      else max(plafond_commun, plafond))
                taux_cite = max(taux_cite, taux)
            plafonnee = plafond_commun is not None
            if plafond_commun is not None:
                majoration += min(majoration_plafonnee, plafond_commun)
            if majoration > 0:
                total += majoration
                detail = f"jusqu'à {taux_cite:.0%} selon le régime"
                if plafonnee:
                    detail += ", plafonnée en euros à la complémentaire"
                avantages.append(AvantageApplique(
                    code="majoration_enfants",
                    libelle="Majoration pour trois enfants et plus",
                    montant=majoration,
                    detail=detail,
                ))

        if avantages_non_contributifs and eligibles_minimum:
            montant_minimum, plafond, fiabilite_minimum = (
                self.minimum_contributif.valeurs(annee_liquidation)
            )
            releve = 0.0
            for indice, prorata in eligibles_minimum:
                pension = pensions[indice]
                plancher = montant_minimum * min(1.0, prorata)
                if 0 < pension.montant < plancher:
                    releve += plancher - pension.montant
            if releve > 0:
                # Écrêtement : le complément est rogné de ce qui dépasse le
                # plafond, tous régimes confondus, et jamais au-delà.
                releve = max(0.0, min(releve, plafond - total))
            if releve > 0:
                total += releve
                minimum_applique = True
                fiabilite_globale = min(fiabilite_globale, fiabilite_minimum)
                avantages.append(AvantageApplique(
                    code="minimum_contributif",
                    libelle="Minimum contributif",
                    montant=releve,
                    detail="portée au plancher, au prorata de la durée acquise",
                ))

        return ResultatActuel(
            pension_annuelle=total,
            pensions_par_regime=pensions,
            avantages_appliques=avantages,
            total_contributif=total_contributif,
            trimestres_valides=trimestres,
            trimestres_requis=trimestres_requis,
            taux_liquidation=taux_retenu,
            minimum_applique=minimum_applique,
            fiabilite=fiabilite_globale,
        )


def _taux_majoration_enfants(regime, nombre_enfants: int) -> float:
    """Taux de majoration pour enfants, régime par régime.

    Le régime général et les régimes spéciaux servent 10 % à partir de trois
    enfants. La fonction publique y ajoute 5 % par enfant au-delà du troisième.
    Les complémentaires servent 10 % aussi, mais plafonnés en euros : le taux
    est le même, c'est :meth:`ScenarioActuel._plafond_majoration` qui borne.
    """
    if nombre_enfants < 3:
        return 0.0
    if regime.famille == "fonction_publique":
        return 0.10 + 0.05 * (nombre_enfants - 3)
    return 0.10


def _trimestres_cotises_apres(carriere: Carriere, age: float,
                              annee_liquidation: int) -> int:
    """Trimestres cotisés à partir de l'année où l'assuré atteint ``age``.

    Seuls ceux-là ouvrent droit à la surcote : c'est une récompense du travail
    prolongé, pas de l'entrée précoce dans la vie active.
    """
    return sum(
        ligne.trimestres_valides
        for ligne in carriere.lignes
        if ligne.cotise
        and ligne.annee < annee_liquidation
        and ligne.annee - carriere.annee_naissance >= age
    )


def _assiette_de_reference(periode: PeriodeRegime, ligne) -> float:
    """Part de la rémunération que ce régime prend en compte.

    Même découpage que dans la boucle de cotisation : un régime qui ne cotise
    que sur le traitement indiciaire ne peut pas liquider sur la rémunération
    primes comprises, sans quoi les primes ouvriraient deux fois des droits —
    au RAFP et à la pension civile — alors qu'elles n'en ouvrent qu'au RAFP.
    """
    if periode.assiette == "primes_uniquement":
        return ligne.revenu * ligne.part_primes
    if periode.assiette == "hors_primes":
        return ligne.revenu * (1.0 - ligne.part_primes)
    return ligne.revenu


def _derniere_annee(regime) -> int:
    """Dernière année pour laquelle le régime a des paramètres."""
    annees = [p.fin if p.fin is not None else 9999 for p in regime.periodes]
    return min(max(annees), 2100) if annees else 2100


class MinimumContributif:
    """Montant du minimum contributif et plafond d'écrêtement, par année.

    Deux grandeurs, et pas une seule : le minimum ne se contente pas de
    relever une petite pension de base, il est ÉCRÊTÉ dès que l'ensemble des
    pensions de l'assuré dépasse un plafond (article L. 173-2). Sans cette
    seconde condition, le modèle servait le minimum à des assurés que leurs
    régimes complémentaires placent déjà bien au-dessus.

    Les deux valeurs sont pour l'instant `estimee` : elles n'ont pas été
    confrontées à la source, et le résultat qui les emploie en hérite.
    """

    def __init__(self, racine: Path, macro: DonneesMacro) -> None:
        self.macro = macro
        self._table: dict[int, tuple[float, float, Fiabilite]] = {}
        chemin = racine / "reference" / "legislation" / "minimum_contributif.csv"
        if not chemin.exists():
            return
        with chemin.open(encoding="utf-8") as flux:
            lignes = (l for l in flux if not l.lstrip().startswith("#"))
            for ligne in csv.DictReader(lignes):
                self._table[int(ligne["annee"])] = (
                    float(ligne["montant"]), float(ligne["plafond"]),
                    Fiabilite.depuis_texte(ligne["fiabilite"]),
                )

    def valeurs(self, annee: int) -> tuple[float, float, Fiabilite]:
        """Montant et plafond de l'année, déflatés depuis l'année connue."""
        if not self._table:
            return 0.0, 0.0, Fiabilite.ESTIMEE
        reference = min(self._table, key=lambda a: abs(a - annee))
        montant, plafond, fiabilite = self._table[reference]
        coefficient = self.macro.coefficient_prix(reference, annee)
        return montant * coefficient, plafond * coefficient, fiabilite
