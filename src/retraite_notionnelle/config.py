"""Paramètres de configuration du modèle.

Toutes les décisions de modélisation contestables sont réunies ici, en un seul
endroit, pour qu'on puisse les faire varier sans toucher au moteur. Les valeurs
par défaut suivent le cahier des charges, à une exception près et une seule :
l'indexation, où le défaut est la règle d'ÉQUILIBRE et non la règle DEMANDÉE.
Un défaut est ce qu'on retient faute d'instruction contraire, pas ce qu'on
cherche à démontrer ; la règle demandée reste à un paramètre de distance.

* indexation par la croissance de la masse salariale — le taux d'équilibre de
  la répartition. Le « triple lock inversé » qui a donné son cahier des charges
  au modèle reste disponible, avec ses variantes (médiane, moyenne, tout en
  nominal), ainsi que la revalorisation réellement pratiquée par le régime
  général ;
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

    #: Médiane des trois mêmes termes, au lieu de leur minimum. Le terme retenu
    #: reste l'un des trois, mais celui du milieu : la règle cesse d'être
    #: gouvernée par la série la plus basse — en pratique la productivité réelle
    #: dès que l'inflation monte — sans pour autant retenir la plus haute.
    #: Variante moins sévère que la règle littérale, et défendable : c'est un
    #: choix robuste au sens statistique, insensible à une série aberrante.
    MEDIANE_TROIS_TAUX = "mediane_trois_taux"

    #: Moyenne arithmétique des trois mêmes termes. Elle donne un poids égal à
    #: chacun, y compris à la série la plus haute, et n'est donc plus une règle
    #: d'austérité. Deux réserves : la moyenne n'est pas un taux observé — aucun
    #: agrégat économique ne progresse à ce rythme —, et elle importe un tiers
    #: du mélange nominal/réel dans le résultat de CHAQUE année, là où le
    #: minimum et la médiane ne le font que les années où le terme réel gagne.
    #: Fournie parce qu'elle a été demandée, avec ce que ce fondement a de
    #: fragile.
    MOYENNE_TROIS_TAUX = "moyenne_trois_taux"

    #: Croissance de la MASSE SALARIALE — l'assiette des cotisations. C'est le
    #: taux de rendement interne d'un système en répartition (Samuelson 1958,
    #: Aaron 1966) : le seul qui laisse le système en équilibre sans toucher au
    #: taux de cotisation, et donc le taux d'indexation que la théorie des
    #: comptes notionnels désigne. Il vaut salaire moyen + emploi salarié, ce
    #: qui le rend NETTEMENT PLUS GÉNÉREUX que toutes les autres règles sur la
    #: période observée : l'emploi salarié a doublé depuis 1950. Ce n'est pas
    #: une règle d'austérité, c'est une règle d'équilibre.
    MASSE_SALARIALE = "masse_salariale"

    #: Revalorisation RÉELLEMENT PRATIQUÉE par le régime général : les
    #: coefficients des arrêtés annuels, tels que le scénario 1 les applique
    #: aux salaires portés au compte (les salaires jusqu'en 1986, les prix
    #: depuis, hors de la plage publiée). C'est le seul mode qui ne suppose
    #: rien : il demande ce qu'aurait donné le compte notionnel s'il avait
    #: rapporté exactement ce que le droit en vigueur a accordé. C'est donc
    #: LUI, et non ``PRIX``, qui neutralise l'indexation quand on veut isoler
    #: l'effet propre des comptes notionnels.
    REVALORISATION_PORTEE_AU_COMPTE = "revalorisation_portee_au_compte"

    #: Indexation sur les seuls prix (règle en vigueur depuis 1993). Ce n'est
    #: la règle du régime général que DEPUIS 1987 : avant, les arrêtés
    #: suivaient les salaires. Prendre cette ligne pour celle du droit positif
    #: sur toute la période est une erreur — voir le mode ci-dessus.
    PRIX = "prix"

    #: Indexation sur le salaire moyen (règle antérieure à 1987).
    SALAIRES = "salaires"


class SourceCotisations(str, Enum):
    """Origine du flux qui alimente le compte notionnel."""

    #: Taux de cotisation retraite effectivement en vigueur dans le régime
    #: d'affiliation, année par année (fidèle au principe « seules les
    #: cotisations comptent »).
    TAUX_HISTORIQUES = "taux_historiques"

    #: Taux unique appliqué à toute la carrière, quel que soit le régime : un
    #: TAUX D'ACQUISITION COMMUN, public et privé confondus. Ce qui a été
    #: prélevé au-delà — le surplus du compte d'affectation spéciale, le taux
    #: d'appel des complémentaires, la contribution d'équilibre d'un régime
    #: spécial — finance alors les engagements hérités du passé et n'ouvre aucun
    #: droit nouveau. Le taux est prélevé UNE FOIS sur la rémunération, et non
    #: une fois par régime : les régimes qui découpent la même tranche voient
    #: leurs assiettes réunies, pas additionnées. Aucun des cinq scénarios ne
    #: l'emploie — il sert à isoler l'effet des règles de liquidation de celui
    #: des différences de taux entre régimes.
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


class PartCotisation(str, Enum):
    """Quelle part de la cotisation retraite alimente le compte notionnel.

    Une cotisation retraite a deux parts : ce que l'assuré supporte et ce que
    son employeur verse. Les porter toutes deux au compte, ou n'y porter que la
    première, ne répond pas à la même question — et le modèle sait maintenant
    faire les deux **symétriquement**, public et privé.

    Il ne l'a pas toujours su. Les fiches de régime ne stockent pas la même
    grandeur selon le secteur : pour le privé, ``taux_cotisation_retraite`` est
    le total salarié + employeur ; pour la fonction publique et les régimes
    spéciaux, c'est la seule retenue de l'agent. Les comparer directement
    opposait un effort entier à un demi-effort, et faisait apparaître entre un
    fonctionnaire et un salarié de même rémunération un écart de 37 % qui ne
    traduisait rien de réel. Faute de mieux, le modèle prêtait alors au public
    la part employeur du privé.

    Deux séries l'en dispensent désormais : ``part_salariale`` dans les fiches,
    qui dit quelle fraction du taux l'assuré supporte, et
    ``legislation/contribution_employeur_public.csv``, qui porte ce que verse un
    employeur public. Les trois valeurs ci-dessous s'appuient sur elles.

    * ``SALARIALE`` (défaut, scénarios 2 et 3) — seule la part que l'assuré
      supporte lui-même alimente le compte. Pour un non-salarié, qui n'a pas
      d'employeur, c'est toute sa cotisation. Aucune convention, aucun emprunt :
      la comparaison public/privé porte sur la même grandeur des deux côtés.
    * ``TOTALE`` (scénarios 4 et 5) — salariale et patronale. La part patronale
      du privé est dans la fiche ; celle du public est celle qui a été
      réellement versée, décret par décret.
    * ``TOTALE_ALIGNEE`` — salariale et patronale, mais la part patronale du
      public est empruntée au statut pivot privé. C'est l'ancienne convention,
      conservée comme contrefactuel : elle répond à « à effort contributif égal,
      que donnerait la règle notionnelle ? », question légitime mais différente.

    Ce que ``TOTALE`` ne dit pas. Les taux employeur publics sont des taux
    d'ÉQUILIBRE, fixés pour que le compte tombe juste : 82,28 % en 2026 ne
    signifie pas qu'un fonctionnaire acquiert 82 % de son traitement en droits
    nouveaux, mais qu'il faut aujourd'hui cette contribution pour payer les
    pensions d'aujourd'hui.
    """

    SALARIALE = "salariale"
    TOTALE = "totale"
    TOTALE_ALIGNEE = "totale_alignee"


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

    **Ceci est une DÉCLARATION, pas une commande.** Aucun de ces drapeaux n'est
    lu par le moteur, et il ne peut pas l'être : dans un compte notionnel, la
    suppression de ces droits n'est pas une option qu'on active, elle est la
    conséquence mécanique de la règle d'accumulation — une année sans
    cotisation n'ajoute rien au compte, un trimestre gratuit n'est pas une
    cotisation, un minimum n'est pas un capital. Remettre l'un d'eux
    supposerait de sortir du modèle. La classe existe pour DIRE, en un seul
    endroit et de façon vérifiable, ce que les scénarios notionnels retirent au
    droit en vigueur ; ``retraite-notionnelle`` l'affiche, la documentation la
    reprend, et un test vérifie que le scénario « système actuel », lui, sert
    bien chacune des lignes qu'il est censé servir.

    Le mettre à faux ne change donc aucun résultat, et le docstring ci-dessous
    ne promet plus le contraire.

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
    #: Le défaut est la règle d'ÉQUILIBRE — la croissance de l'assiette des
    #: cotisations —, et non le triple lock inversé qui a donné son cahier des
    #: charges au modèle. Raison : le triple lock inversé est une règle
    #: proposée, la masse salariale est celle que la théorie de la répartition
    #: désigne, et un défaut doit être ce qu'on retient faute d'instruction
    #: contraire, pas ce qu'on veut démontrer. La règle demandée reste à un
    #: paramètre de distance : ``--indexation triple_lock_inverse``.
    mode_indexation: ModeIndexation = ModeIndexation.MASSE_SALARIALE

    #: Plancher éventuel appliqué au taux d'indexation. ``None`` = aucun
    #: plancher : le triple lock inversé peut être négatif, ce qui est sa
    #: conséquence logique et non un défaut.
    plancher_indexation: float | None = None

    # NOTE : il n'y a pas de paramètre « indexer les pensions liquidées ». Le
    # moteur ne calcule qu'une pension AU MOMENT DE LA LIQUIDATION, dans les
    # euros de cette année-là, pour les cinq scénarios ; il n'existe aucune
    # phase postérieure à revaloriser. Le drapeau qui figurait ici ne servait à
    # rien et laissait croire le contraire. Ce que la règle d'indexation fait
    # aux pensions déjà liquidées reste hors du modèle, et `docs/limites.md` le
    # dit maintenant.

    # --- Cotisations --------------------------------------------------------
    source_cotisations: SourceCotisations = SourceCotisations.TAUX_HISTORIQUES

    #: Taux utilisé si ``source_cotisations == TAUX_UNIFORME``. 25,31 % est
    #: l'effort contributif retraite total — salarié et employeur — d'un salarié
    #: du privé non cadre sous le plafond en 2025 : le taux que le privé
    #: supporte déjà. Aucun des cinq scénarios ne l'emploie ; c'est un
    #: contrefactuel, à activer explicitement.
    taux_cotisation_uniforme: float = 0.2531

    # NOTE : il n'y a pas non plus de paramètre « le taux d'appel ouvre-t-il des
    # droits ». Le compte notionnel porte ce qui a été PRÉLEVÉ, taux d'appel
    # compris — c'est la lecture directe de « seules les cotisations comptent »,
    # et c'est la seule que le moteur sache faire. Le drapeau qui figurait ici
    # n'était lu nulle part : le mettre à faux ne changeait rien.

    #: Part de la cotisation portée au compte : celle de l'assuré seul, ou
    #: celle de l'assuré et de son employeur. Voir :class:`PartCotisation`.
    #: Le défaut est celui des scénarios 2 et 3 ; les scénarios 4 et 5 le font
    #: varier, et rien d'autre.
    part_cotisation: PartCotisation = PartCotisation.SALARIALE

    #: Statut dont les taux servent de référence quand la part employeur du
    #: public est empruntée au privé (``TOTALE_ALIGNEE``), ou quand aucune série
    #: employeur n'est publiée pour le régime (``TOTALE``).
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

    # NOTE : l'âge terminal des tables de mortalité n'est pas un paramètre de
    # simulation mais une constante du module qui les construit —
    # ``donnees.mortalite.AGE_TERMINAL``. Le champ qui figurait ici la doublait
    # sans jamais l'atteindre.

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


#: Configuration de référence. Elle suit le cahier des charges partout sauf sur
#: l'indexation, où elle retient le taux d'équilibre de la répartition ; la
#: lecture littérale du cahier des charges est
#: ``PARAMETRES_DEFAUT.avec(mode_indexation=ModeIndexation.TRIPLE_LOCK_INVERSE)``.
PARAMETRES_DEFAUT = Parametres()
