"""Description d'une carrière individuelle.

Objectif : que n'importe qui puisse décrire sa situation, qu'il dispose de son
relevé de carrière année par année ou seulement de grandes lignes. Trois
niveaux d'entrée sont proposés, du plus précis au plus sommaire :

1. :meth:`Carriere.depuis_lignes` — une ligne par année, telle qu'on la lit sur
   un relevé de carrière Info-Retraite ;
2. :meth:`Carriere.depuis_profil` — statut, années de début et de fin, et un
   profil de rémunération exprimé en multiples du salaire moyen ;
3. :func:`carriere_type` — cas types prédéfinis (cf. :mod:`castypes`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from .donnees.chargement import charger_yaml
from .donnees.macro import DonneesMacro

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
    #: Part de primes dans le revenu (fonction publique) : assiette du RAFP.
    part_primes: float = 0.0

    @property
    def cotise(self) -> bool:
        return self.cotisations_versees and self.revenu > 0


@dataclass
class Carriere:
    """Carrière complète d'un assuré."""

    annee_naissance: int
    sexe: str  # "H" ou "F"
    lignes: list[AnneeCarriere] = field(default_factory=list)
    #: Âge de liquidation effectif (réel pour un retraité, souhaité pour un actif).
    age_liquidation: float | None = None
    #: Nombre d'enfants — sans effet dans les scénarios notionnels, utilisé par
    #: le seul scénario « système actuel » (majorations, MDA).
    nombre_enfants: int = 0
    identifiant: str = "assuré"

    def __post_init__(self) -> None:
        if self.sexe not in ("H", "F"):
            raise ValueError(f"sexe attendu 'H' ou 'F', reçu {self.sexe!r}")
        self.lignes.sort(key=lambda ligne: ligne.annee)

    # -- dates ---------------------------------------------------------------

    @property
    def premiere_annee(self) -> int:
        return min(ligne.annee for ligne in self.lignes)

    @property
    def derniere_annee(self) -> int:
        return max(ligne.annee for ligne in self.lignes)

    @property
    def annee_liquidation(self) -> int:
        if self.age_liquidation is None:
            raise ValueError(
                f"{self.identifiant} : âge de liquidation non renseigné"
            )
        return int(round(self.annee_naissance + self.age_liquidation))

    def age_en(self, annee: int) -> float:
        return annee - self.annee_naissance

    @property
    def deja_liquidee(self) -> bool:
        """Vrai si la retraite est déjà liquidée à l'année courante du modèle.

        Déterminé par comparaison avec l'année de liquidation ; le simulateur
        tranche en fonction de son propre paramètre ``annee_courante``.
        """
        return self.age_liquidation is not None

    # -- agrégats ------------------------------------------------------------

    @cached_property
    def annees_cotisees(self) -> tuple[int, ...]:
        return tuple(ligne.annee for ligne in self.lignes if ligne.cotise)

    @cached_property
    def trimestres_actuels(self) -> int:
        """Trimestres validés au sens du droit en vigueur, tous régimes."""
        return sum(ligne.trimestres_valides for ligne in self.lignes)

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
        niveau_salaire: float = 1.0,
        profil_carriere: str = "plat",
        interruptions: dict[int, str] | None = None,
        nombre_enfants: int = 0,
        part_primes: float = 0.0,
        identifiant: str = "assuré",
    ) -> "Carriere":
        """Construit une carrière à partir de quelques paramètres.

        ``niveau_salaire`` s'exprime en multiples du salaire moyen par tête de
        l'année considérée : 1,0 = salaire moyen, 0,6 ≈ niveau du SMIC,
        3,0 = cadre supérieur. Ce choix d'unité évite à l'utilisateur d'avoir à
        convertir des francs de 1975 en euros.

        ``profil_carriere`` décrit la déformation du salaire relatif au cours de
        la vie active :

        * ``plat`` — le salaire suit exactement le salaire moyen ;
        * ``ascendant`` — le salaire relatif croît de 60 % à 130 % du niveau
          cible (profil ouvrier/employé) ;
        * ``fortement_ascendant`` — de 50 % à 190 % (profil cadre).

        ``interruptions`` associe une année à un type de période non cotisée.
        """
        annee_debut = int(round(annee_naissance + age_debut))
        annee_fin = int(round(annee_naissance + age_liquidation)) - 1
        if annee_fin < annee_debut:
            raise ValueError("âge de liquidation antérieur à l'âge de début d'activité")

        interruptions = interruptions or {}
        duree = max(annee_fin - annee_debut, 1)
        salaire_moyen_reference = _indice_salaire_moyen(macro, annee_debut, annee_fin)

        lignes: list[AnneeCarriere] = []
        for annee in range(annee_debut, annee_fin + 1):
            avancement = (annee - annee_debut) / duree
            deformation = _deformation(profil_carriere, avancement)
            revenu = niveau_salaire * deformation * salaire_moyen_reference[annee]

            type_periode = interruptions.get(annee, "emploi")
            cotise = type_periode == "emploi"
            lignes.append(
                AnneeCarriere(
                    annee=annee,
                    revenu=revenu if cotise else 0.0,
                    affiliation=affiliation,
                    type_periode=type_periode,
                    trimestres_valides=4,
                    cotisations_versees=cotise,
                    part_primes=part_primes,
                )
            )

        return cls(
            annee_naissance=annee_naissance,
            sexe=sexe,
            lignes=lignes,
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
