"""Description d'une carrière individuelle.

Objectif : que n'importe qui puisse décrire sa situation, qu'il dispose de son
relevé de carrière année par année ou seulement de grandes lignes. Trois
niveaux d'entrée sont proposés, du plus précis au plus sommaire :

1. :meth:`Carriere.depuis_lignes` — une ligne par année, telle qu'on la lit sur
   un relevé de carrière Info-Retraite ;
2. :meth:`Carriere.depuis_parcours` — la suite des métiers exercés, chacun avec
   son statut et son niveau de revenu ;
3. :meth:`Carriere.depuis_profil` — le cas d'un seul métier, exercé de bout en
   bout : c'est :meth:`depuis_parcours` avec un métier unique ;
4. :func:`carriere_type` — cas types prédéfinis (cf. :mod:`castypes`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from .donnees.chargement import charger_periodes_non_travaillees, charger_yaml
from .donnees.macro import DonneesMacro
from .calendrier import (
    MOIS_PAR_AN,
    DateMois,
    en_mois,
    fraction_annee,
    mois_travailles,
    trimestres_civils,
)

#: Périodes non cotisées reconnues par le système actuel. Elles ouvrent des
#: droits gratuits aujourd'hui ; elles n'en ouvrent aucun dans les scénarios
#: notionnels, sauf si des cotisations ont réellement été versées.
PERIODES_NON_COTISEES = {
    "chomage_indemnise",
    "chomage_non_indemnise",
    "maladie",
    "invalidite",
    "maternite",
    "education_enfant",
    "service_militaire",
    "inactivite",
    "etudes",
}


@dataclass(frozen=True)
class AnneeCarriere:
    """Une année de carrière."""

    annee: int
    #: Revenu d'activité brut de l'année, EN EUROS COURANTS DE CETTE ANNÉE-LÀ.
    revenu: float
    #: Statut d'affiliation (clé de ``legislation/affiliations.yaml``).
    affiliation: str
    #: Nature de la période.
    type_periode: str = "emploi"
    #: Quotité travaillée (1.0 = temps plein).
    quotite: float = 1.0
    #: Trimestres validés au sens du système ACTUEL (utilisé par le seul
    #: scénario « système actuel »).
    trimestres_valides: int = 4
    #: Des cotisations retraite ont-elles réellement été versées ?
    #: C'est le seul critère qui compte pour les comptes notionnels.
    cotisations_versees: bool = True
    #: Salaire de référence d'avant l'interruption. Les régimes
    #: complémentaires acquièrent des points sur cette base pendant les
    #: périodes indemnisées, financés par l'UNEDIC ou la Sécurité sociale.
    revenu_reference: float = 0.0
    #: Familles de régimes qui encaissent des cotisations sur
    #: ``revenu_reference`` alors que l'année n'est pas travaillée.
    familles_cotisantes: tuple[str, ...] = ()
    #: Part de primes dans le revenu (fonction publique) : assiette du RAFP.
    part_primes: float = 0.0
    #: Part de l'année civile réellement couverte par la carrière. Vaut un
    #: partout, sauf aux deux bords : l'année d'entrée dans la vie active et
    #: celle de la liquidation sont incomplètes, et ``revenu`` ne porte alors
    #: que ce qui a été perçu pendant ces mois-là. Le plafond de la Sécurité
    #: sociale se proratise sur cette même fraction, comme le veut l'article
    #: R. 242-2 : une demi-année de travail n'ouvre qu'un demi-plafond.
    fraction_annee: float = 1.0
    #: Salaire forfaitaire porté au compte du régime de base au titre de
    #: l'assurance vieillesse des parents au foyer. Ce n'est pas un revenu
    #: d'activité — l'année n'est pas cotisée par l'assuré — mais la CNAF
    #: cotise pour lui sur cette assiette, et le salaire entre dans le salaire
    #: annuel moyen. Une période assimilée, elle, n'y entre jamais.
    revenu_avpf: float = 0.0

    @property
    def cotise(self) -> bool:
        return self.cotisations_versees and self.revenu > 0

    @property
    def revenu_annualise(self) -> float:
        """Revenu ramené à l'année pleine.

        C'est le traitement en vigueur, celui que liquident les régimes servant
        sur le dernier traitement ou les six derniers mois de service — et non
        la somme réellement perçue pendant une année tronquée.
        """
        if self.fraction_annee <= 0:
            return 0.0
        return self.revenu / self.fraction_annee


@dataclass(frozen=True)
class Metier:
    """Un métier de la carrière : un statut, un niveau de revenu, une date.

    On faisait autrefois le même métier toute sa vie, et le modèle n'a longtemps
    su décrire que celui-là. Aujourd'hui la carrière se compose : un salarié
    devient artisan, un contractuel passe fonctionnaire, un indépendant revient
    au salariat. Chaque changement fait basculer l'assuré d'un régime à un autre,
    donc d'un taux de cotisation et d'un barème à un autre — c'est exactement ce
    que les comptes notionnels mesurent.

    Le métier court de ``age_debut`` jusqu'au début du suivant ; le dernier
    jusqu'à la liquidation.
    """

    #: Statut d'affiliation (clé de ``legislation/affiliations.yaml``).
    affiliation: str
    #: Âge auquel ce métier commence, en années décimales.
    age_debut: float
    #: Niveau de revenu, en multiples du salaire moyen par tête de l'année.
    niveau_salaire: float = 1.0


@dataclass
class Carriere:
    """Carrière complète d'un assuré."""

    annee_naissance: int
    sexe: str  # "H" ou "F"
    lignes: list[AnneeCarriere] = field(default_factory=list)
    #: Mois de naissance, 1 à 12. Le droit coupe deux générations en cours
    #: d'année — au 1er juillet 1951 et au 1er septembre 1961 — et l'âge à la
    #: liquidation ne se lit qu'à partir de lui. Janvier par défaut : c'est la
    #: convention qui laisse l'âge entier tomber sur le 1er janvier, et donc
    #: l'année civile coïncider avec l'année de carrière.
    mois_naissance: int = 1
    #: Âge de liquidation effectif (réel pour un retraité, souhaité pour un actif).
    age_liquidation: float | None = None
    #: Nombre d'enfants — sans effet dans les scénarios notionnels, utilisé par
    #: le seul scénario « système actuel » (majorations, MDA).
    nombre_enfants: int = 0
    identifiant: str = "assuré"

    def __post_init__(self) -> None:
        if self.sexe not in ("H", "F"):
            raise ValueError(f"sexe attendu 'H' ou 'F', reçu {self.sexe!r}")
        if not 1 <= self.mois_naissance <= 12:
            raise ValueError(
                f"mois de naissance attendu entre 1 et 12, reçu {self.mois_naissance}"
            )
        self.lignes.sort(key=lambda ligne: ligne.annee)

    # -- dates ---------------------------------------------------------------

    @property
    def premiere_annee(self) -> int:
        return min(ligne.annee for ligne in self.lignes)

    @property
    def derniere_annee(self) -> int:
        return max(ligne.annee for ligne in self.lignes)

    @property
    def date_naissance(self) -> DateMois:
        return DateMois(self.annee_naissance, self.mois_naissance)

    @property
    def generation(self) -> float:
        """Génération, mois compris — la clé des tables par génération.

        Deux textes ne coupent pas au 1er janvier : la loi du 9 novembre 2010
        vise les assurés nés à compter du 1er juillet 1951, celle du 14 avril
        2023 ceux nés à compter du 1er septembre 1961. Une génération s'écrit
        donc en années décimales, et le mois de naissance décide de quel côté
        de la coupure l'assuré tombe.
        """
        return self.annee_naissance + (self.mois_naissance - 1) / 12

    @property
    def date_liquidation(self) -> DateMois:
        """Mois où la pension prend effet.

        L'âge de liquidation est compté en mois depuis la date de naissance :
        né en mars 1962, parti à soixante-quatre ans et six mois, l'assuré
        liquide en septembre 2026. Le modèle arrondissait auparavant
        ``naissance + âge`` à l'année la plus proche, ce qui déplaçait la
        liquidation d'un semestre et, l'arrondi étant au pair, la déplaçait
        différemment selon la parité du millésime.
        """
        if self.age_liquidation is None:
            raise ValueError(
                f"{self.identifiant} : âge de liquidation non renseigné"
            )
        return self.date_naissance.plus_mois(en_mois(self.age_liquidation))

    @property
    def annee_liquidation(self) -> int:
        """Année civile où la pension prend effet."""
        return self.date_liquidation.annee

    @property
    def mois_liquidation(self) -> int:
        return self.date_liquidation.mois

    @property
    def fraction_annee_liquidation(self) -> float:
        """Part de l'année de liquidation qui précède le point de départ."""
        return (self.mois_liquidation - 1) / 12

    # -- agrégats ------------------------------------------------------------

    @cached_property
    def annees_cotisees(self) -> tuple[int, ...]:
        return tuple(ligne.annee for ligne in self.lignes if ligne.cotise)

    @cached_property
    def trimestres_actuels(self) -> int:
        """Trimestres validés au sens du droit en vigueur, tous régimes.

        Bornés à l'année de liquidation INCLUSE : une ligne postérieure décrit
        une activité exercée APRÈS le départ en retraite, et le droit ne la fait
        pas entrer dans la durée d'assurance qui commande la décote. Compter ces
        années annulait la décote d'un assuré qui, précisément, part tôt.

        L'année de la liquidation, elle, en fait partie : les mois travaillés
        avant le point de départ valident les trimestres qu'ils ont cotisés,
        dans la limite des trimestres civils écoulés. Les exclure retirait
        jusqu'à quatre trimestres à qui part en fin d'année, et c'est la décote
        qu'ils commandent.
        """
        return sum(self.trimestres_retenus(ligne) for ligne in self.lignes)

    def part_retenue(self, annee: int) -> float:
        """Part de l'année civile qui compte, une fois le départ pris en compte.

        Une ligne de carrière dit ce qui a été perçu dans l'année ; la date de
        liquidation dit jusqu'où l'année compte. Les deux se rencontrent
        l'année du départ, et c'est la plus courte qui l'emporte : un relevé de
        carrière déclare douze mois de 2022, mais qui liquide au 1er juillet
        n'en a travaillé que six avant son point de départ.

        Vaut zéro après l'année de liquidation — on ne cotise pas après être
        parti —, et zéro aussi l'année du départ quand celui-ci tombe au
        1er janvier.
        """
        ligne = self.ligne(annee)
        if ligne is None:
            return 0.0
        if self.age_liquidation is None:
            return ligne.fraction_annee
        if annee > self.annee_liquidation:
            return 0.0
        if annee < self.annee_liquidation:
            return ligne.fraction_annee
        return min(ligne.fraction_annee, self.fraction_annee_liquidation)

    def trimestres_retenus(self, ligne: AnneeCarriere) -> int:
        """Trimestres qu'une ligne fait entrer dans la durée d'assurance.

        Plafonnés par les trimestres CIVILS écoulés avant le point de départ :
        l'année de la liquidation en vaut quatre pour qui part en janvier de
        l'année suivante, un seul pour qui part en avril, aucun pour qui part
        en février.
        """
        part = self.part_retenue(ligne.annee)
        if part <= 0:
            return 0
        return min(ligne.trimestres_valides, trimestres_civils(round(part * 12)))

    def ligne(self, annee: int) -> AnneeCarriere | None:
        for l in self.lignes:
            if l.annee == annee:
                return l
        return None

    def affiliations_utilisees(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(ligne.affiliation for ligne in self.lignes))

    # -- constructeurs -------------------------------------------------------

    @classmethod
    def depuis_lignes(cls, annee_naissance: int, sexe: str,
                      lignes: list[AnneeCarriere], **kwargs) -> "Carriere":
        return cls(annee_naissance=annee_naissance, sexe=sexe, lignes=list(lignes), **kwargs)

    @classmethod
    def depuis_profil(
        cls,
        annee_naissance: int,
        sexe: str,
        affiliation: str,
        age_debut: float,
        age_liquidation: float,
        macro: DonneesMacro,
        mois_naissance: int = 1,
        niveau_salaire: float = 1.0,
        profil_carriere: str = "plat",
        interruptions: dict[int, str] | None = None,
        nombre_enfants: int = 0,
        part_primes: float = 0.0,
        identifiant: str = "assuré",
    ) -> "Carriere":
        """Carrière d'un seul métier, exercé du premier au dernier jour.

        C'est le cas particulier de :meth:`depuis_parcours` à un métier, et il
        se construit par elle : les deux chemins ne peuvent donc pas diverger.
        """
        return cls.depuis_parcours(
            annee_naissance=annee_naissance,
            sexe=sexe,
            metiers=[Metier(affiliation=affiliation, age_debut=age_debut,
                            niveau_salaire=niveau_salaire)],
            age_liquidation=age_liquidation,
            macro=macro,
            mois_naissance=mois_naissance,
            profil_carriere=profil_carriere,
            interruptions=interruptions,
            nombre_enfants=nombre_enfants,
            part_primes=part_primes,
            identifiant=identifiant,
        )

    @classmethod
    def depuis_parcours(
        cls,
        annee_naissance: int,
        sexe: str,
        metiers: list["Metier"],
        age_liquidation: float,
        macro: DonneesMacro,
        mois_naissance: int = 1,
        profil_carriere: str = "plat",
        interruptions: dict[int, str] | None = None,
        nombre_enfants: int = 0,
        part_primes: float = 0.0,
        identifiant: str = "assuré",
    ) -> "Carriere":
        """Construit une carrière à partir de la suite des métiers exercés.

        Chaque :class:`Metier` porte un statut d'affiliation, l'âge auquel il
        commence et un niveau de revenu ; il court jusqu'au début du suivant, et
        le dernier jusqu'à la liquidation. Une carrière d'un seul métier est le
        cas particulier auquel se réduisait tout le modèle : on faisait autrefois
        le même métier toute sa vie, c'est devenu l'exception.

        ``niveau_salaire`` s'exprime en multiples du salaire moyen par tête de
        l'année considérée : 1,0 = salaire moyen, 0,6 ≈ niveau du SMIC,
        3,0 = cadre supérieur. Ce choix d'unité évite à l'utilisateur d'avoir à
        convertir des francs de 1975 en euros.

        ``profil_carriere`` décrit la déformation du salaire relatif au cours de
        la vie active, et il vaut pour la carrière ENTIÈRE, changements de métier
        compris — c'est une progression de carrière, pas d'emploi :

        * ``plat`` — le salaire suit exactement le salaire moyen ;
        * ``ascendant`` — le salaire relatif croît de 60 % à 130 % du niveau
          cible (profil ouvrier/employé) ;
        * ``fortement_ascendant`` — de 50 % à 190 % (profil cadre).

        Le niveau de revenu propre à chaque métier se superpose à cette
        déformation : changer de métier déplace le niveau, il ne remet pas la
        progression à zéro.

        ``interruptions`` associe une année à un type de période non cotisée.

        Les deux bords sont des années INCOMPLÈTES et sont construites comme
        telles : celui qui entre en septembre ne travaille que quatre mois de
        son année d'entrée, celui qui part en août n'en travaille que sept de
        son année de départ. Le modèle comptait ces deux années pour zéro ou
        pour une, selon un arrondi — d'où une marche de plusieurs pour cent au
        milieu de l'année.
        """
        if not metiers:
            raise ValueError("une carrière compte au moins un métier")

        date_naissance = DateMois(annee_naissance, mois_naissance)
        bornes = [date_naissance.plus_mois(en_mois(metier.age_debut))
                  for metier in metiers]
        debut = bornes[0]
        # La pension prend effet ce mois-là : il n'est plus travaillé, la borne
        # est donc EXCLUE.
        fin = date_naissance.plus_mois(en_mois(age_liquidation))
        if fin.rang <= debut.rang:
            raise ValueError("âge de liquidation antérieur à l'âge de début d'activité")
        # Chaque métier s'arrête où commence le suivant : les périodes se
        # touchent bout à bout et couvrent la carrière exactement une fois. Un
        # métier qui commencerait avant le précédent, ou après la liquidation,
        # laisserait un trou ou un recouvrement — donc des mois comptés deux
        # fois, ou pas du tout.
        for precedente, suivante in zip(bornes, bornes[1:]):
            if suivante.rang <= precedente.rang:
                raise ValueError(
                    "les métiers doivent se suivre : chacun commence après le "
                    "précédent"
                )
        if bornes[-1].rang >= fin.rang:
            raise ValueError("le dernier métier commence après la liquidation")
        periodes = list(zip(metiers, bornes, bornes[1:] + [fin]))

        annee_debut = debut.annee
        annees = [
            annee for annee in range(debut.annee, fin.annee + 1)
            if mois_travailles(annee, debut, fin) > 0
        ]
        annee_fin = annees[-1]

        interruptions = interruptions or {}
        motifs = charger_periodes_non_travaillees(macro.racine)
        # Le profil de rémunération se déforme le long de la carrière, et sa
        # longueur se mesure EN MOIS : la mesurer en années civiles la faisait
        # dépendre de l'existence d'une dernière année incomplète, si bien
        # qu'un départ décalé d'un mois déformait tout le profil et faisait
        # BAISSER la pension d'un travail plus long. Le dénominateur est la
        # dernière année pleine, comme avant : une carrière commençant et
        # finissant au 1er janvier retrouve exactement ses anciennes valeurs.
        duree_mois = max(fin.rang - 12 - debut.rang, 12)
        salaire_moyen_reference = _indice_salaire_moyen(macro, annee_debut, annee_fin)

        lignes: list[AnneeCarriere] = []
        for annee in annees:
            part = fraction_annee(annee, debut, fin)
            trimestres_maximum = trimestres_civils(mois_travailles(annee, debut, fin))
            avancement = (max(DateMois(annee, 1).rang, debut.rang)
                          - debut.rang) / duree_mois
            deformation = _deformation(profil_carriere, avancement)
            # Ce que chaque métier a occupé de l'année. La somme vaut les mois
            # travaillés de l'année : les périodes la découpent sans reste.
            mois_par_metier = [mois_travailles(annee, ouverture, cloture)
                               for _, ouverture, cloture in periodes]
            revenu = sum(
                metier.niveau_salaire * deformation
                * salaire_moyen_reference[annee] * (mois / MOIS_PAR_AN)
                for (metier, _, _), mois in zip(periodes, mois_par_metier)
                if mois > 0
            )
            # Le moteur ne connaît qu'une ligne, donc qu'un statut, par année
            # civile : les régimes liquident à l'année. L'année d'un changement
            # de métier est donc rattachée à celui qui en occupe le plus de
            # mois — et, à égalité, à celui qui l'ouvre. Le revenu, lui, reste
            # la somme de ce que les deux ont réellement payé.
            affiliation = periodes[
                max(range(len(periodes)), key=mois_par_metier.__getitem__)
            ][0].affiliation

            type_periode = interruptions.get(annee, "emploi")
            cotise = type_periode == "emploi"
            regle = None if cotise else motifs.get(
                type_periode, motifs.get("sans_activite")
            )
            lignes.append(
                AnneeCarriere(
                    annee=annee,
                    revenu=revenu if cotise else 0.0,
                    affiliation=affiliation,
                    type_periode=type_periode,
                    # Un trimestre s'acquiert par un montant cotisé — 150 fois
                    # le SMIC horaire depuis 2014, 200 avant. Une année à temps
                    # très partiel en valide donc moins de quatre. Les périodes
                    # assimilées, elles, en valident quatre sans condition de
                    # montant : c'est tout leur objet.
                    # Le montant commande le nombre de trimestres, les mois en
                    # commandent le plafond : on ne valide pas quatre trimestres
                    # en sept mois, si gros que soit le salaire.
                    trimestres_valides=min(
                        trimestres_maximum,
                        macro.trimestres_valides(revenu, annee) if cotise
                        else (regle.trimestres_assimiles if regle else 4),
                    ),
                    cotisations_versees=cotise,
                    # Pendant une période indemnisée, l'UNEDIC ou la Sécurité
                    # sociale versent de vraies cotisations aux régimes
                    # complémentaires, assises sur le salaire d'avant.
                    revenu_reference=(
                        0.0 if cotise or regle is None
                        or not regle.ouvre_droits_complementaires else revenu
                    ),
                    familles_cotisantes=(
                        () if cotise or regle is None
                        or not regle.ouvre_droits_complementaires
                        else ("complementaire_prive",)
                    ),
                    fraction_annee=part,
                    part_primes=part_primes,
                    # Assurance vieillesse des parents au foyer : la CNAF
                    # cotise au régime général sur une assiette forfaitaire
                    # égale au SMIC — 1 820 heures, soit le SMIC mensuel
                    # multiplié par douze.
                    revenu_avpf=(
                        0.0 if cotise or regle is None or not regle.avpf
                        else 1820.0 * macro.smic_horaire(annee) * part
                    ),
                )
            )

        return cls(
            annee_naissance=annee_naissance,
            sexe=sexe,
            lignes=lignes,
            mois_naissance=mois_naissance,
            age_liquidation=age_liquidation,
            nombre_enfants=nombre_enfants,
            identifiant=identifiant,
        )


