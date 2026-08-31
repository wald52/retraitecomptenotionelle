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
* trois horloges, comme dans le droit — ce qui s'ACQUIERT est lu à l'année
  travaillée (taux de cotisation, assiette, plafond, prix d'achat du point,
  heures pour valider un trimestre) ; ce qui commande la MONTÉE EN CHARGE des
  réformes est lu à la GÉNÉRATION (durée requise, âge d'ouverture, âge
  d'annulation de la décote, coefficient de minoration, années retenues au
  salaire de référence) ; ce qui LIQUIDE est lu à l'année de liquidation
  (formule du régime, valeur de service du point, barèmes des minima) ;
* avantages datés — la fiche de chaque période dit ce que le régime accordait
  cette année-là, et le moteur ne sert que cela : ni minimum contributif avant
  1983, ni surcote avant 2004, ni trimestres pour enfants avant 1972.

Un écart de quelques pour cent avec la pension réelle est donc attendu.
Ce que le modèle mesure de façon robuste, ce sont les ÉCARTS ENTRE SCÉNARIOS,
tous calculés sur les mêmes carrières et les mêmes séries.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field, replace
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


@dataclass(frozen=True)
class _MajorationEnfants:
    """Trimestres dus au titre des enfants, et régime qui les porte."""

    #: Code du régime dans lequel le droit attribue les trimestres.
    regime: str
    #: Dispositif qui les accorde : ``mda`` ou ``bonifications``.
    dispositif: str
    #: Trimestres accordés au total, tous enfants confondus.
    trimestres: int
    fiabilite: Fiabilite


#: Ce que chaque dispositif s'appelle dans la cascade des avantages.
_LIBELLE_MAJORATION = {
    "mda": "Majoration de durée d'assurance",
    "bonifications": "Bonification pour enfants",
}


@dataclass(frozen=True)
class _EligibleMinimum:
    """Régime de base susceptible d'être porté au minimum contributif.

    Quatre grandeurs, et pas une seule, parce que le droit en demande quatre :
    la pension à relever, les deux fractions de durée qui proratisent le
    montant de base et sa majoration, la condition de taux plein qui ouvre le
    droit, et le coefficient de surcote qu'il faut retirer avant de comparer
    au plancher puis rendre après.
    """

    #: Indice de la pension dans ``ResultatActuel.pensions_par_regime``.
    indice: int
    #: Durée d'assurance acquise dans le régime / durée requise, bornée à 1.
    prorata_assurance: float
    #: Durée COTISÉE acquise dans le régime / durée requise, bornée à 1.
    prorata_cotise: float
    #: La pension est-elle liquidée au taux plein dans ce régime ?
    taux_plein: bool
    #: Coefficient de surcote déjà incorporé au montant de la pension.
    surcote: float = 1.0


@dataclass(frozen=True)
class _EligibleMinimumGaranti:
    """Régime de la fonction publique susceptible d'atteindre son plancher."""

    #: Indice de la pension dans ``ResultatActuel.pensions_par_regime``.
    indice: int
    #: Durée de services acquise dans le régime, en trimestres.
    trimestres_services: int
    #: La pension est-elle liquidée au taux plein, ou l'assuré atteignait-il
    #: l'âge d'ouverture de ses droits avant 2011 ?
    ouvert: bool


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
    #: Âge le plus précoce auquel le droit ouvre cette liquidation, tous
    #: dispositifs compris. ``None`` quand aucun régime en annuités n'en fixe.
    age_ouverture_opposable: float | None = None
    #: La liquidation demandée est-elle ouverte par le droit à cet âge ?
    #: Quand elle ne l'est pas, le montant reste calculé — il faut bien
    #: comparer les scénarios sur la même carrière — mais il ne décrit aucune
    #: pension que le système actuel servirait. C'est un contrefactuel, et le
    #: modèle le dit maintenant au lieu de le laisser croire.
    liquidation_ouverte: bool = True
    #: Ce qui ouvre la liquidation : ``age_legal``, ``carriere_longue``, ou
    #: ``non_ouverte``.
    motif_ouverture: str = "age_legal"
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


