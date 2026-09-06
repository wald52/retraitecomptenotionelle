"""Le coût agrégé des cinq systèmes, année par année, depuis 1959.

Le modèle calcule des pensions individuelles. Cette page en tire une grandeur
collective — ce que le système a coûté, et ce que les quatre autres auraient
coûté — sans devenir pour autant un modèle de population. La méthode tient en
une ligne, et c'est ce qui la rend contrôlable :

    coût du système S en t = dépense OBSERVÉE en t × (masse S / masse actuelle)

La dépense observée vient de la DREES et n'est pas modélisée. Seul le RAPPORT
l'est : c'est la moyenne des écarts de pension entre systèmes, pondérée par le
poids de chaque génération dans la masse de l'année. Un rapport est bien plus
robuste qu'un niveau — les erreurs de niveau du scénario 1, qui est l'étalon, se
retrouvent au dénominateur et s'annulent en grande partie.

CE QUI PÈSE COMBIEN
-------------------
La masse d'une année est reconstituée en croisant les douze cas types avec les
générations de 1880 à 1970, de cinq en cinq. Chaque couple pèse le produit de
deux choses : sa pension en euros constants, et sa PROBABILITÉ D'ÊTRE ENCORE EN
VIE cette année-là, lue dans les tables de mortalité du dépôt — les vraies,
celles qui sont observées depuis 1899.

LES TROIS LIMITES, ET LEUR SENS
-------------------------------
1. **La population est supposée stationnaire.** Chaque génération pèse le même
   effectif de départ ; le baby-boom, lui, en a fait naître un tiers de plus.
   Les poids en sont déplacés, mais pas les écarts qu'ils pondèrent : une
   génération surreprésentée tire le rapport vers SON écart, lequel varie de
   moins de trois points d'une décennie à l'autre après 1980.
2. **Les douze cas types pèsent d'un poids égal.** Ils ne décrivent pas la
   population active française — il y a moins d'agents de conduite que de
   salariés au salaire moyen. C'est la convention de la grille des cas types,
   et elle est ici reconduite plutôt que remplacée par une pondération qu'aucune
   source ne fixerait.
3. **Avant 1975, la reconstitution est mince.** La répartition ne commence
   qu'en 1941 : les générations d'avant 1880 n'ont, dans ce modèle, aucune
   pension, et plusieurs régimes n'existaient pas encore. Les premières années
   reposent donc sur deux ou trois générations et la moitié des cas types. Le
   rapport y est donné, mais il ne vaut pas ce que valent ceux d'après 1980.

Rien de tout cela ne touche aux scénarios 3 et 5 : leur bascule est fixée à
2026, si bien qu'AUCUNE pension servie avant cette date n'en est modifiée. Leur
coût est donc, sur toute la période observée, exactement celui du système
actuel. Ce n'est pas un artefact de la méthode : c'est ce que veut dire
« réforme prospective ».
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .castypes import CAS_TYPES, CasType, calculer_cas_types
from .donnees.chargement import Fiabilite
from .donnees.depenses import DepensesRetraite
from .simulateur import Simulateur

#: Les cinq systèmes, dans l'ordre du tableau de comparaison. Ce sont les
#: attributs de ``Comparaison`` ; « actuel » est l'étalon et le dénominateur.
SCENARIOS: tuple[tuple[str, str], ...] = (
    ("actuel", "1. Système actuel"),
    ("notionnel_retroactif", "2. Notionnel rétroactif, part salariale"),
    ("notionnel_prospectif", "3. Notionnel dès la bascule, part salariale"),
    ("notionnel_retroactif_employeur", "4. Notionnel rétroactif, avec la part patronale"),
    ("notionnel_prospectif_employeur", "5. Notionnel dès la bascule, avec la part patronale"),
)

#: Première génération dont une liquidation puisse tomber après le début de la
#: répartition (1941) : née en 1880, elle liquide à 61 ans en 1941. En deçà, le
#: modèle refuse — à juste titre — de calculer quoi que ce soit.
PREMIERE_GENERATION = 1880

#: Dernière génération retenue. Née en 1970, elle liquide au plus tôt à 52 ans,
#: soit en 2022 : au-delà, aucune pension ne serait servie dans la fenêtre
#: observée, et la simulation serait payée pour rien.
DERNIERE_GENERATION = 1970

#: Pas de la grille de générations. Cinq ans suffisent : le rapport varie de
#: moins d'un point d'une génération à la suivante, et le pas commande
#: directement le temps de calcul de la page.
PAS_GENERATIONS = 5

#: Année à partir de laquelle la reconstitution repose sur l'ensemble des cas
#: types et sur au moins quatre générations. Avant, la page le dit.
PREMIERE_ANNEE_ROBUSTE = 1975


def generations() -> tuple[int, ...]:
    return tuple(range(PREMIERE_GENERATION, DERNIERE_GENERATION + 1, PAS_GENERATIONS))


@dataclass(frozen=True)
class Pensionne:
    """Un couple (cas type, génération), et ce qu'il pèse dans chaque année."""

    #: Année de liquidation : avant elle, aucune pension n'est servie.
    annee_liquidation: int
    #: Probabilité d'être en vie, indice 0 à la liquidation.
    survie: tuple[float, ...]
    #: Pension annuelle en euros constants, par scénario.
    pensions: dict[str, float]

    def poids(self, annee: int) -> float:
        duree = annee - self.annee_liquidation
        if duree < 0 or duree >= len(self.survie):
            return 0.0
        return self.survie[duree]


