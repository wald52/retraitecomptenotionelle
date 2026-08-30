"""Simulateur : assemble les données, le moteur et les cinq scénarios.

C'est le point d'entrée unique. Une seule instance charge les données une fois
et peut ensuite simuler autant de carrières que voulu :

    >>> from retraite_notionnelle import Parametres
    >>> from retraite_notionnelle.simulateur import Simulateur
    >>> simulateur = Simulateur(Parametres())
    >>> carriere = simulateur.carriere_simple(
    ...     annee_naissance=1960, sexe="H",
    ...     affiliation="salarie_prive_non_cadre",
    ...     age_debut=20, age_liquidation=60)
    >>> comparaison = simulateur.simuler(carriere)
    >>> print(comparaison.tableau())     # doctest: +SKIP
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from .carriere import Affiliations, Carriere
from .config import Parametres, PartCotisation
from .donnees.chargement import DonneeInsuffisante, Fiabilite
from .donnees.macro import DonneesMacro
from .donnees.mortalite import DonneesMortalite
from .donnees.regimes import CatalogueRegimes
from .moteur.age_reference import AgeReference
from .moteur.compte import ConstructeurCompte
from .moteur.conversion import Convertisseur
from .moteur.fusion import RegimeFusionne, fusionner
from .moteur.indexation import Indexation
from .scenarios.actuel import ResultatActuel, ScenarioActuel
from .scenarios.notionnel import ResultatNotionnel, ScenarioNotionnel


#: Les quatre scénarios notionnels, dans l'ordre où ils s'affichent, avec le
#: numéro et le titre sous lesquels le tableau, la page et l'API les citent.
#:
#: Deux paires : 2 et 3 ne portent au compte que la part SALARIALE de la
#: cotisation, 4 et 5 y ajoutent la part PATRONALE. À l'intérieur de chaque
#: paire, l'un est rétroactif et l'autre prospectif. Rien d'autre ne les sépare,
#: et c'est ce qui les rend comparables deux à deux : 4 se lit contre 2, 5
#: contre 3, et l'écart mesure exactement ce que l'employeur verse.
SCENARIOS_NOTIONNELS = (
    ("notionnel_retroactif", 2, "Notionnel rétroactif, part salariale"),
    ("notionnel_prospectif", 3, "Notionnel dès {bascule}, part salariale"),
    ("notionnel_retroactif_employeur", 4,
     "Notionnel rétroactif, salariale + patronale"),
    ("notionnel_prospectif_employeur", 5,
     "Notionnel dès {bascule}, salariale + patronale"),
)


@dataclass(frozen=True)
class ContributionEmployeur:
    """Qui a payé le compte notionnel, et sur quelles années.

    En euros courants cumulés, sans revalorisation : la somme de ce qui a
    effectivement transité, et non un capital notionnel. C'est la mesure directe
    de ce qui sépare les scénarios 2 et 3 des scénarios 4 et 5 — le premier
    couple ne porte au compte que ``agent``, le second ``total``.

    Un non-salarié n'a pas d'employeur : ``employeur`` y est nul et les quatre
    scénarios se réduisent à deux.
    """

    #: Cotisations portées au compte par le scénario 4, agent et employeur
    #: confondus.
    total: float
    #: Part de ce total versée par l'employeur.
    employeur: float
    #: Nombre d'années où la contribution employeur PUBLIQUE réelle a été
    #: trouvée, par nature (``appelee``, ``implicite``), et où il a fallu s'en
    #: passer (``repli``). Vide pour un salarié du privé, dont la fiche porte
    #: la répartition : la question ne s'y pose pas.
    annees_par_origine: dict[str, int]

    @property
    def agent(self) -> float:
        """Ce qui reste : la cotisation que l'assuré supporte lui-même."""
        return self.total - self.employeur

    @property
    def part(self) -> float:
        """Part de l'employeur dans le total versé, entre 0 et 1."""
        return self.employeur / self.total if self.total else 0.0

    @property
    def a_un_employeur(self) -> bool:
        return self.employeur > 0

    @property
    def concerne_un_regime_public(self) -> bool:
        return bool(self.annees_par_origine)

    @property
    def annees_trouvees(self) -> int:
        return sum(nombre for origine, nombre in self.annees_par_origine.items()
                   if origine != "repli")

    @property
    def annees_repli(self) -> int:
        return self.annees_par_origine.get("repli", 0)