def _au_trimestre_superieur(trimestres: float) -> int:
    """Nombre de trimestres arrondi à l'entier supérieur, jamais négatif.

    C'est la règle de l'article R. 351-27 pour la décote, et celle que la
    caisse illustre dans son exemple pour les coefficients d'anticipation : un
    assuré à qui il manque trois ans et dix mois se voit opposer seize
    trimestres, pas quinze. La tolérance de 10⁻³ évite qu'un flottant tout juste
    au-dessus d'un entier n'en fasse compter un de plus.
    """
    return max(0, -(-int(round(trimestres * 1000)) // 1000))


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
    manquants = _au_trimestre_superieur(trimestres_manquants)
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


class MajorationsPourEnfants:
    """Trimestres accordés au titre des enfants, dispositif par dispositif.

    Le module en servait huit par enfant, à tout assuré, à toute date et dans
    tout régime. Le droit n'en a jamais servi autant : la majoration de durée
    d'assurance n'existe pas avant 1972, elle vaut un an par enfant jusqu'en
    1974, elle est attribuée à la mère, et la fonction publique ne l'applique
    pas — elle a sa propre bonification, qui vaut un an par enfant né avant
    2004 et deux trimestres pour les enfants nés depuis. Un père de trois
    enfants recevait ainsi douze trimestres que la loi ne lui a jamais donnés,
    de quoi effacer une décote entière.

    Le fichier ``legislation/majoration_duree_assurance.csv`` porte ces règles
    et leurs dates ; le ``dispositif`` de chaque ligne reprend le code que la
    fiche de régime déclare dans ``avantages_non_contributifs``, de sorte que
    c'est la fiche qui dit quel régime accorde quoi, et la table combien.

    Deux horloges, et la distinction est dans les textes : la MDA se lit à
    l'ANNÉE DE LIQUIDATION, puisque c'est le droit en vigueur au départ qui la
    sert ; la bonification se lit à l'ANNÉE DE NAISSANCE DE L'ENFANT, que
    l'article désigne expressément.
    """

    #: Âge présumé de la mère à la naissance de ses enfants. Le modèle ne
    #: collecte pas leur date de naissance ; il la déduit de cette convention,
    #: qui est l'âge moyen des mères à l'accouchement (vingt-huit ans dans les
    #: années 1980, trente et un aujourd'hui — INSEE, état civil). Elle ne
    #: commande qu'une bascule, celle des quatre trimestres aux deux
    #: trimestres de la fonction publique, et c'est pourquoi les lignes qui en
    #: dépendent sont au niveau « moyenne ».
    AGE_PRESUME_A_LA_NAISSANCE = 30

    def __init__(self, racine: Path) -> None:
        self._table: list[tuple[str, str, int, int, int, int, str, Fiabilite]] = []
        chemin = (racine / "reference" / "legislation"
                  / "majoration_duree_assurance.csv")
        if not chemin.exists():
            return
        with chemin.open(encoding="utf-8") as flux:
            lignes = (l for l in flux if not l.lstrip().startswith("#"))
            for ligne in csv.DictReader(lignes):
                self._table.append((
                    ligne["dispositif"],
                    ligne["reference"],
                    int(ligne["debut"]),
                    int(ligne["fin"]),
                    int(ligne["trimestres_par_enfant"]),
                    int(ligne["enfants_minimum"]),
                    ligne["beneficiaire"],
                    Fiabilite.depuis_texte(ligne["fiabilite"]),
                ))

    def par_enfant(self, dispositif: str, sexe: str, annee_naissance: int,
                   annee_liquidation: int,
                   nombre_enfants: int) -> tuple[int, Fiabilite] | None:
        """Trimestres accordés PAR ENFANT, ou ``None`` si rien n'est dû.

        ``None`` couvre les quatre cas où le droit ne donne rien : le
        dispositif n'existe pas encore à la date qui le commande, il n'a jamais
        existé dans ce régime, l'assuré n'en est pas le bénéficiaire, ou il n'a
        pas élevé le nombre d'enfants que la ligne exige — la loi Boulin
        demandait deux enfants là où les suivantes se contentent d'un.
        """
        for (code, reference, debut, fin, trimestres, enfants_minimum,
             beneficiaire, fiabilite) in self._table:
            if code != dispositif:
                continue
            annee = (annee_liquidation if reference == "liquidation"
                     else annee_naissance + self.AGE_PRESUME_A_LA_NAISSANCE)
            if not debut <= annee <= fin:
                continue
            if beneficiaire == "mere" and sexe != "F":
                return None
            if nombre_enfants < enfants_minimum:
                return None
            return trimestres, fiabilite
        return None


class SurcoteParentale:
    """Surcote parentale — article L. 351-1-2-1 du code de la sécurité sociale.

    Le dernier avantage familial créé par le droit, et la contrepartie directe
    du recul de l'âge légal : un assuré qui avait sa durée requise à 63 ans
    s'est vu imposer par la loi du 14 avril 2023 une année de travail de plus
    qui ne lui rapportait rien, la surcote ordinaire ne récompensant que les
    trimestres accomplis APRÈS l'âge légal. La loi comble ce trou pour les
    seuls parents : 1,25 % par trimestre acquis entre 63 ans et l'âge légal,
    quatre trimestres au plus, à qui détient au moins un trimestre de
    majoration de durée d'assurance au titre des enfants.

    C'est ce trimestre-là qui ouvre le droit, et non le sexe : un père qui
    détient des trimestres pour enfants y a droit comme la mère.
    """

    def __init__(self, racine: Path) -> None:
        self._table: list[tuple[int, int, float, float, int, Fiabilite]] = []
        chemin = racine / "reference" / "legislation" / "surcote_parentale.csv"
        if not chemin.exists():
            return
        with chemin.open(encoding="utf-8") as flux:
            lignes = (l for l in flux if not l.lstrip().startswith("#"))
            for ligne in csv.DictReader(lignes):
                self._table.append((
                    int(ligne["debut"]),
                    int(ligne["fin"]),
                    float(ligne["age_ouverture"]),
                    float(ligne["taux_par_trimestre"]),
                    int(ligne["trimestres_maximum"]),
                    Fiabilite.depuis_texte(ligne["fiabilite"]),
                ))

    def parametres(self, annee_liquidation: int
                   ) -> tuple[float, float, int, Fiabilite] | None:
        """Âge d'ouverture, taux par trimestre, plafond et fiabilité."""
        for debut, fin, age, taux, maximum, fiabilite in self._table:
            if debut <= annee_liquidation <= fin:
                return age, taux, maximum, fiabilite
        return None


class DecoteFonctionPublique:
    """Barème de décote de l'article L. 14 du code des pensions.

    Deux paramètres, lus à l'ANNÉE DE LIQUIDATION parce que la montée en charge
    voulue par la loi du 21 août 2003 est calendaire et non générationnelle :

    * le **coefficient** de minoration par trimestre, d'un huitième de point
      par an de 0,125 % en 2006 à 1,25 % en 2015 ;
    * le nombre de **trimestres retranchés à la limite d'âge** pour obtenir
      l'âge d'annulation de la décote, de seize en 2006 à zéro en 2020.

    Rien avant 2006 : la décote n'existait pas dans la fonction publique.
    """

    def __init__(self, racine: Path) -> None:
        self._table: dict[int, tuple[int, float, Fiabilite]] = {}
        chemin = racine / "reference" / "legislation" / "decote_fonction_publique.csv"
        if not chemin.exists():
            return
        with chemin.open(encoding="utf-8") as flux:
            lignes = (l for l in flux if not l.lstrip().startswith("#"))
            for ligne in csv.DictReader(lignes):
                self._table[int(ligne["annee"])] = (
                    int(ligne["trimestres_avant_limite"]),
                    float(ligne["coefficient"]),
                    Fiabilite.depuis_texte(ligne["fiabilite"]),
                )
        self._annees = sorted(self._table)

    def parametres(self, annee: int) -> tuple[int, float, Fiabilite] | None:
        """Barème en vigueur l'année demandée, ou ``None`` avant sa création."""
        if not self._table or annee < self._annees[0]:
            return None
        applicable = self._annees[0]
        for candidate in self._annees:
            if candidate > annee:
                break
            applicable = candidate
        return self._table[applicable]


class MinimumVieillesse:
    """Allocation de solidarité aux personnes âgées (ASPA).

    Le dernier plancher du système actuel, et le seul qui ne suppose aucune
    cotisation : une allocation DIFFÉRENTIELLE qui porte les ressources au
    montant du barème. Ce n'est pas une pension — elle est soumise à condition
    d'âge, de ressources du foyer et de demande, et récupérable sur les
    successions —, d'où la ligne séparée dans la cascade et le paramètre qui
    permet de la retirer.
    """

    #: Âge d'ouverture de droit commun. L'âge légal suffit en cas d'inaptitude,
    #: que le modèle ne connaît pas.
    AGE_OUVERTURE = 65

    def __init__(self, racine: Path, macro: DonneesMacro) -> None:
        self.macro = macro
        self._table: dict[int, tuple[float, Fiabilite]] = {}
        chemin = racine / "reference" / "legislation" / "minimum_vieillesse.csv"
        if not chemin.exists():
            return
        with chemin.open(encoding="utf-8") as flux:
            lignes = (l for l in flux if not l.lstrip().startswith("#"))
            for ligne in csv.DictReader(lignes):
                self._table[int(ligne["annee"])] = (
                    float(ligne["valeur"]),
                    Fiabilite.depuis_texte(ligne["fiabilite"]),
                )
        self._annees = sorted(self._table)

    def plafond(self, annee: int) -> tuple[float, Fiabilite] | None:
        """Montant maximal d'une personne seule, l'année demandée."""
        if not self._table:
            return None
        if annee in self._table:
            return self._table[annee]
        anterieures = [a for a in self._annees if a < annee]
        ancre = max(anterieures) if anterieures else self._annees[0]
        valeur, fiabilite = self._table[ancre]
        return valeur * self.macro.coefficient_prix(ancre, annee), fiabilite


class CarriereLongue:
    """Départ anticipé pour carrière longue — article L. 351-1-1.

    La principale porte d'entrée avant l'âge légal, et la seule qui se déduise
    de la carrière elle-même : la pénibilité, l'invalidité et l'inaptitude
    demandent des informations que le modèle n'a pas.
    """

    def __init__(self, racine: Path) -> None:
        self._table: dict[int, list[tuple[int, int, float, int, Fiabilite]]] = {}
        chemin = racine / "reference" / "legislation" / "carriere_longue.csv"
        if not chemin.exists():
            return
        with chemin.open(encoding="utf-8") as flux:
            lignes = (l for l in flux if not l.lstrip().startswith("#"))
            for ligne in csv.DictReader(lignes):
                self._table.setdefault(int(ligne["annee"]), []).append((
                    int(ligne["age_debut_maximum"]),
                    int(ligne["trimestres_debut"]),
                    float(ligne["age_depart"]),
                    int(ligne["trimestres_supplementaires"]),
                    Fiabilite.depuis_texte(ligne["fiabilite"]),
                ))
        self._annees = sorted(self._table)

    def age_de_depart(self, carriere: Carriere, annee_liquidation: int,
                      trimestres_cotises: int,
                      requis: int) -> tuple[float, Fiabilite] | None:
        """Âge le plus précoce ouvert par le dispositif, ou ``None``.

        La condition d'entrée précoce se lit sur les trimestres COTISÉS validés
        avant la fin de l'année civile des seize, dix-huit, vingt ou vingt et un
        ans. La condition de durée porte, elle aussi, sur les seuls trimestres
        cotisés — c'est ce qui distingue ce dispositif de la durée d'assurance
        qui commande la décote.
        """
        if not self._table or annee_liquidation < self._annees[0]:
            return None
        applicable = self._annees[0]
        for candidate in self._annees:
            if candidate > annee_liquidation:
                break
            applicable = candidate

        ouvertures = []
        for age_max, trimestres_debut, age_depart, supplement, fiabilite in \
                self._table[applicable]:
            acquis = sum(
                ligne.trimestres_valides for ligne in carriere.lignes
                if ligne.cotise
                and ligne.annee <= carriere.annee_naissance + age_max
                and ligne.annee < annee_liquidation
            )
            if acquis < trimestres_debut:
                continue
            if trimestres_cotises < requis + supplement:
                continue
            ouvertures.append((age_depart, fiabilite))
        return min(ouvertures) if ouvertures else None


class MinimumGaranti:
    """Minimum garanti de la fonction publique — article L. 17 du code des
    pensions civiles et militaires de retraite.

    Le pendant, dans la fonction publique, du minimum contributif du privé. Il
    n'en a ni la forme ni la logique : ce n'est pas un plancher proratisé, mais
    un BARÈME EN ESCALIER sur la durée de services, rapporté à un traitement de
    référence gelé — celui de l'indice majoré 227 au 1er janvier 2004,
    revalorisé sur les prix depuis. Une durée de quinze ans en ouvre 57,5 %,
    trente ans 95 %, quarante ans la totalité.

    Le module ne le servait pas, alors que les fiches de régime le déclarent et
    que les Neutralisations annoncent le retirer dans les scénarios notionnels.
    On ne retire pas ce qui n'a jamais été mis : le fonctionnaire à carrière
    courte était servi sans plancher, et l'étalon sous-estimait le système
    actuel là même où il protège le plus.
    """

    #: Quinze ans de services, en trimestres : première marche du barème.
    SEUIL_BAS = 60
    #: Quarante ans de services : au-delà, la référence est servie en entier.
    SEUIL_HAUT = 160
    #: Année à partir de laquelle la référence est gelée puis indexée sur les
    #: prix, au lieu de suivre le point d'indice.
    ANNEE_GEL = 2004

    def __init__(self, racine: Path, macro: DonneesMacro) -> None:
        self.macro = macro
        self._bareme: dict[int, tuple[int, float, float, float, int, Fiabilite]] = {}
        self._point: dict[int, tuple[float, Fiabilite]] = {}
        self._montants: dict[int, tuple[float, Fiabilite]] = {}
        dossier = racine / "reference" / "legislation"
        chemin = dossier / "minimum_garanti.csv"
        if chemin.exists():
            with chemin.open(encoding="utf-8") as flux:
                lignes = (l for l in flux if not l.lstrip().startswith("#"))
                for ligne in csv.DictReader(lignes):
                    self._bareme[int(ligne["annee"])] = (
                        int(ligne["indice_majore"]),
                        float(ligne["part_15_ans"]),
                        float(ligne["points_15_30"]),
                        float(ligne["points_30_40"]),
                        int(ligne["trimestres_seuil"]),
                        Fiabilite.depuis_texte(ligne["fiabilite"]),
                    )
        for fichier, table in (("point_indice_fonction_publique.csv", self._point),
                               ("minimum_garanti_montants.csv", self._montants)):
            chemin = dossier / fichier
            if not chemin.exists():
                continue
            with chemin.open(encoding="utf-8") as flux:
                lignes = (l for l in flux if not l.lstrip().startswith("#"))
                for ligne in csv.DictReader(lignes):
                    table[int(ligne["annee"])] = (
                        float(ligne["valeur"]),
                        Fiabilite.depuis_texte(ligne["fiabilite"]),
                    )
        self._annees_bareme = sorted(self._bareme)
        self._annees_montants = sorted(self._montants)

    def _point_indice(self, annee: int) -> tuple[float, Fiabilite] | None:
        """Traitement annuel d'un point d'indice majoré, l'année demandée."""
        if not self._point:
            return None
        anterieures = [a for a in self._point if a <= annee]
        return self._point[max(anterieures)] if anterieures else None

    #: Indice majoré auquel se rapportent les montants transcrits.
    INDICE_REFERENCE = 227

    def reference(self, annee_liquidation: int) -> tuple[float, Fiabilite] | None:
        """Montant plein du minimum garanti, quarante ans de services.

        Trois cas, et dans cet ordre :

        * **un montant servi est connu** pour l'année — il prime sur tout
          calcul, comme pour le minimum contributif, et pour la même raison :
          la revalorisation des pensions à laquelle l'article renvoie a été
          gelée en 2014 et sous-indexée depuis, si bien qu'une projection sur
          les prix dépasse de plusieurs points ce qui a été payé ;
        * **après 2004**, la référence est le traitement gelé de l'indice
          majoré 227 au 1er janvier 2004, projeté sur les prix depuis l'ancre
          en vigueur ;
        * **avant 2004**, le gel n'existe pas : c'est le traitement de l'indice
          majoré de l'année, au point d'indice de cette année-là.

        Le montant est ensuite ramené à l'indice majoré de l'année de
        liquidation, qui monte de 217 en 2004 à 227 en 2013.
        """
        bareme = self.bareme(annee_liquidation)
        if bareme is None:
            return None
        indice, _, _, _, _, fiabilite_bareme = bareme

        if annee_liquidation <= self.ANNEE_GEL and annee_liquidation not in self._montants:
            point = self._point_indice(annee_liquidation)
            if point is None:
                return None
            return indice * point[0], min(fiabilite_bareme, point[1])

        if not self._annees_montants:
            return None
        if annee_liquidation in self._montants:
            valeur, fiabilite = self._montants[annee_liquidation]
        else:
            anterieures = [a for a in self._annees_montants if a < annee_liquidation]
            ancre = max(anterieures) if anterieures else self._annees_montants[0]
            valeur, fiabilite = self._montants[ancre]
            valeur *= self.macro.coefficient_prix(ancre, annee_liquidation)
        return (valeur * indice / self.INDICE_REFERENCE,
                min(fiabilite_bareme, fiabilite))

    def bareme(self, annee_liquidation: int):
        """Paramètres en vigueur l'année de liquidation, ou ``None`` avant 1976."""
        if not self._bareme or annee_liquidation < self._annees_bareme[0]:
            return None
        applicable = self._annees_bareme[0]
        for candidate in self._annees_bareme:
            if candidate > annee_liquidation:
                break
            applicable = candidate
        return self._bareme[applicable]

    def montant(self, annee_liquidation: int,
                trimestres_services: int) -> tuple[float, Fiabilite] | None:
        """Plancher opposable pour une durée de services donnée."""
        bareme = self.bareme(annee_liquidation)
        reference = self.reference(annee_liquidation)
        if bareme is None or reference is None:
            return None
        _, part, points_bas, points_haut, seuil, _ = bareme
        duree = max(0, min(trimestres_services, self.SEUIL_HAUT))
        if duree <= 0:
            return None
        if duree < self.SEUIL_BAS:
            taux = part * duree / self.SEUIL_BAS
        elif duree >= self.SEUIL_HAUT:
            taux = 1.0
        elif duree < seuil:
            taux = part + (duree - self.SEUIL_BAS) * points_bas
        else:
            taux = (part + (seuil - self.SEUIL_BAS) * points_bas
                    + (duree - seuil) * points_haut)
        return reference[0] * taux, reference[1]


@dataclass(frozen=True)
class ConversionPoint:
    """Ce que devient un point à une fusion, ou à un changement d'unité."""

    annee_effet: int
    #: Régime qui reprend les points, ou ``None`` pour un changement d'échelle
    #: interne au régime lui-même.
    successeur: str | None
    #: Un point d'origine vaut ce nombre de points d'arrivée.
    coefficient: float
    fiabilite: Fiabilite


class ConversionsPoints:
    """Coefficients de conversion des points, lus et non devinés.

    Un point n'est pas une grandeur universelle : c'est l'unité de compte d'un
    régime, et elle change quand le régime change. Le moteur déduisait ces
    coefficients du RAPPORT de deux valeurs de service prises aux bornes des
    séries publiées, ce qui a produit deux erreurs distinctes.

    La première tenait à la date : la valeur du successeur était lue à sa
    PREMIÈRE année publiée. Or les séries ``arrco`` et ``ircantec`` sont
    rétro-remplies bien avant leur fusion — la première depuis 1957 avec les
    valeurs de l'UNIRS, la seconde depuis 1949 avec celles de l'IPACTE. Le
    rapport comparait alors deux valeurs distantes de quarante ou soixante-dix
    ans : le point UNIRS ressortait quinze fois trop cher pour toute
    liquidation postérieure à 1998, le point IPACTE cinquante fois trop cher
    au-delà de 2022, et jusqu'à 35 % de la pension du scénario 1 n'avait aucune
    existence.

    La seconde tenait au jour : la valeur du successeur était prise au
    31 décembre de l'année de fusion quand la conversion s'opère au 1er
    janvier — un pour cent d'écart sur tous les points d'avant 2019.

    Une troisième erreur n'était pas une conversion mal faite mais une
    conversion ABSENTE : l'unification de l'Arrco au 1er janvier 1999 change
    l'unité sans changer le code du régime. C'est ce que décrivent les lignes
    dont le ``successeur`` est vide.
    """

    def __init__(self, racine: Path) -> None:
        self._fusions: dict[tuple[str, str], ConversionPoint] = {}
        self._echelles: dict[str, list[ConversionPoint]] = {}
        chemin = racine / "reference" / "regimes" / "conversions_points.csv"
        if not chemin.exists():
            return
        with chemin.open(encoding="utf-8") as flux:
            lignes = (l for l in flux if not l.lstrip().startswith("#"))
            for ligne in csv.DictReader(lignes):
                conversion = ConversionPoint(
                    annee_effet=int(ligne["annee_effet"]),
                    successeur=ligne["successeur"] or None,
                    coefficient=float(ligne["coefficient"]),
                    fiabilite=Fiabilite.depuis_texte(ligne["fiabilite"]),
                )
                if conversion.successeur is not None:
                    self._fusions[(ligne["regime"], conversion.successeur)] = conversion
                else:
                    self._echelles.setdefault(ligne["regime"], []).append(conversion)
        for conversions in self._echelles.values():
            conversions.sort(key=lambda c: c.annee_effet)

    def fusion(self, regime: str, successeur: str) -> ConversionPoint | None:
        """Coefficient de reprise des points de ``regime`` par ``successeur``."""
        return self._fusions.get((regime, successeur))

    def echelle(self, regime: str, annee_acquisition: int,
                annee_liquidation: int) -> tuple[float, Fiabilite]:
        """Facteur d'unité entre l'année d'acquisition et celle de liquidation.

        Un point acheté au prix de 1998 et servi à la valeur de 2029 n'est pas
        la même unité : l'Arrco a changé d'échelle entre-temps. Le facteur
        n'intervient que si le changement tombe APRÈS l'acquisition et AVANT ou
        À la liquidation — une liquidation de 1995 lit une valeur de service de
        l'ancienne échelle, et n'a rien à convertir.
        """
        facteur = 1.0
        fiabilite = Fiabilite.CERTIFIEE
        for conversion in self._echelles.get(regime, ()):
            if annee_acquisition < conversion.annee_effet <= annee_liquidation:
                facteur *= conversion.coefficient
                fiabilite = min(fiabilite, conversion.fiabilite)
        return facteur, fiabilite


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
        self.conversions_points = ConversionsPoints(parametres.racine_donnees)
        self.durees_requises = DureesRequises(parametres.racine_donnees)
        self.ages_ouverture = AgesOuverture(parametres.racine_donnees)
        self.ages_annulation_decote = AgesAnnulationDecote(parametres.racine_donnees)
        self.coefficients_minoration = CoefficientsMinoration(parametres.racine_donnees)
        self.annees_salaire_reference = AnneesSalaireReference(parametres.racine_donnees)
        self.majorations_enfants = MajorationsPourEnfants(parametres.racine_donnees)
        self.surcote_parentale = SurcoteParentale(parametres.racine_donnees)
        self.decote_fonction_publique = DecoteFonctionPublique(
            parametres.racine_donnees
        )
        self.minimum_contributif = MinimumContributif(parametres.racine_donnees, macro)
        self.minimum_garanti = MinimumGaranti(parametres.racine_donnees, macro)
        self.carriere_longue = CarriereLongue(parametres.racine_donnees)
        self.minimum_vieillesse = MinimumVieillesse(parametres.racine_donnees, macro)

    # -- valorisation des points ---------------------------------------------

    def valeur_du_point(self, code: str,
                        annee_liquidation: int) -> tuple[float, Fiabilite] | None:
        """Ce que vaut, à la liquidation, un point acquis dans ``code``.

        Un régime fermé ne sert plus ses points : ils ont été convertis dans son
        successeur, au coefficient que l'accord de fusion a fixé. La méthode
        remonte la chaîne des successions (UNIRS -> Arrco -> Agirc-Arrco,
        Agirc -> Agirc-Arrco, IPACTE et IGRANTE -> Ircantec) en cumulant ces
        coefficients, qui sont LUS dans ``regimes/conversions_points.csv`` et
        non plus déduits d'un rapport de valeurs de service.

        **Les déduire coûtait cher.** Le rapport était pris entre la dernière
        valeur publiée du régime d'origine et la PREMIÈRE du successeur ; or les
        séries ``arrco`` et ``ircantec`` sont rétro-remplies bien avant leur
        fusion, si bien qu'on comparait deux valeurs distantes de quarante ou
        soixante-dix ans. Le point UNIRS ressortait quinze fois trop cher pour
        toute liquidation postérieure à 1998, le point IPACTE cinquante fois
        trop cher au-delà de 2022. Et là même où les deux bornes tombaient
        juste, la valeur du successeur était celle du 31 décembre quand la
        conversion s'opère au 1er janvier : un pour cent de trop peu sur tous
        les points d'avant 2019.

        Quand la chaîne s'arrête — plus de successeur, ou aucun coefficient
        déclaré — la dernière valeur publiée est ramenée en euros de la
        liquidation par l'indice des prix. C'est une approximation, signalée
        comme telle par la fiabilité renvoyée ; c'est surtout un aveu
        d'ignorance, préférable à un coefficient inventé.
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
            reprise = (self.conversions_points.fusion(courant, successeur)
                       if successeur else None)
            if reprise is None:
                ancienne = self.valeurs_point.service(courant, derniere)
                return (
                    conversion * ancienne[0]
                    * self.macro.coefficient_prix(derniere, annee_liquidation),
                    min(fiabilite, ancienne[1], Fiabilite.MOYENNE),
                )

            conversion *= reprise.coefficient
            fiabilite = min(fiabilite, reprise.fiabilite)
            courant = successeur
        return None  # pragma: no cover - chaîne de successions cyclique

    # -- salaire de référence ------------------------------------------------

    def salaire_de_reference(self, code: str, carriere: Carriere,
                             periode: PeriodeRegime,
                             annee_liquidation: int, plafonner: bool,
                             generation: int | None = None,
                             avpf: bool = True) -> float:
        """Salaire de référence, exprimé en euros de l'année de liquidation.

        **Il porte sur les seules années passées DANS CE régime.** Un régime ne
        liquide que ce qui lui a été déclaré : la pension civile se calcule sur
        le traitement des six derniers mois de service, pas sur le dernier
        salaire d'une carrière poursuivie ailleurs, et le salaire annuel moyen
        du régime général ne retient que les salaires portés à son compte. Sans
        cette condition, un polypensionné passé de la fonction publique au privé
        liquidait sa pension civile sur son salaire privé de fin de carrière —
        et le prorata de durée, lui, restait celui du régime : le modèle
        rapportait une part de carrière publique à une assiette qui ne l'était
        pas.

        Trois autres règles de droit commandent ce calcul, et le modèle les
        applique toutes.

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
        avpf_ouvert = (
            avpf and "avpf" in periode.avantages_non_contributifs
        )
        revenus: list[float] = []
        for ligne in carriere.lignes:
            if ligne.annee >= annee_liquidation:
                continue
            if code not in self.affiliations.regimes(ligne.affiliation, ligne.annee):
                continue
            if not ligne.cotise:
                # Assurance vieillesse des parents au foyer : la CNAF cotise
                # sur une assiette forfaitaire égale au SMIC, et ce salaire est
                # PORTÉ AU COMPTE. C'est ce qui la distingue d'une période
                # assimilée, laquelle valide des trimestres sans jamais ajouter
                # de salaire — et c'est ce que le modèle ne faisait pas, alors
                # que le cas type « carrière interrompue » l'annonçait.
                if not (avpf_ouvert and ligne.revenu_avpf > 0):
                    continue
                revenu = ligne.revenu_avpf
            else:
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

    def _decote(self, periode: PeriodeRegime, carriere: Carriere,
                annee_liquidation: int
                ) -> tuple[float | None, float, Fiabilite | None]:
        """Décote opposable : coefficient, âge d'annulation, fiabilité.

        Un régime sans décote — fonction publique avant 2006, régimes spéciaux
        avant 2008 — n'en acquiert pas une parce que la table en porte une :
        ``None`` dans la fiche reste ``None`` ici, et le coefficient renvoyé
        est ``None``.

        **La fonction publique n'a pas la décote du régime général.** L'article
        L. 14 du code des pensions lui donne la sienne, montée en charge de
        2006 à 2020, et surtout un âge d'annulation qui n'est pas un âge en
        propre : c'est la LIMITE D'ÂGE du grade, diminuée d'un nombre de
        trimestres décroissant. Un sédentaire liquidant en 2012 voyait sa
        décote s'annuler à 63 ans, pas à 67 — et chaque trimestre manquant lui
        coûtait 0,875 %, pas 1,25 %. Lui opposer le barème du privé retirait
        jusqu'à un sixième de sa pension.
        """
        age_annulation = self._age_taux_plein(periode, carriere)
        if periode.bareme_decote == "fonction_publique":
            parametres = self.decote_fonction_publique.parametres(annee_liquidation)
            if parametres is None:
                return None, age_annulation, None
            trimestres_avant, coefficient, fiabilite = parametres
            return coefficient, age_annulation - trimestres_avant / 4.0, fiabilite
        if periode.decote_par_trimestre is None:
            return None, age_annulation, None
        if periode.decote_par_generation:
            par_generation = self.coefficients_minoration.coefficient(
                carriere.annee_naissance
            )
            if par_generation is not None:
                return par_generation[0], age_annulation, par_generation[1]
        return periode.decote_par_trimestre, age_annulation, None

    def _trimestres_de_decote(self, periode: PeriodeRegime, trimestres: int,
                              requis: int, age_liquidation: float,
                              age_annulation: float) -> float:
        """Trimestres de décote opposables, plafond compris.

        Le décompte retient le plus favorable des deux : trimestres manquants
        pour la durée requise, ou trimestres manquants jusqu'à l'âge
        d'annulation de la décote. Et il est PLAFONNÉ — vingt trimestres dans
        tous les régimes qui appliquent une décote. Sans ce plafond, un départ
        dix ans avant l'heure retirait la moitié de la pension là où le droit
        n'en retire que le quart.

        Le décompte par l'ÂGE est arrondi à l'entier supérieur, comme le veut
        l'article R. 351-27. Les âges d'annulation des générations 1951 à 1954
        valent 65,33, 65,75, 66,17 et 66,58 ans : sans cet arrondi, on opposait
        13,32 trimestres à un assuré né en 1951 parti à 62 ans, quand le droit
        lui en oppose 14. Le barème d'anticipation de l'Agirc-Arrco, lui,
        arrondissait déjà — les deux décomptes suivent maintenant la même règle.
        """
        manquants_age = float(_au_trimestre_superieur(
            (age_annulation - age_liquidation) * 4
        ))
        if periode.decote_annulee_par_la_duree:
            trimestres_decote = min(max(0, requis - trimestres), manquants_age)
        else:
            # Avant l'ordonnance du 26 mars 1982, le taux ne dépendait QUE de
            # l'âge : le régime général servait 20 % à 60 ans, majorés de
            # 4 points par année différée, puis — loi Boulin — 50 % à 65 ans,
            # diminués de 5 points par année anticipée. Aucune durée, si longue
            # fût-elle, n'ouvrait le taux plein avant l'âge. Annuler la décote
            # par la durée, comme le fait le droit d'après 1982, servait le taux
            # plein à 60 ans à des générations auxquelles la loi ne l'a jamais
            # donné.
            trimestres_decote = manquants_age
        if trimestres_decote <= 0:
            return 0.0
        if periode.decote_trimestres_maximum is not None:
            trimestres_decote = min(trimestres_decote, periode.decote_trimestres_maximum)
        return trimestres_decote

    def _abattement_points(self, periode: PeriodeRegime, carriere: Carriere,
                           trimestres: int, requis: int,
                           age_liquidation: float,
                           annee_liquidation: int) -> float:
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

        decote, age_annulation, _ = self._decote(
            periode, carriere, annee_liquidation
        )
        if decote is None:
            return 1.0
        trimestres_decote = self._trimestres_de_decote(
            periode, trimestres, requis, age_liquidation, age_annulation
        )
        return max(0.0, 1.0 - decote * trimestres_decote)

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

    def _majoration_pour_enfants(self, carriere: Carriere,
                                 trimestres_par_regime: dict[str, int],
                                 annee_liquidation: int
                                 ) -> _MajorationEnfants | None:
        """Trimestres dus au titre des enfants, et régime qui les porte.

        Le droit n'attribue pas ces trimestres au-dessus des régimes : il les
        donne DANS un régime, et ils comptent donc aussi dans sa
        proratisation, pas seulement dans la décote tous régimes confondus.
        On retient donc, parmi les régimes en annuités dont la fiche de
        l'année de liquidation porte un dispositif que la table sert, celui
        qui accorde le plus ; à égalité, celui où l'assuré a validé le plus de
        trimestres ; à égalité encore, le dernier code par ordre alphabétique,
        pour que le résultat ne dépende pas de l'ordre d'un dictionnaire.

        Renvoie ``None`` quand rien n'est dû : pas d'enfant, aucun régime
        porteur, dispositif pas encore né, ou assuré qui n'en est pas le
        bénéficiaire.
        """
        if carriere.nombre_enfants <= 0:
            return None
        candidats: list[tuple[int, int, str, str, Fiabilite]] = []
        for code, valides in trimestres_par_regime.items():
            if code not in self.catalogue:
                continue
            regime = self.catalogue[code]
            periode = regime.periode(min(annee_liquidation, _derniere_annee(regime)))
            if periode is None or periode.type_calcul != "annuites":
                continue
            for dispositif in periode.avantages_non_contributifs:
                accorde = self.majorations_enfants.par_enfant(
                    dispositif, carriere.sexe, carriere.annee_naissance,
                    annee_liquidation, carriere.nombre_enfants,
                )
                if accorde is None:
                    continue
                trimestres, fiabilite = accorde
                candidats.append((
                    trimestres * carriere.nombre_enfants, valides, dispositif,
                    code, fiabilite,
                ))
        if not candidats:
            return None
        trimestres, _, dispositif, code, fiabilite = max(
            candidats, key=lambda c: (c[0], c[1], c[3])
        )
        return _MajorationEnfants(
            regime=code, dispositif=dispositif, trimestres=trimestres,
            fiabilite=fiabilite,
        )

    # -- calcul --------------------------------------------------------------

    def calculer(self, carriere: Carriere,
                 ignorer_penalite_age: bool = False,
                 avantages_non_contributifs: bool = True,
                 avpf: bool = True) -> ResultatActuel:
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

        pensions: list[PensionRegime] = []
        fiabilite_globale = Fiabilite.CERTIFIEE
        trimestres_requis = 0
        taux_retenu = 0.0

        #: Régimes de base qui portent le minimum contributif : indice dans
        #: ``pensions``, prorata de durée d'assurance, prorata de durée
        #: COTISÉE, et condition de taux plein remplie ou non.
        eligibles_minimum: list[_EligibleMinimum] = []
        #: Régimes de la fonction publique qui portent le minimum garanti.
        eligibles_garanti: list[_EligibleMinimumGaranti] = []

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
        # Durée COTISÉE dans chaque régime : c'est elle, et non la durée
        # d'assurance, qui proratise la majoration du minimum contributif au
        # titre des périodes cotisées (D. 351-2-2).
        trimestres_cotises_par_regime: dict[str, int] = {}

        for ligne in carriere.lignes:
            if ligne.annee >= annee_liquidation:
                continue
            for code in self.affiliations.regimes(ligne.affiliation, ligne.annee):
                if code not in self.catalogue:
                    continue
                trimestres_par_regime[code] = (
                    trimestres_par_regime.get(code, 0) + ligne.trimestres_valides
                )
                if ligne.cotise:
                    trimestres_cotises_par_regime[code] = (
                        trimestres_cotises_par_regime.get(code, 0)
                        + ligne.trimestres_valides
                    )

        # Les trimestres accordés au titre des enfants ne flottent pas au-dessus
        # des régimes : le droit les attribue DANS un régime, et ils comptent
        # donc aussi dans sa proratisation, pas seulement dans la décote tous
        # régimes confondus. Les ignorer là amputait la pension d'une mère de
        # famille de la part que la majoration est censée lui rendre. Le régime
        # retenu est celui qui accorde le plus — exact pour une carrière
        # mono-affiliée, qui est le cas ordinaire, approché pour un
        # polypensionné, à qui le droit ferait porter la majoration par chacun
        # de ses régimes.
        majoration_enfants = (
            self._majoration_pour_enfants(
                carriere, trimestres_par_regime, annee_liquidation
            ) if avantages_non_contributifs else None
        )
        if majoration_enfants is not None:
            trimestres += majoration_enfants.trimestres
            trimestres_par_regime[majoration_enfants.regime] += (
                majoration_enfants.trimestres
            )
            fiabilite_globale = min(fiabilite_globale, majoration_enfants.fiabilite)

        for ligne in carriere.lignes:
            if ligne.annee >= annee_liquidation:
                # Une ligne postérieure à la liquidation décrit une activité
                # exercée APRÈS le départ : elle n'ouvre pas de droits dans la
                # pension qu'on liquide. La durée d'assurance et le salaire de
                # référence l'écartaient déjà ; l'acquisition de points et de
                # cotisations, elle, l'encaissait encore.
                continue
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
                    pass_annuel = self.macro.plafond_securite_sociale(ligne.annee)
                    borne_basse, borne_haute = periode.bornes_assiette_en_euros(
                        pass_annuel
                    )
                    base = base_ligne
                    if periode.assiette == "primes_uniquement":
                        base = base_ligne * ligne.part_primes
                    elif periode.assiette == "hors_primes":
                        base = base_ligne * (1.0 - ligne.part_primes)
                    plafond = base if borne_haute is None else borne_haute
                    assiette = max(0.0, min(base, plafond) - borne_basse)
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
                        echelle, fiabilite_echelle = self.conversions_points.echelle(
                            code, ligne.annee, annee_liquidation
                        )
                        points_acquis[code] = points_acquis.get(code, 0.0) + (
                            periode.points_maximum * assiette / repere * echelle
                        )
                        fiabilite_points[code] = min(
                            fiabilite_points.get(code, Fiabilite.CERTIFIEE),
                            regime.fiabilite, fiabilite_echelle,
                        )
                        continue
                    achat = (self.valeurs_point.achat(code, ligne.annee)
                             if periode.type_calcul in ("points", "mixte") else None)
                    if achat is not None:
                        reference, taux_appel, fiabilite_achat = achat
                        points_annee = cotisation / (taux_appel * reference)
                        if periode.points_minimum_annuels is not None:
                            # Garantie minimale de points de l'Agirc : tout
                            # cadre cotisant en acquiert au moins 120 par an de
                            # 1989 à 2018, même quand sa tranche B est nulle,
                            # c'est-à-dire même quand son salaire ne dépasse pas
                            # le plafond de la Sécurité sociale. La fiche la
                            # déclarait ; le moteur ne la servait pas, et un
                            # cadre payé sous le plafond n'acquérait rien à
                            # l'Agirc là où le droit lui donnait ces points.
                            points_annee = max(
                                points_annee, periode.points_minimum_annuels
                            )
                        # Changement d'unité entre l'achat et le service : les
                        # points Arrco d'avant 1999 sont ceux de l'UNIRS, et
                        # valent 0,387464 point du régime unifié. Sans cette
                        # conversion, cent euros cotisés en 1998 produisaient
                        # 30,31 € de pension quand les mêmes cent euros de 1999
                        # n'en produisaient que 11,15 — un facteur 2,7 en une
                        # année, pour une unification qui était neutre.
                        echelle, fiabilite_echelle = self.conversions_points.echelle(
                            code, ligne.annee, annee_liquidation
                        )
                        points_acquis[code] = (
                            points_acquis.get(code, 0.0) + points_annee * echelle
                        )
                        fiabilite_points[code] = min(
                            fiabilite_points.get(code, Fiabilite.CERTIFIEE),
                            fiabilite_achat, fiabilite_echelle,
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
        #: Âge d'ouverture des droits le plus précoce parmi les régimes de base
        #: de la carrière. Un polypensionné liquide en réalité chaque pension à
        #: l'âge de son régime ; le modèle liquide tout à la fois, et retient
        #: donc l'âge du régime le plus précoce — celui d'un régime spécial,
        #: quand il y en a un.
        age_ouverture_reference: float | None = None
        for code in sorted(set(cumul_cotisations) | set(points_acquis)):
            regime = self.catalogue[code]
            periode = regime.periode(min(annee_liquidation, _derniere_annee(regime)))
            if periode is None or periode.type_calcul != "annuites":
                continue
            requis_reference = max(
                requis_reference, self._duree_requise(periode, carriere)[0]
            )
            age_regime = self._age_ouverture(periode, carriere)
            age_ouverture_reference = (
                age_regime if age_ouverture_reference is None
                else min(age_ouverture_reference, age_regime)
            )
        requis_reference = requis_reference or 160

        # Trimestres réellement COTISÉS, tous régimes : ils commandent la
        # carrière longue et la majoration du minimum contributif.
        trimestres_cotises = sum(
            ligne.trimestres_valides for ligne in carriere.lignes
            if ligne.cotise and ligne.annee < annee_liquidation
        )

        # Le droit ouvre-t-il cette liquidation à cet âge ? La question n'était
        # pas posée : le modèle servait une pension décotée à qui ne pouvait
        # pas encore liquider, ce qui n'est ni le droit ni un contrefactuel
        # utile. Elle l'est maintenant, et la réponse accompagne le montant.
        motif_ouverture = "age_legal"
        liquidation_ouverte = True
        if age_ouverture_reference is not None and age_liquidation < age_ouverture_reference:
            anticipe = self.carriere_longue.age_de_depart(
                carriere, annee_liquidation, trimestres_cotises, requis_reference
            )
            if anticipe is not None and age_liquidation >= anticipe[0]:
                motif_ouverture = "carriere_longue"
                age_ouverture_reference = anticipe[0]
                fiabilite_globale = min(fiabilite_globale, anticipe[1])
            else:
                motif_ouverture = "non_ouverte"
                liquidation_ouverte = False

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
                        age_liquidation, annee_liquidation,
                    )
                pensions.append(PensionRegime(
                    regime=code, montant=montant, type_calcul=periode.type_calcul,
                    detail=" + ".join(details) or "aucun droit",
                    fiabilite=fiabilite_regime,
                ))
                continue

            # Régimes en annuités — et régimes FORFAITAIRES, dont la pension ne
            # dépend pas du revenu mais de la seule durée. Le second cas se
            # traite comme le premier en remplaçant le salaire de référence par
            # le montant forfaitaire : c'est bien un `montant × taux × durée /
            # durée requise`, à ceci près que le montant est le même pour tous.
            # Faute de ce montant, la fiche retombait sur la moyenne des
            # revenus, c'est-à-dire sur un taux de remplacement de 100 %.
            plafonner = periode.assiette in ("plafonnee", "tranche_1", "tranche_a")
            if periode.pension_forfaitaire_annuelle is not None:
                salaire_reference = (
                    periode.pension_forfaitaire_annuelle
                    * self.macro.coefficient_prix(
                        periode.pension_forfaitaire_annee or annee_liquidation,
                        annee_liquidation,
                    )
                )
            else:
                salaire_reference = self.salaire_de_reference(
                    code, carriere, periode, annee_liquidation, plafonner,
                    carriere.annee_naissance, avpf,
                )
            requis, fiabilite_duree = self._duree_requise(periode, carriere)
            if fiabilite_duree is not None:
                fiabilite_globale = min(fiabilite_globale, fiabilite_duree)
            trimestres_requis = max(trimestres_requis, requis)
            trimestres_regime = min(trimestres_par_regime.get(code, 0), requis)

            taux = periode.taux_plein or 0.5
            #: Part du taux qui vient de la surcote. Le minimum contributif se
            #: compare à la pension AVANT surcote : il faut donc pouvoir la
            #: retirer, puis la rendre.
            coefficient_surcote = 1.0
            #: Trimestres de décote effectivement retenus : la condition
            #: d'ouverture du minimum garanti en dépend.
            trimestres_decote = 0.0
            if not ignorer_penalite_age:
                decote, age_annulation, fiabilite_decote = self._decote(
                    periode, carriere, annee_liquidation
                )
                trimestres_decote = self._trimestres_de_decote(
                    periode, trimestres, requis, age_liquidation, age_annulation
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
                        coefficient_surcote = (
                            1.0 + periode.surcote_par_trimestre * supplementaires
                        )
                        taux *= coefficient_surcote

            taux_retenu = max(taux_retenu, taux)
            montant = salaire_reference * taux * (trimestres_regime / requis)
            if "minimum_contributif" in periode.avantages_non_contributifs:
                # Le minimum ne relève que les régimes de base qui le portent,
                # et au prorata de la durée acquise DANS CE régime — durée
                # d'assurance pour le montant de base, durée COTISÉE pour la
                # majoration au titre des périodes cotisées.
                #
                # Et il ne relève que les pensions LIQUIDÉES AU TAUX PLEIN
                # (L. 351-10) : durée requise atteinte, ou âge d'annulation de
                # la décote atteint. Le servir à un assuré décoté, comme le
                # faisait ce module, revenait à faire garantir par le système
                # actuel un départ que le droit sanctionne — et gonflait
                # l'étalon de 20 % sur les petites pensions parties tôt.
                cotises_regime = min(
                    trimestres_cotises_par_regime.get(code, 0), requis
                )
                eligibles_minimum.append(_EligibleMinimum(
                    indice=len(pensions),
                    prorata_assurance=trimestres_regime / requis,
                    prorata_cotise=cotises_regime / requis,
                    taux_plein=(
                        trimestres >= requis
                        or age_liquidation >= self._age_taux_plein(periode, carriere)
                    ),
                    surcote=coefficient_surcote,
                ))
            if "minimum_garanti" in periode.avantages_non_contributifs:
                # Depuis la loi du 9 novembre 2010, le minimum garanti n'est dû
                # qu'au taux plein — décote nulle, ou durée requise atteinte.
                # Les assurés qui atteignaient l'âge d'ouverture de leurs
                # droits avant 2011 gardent le droit inconditionnel.
                age_ouverture = self._age_ouverture(periode, carriere)
                eligibles_garanti.append(_EligibleMinimumGaranti(
                    indice=len(pensions),
                    trimestres_services=trimestres_par_regime.get(code, 0),
                    ouvert=(
                        carriere.annee_naissance + age_ouverture < 2011
                        or trimestres_decote <= 0
                        or trimestres >= requis
                    ),
                ))
            pensions.append(PensionRegime(
                regime=code, montant=montant, type_calcul="annuites",
                detail=(
                    f"{'forfait' if periode.pension_forfaitaire_annuelle is not None else 'SR'} "
                    f"{salaire_reference:,.0f} € × taux {taux:.2%} "
                    f"× {trimestres_regime}/{requis}"
                ),
                fiabilite=regime.fiabilite,
            ))

        total = sum(p.montant for p in pensions)
        total_contributif = total
        avantages: list[AvantageApplique] = []

        # Avantages non contributifs du droit positif, DANS L'ORDRE OÙ LE DROIT
        # LES APPLIQUE, et l'ordre commande le résultat : la majoration de durée
        # d'assurance et l'AVPF d'abord, qui déplacent la décote, la
        # proratisation et le salaire annuel moyen ; puis les deux minima, qui
        # portent la pension de base à son plancher ; puis seulement la
        # majoration pour enfants, qui se calcule SUR CE plancher ; l'ASPA
        # enfin, qui est différentielle et complète tout le reste.
        #
        # Ce module prenait le minimum et la majoration dans l'autre sens : les
        # 10 % portaient sur une pension que le minimum n'avait pas encore
        # relevée, et l'écrêtement du minimum comparait au plafond un total qui
        # incluait déjà la majoration, alors que l'article L. 173-2 ne retient
        # que les pensions personnelles.
        minimum_applique = False

        if avantages_non_contributifs and majoration_enfants is not None:
            # Effet des trimestres accordés au titre des enfants : la même
            # carrière sans eux, tout le reste égal. C'est la seule façon
            # d'isoler un avantage qui agit sur la décote et sur la
            # proratisation.
            sans_mda = self.calculer(
                carriere, ignorer_penalite_age, avantages_non_contributifs=False,
                avpf=avpf,
            )
            effet = total - sans_mda.total_contributif
            # Ces trimestres sont déjà incorporés aux pensions de régime : la
            # base contributive de la cascade est celle d'AVANT, sans quoi leur
            # effet serait compté deux fois.
            total_contributif = sans_mda.total_contributif
            if abs(effet) > 1e-9:
                avantages.append(AvantageApplique(
                    code="majoration_duree_assurance",
                    libelle=_LIBELLE_MAJORATION[majoration_enfants.dispositif],
                    montant=effet,
                    detail=f"{majoration_enfants.trimestres} trimestres pour "
                           f"{carriere.nombre_enfants} enfant"
                           f"{'s' if carriere.nombre_enfants > 1 else ''}, "
                           f"au titre du régime « {majoration_enfants.regime} »",
                ))

        if (avantages_non_contributifs and avpf
                and any(ligne.revenu_avpf > 0 for ligne in carriere.lignes)):
            # Effet de l'AVPF, mesuré comme celui de la MDA : la même carrière
            # sans le salaire forfaitaire porté au compte. Il joue en amont de
            # tout le reste, puisqu'il déplace le salaire annuel moyen — et il
            # peut jouer dans les deux sens : il relève une carrière longue à
            # bas salaire, il abaisse la moyenne d'une carrière courte et bien
            # payée, où les années au SMIC viennent s'ajouter aux années
            # retenues au lieu de les remplacer.
            sans_avpf = self.calculer(
                carriere, ignorer_penalite_age,
                avantages_non_contributifs=False, avpf=False,
            )
            effet_avpf = total_contributif - sans_avpf.total_contributif
            total_contributif = sans_avpf.total_contributif
            if abs(effet_avpf) > 1e-9:
                avantages.insert(0, AvantageApplique(
                    code="avpf",
                    libelle="Assurance vieillesse des parents au foyer",
                    montant=effet_avpf,
                    detail="salaire forfaitaire au SMIC porté au compte",
                ))

        if avantages_non_contributifs and eligibles_minimum:
            # Le minimum contributif ne relève que les pensions liquidées AU
            # TAUX PLEIN (L. 351-10). Sa majoration au titre des périodes
            # cotisées demande en outre 120 trimestres cotisés tous régimes ;
            # elle se proratise sur la durée COTISÉE dans le régime, quand le
            # montant de base se proratise sur sa durée d'assurance
            # (D. 351-2-2). Ce n'est pas la même fraction : une carrière
            # entrecoupée de chômage indemnisé valide sa durée d'assurance
            # sans cotiser, et n'a donc droit qu'à une part de la majoration.
            montant_base, montant_majore, plafond, fiabilite_minimum = (
                self.minimum_contributif.valeurs(annee_liquidation)
            )
            majoration_ouverte = (
                trimestres_cotises >= TRIMESTRES_COTISES_MINIMUM_MAJORE
            )
            #: Complément dû à chaque régime, avant écrêtement.
            complements: dict[int, float] = {}
            for eligible in eligibles_minimum:
                if not eligible.taux_plein:
                    continue
                pension = pensions[eligible.indice]
                # Le minimum se compare à la pension AVANT surcote : le droit
                # porte la pension au plancher, puis applique la surcote au
                # montant relevé. Comparer une pension déjà surcotée au
                # plancher refusait le minimum à qui a travaillé plus
                # longtemps que la durée requise pour un salaire minime.
                nue = pension.montant / eligible.surcote
                plancher = montant_base * min(1.0, eligible.prorata_assurance)
                if majoration_ouverte:
                    plancher += (montant_majore - montant_base) * min(
                        1.0, eligible.prorata_cotise
                    )
                if 0 < nue < plancher:
                    complements[eligible.indice] = (
                        (plancher - nue) * eligible.surcote
                    )
            releve = sum(complements.values())
            if releve > 0:
                # Écrêtement de l'article L. 173-2 : le complément est rogné de
                # ce qui dépasse le plafond, tous régimes confondus, et jamais
                # au-delà. La comparaison porte sur les pensions PERSONNELLES,
                # majorations pour enfants exclues — raison de plus pour que
                # celles-ci se calculent après, sur le montant relevé.
                admissible = max(0.0, min(releve, plafond - total))
                if admissible < releve:
                    facteur = admissible / releve
                    complements = {
                        indice: complement * facteur
                        for indice, complement in complements.items()
                    }
                releve = admissible
            if releve > 0:
                for indice, complement in complements.items():
                    pensions[indice] = replace(
                        pensions[indice],
                        montant=pensions[indice].montant + complement,
                        detail=(pensions[indice].detail
                                + ", porté au minimum contributif"),
                    )
                total += releve
                minimum_applique = True
                fiabilite_globale = min(fiabilite_globale, fiabilite_minimum)
                avantages.append(AvantageApplique(
                    code="minimum_contributif",
                    libelle="Minimum contributif",
                    montant=releve,
                    detail=(
                        "porté au plancher, au prorata de la durée acquise"
                        + (", majoration des périodes cotisées comprise"
                           if majoration_ouverte else "")
                    ),
                ))

        if avantages_non_contributifs and eligibles_garanti:
            # Le minimum garanti n'est pas un minimum proratisé mais un BARÈME
            # sur la durée de services : quinze ans en ouvrent 57,5 % de la
            # référence, trente ans 95 %, quarante ans la totalité. Il ne
            # s'ajoute pas à la pension, il s'y substitue quand il lui est
            # supérieur.
            releve_garanti = 0.0
            for eligible in eligibles_garanti:
                if not eligible.ouvert:
                    continue
                plancher = self.minimum_garanti.montant(
                    annee_liquidation, eligible.trimestres_services
                )
                if plancher is None:
                    continue
                pension = pensions[eligible.indice]
                if 0 < pension.montant < plancher[0]:
                    complement = plancher[0] - pension.montant
                    releve_garanti += complement
                    fiabilite_globale = min(fiabilite_globale, plancher[1])
                    pensions[eligible.indice] = replace(
                        pension,
                        montant=plancher[0],
                        detail=pension.detail + ", porté au minimum garanti",
                    )
            if releve_garanti > 0:
                total += releve_garanti
                avantages.append(AvantageApplique(
                    code="minimum_garanti",
                    libelle="Minimum garanti de la fonction publique",
                    montant=releve_garanti,
                    detail="barème de l'article L. 17, sur la durée de services",
                ))

        # Surcote parentale (L. 351-1-2-1) : elle vient APRÈS les minima,
        # comme la surcote ordinaire, et AVANT la majoration pour enfants, qui
        # se calcule sur la pension surcotée. Elle ne récompense pas les mêmes
        # trimestres que la surcote ordinaire — celle-ci ne compte qu'au-delà
        # de l'âge légal, celle-là entre 63 ans et l'âge légal — et les deux se
        # cumulent donc sans se recouvrir.
        parametres_parentale = (
            self.surcote_parentale.parametres(annee_liquidation)
            if (avantages_non_contributifs and majoration_enfants is not None
                and not ignorer_penalite_age)
            else None
        )
        if parametres_parentale is not None:
            age_parental, taux_parental, maximum, fiabilite_parentale = (
                parametres_parentale
            )
            gain_parental = 0.0
            trimestres_parentaux = 0
            for indice, pension in enumerate(pensions):
                regime = self.catalogue[pension.regime]
                periode = regime.periode(
                    min(annee_liquidation, _derniere_annee(regime))
                )
                if (periode is None or "surcote_parentale"
                        not in periode.avantages_non_contributifs):
                    continue
                age_legal = self._age_ouverture(periode, carriere)
                requis = self._duree_requise(periode, carriere)[0]
                # La durée s'apprécie À 63 ANS, trimestres pour enfants
                # compris : c'est bien la durée qu'oppose la loi, et l'assuré
                # les détient déjà à cet âge.
                acquis = majoration_enfants.trimestres + _trimestres_valides_avant(
                    carriere, age_parental, annee_liquidation
                )
                if requis <= 0 or acquis < requis:
                    continue
                # La fenêtre ne dure quatre trimestres que si l'âge légal est
                # de 64 ans : la génération 1965, dont l'âge légal est de
                # 63 ans et trois mois, n'en a qu'un à faire valoir. Le modèle
                # ne date pas les trimestres au jour, et lui en compterait
                # quatre — d'où ce plafond, qui est la largeur de la fenêtre.
                fenetre = round((age_legal - age_parental) * 4)
                # Surtout pas `trimestres` : c'est la durée d'assurance tous
                # régimes, et l'écraser ici la faisait tomber à quatre.
                acquis_parentaux = min(maximum, fenetre, _trimestres_cotises_entre(
                    carriere, age_parental, age_legal, annee_liquidation
                ))
                if acquis_parentaux <= 0:
                    continue
                supplement = pension.montant * taux_parental * acquis_parentaux
                pensions[indice] = replace(
                    pension,
                    montant=pension.montant + supplement,
                    detail=(pension.detail + ", surcote parentale "
                            f"{taux_parental * acquis_parentaux:.2%}"),
                )
                gain_parental += supplement
                trimestres_parentaux = max(trimestres_parentaux, acquis_parentaux)
            if gain_parental > 0:
                total += gain_parental
                fiabilite_globale = min(fiabilite_globale, fiabilite_parentale)
                avantages.append(AvantageApplique(
                    code="surcote_parentale",
                    libelle="Surcote parentale",
                    montant=gain_parental,
                    detail=(f"{taux_parental * trimestres_parentaux:.2%} pour "
                            f"{trimestres_parentaux} trimestre"
                            f"{'s' if trimestres_parentaux > 1 else ''} entre "
                            f"{age_parental:g} ans et l'âge légal"),
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

        if (avantages_non_contributifs
                and self.parametres.minimum_vieillesse_dans_le_scenario_actuel
                and age_liquidation >= MinimumVieillesse.AGE_OUVERTURE):
            # L'ASPA vient en DERNIER, et pour cause : elle est différentielle.
            # Elle complète tout le reste, majorations comprises, jusqu'au
            # montant du barème — c'est la seule prestation du système actuel
            # qui ne suppose aucune cotisation, et donc celle qui creuse le
            # plus l'écart avec un compte notionnel.
            barème = self.minimum_vieillesse.plafond(annee_liquidation)
            if barème is not None and total < barème[0]:
                complement = barème[0] - total
                total = barème[0]
                fiabilite_globale = min(fiabilite_globale, barème[1])
                avantages.append(AvantageApplique(
                    code="minimum_vieillesse",
                    libelle="Minimum vieillesse (ASPA)",
                    montant=complement,
                    detail="allocation différentielle, barème d'une personne seule",
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
            age_ouverture_opposable=age_ouverture_reference,
            liquidation_ouverte=liquidation_ouverte,
            motif_ouverture=motif_ouverture,
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


def _trimestres_valides_avant(carriere: Carriere, age: float,
                              annee_liquidation: int) -> int:
    """Durée d'assurance acquise avant l'année où l'assuré atteint ``age``.

    Périodes assimilées comprises : c'est la durée d'assurance qu'oppose la
    condition de taux plein, et non la seule durée cotisée.
    """
    return sum(
        ligne.trimestres_valides
        for ligne in carriere.lignes
        if ligne.annee < annee_liquidation
        and ligne.annee - carriere.annee_naissance < age
    )


def _trimestres_cotises_entre(carriere: Carriere, age_bas: float, age_haut: float,
                              annee_liquidation: int) -> int:
    """Trimestres cotisés entre deux âges — bas inclus, haut exclu.

    C'est la fenêtre qu'ouvre la surcote parentale : entre 63 ans et l'âge
    légal, là où la surcote ordinaire ne compte encore rien.
    """
    return sum(
        ligne.trimestres_valides
        for ligne in carriere.lignes
        if ligne.cotise
        and ligne.annee < annee_liquidation
        and age_bas <= ligne.annee - carriere.annee_naissance < age_haut
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


#: Durée cotisée, tous régimes, qui ouvre la majoration du minimum contributif
#: au titre des périodes cotisées (article L. 351-10 du code de la sécurité
#: sociale). En deçà, seul le montant de base est dû.
TRIMESTRES_COTISES_MINIMUM_MAJORE = 120

#: Année à partir de laquelle chaque montant suit le SMIC et non plus les prix.
#: Le plafond d'écrêtement bascule avec le décret du 14 février 2014, qui le
#: revalorise « aux mêmes dates et dans les mêmes proportions que le salaire
#: minimum de croissance » (D. 173-21-0-0-1) ; les deux minima basculent avec
#: la réforme du 14 avril 2023. Avant ces dates, ils suivaient les prix, comme
#: les pensions.
INDEXATION_SUR_LE_SMIC = {
    "montant_base": 2023,
    "montant_majore": 2023,
    "plafond_ecretement": 2014,
}


class MinimumContributif:
    """Minimum contributif, minimum majoré et plafond d'écrêtement.

    Trois grandeurs, et pas une seule :

    * le **minimum**, auquel est portée la pension de base d'un assuré au taux
      plein, au prorata de sa durée dans le régime ;
    * le **minimum majoré**, servi à sa place quand la durée COTISÉE atteint la
      durée requise — près d'un cinquième au-dessus du premier ;
    * le **plafond d'écrêtement** de l'article L. 173-2 : le complément est
      rogné dès que l'ensemble des pensions dépasse ce total. Sans cette
      condition, le modèle servait le minimum à des assurés que leurs régimes
      complémentaires placent déjà bien au-dessus.

    Les trois sont des **ancres datées**, lues dans le code de la sécurité
    sociale (D. 351-2-1 et D. 173-21-0-0-1) et non dans une série annuelle : le
    code n'est pas modifié chaque année, les montants sont revalorisés par
    l'effet de la loi. C'est donc au modèle de le faire, et sur le bon index —
    **le SMIC** à partir de la date d'effet, les prix avant elle. Les
    revaloriser sur les prix comme le faisait ce module les décrochait d'autant
    que le SMIC a progressé plus vite.
    """

    def __init__(self, racine: Path, macro: DonneesMacro) -> None:
        self.macro = macro
        self._table: dict[tuple[str, int], tuple[float, Fiabilite]] = {}
        chemin = racine / "reference" / "legislation" / "minimum_contributif.csv"
        if not chemin.exists():
            return
        with chemin.open(encoding="utf-8") as flux:
            lignes = (l for l in flux if not l.lstrip().startswith("#"))
            for ligne in csv.DictReader(lignes):
                self._table[(ligne["mesure"], int(ligne["annee"]))] = (
                    float(ligne["valeur"]),
                    Fiabilite.depuis_texte(ligne["fiabilite"]),
                )

    def _revalorise(self, mesure: str, annee: int) -> tuple[float, Fiabilite]:
        """Ancre de la mesure, portée à l'année demandée.

        **Un montant connu passe avant tout calcul.** Quand l'année demandée
        figure au fichier, on la sert telle quelle : c'est ce que les caisses
        ont payé, et aucune projection ne vaut mieux que cela.

        Sinon, on projette depuis la valeur EN VIGUEUR à cette date — la
        dernière fixée avant elle, jamais une postérieure. Ramener une valeur
        postérieure en arrière ferait glisser dans le passé les marches que la
        loi a créées : la réforme de 2023 a relevé le minimum majoré de plus de
        30 %, et l'appliquer à 2020 le surestimait de 7,6 % par rapport au
        montant que l'État a lui-même rappelé.

        L'index de la projection ne dépend pas de l'ancre mais de l'ANNÉE
        TRAVERSÉE : les prix jusqu'à la bascule que la loi a fixée pour cette
        grandeur, le SMIC ensuite. Un montant ancré en 2007 et lu en 2015 se
        revalorise donc sur les prix, règle d'alors, quand le même ancré en
        2023 et lu en 2025 se revalorise sur le SMIC.
        """
        ancres = sorted(a for (m, a) in self._table if m == mesure)
        if not ancres:
            return 0.0, Fiabilite.ESTIMEE
        if annee in ancres:
            return self._table[(mesure, annee)]
        anterieures = [a for a in ancres if a < annee]
        reference = max(anterieures) if anterieures else ancres[0]
        valeur, fiabilite = self._table[(mesure, reference)]

        bascule = INDEXATION_SUR_LE_SMIC[mesure]
        pivot = min(max(reference, bascule), annee)
        coefficient = (self.macro.coefficient_prix(reference, pivot)
                       * self.macro.coefficient_smic(pivot, annee))
        return valeur * coefficient, fiabilite

    def valeurs(self, annee: int) -> tuple[float, float, float, Fiabilite]:
        """Montant de base, montant majoré et plafond d'écrêtement de l'année.

        Les deux montants sont rendus ensemble parce que le droit les additionne
        plutôt qu'il ne choisit entre eux : la pension est portée au montant de
        BASE au prorata de la durée d'assurance acquise dans le régime, puis
        l'écart entre le majoré et le base s'y ajoute au prorata de la seule
        durée COTISÉE. Servir l'un OU l'autre, comme le faisait ce module,
        donnait le montant plein de la majoration à qui n'a cotisé qu'une part
        de sa durée, et rien du tout à qui lui manque un trimestre.
        """
        if not self._table:
            return 0.0, 0.0, 0.0, Fiabilite.ESTIMEE
        base, fiabilite_base = self._revalorise("montant_base", annee)
        majore, fiabilite_majore = self._revalorise("montant_majore", annee)
        plafond, fiabilite_plafond = self._revalorise("plafond_ecretement", annee)
        return base, majore, plafond, min(
            fiabilite_base, fiabilite_majore, fiabilite_plafond
        )