@dataclass
class CoutAnnuel:
    """Le coût d'une année, observé puis recalculé pour chaque système."""

    annee: int
    #: Dépense observée, en millions d'euros courants.
    observee: float
    #: Coefficient de passage en euros constants de l'année de référence.
    coefficient_constants: float
    #: Part de la dépense observée dans le PIB de la même année.
    part_pib: float
    #: Rapport de la masse de chaque système à celle du système actuel.
    rapports: dict[str, float]
    #: Nombre de couples (cas type, génération) qui portent l'année.
    pensionnes: int

    def cout(self, scenario: str) -> float:
        """Coût du système, en millions d'euros courants de l'année."""
        return self.observee * self.rapports[scenario]

    def cout_constants(self, scenario: str) -> float:
        return self.cout(scenario) * self.coefficient_constants

    @property
    def observee_constants(self) -> float:
        return self.observee * self.coefficient_constants


@dataclass
class Cout:
    """La série complète, et les cumuls qu'on en tire."""

    annees: list[CoutAnnuel] = field(default_factory=list)
    #: Année d'expression des euros constants.
    annee_euros: int = 0
    #: Générations effectivement simulées.
    generations: tuple[int, ...] = ()
    #: Cas types que le modèle a refusé de calculer, par motif.
    echecs: dict[str, int] = field(default_factory=dict)
    fiabilite: Fiabilite = Fiabilite.ESTIMEE

    @property
    def premiere_annee(self) -> int:
        return self.annees[0].annee

    @property
    def derniere_annee(self) -> int:
        return self.annees[-1].annee

    def cumul(self, scenario: str) -> float:
        """Cumul depuis la première année, en millions d'euros CONSTANTS.

        Sommer des euros courants de 1959 et de 2024 n'aurait aucun sens : les
        premiers valent une vingtaine de fois les seconds. Le cumul est donc
        celui des montants ramenés à une même unité.
        """
        return sum(annee.cout_constants(scenario) for annee in self.annees)

    def cumul_observe(self) -> float:
        return sum(annee.observee_constants for annee in self.annees)

    def confondus_avec_actuel(self) -> tuple[str, ...]:
        """Scénarios dont le coût ne s'écarte JAMAIS de celui du système actuel.

        Sur la fenêtre observée, ce sont les scénarios prospectifs : leur
        bascule est postérieure à la dernière année publiée, si bien qu'aucune
        pension n'en est modifiée et que le rapport vaut exactement un. L'égalité
        est stricte et non approchée — le scénario prospectif RECOPIE la pension
        du scénario actuel pour qui a liquidé avant la bascule —, et c'est
        pourquoi elle se teste à l'identité.

        Le calcul est fait, et non écrit en dur : une bascule avancée avant la
        dernière année observée séparerait les courbes, et la page le montrerait.
        """
        return tuple(
            scenario for scenario, _ in SCENARIOS
            if scenario != "actuel"
            and all(ligne.rapports[scenario] == 1.0 for ligne in self.annees)
        )

    def annee(self, millesime: int) -> CoutAnnuel | None:
        for ligne in self.annees:
            if ligne.annee == millesime:
                return ligne
        return None