@dataclass
class Comparaison:
    """Les cinq résultats, côte à côte, pour une même carrière."""

    carriere: Carriere
    actuel: ResultatActuel
    notionnel_retroactif: ResultatNotionnel
    notionnel_prospectif: ResultatNotionnel
    notionnel_retroactif_employeur: ResultatNotionnel
    notionnel_prospectif_employeur: ResultatNotionnel
    regime_fusionne: RegimeFusionne
    parametres: Parametres
    #: Coefficient de passage des euros de l'année de liquidation aux euros
    #: constants de ``parametres.annee_euros_constants``.
    coefficient_euros_constants: float = 1.0

    # -- indicateurs ---------------------------------------------------------

    def en_euros_constants(self, montant: float) -> float:
        return montant * self.coefficient_euros_constants

    @property
    def fiabilite(self) -> Fiabilite:
        """Fiabilité de l'ÉTALON et des deux scénarios de référence.

        Les scénarios 4 et 5 en sont exclus à dessein : ils reposent sur une
        série employeur qui n'existe pas pour tous les régimes ni sur toutes les
        années. Les laisser qualifier l'ensemble ferait retomber toute
        simulation publique à « estimée » alors que les trois premiers
        scénarios, eux, ne se sont pas dégradés. Chacun porte sa propre
        fiabilité, et la sortie JSON les donne une à une.
        """
        return min(
            self.actuel.fiabilite,
            self.notionnel_retroactif.fiabilite,
            self.notionnel_prospectif.fiabilite,
        )

    @property
    def contribution_employeur(self) -> ContributionEmployeur:
        """Agent, employeur, total — la décomposition du scénario 4."""
        compte = self.notionnel_retroactif_employeur.compte
        return ContributionEmployeur(
            total=compte.cotisations_versees,
            employeur=compte.cotisations_employeur,
            annees_par_origine=compte.annees_part_employeur,
        )

    def variation(self, scenario: str) -> float:
        """Écart relatif d'un scénario notionnel au système actuel."""
        reference = self.actuel.pension_annuelle
        if reference <= 0:
            return float("nan")
        cible = getattr(self, scenario).pension_annuelle
        return cible / reference - 1.0

    @property
    def taux_remplacement_actuel(self) -> float:
        return _taux_remplacement(self.carriere, self.actuel.pension_annuelle)

    @property
    def taux_remplacement_retroactif(self) -> float:
        return _taux_remplacement(
            self.carriere, self.notionnel_retroactif.pension_annuelle
        )

    @property
    def taux_remplacement_prospectif(self) -> float:
        return _taux_remplacement(
            self.carriere, self.notionnel_prospectif.pension_annuelle
        )

    def taux_remplacement(self, scenario: str) -> float:
        """Taux de remplacement de n'importe lequel des scénarios notionnels."""
        return _taux_remplacement(
            self.carriere, getattr(self, scenario).pension_annuelle
        )

    # -- restitution ---------------------------------------------------------

    def tableau(self) -> str:
        c = self.carriere
        ecart = self.notionnel_retroactif.ecart_age
        conversion = self.notionnel_retroactif.conversion

        lignes = [
            f"Assuré : {c.identifiant} — né(e) en {c.annee_naissance}, sexe {c.sexe}",
            f"Carrière : {c.premiere_annee}-{c.derniere_annee}, "
            f"{len(c.annees_cotisees)} années cotisées, "
            f"{c.trimestres_actuels} trimestres au sens actuel",
            f"Liquidation : {c.age_liquidation:g} ans en {c.annee_liquidation}",
            f"Âge de référence à cliquet : {ecart.age_reference:g} ans -> {ecart}",
            f"Coefficient de conversion : {conversion.diviseur:.2f} "
            f"(espérance de vie résiduelle {conversion.esperance_residuelle:.2f} ans, "
            f"table {conversion.table})",
            "",
            f"Montants bruts annuels. La colonne « constants » convertit en euros "
            f"de {self.parametres.annee_euros_constants},",
            "seule unité permettant de comparer des liquidations d'années différentes.",
            "",
            f"{'Scénario':<54} {'Courants':>11} {'Constants':>11} "
            f"{'Mensuel':>9} {'Écart':>8}",
            "-" * 96,
        ]

        def ligne(nom: str, montant: float, ecart_relatif: float | None) -> str:
            variation = "réf." if ecart_relatif is None else f"{ecart_relatif:+.1%}"
            constant = self.en_euros_constants(montant)
            return (
                f"{nom:<54} {montant:>10,.0f}€ {constant:>10,.0f}€ "
                f"{constant/12:>8,.0f}€ {variation:>8}"
            )

        lignes.append(ligne("1. Système actuel", self.actuel.pension_annuelle, None))
        for cle, numero, titre in SCENARIOS_NOTIONNELS:
            lignes.append(ligne(
                f"{numero}. " + titre.format(bascule=self.parametres.annee_bascule),
                getattr(self, cle).pension_annuelle,
                self.variation(cle),
            ))

        rente_capi = self.notionnel_retroactif.rente_capitalisation_annuelle
        if rente_capi > 0:
            lignes += [
                "-" * 96,
                ligne("   compartiment capitalisation (servi à part)", rente_capi, None),
            ]

        lignes += [
            "",
            f"Taux de remplacement — actuel {self.taux_remplacement_actuel:.1%}, "
            f"rétroactif {self.taux_remplacement_retroactif:.1%}, "
            f"prospectif {self.taux_remplacement_prospectif:.1%}",
            f"Capital notionnel rétroactif : "
            f"{self.notionnel_retroactif.capital_notionnel:,.0f} € "
            f"(cotisations versées {self.notionnel_retroactif.compte.cotisations_versees:,.0f} €, "
            f"rendement cumulé ×{self.notionnel_retroactif.compte.rendement_cumule:.2f})",
            f"Fiabilité du résultat : {self.fiabilite} "
            f"— voir docs/limites.md avant toute interprétation",
        ]

        employeur = self.contribution_employeur
        if employeur.a_un_employeur or employeur.concerne_un_regime_public:
            lignes += ["", "Qui verse la cotisation, en euros courants cumulés :"]
            if employeur.a_un_employeur:
                lignes += [
                    f"  part salariale     {employeur.agent:>13,.0f} €"
                    f"   scénarios 2 et 3",
                    f"  part patronale     {employeur.employeur:>13,.0f} €"
                    f"   soit {employeur.part:.0%} du total",
                    f"  total              {employeur.total:>13,.0f} €"
                    f"   scénarios 4 et 5",
                ]
            if employeur.concerne_un_regime_public:
                lignes.append(
                    f"  contribution employeur publique trouvée sur "
                    f"{employeur.annees_trouvees} année(s)"
                    + (f", inconnue sur {employeur.annees_repli} — le taux du "
                       "privé y tient lieu d'étalon"
                       if employeur.annees_repli else "")
                )

        if self.actuel.minimum_applique:
            lignes.append(
                "Note : le minimum contributif s'applique dans le scénario 1 ; "
                "il est supprimé dans les scénarios 2 à 5."
            )
        if not self.actuel.liquidation_ouverte:
            age = self.actuel.age_ouverture_opposable
            lignes.append(
                "ATTENTION : le droit en vigueur N'OUVRE PAS cette liquidation à "
                f"{self.carriere.age_liquidation:g} ans"
                + (f" — il faut attendre {age:g} ans" if age is not None else "")
                + ". Le montant du scénario 1 est un contrefactuel, pas une "
                "pension que le système actuel servirait."
            )
        return "\n".join(lignes)

    def dictionnaire(self) -> dict:
        """Forme sérialisable, pour une API ou un export."""
        return {
            "assure": {
                "identifiant": self.carriere.identifiant,
                "annee_naissance": self.carriere.annee_naissance,
                "sexe": self.carriere.sexe,
                "age_liquidation": self.carriere.age_liquidation,
                "annee_liquidation": self.carriere.annee_liquidation,
                "annees_cotisees": len(self.carriere.annees_cotisees),
                "trimestres_actuels": self.carriere.trimestres_actuels,
                "affiliations": list(self.carriere.affiliations_utilisees()),
            },
            "age_reference": {
                "age": self.notionnel_retroactif.ecart_age.age_reference,
                "ecart_annees": self.notionnel_retroactif.ecart_age.ecart,
                "anticipe": self.notionnel_retroactif.ecart_age.anticipe,
            },
            "conversion": {
                "diviseur": self.notionnel_retroactif.conversion.diviseur,
                "esperance_residuelle": self.notionnel_retroactif.conversion.esperance_residuelle,
                "table": self.notionnel_retroactif.conversion.table,
            },
            "scenarios": {
                "actuel": {
                    "pension_annuelle": self.actuel.pension_annuelle,
                    "pension_annuelle_euros_constants": self.en_euros_constants(
                        self.actuel.pension_annuelle
                    ),
                    "pension_mensuelle": self.actuel.pension_mensuelle,
                    "taux_remplacement": self.taux_remplacement_actuel,
                    "par_regime": [
                        {"regime": p.regime, "montant": p.montant, "detail": p.detail}
                        for p in self.actuel.pensions_par_regime
                    ],
                    "minimum_applique": self.actuel.minimum_applique,
                    "liquidation_ouverte": self.actuel.liquidation_ouverte,
                    "motif_ouverture": self.actuel.motif_ouverture,
                    "age_ouverture_opposable": self.actuel.age_ouverture_opposable,
                    "total_contributif": self.actuel.total_contributif,
                    "avantages_appliques": [
                        {"code": a.code, "libelle": a.libelle,
                         "montant": a.montant, "detail": a.detail}
                        for a in self.actuel.avantages_appliques
                    ],
                },
                **{
                    cle: _resume_notionnel(
                        getattr(self, cle), self.taux_remplacement(cle),
                        self.variation(cle), self.coefficient_euros_constants,
                    )
                    for cle, _, _ in SCENARIOS_NOTIONNELS
                },
            },
            "contribution_employeur": {
                "total": self.contribution_employeur.total,
                "employeur": self.contribution_employeur.employeur,
                "agent": self.contribution_employeur.agent,
                "part": self.contribution_employeur.part,
                "annees_par_origine": dict(
                    sorted(self.contribution_employeur.annees_par_origine.items())
                ),
            },
            "unite": {
                "euros_constants_de": self.parametres.annee_euros_constants,
                "coefficient": self.coefficient_euros_constants,
                "scenario_projection": self.parametres.scenario_projection,
            },
            "regime_fusionne": {
                "annee_bascule": self.regime_fusionne.annee_bascule,
                "age_ouverture": self.regime_fusionne.age_ouverture,
                "age_taux_plein": self.regime_fusionne.age_taux_plein,
                "duree_requise_trimestres": self.regime_fusionne.duree_requise_trimestres,
                "taux_cotisation": self.regime_fusionne.taux_cotisation_retraite,
                "regimes_fusionnes": list(self.regime_fusionne.regimes_fusionnes),
                "origines": dict(self.regime_fusionne.origines),
            },
            "fiabilite": str(self.fiabilite),
        }