def _deformation(profil: str, avancement: float) -> float:
    if profil == "plat":
        return 1.0
    if profil == "ascendant":
        return 0.60 + 0.70 * avancement
    if profil == "fortement_ascendant":
        return 0.50 + 1.40 * avancement
    raise ValueError(f"profil de carrière inconnu : {profil!r}")


def _indice_salaire_moyen(macro: DonneesMacro, debut: int, fin: int) -> dict[int, float]:
    """Salaire moyen par tête reconstitué en euros courants de chaque année.

    La série de comptes nationaux ne donne que des TAUX DE CROISSANCE. On les
    cumule à partir d'un point d'ancrage : le salaire moyen par tête du secteur
    privé en 2024, arrondi à 40 000 € bruts annuels. Ce point d'ancrage est un
    paramètre documenté, pas une donnée certifiée — il déplace proportionnellement
    tous les revenus reconstitués, donc toutes les pensions, mais il est sans
    effet sur les RAPPORTS entre scénarios, qui sont l'objet du modèle.
    """
    ancrage_annee, ancrage_valeur = 2024, 40_000.0
    valeurs = {ancrage_annee: ancrage_valeur}

    borne_haute = max(fin, ancrage_annee)
    for annee in range(ancrage_annee + 1, borne_haute + 1):
        valeurs[annee] = valeurs[annee - 1] * (1 + macro.salaire_moyen(annee))

    borne_basse = min(debut, ancrage_annee)
    for annee in range(ancrage_annee - 1, borne_basse - 1, -1):
        valeurs[annee] = valeurs[annee + 1] / (1 + macro.salaire_moyen(annee + 1))

    return valeurs