def _pensionnes(simulateur: Simulateur,
                cas_types: tuple[CasType, ...]) -> tuple[list[Pensionne], dict[str, int]]:
    """Simule la grille et en tire, pour chaque couple, son poids dans le temps."""
    grille = calculer_cas_types(simulateur, cas_types, generations())
    mortalite = simulateur.mortalite
    pensionnes: list[Pensionne] = []
    for comparaison in grille.resultats.values():
        carriere = comparaison.carriere
        pensionnes.append(Pensionne(
            annee_liquidation=carriere.annee_liquidation,
            survie=mortalite.courbe(
                carriere.age_liquidation, float(carriere.annee_liquidation), None
            ),
            pensions={
                scenario: comparaison.en_euros_constants(
                    getattr(comparaison, scenario).pension_annuelle
                )
                for scenario, _ in SCENARIOS
            },
        ))
    motifs: dict[str, int] = {}
    for motif in grille.echecs.values():
        motifs[motif] = motifs.get(motif, 0) + 1
    return pensionnes, motifs


def calculer_cout(simulateur: Simulateur, depenses: DepensesRetraite,
                  cas_types: tuple[CasType, ...] = CAS_TYPES) -> Cout:
    """Le coût observé et les quatre contrefactuels, année par année.

    Les années où le modèle ne sert AUCUNE pension — celles d'avant la première
    liquidation possible — sont écartées : un rapport y serait une division par
    zéro, et non un résultat.
    """
    pensionnes, echecs = _pensionnes(simulateur, cas_types)
    macro = simulateur.macro
    annee_euros = simulateur.parametres.annee_euros_constants

    lignes: list[CoutAnnuel] = []
    for annee in depenses.annees():
        masses = {scenario: 0.0 for scenario, _ in SCENARIOS}
        vivants = 0
        for pensionne in pensionnes:
            poids = pensionne.poids(annee)
            if poids <= 0.0:
                continue
            vivants += 1
            for scenario, _ in SCENARIOS:
                masses[scenario] += poids * pensionne.pensions[scenario]
        if masses["actuel"] <= 0.0:
            continue
        lignes.append(CoutAnnuel(
            annee=annee,
            observee=depenses.depense(annee),
            coefficient_constants=macro.coefficient_prix(annee, annee_euros),
            part_pib=depenses.part_pib(annee),
            rapports={
                scenario: masses[scenario] / masses["actuel"]
                for scenario, _ in SCENARIOS
            },
            pensionnes=vivants,
        ))

    fiabilite = min(
        (depenses.fiabilite(ligne.annee) for ligne in lignes),
        default=Fiabilite.ESTIMEE,
    )
    return Cout(
        annees=lignes,
        annee_euros=annee_euros,
        generations=generations(),
        echecs=echecs,
        # Le contrefactuel ne peut jamais valoir mieux qu'« estimé » : la
        # dépense observée est certifiée, le rapport qui la corrige ne l'est
        # pas et ne peut pas l'être — aucune institution ne publie ce qu'un
        # système qui n'a pas existé aurait coûté.
        fiabilite=min(fiabilite, Fiabilite.ESTIMEE),
    )