def _resume_notionnel(resultat: ResultatNotionnel, taux_remplacement: float,
                      variation: float, coefficient: float = 1.0) -> dict:
    return {
        "pension_annuelle": resultat.pension_annuelle,
        "pension_annuelle_euros_constants": resultat.pension_annuelle * coefficient,
        "pension_mensuelle": resultat.pension_mensuelle,
        "taux_remplacement": taux_remplacement,
        "variation_vs_actuel": variation,
        "capital_notionnel": resultat.capital_notionnel,
        "capital_droits_acquis": resultat.capital_droits_acquis,
        "droits_acquis": None if resultat.droits_acquis is None else {
            "pension_figee": resultat.droits_acquis.pension_figee,
            "age_conversion": resultat.droits_acquis.age_conversion,
            "diviseur": resultat.droits_acquis.diviseur,
            "capital_a_la_bascule": resultat.droits_acquis.capital_a_la_bascule,
            "coefficient_revalorisation": resultat.droits_acquis.coefficient_revalorisation,
            "capital": resultat.droits_acquis.capital,
        },
        "cotisations_versees": resultat.compte.cotisations_versees,
        "rendement_cumule": resultat.compte.rendement_cumule,
        "cotisations_employeur": resultat.compte.cotisations_employeur,
        "annees_part_employeur": dict(
            sorted(resultat.compte.annees_part_employeur.items())
        ),
        "rente_capitalisation": resultat.rente_capitalisation_annuelle,
        "fiabilite": str(resultat.fiabilite),
    }


