"""Ce que la retraite a coûté : les dépenses réellement versées, depuis 1959.

Le reste du modèle calcule des DROITS — ce qu'une carrière ouvre. Ce module
porte la grandeur inverse et complémentaire : ce que la collectivité a
effectivement payé, année par année, système par système. Les deux ne se
déduisent pas l'une de l'autre, et c'est bien pourquoi il faut les deux.

La source est unique : les Comptes de la protection sociale de la DREES, risque
vieillesse-survie. C'est la seule série longue française de dépenses de retraite
publiée par son producteur, et le critère 1 du manifeste des sources — le
producteur prime sur le repreneur — la désigne sans hésitation.

Deux couvertures, et il faut les distinguer pour lire quoi que ce soit :

* le **total tous régimes** court de 1959 à 2024, sans trou ;
* la **ventilation par système** ne commence qu'en 1990, parce que la
  nomenclature d'avant ne se raccorde pas à celle d'après.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .chargement import Fiabilite, SerieAnnuelle, charger_serie_annuelle


@dataclass(frozen=True)
class Systeme:
    """Un système de retraite, au découpage des Comptes de la protection sociale.

    ``repartition`` dit si le système relève de la RÉPARTITION OBLIGATOIRE. Ce
    n'est pas une nuance : le risque vieillesse-survie porte aussi la
    capitalisation, l'aide sociale aux personnes âgées et le minimum vieillesse,
    et l'on ne compare pas des comptes notionnels à une allocation
    personnalisée d'autonomie.
    """

    code: str
    libelle: str
    glose: str
    repartition: bool


#: Les treize postes de la ventilation, dans l'ordre d'affichage : la
#: répartition obligatoire d'abord, par masse décroissante en 2024, puis ce qui
#: n'en relève pas. Les codes sont ceux qu'écrit ``scripts/verifier_donnees.py``
#: depuis les organismes de la DREES ; le test ``test_les_systemes_couvrent_la
#: _ventilation`` vérifie que les deux listes ne divergent pas.
SYSTEMES: tuple[Systeme, ...] = (
    Systeme(
        "regime_general", "Régime général (Cnav)",
        "Le socle des salariés du privé. Il absorbe depuis 2020 les artisans et "
        "les commerçants, dont le régime a été adossé à la Cnav : la marche de "
        "cette année-là est une réorganisation, pas une dépense nouvelle.",
        True,
    ),
    Systeme(
        "agirc_arrco", "Agirc-Arrco",
        "Les complémentaires des salariés du privé, deux caisses jusqu'en 2018 "
        "et une seule depuis. À elles seules, un quart de la dépense.",
        True,
    ),
    Systeme(
        "fonction_publique_etat", "Fonction publique d'État",
        "Les pensions civiles et militaires de l'État, versées par le compte "
        "d'affectation spéciale « Pensions ». La territoriale et l'hospitalière "
        "n'y sont pas : la DREES les range avec les régimes spéciaux.",
        True,
    ),
    Systeme(
        "regimes_speciaux", "Régimes spéciaux",
        "La CNRACL — fonction publique territoriale et hospitalière —, la SNCF, "
        "la RATP, les industries électriques et gazières et les autres, réunies "
        "par la comptabilité nationale sous un seul poste.",
        True,
    ),
    Systeme(
        "exploitants_agricoles", "Exploitants agricoles",
        "Le régime des chefs d'exploitation, dont la dépense recule en euros "
        "constants depuis trente ans : ses cotisants ont disparu avant ses "
        "pensionnés.",
        True,
    ),
    Systeme(
        "professions_liberales", "Professions libérales (CNAVPL)",
        "Base et complémentaires des sections professionnelles.",
        True,
    ),
    Systeme(
        "salaries_agricoles", "Salariés agricoles",
        "Le régime aligné de la MSA.",
        True,
    ),
    Systeme(
        "ircantec", "Ircantec",
        "La complémentaire des agents non titulaires de l'État et des "
        "collectivités.",
        True,
    ),
    Systeme(
        "non_salaries_autres", "Autres régimes de non-salariés",
        "Ce qui reste des régimes de non-salariés une fois les exploitants "
        "agricoles et les professions libérales mis à part — la part la plus "
        "réduite depuis l'adossement du RSI à la Cnav.",
        True,
    ),
    Systeme(
        "repartition_autres", "Autres régimes par répartition",
        "Fonds spéciaux, régimes résiduels, prestations vieillesse versées par "
        "les branches maladie et famille.",
        True,
    ),
    Systeme(
        "solidarite_etat", "Solidarité de l'État",
        "Minimum vieillesse et crédits d'impôt liés à l'âge. Non contributif : "
        "aucun compte notionnel ne le porterait, et c'est précisément ce que "
        "les scénarios notionnels retirent.",
        False,
    ),
    Systeme(
        "aide_sociale_locale", "Aide sociale des collectivités",
        "Allocation personnalisée d'autonomie, hébergement des personnes âgées "
        "dépendantes. Ce n'est pas de la retraite : c'est de la dépendance, que "
        "le risque vieillesse-survie loge au même endroit.",
        False,
    ),
    Systeme(
        "supplementaire", "Retraite supplémentaire",
        "Capitalisation : RAFP, contrats collectifs d'assurance, de prévoyance "
        "et de mutuelle, régimes d'entreprise. Un capital est placé — c'est ce "
        "qui la sépare de tout le reste de ce tableau.",
        False,
    ),
)

CODES_SYSTEMES = tuple(systeme.code for systeme in SYSTEMES)


class DepensesRetraite:
    """Les dépenses observées, avec leur ventilation et le PIB qui les rapporte."""

    def __init__(self, racine: Path) -> None:
        macro = racine / "reference" / "macro"
        self.total = charger_serie_annuelle(
            macro / "depenses_retraite.csv", "depenses_meur", nom="depenses_retraite"
        )
        self.pib = charger_serie_annuelle(
            macro / "pib_courant.csv", "pib_meur", nom="pib_courant"
        )
        self.systemes: dict[str, SerieAnnuelle] = {}
        for systeme in SYSTEMES:
            self.systemes[systeme.code] = charger_serie_annuelle(
                macro / "depenses_retraite_regimes.csv", "depenses_meur",
                nom=f"depenses_{systeme.code}", filtre={"regime": systeme.code},
            )

    # -- bornes --------------------------------------------------------------

    @property
    def premiere_annee(self) -> int:
        return self.total.premiere_annee

    @property
    def derniere_annee(self) -> int:
        return self.total.derniere_annee

    @property
    def premiere_annee_ventilee(self) -> int:
        return max(serie.premiere_annee for serie in self.systemes.values())

    def annees(self) -> list[int]:
        return list(range(self.premiere_annee, self.derniere_annee + 1))

    def annees_ventilees(self) -> list[int]:
        return list(range(self.premiere_annee_ventilee, self.derniere_annee + 1))

    # -- lectures ------------------------------------------------------------

    def depense(self, annee: int) -> float:
        """Dépense totale du risque vieillesse-survie, en millions d'euros courants."""
        return self.total(annee)

    def depense_systeme(self, code: str, annee: int) -> float:
        return self.systemes[code](annee)

    def part_pib(self, annee: int) -> float:
        """Part de la dépense dans le produit intérieur brut de la même année."""
        return self.total(annee) / self.pib(annee)

    def repartition(self, annee: int) -> float:
        """Ce que coûte la seule répartition obligatoire, ventilation à l'appui.

        Le total publié est plus large : il porte aussi la capitalisation,
        l'aide sociale aux personnes âgées et le minimum vieillesse. Cette
        somme les retranche — et n'est donc disponible que sur les années
        ventilées.
        """
        return sum(
            self.systemes[systeme.code](annee)
            for systeme in SYSTEMES if systeme.repartition
        )

    def fiabilite(self, annee: int) -> Fiabilite:
        return min(self.total.fiabilite(annee), self.pib.fiabilite(annee))
