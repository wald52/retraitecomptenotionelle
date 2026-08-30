"""Paramètres de configuration du modèle.

Toutes les décisions de modélisation contestables sont réunies ici, en un seul
endroit, pour qu'on puisse les faire varier sans toucher au moteur. Les valeurs
par défaut correspondent au cahier des charges :

* indexation par « triple lock inversé » (minimum des trois taux) ;
* âge de référence à cliquet ;
* neutralisation intégrale des droits non contributifs ;
* fusion des régimes au cas le plus défavorable à compter de l'année de bascule.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path


RACINE_PROJET = Path(__file__).resolve().parents[2]
RACINE_DONNEES = RACINE_PROJET / "data"


class ModeIndexation(str, Enum):
    """Règle de revalorisation des comptes et des pensions."""

    #: min(inflation, croissance du salaire moyen nominal, productivité réelle).
    #: C'est la règle demandée, littéralement. Elle mêle un taux réel
    #: (productivité) à deux taux nominaux : en période de forte inflation, le
    #: minimum est presque toujours la productivité réelle, ce qui écrase la
    #: valeur réelle des comptes et des pensions. Effet voulu, mais massif :
    #: cf. docs/methodologie.md §3 et docs/limites.md §2.
    TRIPLE_LOCK_INVERSE = "triple_lock_inverse"

    #: Variante homogène : les trois termes sont ramenés en nominal
    #: (productivité réelle + inflation) avant de prendre le minimum.
    #: Fournie pour mesurer l'effet du mélange nominal/réel, pas par défaut.
    TRIPLE_LOCK_INVERSE_NOMINAL = "triple_lock_inverse_nominal"

    #: Indexation sur les seuls prix (règle en vigueur depuis 1993).
    PRIX = "prix"

    #: Indexation sur le salaire moyen (règle antérieure à 1987).
    SALAIRES = "salaires"


class SourceCotisations(str, Enum):
    """Origine du flux qui alimente le compte notionnel."""

    #: Taux de cotisation retraite effectivement en vigueur dans le régime
    #: d'affiliation, année par année (fidèle au principe « seules les
    #: cotisations comptent »).
    TAUX_HISTORIQUES = "taux_historiques"

    #: Taux unique appliqué à toute la carrière, quel que soit le régime.
    #: Utile pour isoler l'effet des règles de liquidation de l'effet des
    #: différences de taux de cotisation entre régimes.
    TAUX_UNIFORME = "taux_uniforme"


class ModeAgeReference(str, Enum):
    """Construction de l'âge auquel une liquidation est réputée « à l'heure »."""

    #: Cliquet sur l'âge du taux plein du régime général : l'âge de référence
    #: ne redescend jamais. Un départ à 60 ans en 1990 est donc traité comme
    #: une anticipation de 5 ans par rapport à l'âge de référence de 65 ans.
    CLIQUET_LEGAL = "cliquet_legal"

    #: Cliquet légal jusqu'à l'année de bascule, puis indexation sur
    #: l'espérance de vie de façon à stabiliser le ratio durée de
    #: retraite / durée de carrière.
    CLIQUET_PUIS_ESPERANCE_VIE = "cliquet_puis_esperance_vie"

    #: Âge du taux plein en vigueur l'année de liquidation, sans cliquet.
    #: Reproduit le droit positif ; sert de contrefactuel.
    LEGAL_SANS_CLIQUET = "legal_sans_cliquet"


class ContributionEmployeurPublic(str, Enum):
    """Que faire de la contribution employeur des régimes publics et spéciaux.

    Les fiches de régime ne stockent pas la même chose selon le secteur. Pour
    le privé, ``taux_cotisation_retraite`` est le total salarié + employeur —
    25,7 % pour un salarié en 2023. Pour la fonction publique et les régimes
    spéciaux, c'est la seule retenue de l'agent : 11,10 %, parfois 7 %.
    Alimenter un compte notionnel avec ces deux grandeurs revient à comparer un
    effort contributif complet à un demi-effort, et fait apparaître un écart de
    37 % entre un fonctionnaire et un salarié de même rémunération qui ne
    traduit rien de réel.

    Trois traitements sont concevables, deux sont disponibles :

    * ``EXCLUE`` — le taux stocké est utilisé tel quel. C'est ce que le modèle
      faisait sans le dire. Sous-estime massivement les carrières publiques.
    * ``ALIGNEE_SUR_LE_PRIVE`` (défaut) — les périodes marquées ``agent_seul``
      reçoivent le taux total du statut pivot privé de l'année. Seul traitement
      qui rende les 22 statuts comparables, et c'est déjà ce que fait la fusion
      des régimes après la bascule.

    Un troisième traitement, « contribution réelle de l'État », **n'est pas
    disponible, et ne peut pas l'être** : avant la création du compte
    d'affectation spéciale Pensions par la LOLF, en 2006, il n'existait aucun
    taux de contribution employeur de l'État. Les pensions étaient payées sur
    crédits budgétaires, sans taux. Le taux de 74,28 % qui existe depuis est un
    taux d'ÉQUILIBRE, recalculé pour que le compte tombe juste : l'injecter
    dans un compte notionnel rendrait le calcul circulaire, puisque les
    cotisations y seraient égales aux pensions par construction. Il n'y a donc
    pas de série historique de cotisations employeur publiques à retrouver.
    """

    EXCLUE = "exclue"
    ALIGNEE_SUR_LE_PRIVE = "alignee_sur_le_prive"


class AgeConversionDroitsAcquis(str, Enum):
    """Âge auquel les droits figés à la bascule sont convertis en capital.

    Le scénario prospectif transforme une pension déjà acquise en capital
    notionnel d'ouverture, en la multipliant par un diviseur. Reste à choisir
    l'âge auquel ce diviseur est pris — et le choix n'est pas neutre, puisque le
    capital sera ensuite redivisé par le diviseur de l'âge réel de liquidation.

    * ``REFERENCE`` valorise au diviseur de l'âge de référence. Un assuré qui
      liquide avant cet âge subit donc, sur ses droits déjà ouverts, un
      abattement égal au rapport des deux diviseurs — de l'ordre de 10 % pour
      trois ans d'écart. C'est la lecture stricte : dans un système notionnel,
      l'âge de départ se paie, y compris sur le passé.
    * ``LIQUIDATION`` valorise au diviseur de l'âge effectif de départ, pris à
      l'année de bascule. La conversion devient alors neutre : le passage aux
      comptes notionnels ne retire rien à des droits déjà ouverts, que le
      système actuel aurait servis sans décote. C'est la convention qu'une
      réforme réelle retiendrait, et le contrefactuel qui mesure ce que coûte
      l'autre.

    Dans les deux cas, l'écart de longévité entre l'année de bascule et l'année
    de liquidation subsiste : c'est un effet de table, pas une pénalité d'âge.
    """

    REFERENCE = "reference"
    LIQUIDATION = "liquidation"


class TableConversion(str, Enum):
    """Table de mortalité servant au coefficient de conversion."""

    #: Table unisexe (moyenne pondérée hommes/femmes). Choix par défaut :
    #: c'est la pratique des systèmes notionnels suédois et italien, et une
    #: table sexuée ferait mécaniquement baisser la pension des femmes de
    #: 8 à 12 % à capital notionnel identique.
    UNISEXE = "unisexe"

    #: Table par sexe. Actuariellement exacte, juridiquement inapplicable en
    #: France (principe de non-discrimination). Fournie pour mesurer l'écart.
    PAR_SEXE = "par_sexe"


@dataclass(frozen=True)
class Neutralisations:
    """Droits retirés du calcul, conformément au principe « seules les
    cotisations comptent ».

    Chaque drapeau à ``True`` signifie : ce droit est SUPPRIMÉ dans les
    scénarios notionnels. Ces drapeaux ne sont jamais lus par le scénario
    « système actuel » : ils décrivent ce que les scénarios notionnels retirent,
    pas ce que le droit en vigueur accorde.

    **Ce que le scénario 1 sert vraiment**, et il ne l'a pas toujours fait :
    minimum contributif, minimum garanti, minimum vieillesse, majoration pour
    enfants, majoration de durée d'assurance et bonification pour enfants de la
    fonction publique, AVPF, périodes assimilées, garantie minimale de points,
    carrière longue, décote et surcote.

    **Ce qu'il ne sert pas**, et qu'il ne peut donc pas retirer : la réversion,
    qui concerne le conjoint survivant et non l'assuré ; les bonifications de
    SERVICE — dépaysement, campagne militaire, cinquième — et la catégorie
    active, qui supposent de connaître le corps d'appartenance, la bonification
    pour ENFANTS étant, elle, servie depuis qu'elle est datée ; la
    pension majorée de référence du régime agricole ; les coefficients de
    solidarité et majorants de l'Agirc-Arrco, dispositif éteint dont l'effet
    temporaire serait représenté faussement par un modèle qui ne calcule qu'une
    pension annuelle unique. Voir ``docs/limites.md``.
    """

    minimum_contributif: bool = True
    minimum_garanti: bool = True
    minimum_vieillesse_aspa: bool = True
    pension_majoree_reference: bool = True
    majoration_enfants: bool = True
    majoration_duree_assurance: bool = True
    assurance_vieillesse_parents_au_foyer: bool = True
    reversion: bool = True
    bonifications: bool = True
    categorie_active: bool = True
    periodes_assimilees: bool = True
    garantie_minimale_points: bool = True
    carriere_longue: bool = True
    decote_surcote: bool = True
    coefficient_solidarite: bool = True

    def actives(self) -> list[str]:
        return [nom for nom, valeur in self.__dict__.items() if valeur]


@dataclass(frozen=True)
class Parametres:
    """Jeu complet de paramètres d'une simulation."""

    # --- Bornes temporelles -------------------------------------------------
    #: Année d'origine du système par répartition. 1941 = allocation aux vieux
    #: travailleurs salariés, premier mécanisme financé par les cotisations des
    #: actifs. Mettre 1945 pour partir des ordonnances créant la Sécurité sociale.
    annee_debut_repartition: int = 1941

    #: Année de bascule du scénario prospectif : les droits acquis jusqu'à cette
    #: année incluse sont calculés selon les règles actuelles, les droits
    #: postérieurs selon le compte notionnel du régime fusionné.
    annee_bascule: int = 2026

    #: Dernière année disponible dans les séries macroéconomiques.
    annee_courante: int = 2026

    #: Année dans les euros de laquelle les résultats sont exprimés. Sans cette
    #: conversion, comparer une pension liquidée en 1975 à une pension de 2064
    #: n'a aucun sens : l'écart de niveau des prix dépasse largement l'effet de
    #: la réforme simulée.
    annee_euros_constants: int = 2026

    #: Scénario de projection macroéconomique au-delà de la dernière observation
    #: (clé de ``data/reference/macro/hypotheses_projection.yaml``).
    scenario_projection: str = "cor_central"

    # --- Indexation ---------------------------------------------------------
    mode_indexation: ModeIndexation = ModeIndexation.TRIPLE_LOCK_INVERSE

    #: Plancher éventuel appliqué au taux d'indexation. ``None`` = aucun
    #: plancher : le triple lock inversé peut être négatif, ce qui est sa
    #: conséquence logique et non un défaut.
    plancher_indexation: float | None = None

    #: Applique la même règle d'indexation aux pensions déjà liquidées.
    indexer_pensions_liquidees: bool = True

    # --- Cotisations --------------------------------------------------------
    source_cotisations: SourceCotisations = SourceCotisations.TAUX_HISTORIQUES

    #: Taux utilisé si ``source_cotisations == TAUX_UNIFORME``.
    taux_cotisation_uniforme: float = 0.2531

    #: Les cotisations prélevées sans contrepartie de droits (taux d'appel
    #: Agirc-Arrco, contribution d'équilibre) alimentent-elles le compte ?
    #: ``True`` est cohérent avec « seules les cotisations comptent » : ce qui a
    #: été prélevé pour la retraite ouvre des droits.
    taux_appel_ouvre_droits: bool = True

    #: Traitement de la contribution employeur des régimes publics et spéciaux,
    #: dont les fiches ne stockent que la retenue de l'agent. Voir
    #: :class:`ContributionEmployeurPublic` — c'est le paramètre auquel
    #: renvoient les notes de `data/reference/regimes/fonction_publique.yaml`.
    traitement_contribution_employeur_etat: ContributionEmployeurPublic = (
        ContributionEmployeurPublic.ALIGNEE_SUR_LE_PRIVE
    )

    #: Statut dont les taux servent de référence quand la contribution
    #: employeur publique est alignée sur le privé.
    statut_pivot_cotisations: str = "salarie_prive_non_cadre"

    #: Plafonnement de l'assiette notionnelle, en multiples du plafond annuel de
    #: la Sécurité sociale. ``None`` = assiette déplafonnée.
    plafond_assiette_en_pass: float | None = 8.0

    # --- Âge de référence ---------------------------------------------------
    mode_age_reference: ModeAgeReference = ModeAgeReference.CLIQUET_LEGAL

    #: Ratio cible durée de retraite / durée de carrière, utilisé seulement en
    #: mode CLIQUET_PUIS_ESPERANCE_VIE.
    ratio_cible_retraite_carriere: float = 0.50

    # --- Conversion en rente ------------------------------------------------
    table_conversion: TableConversion = TableConversion.UNISEXE

    #: Taux de préfinancement (« front-loading ») incorporé au diviseur.
    #: 0 signifie : le diviseur est l'espérance de vie résiduelle actualisée au
    #: même taux que l'indexation, les deux se compensant exactement. C'est le
    #: choix par défaut, le plus lisible.
    taux_anticipe_conversion: float = 0.0

    #: Âge auquel les droits figés à la bascule sont convertis en capital
    #: d'ouverture, dans le scénario prospectif. ``REFERENCE`` applique aux
    #: droits déjà acquis la sanction du départ anticipé ; ``LIQUIDATION`` rend
    #: la conversion neutre. Voir :class:`AgeConversionDroitsAcquis`.
    age_conversion_droits_acquis: AgeConversionDroitsAcquis = (
        AgeConversionDroitsAcquis.REFERENCE
    )

    #: Table de génération (mortalité prospective) plutôt que table du moment.
    #: Une table du moment sous-estime la longévité des générations récentes et
    #: surestime donc leur pension.
    table_generation: bool = True

    #: Âge maximal considéré dans les tables.
    age_maximal: int = 120

    # --- Fusion des régimes -------------------------------------------------
    #: À compter de ``annee_bascule``, tous les régimes sont remplacés par un
    #: régime unique dont les paramètres sont les plus défavorables de
    #: l'ensemble des régimes existants.
    fusion_au_plus_defavorable: bool = True

    # --- Scénario « système actuel » ----------------------------------------
    #: Le minimum vieillesse (ASPA) fait-il partie de l'étalon ?
    #:
    #: C'est une décision de modélisation, pas un détail technique. L'ASPA est
    #: le dernier plancher du système actuel et le seul qui ne suppose aucune
    #: cotisation : l'omettre sous-estime le système en vigueur là même où
    #: l'écart avec un compte notionnel est le plus grand. Mais ce n'est pas une
    #: pension — elle est soumise à condition d'âge (65 ans), de ressources DU
    #: FOYER, et de demande, avec un non-recours que la DREES estime à la
    #: moitié des ayants droit ; elle est en outre récupérable sur les
    #: successions.
    #:
    #: Elle est donc servie par défaut, sous le barème d'une personne seule
    #: sans autre ressource — le cas le plus favorable —, et toujours comme une
    #: LIGNE SÉPARÉE de la cascade, de sorte qu'on puisse la retrancher d'un
    #: coup d'œil. Mettre ce paramètre à ``False`` la retire du calcul.
    minimum_vieillesse_dans_le_scenario_actuel: bool = True

    # --- Neutralisations ----------------------------------------------------
    neutralisations: Neutralisations = field(default_factory=Neutralisations)

    # --- Compartiments hors répartition -------------------------------------
    #: Les régimes marqués ``hors_repartition`` (RAFP, ex-assurances sociales)
    #: sont isolés et ne sont jamais convertis en capital notionnel.
    isoler_capitalisation: bool = True

    # --- Contrôle qualité des données ---------------------------------------
    #: Niveau de fiabilité minimal exigé des séries utilisées. En dessous, la
    #: simulation lève une erreur au lieu de produire un chiffre trompeur.
    #: Valeurs : "estimee" (tout accepter), "moyenne", "haute", "certifiee".
    fiabilite_minimale: str = "estimee"

    # --- Chemins ------------------------------------------------------------
    racine_donnees: Path = RACINE_DONNEES

    def avec(self, **modifications) -> "Parametres":
        """Retourne une copie modifiée (les paramètres sont immuables)."""
        return replace(self, **modifications)


#: Configuration de référence, celle qui répond littéralement au cahier des charges.
PARAMETRES_DEFAUT = Parametres()