def _taux_remplacement(carriere: Carriere, pension: float) -> float:
    """Pension rapportée au dernier revenu d'activité."""
    derniers = [l for l in carriere.lignes if l.cotise]
    if not derniers or pension <= 0:
        return 0.0
    return pension / derniers[-1].revenu


class Simulateur:
    """Façade : charge les données une fois, simule autant de carrières que voulu."""

    def __init__(self, parametres: Parametres | None = None) -> None:
        self.parametres = parametres or Parametres()
        racine = self.parametres.racine_donnees
        if not racine.exists():
            raise FileNotFoundError(
                f"répertoire de données introuvable : {racine}. "
                "Lancer le simulateur depuis la racine du dépôt, ou renseigner "
                "Parametres(racine_donnees=...)."
            )

    # -- données -------------------------------------------------------------

    @cached_property
    def macro(self) -> DonneesMacro:
        return DonneesMacro(
            self.parametres.racine_donnees,
            scenario_projection=self.parametres.scenario_projection,
        )

    @cached_property
    def mortalite(self) -> DonneesMortalite:
        return DonneesMortalite(self.parametres.racine_donnees)

    @cached_property
    def catalogue(self) -> CatalogueRegimes:
        return CatalogueRegimes(self.parametres.racine_donnees)

    @cached_property
    def affiliations(self) -> Affiliations:
        return Affiliations(self.parametres.racine_donnees)

    # -- moteur --------------------------------------------------------------

    @cached_property
    def indexation(self) -> Indexation:
        return Indexation(self.macro, self.parametres)

    @cached_property
    def convertisseur(self) -> Convertisseur:
        return Convertisseur(self.mortalite, self.parametres)

    @cached_property
    def age_reference(self) -> AgeReference:
        return AgeReference(self.parametres.racine_donnees, self.parametres, self.mortalite)

    @cached_property
    def constructeur(self) -> ConstructeurCompte:
        return ConstructeurCompte(
            self.macro, self.catalogue, self.affiliations,
            self.indexation, self.parametres,
        )

    def _constructeur_variante(self, **modifications) -> ConstructeurCompte:
        """Constructeur identique, sauf sur ce qui alimente le compte.

        Les scénarios 4 et 5 ne diffèrent du scénario 2 que par leur flux de
        cotisations : mêmes données, même indexation, même liquidation. Ils se
        construisent donc en dérivant les paramètres, ce qui garantit qu'aucune
        autre différence ne peut s'y glisser à l'insu du lecteur.
        """
        return ConstructeurCompte(
            self.macro, self.catalogue, self.affiliations,
            self.indexation, self.parametres.avec(**modifications),
        )

    @cached_property
    def constructeur_employeur(self) -> ConstructeurCompte:
        """Le constructeur des scénarios 4 et 5 : un seul, pour les deux.

        Il ne diffère de celui des scénarios 2 et 3 que par un paramètre : la
        part de la cotisation portée au compte.
        """
        return self._constructeur_variante(
            part_cotisation=PartCotisation.TOTALE,
        )

    @cached_property
    def scenario_actuel(self) -> ScenarioActuel:
        return ScenarioActuel(
            self.macro, self.catalogue, self.affiliations, self.parametres
        )

    @cached_property
    def scenario_notionnel(self) -> ScenarioNotionnel:
        return ScenarioNotionnel(
            self.constructeur, self.convertisseur, self.age_reference,
            self.scenario_actuel, self.parametres,
        )

    @cached_property
    def scenario_employeur(self) -> ScenarioNotionnel:
        """Scénarios 4 et 5 : le scénario notionnel, cotisations employeur incluses.

        Le même objet sert aux deux, comme :attr:`scenario_notionnel` sert aux
        scénarios 2 et 3 : c'est le point de départ du compte — origine de la
        répartition ou année de bascule — qui les distingue, pas le calcul.
        """
        return ScenarioNotionnel(
            self.constructeur_employeur, self.convertisseur,
            self.age_reference, self.scenario_actuel, self.parametres,
        )

    @cached_property
    def regime_fusionne(self) -> RegimeFusionne:
        return fusionner(self.catalogue, self.parametres.annee_bascule)

    # -- usage ---------------------------------------------------------------

    def carriere_simple(self, annee_naissance: int, sexe: str, affiliation: str,
                        age_debut: float, age_liquidation: float, **kwargs) -> Carriere:
        """Construit une carrière à partir de cinq informations.

        C'est le chemin le plus court pour qu'un assuré se simule sans rien
        connaître de la mécanique des régimes.
        """
        if affiliation not in self.affiliations:
            raise KeyError(
                f"affiliation inconnue : {affiliation!r}. Disponibles : "
                + ", ".join(self.affiliations.codes)
            )
        return Carriere.depuis_profil(
            annee_naissance=annee_naissance,
            sexe=sexe,
            affiliation=affiliation,
            age_debut=age_debut,
            age_liquidation=age_liquidation,
            macro=self.macro,
            **kwargs,
        )

    def simuler(self, carriere: Carriere) -> Comparaison:
        """Calcule les cinq scénarios pour une carrière."""
        self._verifier_fiabilite(carriere)

        fusionne = self.regime_fusionne if self.parametres.fusion_au_plus_defavorable else None

        actuel = self.scenario_actuel.calculer(carriere)
        retroactif = self.scenario_notionnel.retroactif(carriere, fusionne)
        prospectif = self.scenario_notionnel.prospectif(carriere, self.regime_fusionne)
        retroactif_employeur = self.scenario_employeur.retroactif(
            carriere, fusionne,
            libelle="Comptes notionnels rétroactifs, cotisation salariale et patronale",
        )
        prospectif_employeur = self.scenario_employeur.prospectif(
            carriere, self.regime_fusionne,
            libelle="Comptes notionnels à compter de la bascule, "
                    "cotisation salariale et patronale",
        )

        self.mortalite.enregistrer_cache()

        return Comparaison(
            carriere=carriere,
            actuel=actuel,
            notionnel_retroactif=retroactif,
            notionnel_prospectif=prospectif,
            notionnel_retroactif_employeur=retroactif_employeur,
            notionnel_prospectif_employeur=prospectif_employeur,
            regime_fusionne=self.regime_fusionne,
            parametres=self.parametres,
            coefficient_euros_constants=self.macro.coefficient_prix(
                carriere.annee_liquidation, self.parametres.annee_euros_constants
            ),
        )

    def _verifier_fiabilite(self, carriere: Carriere) -> None:
        exigee = Fiabilite.depuis_texte(self.parametres.fiabilite_minimale)
        if exigee == Fiabilite.ESTIMEE:
            return
        disponible = self.macro.fiabilite_sur(
            carriere.premiere_annee, carriere.annee_liquidation
        )
        if disponible < exigee:
            raise DonneeInsuffisante(
                f"les séries macroéconomiques couvrant "
                f"{carriere.premiere_annee}-{carriere.annee_liquidation} sont de "
                f"fiabilité « {disponible} », inférieure au minimum exigé "
                f"« {exigee} ». Certifier les données ou abaisser "
                "Parametres.fiabilite_minimale."
            )
