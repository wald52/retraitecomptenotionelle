"""Scénarios 2 à 5 — les comptes notionnels.

**Scénario 2, rétroactif.** Le compte notionnel est ouvert à l'entrée dans la
vie active, ou à l'année d'origine de la répartition si la carrière a commencé
avant. Toute la carrière est recalculée : les cotisations réellement versées
alimentent le compte, la revalorisation applique le triple lock inversé année
par année depuis l'origine, et la pension est le solde divisé par le coefficient
de conversion à l'âge effectif de liquidation. Un départ à 55 ans dans un régime
spécial en 1985 est donc traité comme ce qu'il est : douze années de cotisations
en moins et douze années de rente en plus.

**Scénario 3, prospectif.** Les droits acquis jusqu'à l'année de bascule sont
figés selon les règles actuelles, convertis en capital notionnel d'ouverture,
puis le compte fonctionne en notionnel au-delà. C'est la variante qui respecte
les droits acquis — celle qu'une réforme réelle retiendrait.

La conversion des droits acquis pose une question qu'aucune convention ne
tranche seule : à quel capital notionnel correspond une pension annuelle promise
de X euros ? La réponse retenue ici est la seule cohérente avec le reste du
modèle — celle qui inverse la formule de liquidation :

.. math::  K_{\\text{ouverture}} = P_{\\text{acquise}} \\times G(a_c, B)

où :math:`P_{\\text{acquise}}` est la pension de droits figés à l'année de
bascule :math:`B` et :math:`G` le coefficient de conversion à l'âge :math:`a_c`.

Le choix de :math:`a_c` est le seul endroit du modèle où le passage aux comptes
notionnels peut, à lui seul, retirer quelque chose à des droits déjà ouverts. À
l'âge de référence (défaut), un assuré qui liquide avant cet âge voit son
capital d'ouverture minoré du rapport des diviseurs — l'anticipation est payée
une seconde fois, sur le passé. À l'âge effectif de liquidation, la conversion
est neutre. Le paramètre :attr:`Parametres.age_conversion_droits_acquis` permet
de mesurer l'écart entre les deux conventions.

**Scénarios 4 et 5 : ce que le public verse, et ce qu'il acquerrait.** Ils
reprennent exactement le calcul du scénario 2 — même carrière, même indexation,
même liquidation — et ne changent que le flux qui alimente le compte. Ils
existent parce que la question de la part employeur des régimes publics n'a pas
une réponse mais deux, qui ne mesurent pas la même chose.

*Scénario 4, financement historique.* La contribution réellement versée par
l'employeur public s'ajoute à la retenue de l'agent : taux implicite de l'État
de 1995 à 2005, taux appelé par le compte d'affectation spéciale depuis 2006,
taux CNRACL depuis 1948, T1 + T2 de la SNCF de 2007 à 2018. Il répond à :
« qu'aurait donné un compte notionnel si tout ce qui a été consacré aux pensions
avait été porté au compte des actifs ? » Le chiffre est spectaculaire, et c'est
son défaut : un taux d'équilibre de 82 % transforme en droits individuels une
contribution destinée à payer les retraités du moment.

*Scénario 5, taux d'acquisition commun.* Un seul taux pour tout le monde, public
et privé — celui que le privé supporte déjà. Ce qui est prélevé au-delà, surplus
du CAS, taux d'appel des complémentaires, contribution d'équilibre d'un régime
spécial, reste une contribution de transition et n'ouvre aucun droit. C'est la
lecture qu'une réforme retiendrait : peu importe alors que la cotisation soit
dite salariale ou patronale, seule compte la somme des deux.

Entre les deux, le scénario 2 tient une position intermédiaire : il aligne le
public sur l'effort du privé, mais laisse au privé ses taux historiques.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..carriere import Carriere
from ..config import AgeConversionDroitsAcquis, Parametres
from ..donnees.chargement import Fiabilite
from ..moteur.age_reference import AgeReference, EcartAge
from ..moteur.compte import CompteNotionnel, ConstructeurCompte
from ..moteur.conversion import CoefficientConversion, Convertisseur
from ..moteur.fusion import RegimeFusionne
from .actuel import ScenarioActuel


@dataclass(frozen=True)
class DroitsAcquis:
    """Étapes de la conversion des droits figés en capital d'ouverture.

    Conservées telles quelles pour que la page de simulation puisse afficher la
    cascade complète : sans elles, le capital d'ouverture est un nombre qui
    tombe du ciel.
    """

    #: Pension que la carrière tronquée à la bascule ouvre selon les règles
    #: actuelles, avantages non contributifs retirés — en euros de la bascule.
    pension_figee: float
    #: Âge auquel le diviseur de conversion est pris.
    age_conversion: float
    #: Diviseur correspondant, à l'année de bascule.
    diviseur: float
    #: ``pension_figee × diviseur`` — le capital d'ouverture, en euros de la bascule.
    capital_a_la_bascule: float
    #: Revalorisation du capital d'ouverture, de la bascule à la liquidation.
    coefficient_revalorisation: float
    #: Capital d'ouverture revalorisé, en euros de la liquidation.
    capital: float


@dataclass
class ResultatNotionnel:
    """Pension issue d'un compte notionnel, et tout ce qui l'explique."""

    pension_annuelle: float
    capital_notionnel: float
    capital_droits_acquis: float
    compte: CompteNotionnel
    conversion: CoefficientConversion
    ecart_age: EcartAge
    capital_capitalisation: float
    fiabilite: Fiabilite
    libelle: str
    #: Détail de la conversion des droits figés — seulement en prospectif.
    droits_acquis: DroitsAcquis | None = None

    @property
    def pension_mensuelle(self) -> float:
        return self.pension_annuelle / 12.0

    @property
    def rente_capitalisation_annuelle(self) -> float:
        """Rente issue du compartiment de capitalisation, servie à part.

        Le RAFP et les droits des anciennes assurances sociales ne sont pas
        convertis en capital notionnel : ils restent dans un compartiment
        distinct, converti au même coefficient actuariel.
        """
        if self.conversion.diviseur <= 0:
            return 0.0
        return self.capital_capitalisation / self.conversion.diviseur


class ScenarioNotionnel:
    """Produit les deux variantes de comptes notionnels."""

    def __init__(
        self,
        constructeur: ConstructeurCompte,
        convertisseur: Convertisseur,
        age_reference: AgeReference,
        scenario_actuel: ScenarioActuel,
        parametres: Parametres,
    ) -> None:
        self.constructeur = constructeur
        self.convertisseur = convertisseur
        self.age_reference = age_reference
        self.scenario_actuel = scenario_actuel
        self.parametres = parametres

    def _sexe(self, carriere: Carriere) -> str | None:
        from ..config import TableConversion

        if self.parametres.table_conversion is TableConversion.UNISEXE:
            return None
        return carriere.sexe

    # -- scénario 2 ----------------------------------------------------------

    def retroactif(self, carriere: Carriere,
                   regime_fusionne: RegimeFusionne | None = None,
                   libelle: str = "Comptes notionnels rétroactifs") -> ResultatNotionnel:
        """Comptes notionnels appliqués depuis l'origine de la répartition.

        Les scénarios 4 et 5 empruntent ce même chemin : ce qui les distingue du
        scénario 2 tient entièrement à ce qui alimente le compte, donc aux
        paramètres du constructeur, et non au calcul de la pension. Seul le
        libellé change ici.
        """
        annee_liquidation = carriere.annee_liquidation
        age_liquidation = carriere.age_liquidation or 0.0

        compte = self.constructeur.construire(
            carriere,
            annee_liquidation=annee_liquidation,
            annee_debut=carriere.premiere_annee,
            regime_fusionne=regime_fusionne,
        )
        conversion = self.convertisseur.coefficient(
            age_liquidation, annee_liquidation, self._sexe(carriere)
        )
        pension = compte.capital / conversion.diviseur

        return ResultatNotionnel(
            pension_annuelle=pension,
            capital_notionnel=compte.capital,
            capital_droits_acquis=0.0,
            compte=compte,
            conversion=conversion,
            ecart_age=self.age_reference.ecart(age_liquidation, annee_liquidation),
            capital_capitalisation=compte.capital_hors_repartition,
            fiabilite=min(compte.fiabilite, conversion.fiabilite),
            libelle=libelle,
        )

    # -- scénario 3 ----------------------------------------------------------

    def prospectif(self, carriere: Carriere,
                   regime_fusionne: RegimeFusionne) -> ResultatNotionnel:
        """Droits figés à la bascule, comptes notionnels au-delà.

        Pour un assuré dont la retraite est déjà liquidée à la bascule, ce
        scénario ne peut rien changer : ses droits sont intégralement acquis.
        La méthode renvoie alors sa pension actuelle, de sorte que le tableau
        comparatif reste lisible — un retraité de 2005 voit bien « aucun effet »
        sur la ligne 3, et non un chiffre recalculé qui n'aurait aucun sens.
        """
        annee_liquidation = carriere.annee_liquidation
        age_liquidation = carriere.age_liquidation or 0.0
        bascule = self.parametres.annee_bascule

        if annee_liquidation <= bascule:
            return self._deja_liquide(carriere)

        droits_acquis = self._droits_acquis(carriere, bascule)
        capital_acquis = droits_acquis.capital if droits_acquis else 0.0

        compte = self.constructeur.construire(
            carriere,
            annee_liquidation=annee_liquidation,
            annee_debut=bascule,
            regime_fusionne=regime_fusionne,
        )
        conversion = self.convertisseur.coefficient(
            age_liquidation, annee_liquidation, self._sexe(carriere)
        )
        capital_total = compte.capital + capital_acquis
        pension = capital_total / conversion.diviseur

        return ResultatNotionnel(
            pension_annuelle=pension,
            capital_notionnel=capital_total,
            capital_droits_acquis=capital_acquis,
            compte=compte,
            conversion=conversion,
            ecart_age=self.age_reference.ecart(age_liquidation, annee_liquidation),
            capital_capitalisation=compte.capital_hors_repartition,
            fiabilite=min(compte.fiabilite, conversion.fiabilite),
            libelle="Comptes notionnels à compter de la bascule",
            droits_acquis=droits_acquis,
        )

    def _deja_liquide(self, carriere: Carriere) -> ResultatNotionnel:
        """Cas d'un assuré déjà retraité à la bascule : rien ne change."""
        annee_liquidation = carriere.annee_liquidation
        age_liquidation = carriere.age_liquidation or 0.0
        actuel = self.scenario_actuel.calculer(carriere)
        conversion = self.convertisseur.coefficient(
            age_liquidation, annee_liquidation, self._sexe(carriere)
        )
        compte = self.constructeur.construire(
            carriere,
            annee_liquidation=annee_liquidation,
            annee_debut=annee_liquidation,  # aucune cotisation postérieure
        )
        return ResultatNotionnel(
            pension_annuelle=actuel.pension_annuelle,
            capital_notionnel=actuel.pension_annuelle * conversion.diviseur,
            capital_droits_acquis=actuel.pension_annuelle * conversion.diviseur,
            compte=compte,
            conversion=conversion,
            ecart_age=self.age_reference.ecart(age_liquidation, annee_liquidation),
            capital_capitalisation=0.0,
            fiabilite=actuel.fiabilite,
            libelle="Retraite déjà liquidée à la bascule — droits inchangés",
        )

    def _droits_acquis(self, carriere: Carriere, bascule: int) -> DroitsAcquis | None:
        """Convertit les droits figés à la bascule en capital notionnel.

        Les droits sont ceux qu'aurait produits la carrière si elle s'était
        arrêtée à la bascule, calculés selon les règles actuelles mais
        DÉBARRASSÉS des avantages non contributifs — conformément au principe
        « seules les cotisations comptent », qui vaut aussi pour le passé.

        La valorisation se fait à l'année de bascule, sans décote ni surcote :
        on mesure des droits déjà ouverts, pas une liquidation anticipée.

        Reste l'âge auquel prendre le diviseur, et c'est le paramètre
        :attr:`Parametres.age_conversion_droits_acquis` qui tranche :
        l'âge de référence fait payer l'anticipation une seconde fois, sur des
        droits pourtant déjà ouverts ; l'âge effectif de liquidation rend la
        conversion neutre. Dans les deux cas, l'écart de longévité entre la
        bascule et la liquidation subsiste.
        """
        lignes_avant = [l for l in carriere.lignes if l.annee < bascule]
        if not lignes_avant:
            return None

        carriere_tronquee = Carriere(
            annee_naissance=carriere.annee_naissance,
            sexe=carriere.sexe,
            lignes=list(lignes_avant),
            # L'année de liquidation de cette carrière fictive doit être
            # l'année de bascule : c'est en euros de cette année-là que les
            # droits acquis sont valorisés.
            age_liquidation=float(bascule - carriere.annee_naissance),
            nombre_enfants=0,  # avantages familiaux neutralisés
            identifiant=f"{carriere.identifiant} (droits figés {bascule})",
        )
        droits = self.scenario_actuel.calculer(
            carriere_tronquee,
            ignorer_penalite_age=True,
            avantages_non_contributifs=False,
        )

        if self.parametres.age_conversion_droits_acquis is AgeConversionDroitsAcquis.REFERENCE:
            age_conversion = self.age_reference.age(bascule)
        else:
            age_conversion = carriere.age_liquidation or self.age_reference.age(bascule)
        conversion = self.convertisseur.coefficient(
            age_conversion, bascule, self._sexe(carriere)
        )
        capital_a_la_bascule = droits.pension_annuelle * conversion.diviseur

        # Le capital d'ouverture se revalorise ensuite comme tout compte notionnel.
        coefficient = self.constructeur.indexation.coefficient(
            bascule, carriere.annee_liquidation
        )
        return DroitsAcquis(
            pension_figee=droits.pension_annuelle,
            age_conversion=age_conversion,
            diviseur=conversion.diviseur,
            capital_a_la_bascule=capital_a_la_bascule,
            coefficient_revalorisation=coefficient,
            capital=capital_a_la_bascule * coefficient,
        )