class Affiliations:
    """Correspondance statut -> régimes, année par année."""

    def __init__(self, racine: Path) -> None:
        contenu = charger_yaml(racine / "reference" / "legislation" / "affiliations.yaml")
        self._profils: dict[str, dict] = contenu.get("affiliations", {})
        if not self._profils:
            raise ValueError("aucun profil d'affiliation chargé")

    def __contains__(self, code: str) -> bool:
        return code in self._profils

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(sorted(self._profils))

    def libelle(self, code: str) -> str:
        return self._profils[code].get("libelle", code)

    def sans_employeur(self, affiliation: str) -> bool:
        """Ce statut cotise-t-il sans employeur ?

        Vrai pour les non-salariés : leur cotisation est intégralement
        personnelle. Le drapeau est porté par le STATUT et non par le régime,
        parce qu'un non-salarié relève souvent d'un régime partagé avec des
        salariés — un artisan cotise au régime général, dont la fiche porte la
        répartition d'un salarié. Le taux y est le bon ; la répartition, non.
        """
        return bool(self._profils.get(affiliation, {}).get("sans_employeur", False))

    def regimes(self, affiliation: str, annee: int) -> tuple[str, ...]:
        """Régimes applicables à ce statut cette année-là."""
        if affiliation not in self._profils:
            raise KeyError(
                f"affiliation inconnue : {affiliation!r}. Disponibles : "
                + ", ".join(self.codes)
            )
        for periode in self._profils[affiliation].get("periodes", []):
            fin = periode.get("fin")
            if periode["debut"] <= annee and (fin is None or annee <= fin):
                return tuple(periode.get("regimes") or ())
        return ()
