"""Contenu des pages : formulaire, résultats, cas types, méthode, données.

Ce module ne dépend que de la bibliothèque standard et du moteur. Il est utilisé
tel quel par le serveur FastAPI (:mod:`.application`), et sert de référence au
portage JavaScript qui fait tourner le site (``moteur/js/pages.js``) : les deux
rendus sont comparés caractère par caractère par ``tests/js/moteur.test.js``.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from html import escape
from urllib.parse import urlencode

from ..calendrier import en_mois, formater_age
from ..castypes import CAS_TYPES, GENERATIONS, calculer_cas_types
from ..config import (
    AgeConversionDroitsAcquis,
    PartCotisation,
    ModeAgeReference,
    ModeIndexation,
    Parametres,
    TableConversion,
)
from ..donnees.chargement import DonneeInsuffisante, journal_certification
from ..simulateur import Comparaison, Simulateur
from . import gabarit as g

PROFILS = [
    ("plat", "Plat — le salaire suit le salaire moyen"),
    ("ascendant", "Ascendant — profil employé/ouvrier"),
    ("fortement_ascendant", "Fortement ascendant — profil cadre"),
]

INDEXATIONS = [
    ("triple_lock_inverse", "Triple lock inversé (règle demandée)"),
    ("triple_lock_inverse_nominal", "Triple lock inversé, tout en nominal"),
    ("prix", "Prix"),
    ("salaires", "Salaire moyen"),
]

AGES_REFERENCE = [
    ("cliquet_legal", "Cliquet légal (défaut)"),
    ("cliquet_puis_esperance_vie", "Cliquet puis espérance de vie"),
    ("legal_sans_cliquet", "Âge légal, sans cliquet"),
]

TABLES = [("unisexe", "Unisexe (défaut)"), ("par_sexe", "Par sexe")]

PARTS_COTISATION = [
    ("salariale", "Part salariale seule (défaut)"),
    ("totale", "Salariale et patronale"),
    ("totale_alignee", "Salariale et patronale, public aligné sur le privé"),
]

CONVERSIONS_ACQUIS = [
    ("reference", "À l'âge de référence (défaut)"),
    ("liquidation", "À l'âge de départ effectif"),
]

PROJECTIONS = [
    ("cor_central", "COR central"),
    ("cor_favorable", "COR favorable"),
    ("cor_defavorable", "COR défavorable"),
    ("stagnation", "Stagnation"),
]


#: Mois de naissance. Le droit coupe deux générations en cours d'année — au
#: 1er juillet 1951, au 1er septembre 1961 — et l'âge à la liquidation ne se
#: lit qu'à partir de lui.
MOIS_NAISSANCE = [
    ("1", "janvier"), ("2", "février"), ("3", "mars"), ("4", "avril"),
    ("5", "mai"), ("6", "juin"), ("7", "juillet"), ("8", "août"),
    ("9", "septembre"), ("10", "octobre"), ("11", "novembre"), ("12", "décembre"),
]

#: Mois qui s'ajoutent aux années entières d'un âge.
MOIS_AGE = [(str(m), "0 mois" if m == 0 else f"{m} mois") for m in range(12)]


class ErreurSaisie(ValueError):
    """Saisie inexploitable, à afficher telle quelle à l'utilisateur."""


@dataclass
class Saisie:
    """Paramètres d'une simulation, tels que l'utilisateur les a saisis."""

    naissance: int = 1975
    naissance_mois: int = 1
    sexe: str = "H"
    statut: str = "salarie_prive_non_cadre"
    debut: float = 21
    liquidation: float = 64
    salaire: float = 1.0
    profil: str = "ascendant"
    primes: float = 0.0
    enfants: int = 0
    interruptions: str = ""
    indexation: str = "triple_lock_inverse"
    age_reference: str = "cliquet_legal"
    table: str = "unisexe"
    conversion_acquis: str = "reference"
    part_cotisation: str = "salariale"
    projection: str = "cor_central"
    bascule: int = 2026
    euros: int = 2026
    #: Vrai si la requête portait des paramètres, donc s'il faut calculer.
    demandee: bool = False

    @classmethod
    def depuis_requete(cls, parametres: dict[str, str]) -> "Saisie":
        defauts = cls()
        saisie = cls(
            naissance=_entier(parametres, "naissance", defauts.naissance),
            naissance_mois=_entier(
                parametres, "naissance_mois", defauts.naissance_mois
            ),
            sexe="F" if parametres.get("sexe") == "F" else "H",
            statut=parametres.get("statut") or defauts.statut,
            debut=_age_saisi(parametres, "debut", defauts.debut),
            liquidation=_age_saisi(parametres, "liquidation", defauts.liquidation),
            salaire=_reel(parametres, "salaire", defauts.salaire),
            profil=_parmi(parametres, "profil", PROFILS, defauts.profil),
            primes=_reel(parametres, "primes", defauts.primes),
            enfants=_entier(parametres, "enfants", defauts.enfants),
            interruptions=(parametres.get("interruptions") or "").strip(),
            indexation=_parmi(parametres, "indexation", INDEXATIONS, defauts.indexation),
            age_reference=_parmi(
                parametres, "age_reference", AGES_REFERENCE, defauts.age_reference
            ),
            table=_parmi(parametres, "table", TABLES, defauts.table),
            conversion_acquis=_parmi(
                parametres, "conversion_acquis", CONVERSIONS_ACQUIS,
                defauts.conversion_acquis,
            ),
            part_cotisation=_parmi(
                parametres, "part_cotisation", PARTS_COTISATION,
                defauts.part_cotisation,
            ),
            projection=_parmi(parametres, "projection", PROJECTIONS, defauts.projection),
            bascule=_entier(parametres, "bascule", defauts.bascule),
            euros=_entier(parametres, "euros", defauts.euros),
            demandee=bool(parametres),
        )
        saisie.verifier()
        return saisie

    def verifier(self) -> None:
        if not 1 <= self.naissance_mois <= 12:
            raise ErreurSaisie("Mois de naissance attendu entre 1 et 12.")
        if not 1900 <= self.naissance <= 2020:
            raise ErreurSaisie(
                f"Année de naissance hors du champ du modèle : {self.naissance}. "
                "Attendu entre 1900 et 2020."
            )
        if not 14 <= self.debut <= 40:
            raise ErreurSaisie("Âge de début d'activité attendu entre 14 et 40 ans.")
        if not 40 <= self.liquidation <= 75:
            raise ErreurSaisie("Âge de liquidation attendu entre 40 et 75 ans.")
        if self.liquidation <= self.debut:
            raise ErreurSaisie(
                "L'âge de liquidation doit être postérieur à l'âge de début d'activité."
            )
        if not 0.1 <= self.salaire <= 10:
            raise ErreurSaisie(
                "Niveau de revenu attendu entre 0,1 et 10 fois le salaire moyen."
            )
        if not 0 <= self.primes <= 0.6:
            raise ErreurSaisie("Part de primes attendue entre 0 et 0,6.")

    @property
    def liquidation_mois(self) -> int:
        """Mois qui s'ajoutent aux années entières de l'âge de départ."""
        return en_mois(self.liquidation) % 12

    @property
    def debut_mois(self) -> int:
        return en_mois(self.debut) % 12

    def parametres(self, base: Parametres) -> Parametres:
        return base.avec(
            mode_indexation=ModeIndexation(self.indexation),
            mode_age_reference=ModeAgeReference(self.age_reference),
            table_conversion=TableConversion(self.table),
            age_conversion_droits_acquis=AgeConversionDroitsAcquis(
                self.conversion_acquis
            ),
            part_cotisation=PartCotisation(
                self.part_cotisation
            ),
            scenario_projection=self.projection,
            annee_bascule=self.bascule,
            annee_euros_constants=self.euros,
        )

    def interruptions_analysees(self) -> dict[int, str]:
        """« 1995:1999:education_enfant, 2003:2004:chomage_indemnise » -> dict."""
        plages: dict[int, str] = {}
        for morceau in self.interruptions.replace("\n", ",").split(","):
            morceau = morceau.strip()
            if not morceau:
                continue
            try:
                debut, fin, motif = morceau.split(":")
                for annee in range(int(debut), int(fin) + 1):
                    plages[annee] = motif.strip()
            except ValueError:
                raise ErreurSaisie(
                    f"Interruption mal formée : « {morceau} ». Attendu "
                    "« année_début:année_fin:motif », par exemple "
                    "1995:1999:education_enfant."
                ) from None
        return plages

    def requete(self, **remplacements) -> str:
        champs = {
            "naissance": self.naissance, "naissance_mois": self.naissance_mois,
            "sexe": self.sexe, "statut": self.statut,
            # L'âge s'écrit en années ENTIÈRES et en mois : « 64 ans et sept
            # mois » plutôt que « 64,583333 ». L'adresse reste lisible, et une
            # ancienne adresse portant un âge décimal reste comprise.
            "debut": en_mois(self.debut) // 12, "debut_mois": self.debut_mois,
            "liquidation": en_mois(self.liquidation) // 12,
            "liquidation_mois": self.liquidation_mois,
            "salaire": _nombre(self.salaire), "profil": self.profil,
            "primes": _nombre(self.primes), "enfants": self.enfants,
            "interruptions": self.interruptions, "indexation": self.indexation,
            "age_reference": self.age_reference, "table": self.table,
            "conversion_acquis": self.conversion_acquis,
            "part_cotisation": self.part_cotisation,
            "projection": self.projection, "bascule": self.bascule, "euros": self.euros,
        }
        champs.update(remplacements)
        return urlencode(champs)


def _entier(parametres: dict[str, str], nom: str, defaut: int) -> int:
    valeur = parametres.get(nom)
    if valeur in (None, ""):
        return defaut
    try:
        return int(float(valeur))
    except ValueError:
        raise ErreurSaisie(f"« {nom} » doit être un nombre entier (reçu : {valeur}).") from None


def _reel(parametres: dict[str, str], nom: str, defaut: float) -> float:
    valeur = parametres.get(nom)
    if valeur in (None, ""):
        return defaut
    try:
        return float(str(valeur).replace(",", "."))
    except ValueError:
        raise ErreurSaisie(f"« {nom} » doit être un nombre (reçu : {valeur}).") from None


def _age_saisi(parametres: dict[str, str], nom: str, defaut: float) -> float:
    """Âge lu en années entières plus un nombre de mois.

    Le formulaire envoie deux champs — ``liquidation`` et ``liquidation_mois``
    —, et l'adresse les porte tous deux : « 64 ans et sept mois » s'y lit tel
    quel. Une adresse ancienne ne portant qu'un âge décimal — ``liquidation=64.5``
    — reste valide et vaut ce qu'elle a toujours valu : le champ des mois est
    alors absent, et la partie décimale fait foi.
    """
    annees = _reel(parametres, nom, defaut)
    cle = f"{nom}_mois"
    if parametres.get(cle) in (None, ""):
        return annees
    mois = _entier(parametres, cle, 0)
    if not 0 <= mois <= 11:
        raise ErreurSaisie(f"« {cle} » doit être compris entre 0 et 11 mois.")
    return math.floor(annees) + mois / 12


def _parmi(parametres: dict[str, str], nom: str,
           options: list[tuple[str, str]], defaut: str) -> str:
    valeur = parametres.get(nom)
    codes = {code for code, _ in options}
    return valeur if valeur in codes else defaut


def _nombre(valeur: float) -> str:
    """Valeur telle qu'elle est réinjectée dans un champ de formulaire."""
    return f"{valeur:g}"


def _age(valeur: float) -> str:
    """Âge à la française, en ans et en mois : « 64 ans », « 64 ans et 9 mois ».

    Le modèle date la liquidation au mois : l'écrire « 64,75 » demanderait au
    lecteur de multiplier par douze pour retrouver ce qu'il a saisi.
    """
    return formater_age(valeur)


# -- fabrique ----------------------------------------------------------------


@dataclass
class Contexte:
    """Simulateurs mémorisés par jeu de paramètres.

    Le chargement des données coûte quelques dixièmes de seconde ; une
    simulation en coûte dix millisecondes. On garde donc une instance par jeu
    de paramètres rencontré.
    """

    base: Parametres = field(default_factory=Parametres)
    _instances: dict[Parametres, Simulateur] = field(default_factory=dict)

    def simulateur(self, parametres: Parametres | None = None) -> Simulateur:
        parametres = parametres or self.base
        if parametres not in self._instances:
            self._instances[parametres] = Simulateur(parametres)
        return self._instances[parametres]

    def simuler(self, saisie: Saisie) -> Comparaison:
        simulateur = self.simulateur(saisie.parametres(self.base))
        if saisie.statut not in simulateur.affiliations:
            raise ErreurSaisie(f"Statut d'affiliation inconnu : « {saisie.statut} ».")
        carriere = simulateur.carriere_simple(
            annee_naissance=saisie.naissance,
            sexe=saisie.sexe,
            affiliation=saisie.statut,
            age_debut=saisie.debut,
            mois_naissance=saisie.naissance_mois,
            age_liquidation=saisie.liquidation,
            niveau_salaire=saisie.salaire,
            profil_carriere=saisie.profil,
            interruptions=saisie.interruptions_analysees(),
            nombre_enfants=saisie.enfants,
            part_primes=saisie.primes,
            identifiant="assuré",
        )
        return simulateur.simuler(carriere)


#: Titre de chaque page, dans l'ordre de la navigation.
TITRES = {
    "/": "Simuler",
    "/cas-types": "Cas types",
    "/methode": "Méthode",
    "/donnees": "Données",
}


def rendre(contexte: Contexte, chemin: str,
           parametres: dict[str, str] | None = None) -> tuple[str, str]:
    """Contenu d'une page : ``(titre, corps HTML)``.

    Point d'entrée unique du rendu. Le serveur l'enveloppe dans un document
    complet, le navigateur en remplace le contenu de ``<main>``. Les erreurs de
    saisie sont rendues dans la page, jamais levées : une adresse mal formée
    doit afficher un message, pas une trace d'exécution.
    """
    if chemin == "/cas-types":
        return TITRES[chemin], _cas_types(contexte)
    if chemin == "/methode":
        return TITRES[chemin], _methode(contexte)
    if chemin == "/donnees":
        return TITRES[chemin], _donnees(contexte)

    try:
        saisie = Saisie.depuis_requete(parametres or {})
    except ErreurSaisie as erreur:
        saisie = Saisie(demandee=False)
        return TITRES["/"], (
            _presentation() + _erreur(str(erreur)) + _formulaire(saisie, contexte)
        )

    corps = _presentation() + _formulaire(saisie, contexte)
    if saisie.demandee:
        try:
            corps += _resultats(contexte, saisie)
        except (ErreurSaisie, DonneeInsuffisante, KeyError, ValueError) as erreur:
            corps += _erreur(str(erreur))
    return TITRES["/"], corps


def statuts(contexte: Contexte) -> list[dict[str, str]]:
    affiliations = contexte.simulateur().affiliations
    return [{"code": code, "libelle": affiliations.libelle(code)}
            for code in affiliations.codes]


# -- fragments ---------------------------------------------------------------


def _erreur(message: str) -> str:
    return f'<div class="erreur"><strong>Saisie refusée.</strong> {escape(message)}</div>'


def _presentation() -> str:
    return f"""
<p class="chapeau">Ce simulateur calcule, pour une même carrière, ce que verse le
système de retraite français tel qu'il est, et ce que verserait un système
en <strong>comptes notionnels</strong> — pension strictement proportionnelle aux
cotisations versées, divisée par l'espérance de vie restante à la liquidation —
appliqué de deux façons : <strong>rétroactivement</strong> depuis 1941, ou
seulement <strong>à compter de 2026</strong>.</p>

<div class="note"><strong>À lire avant les chiffres.</strong> Le scénario
rétroactif n'est pas une proposition de réforme : c'est un contrefactuel, qui
mesure ce qu'aurait produit une règle purement contributive appliquée depuis
l'origine de la répartition. L'essentiel de l'écart qu'il affiche vient de la
<a href="{g.lien('/methode', 'indexation')}">règle d'indexation</a>, pas du passage aux comptes
notionnels — le simulateur permet de séparer les deux effets.</div>
"""


def _formulaire(saisie: Saisie, contexte: Contexte) -> str:
    affiliations = contexte.simulateur().affiliations
    statuts = [(code, affiliations.libelle(code)) for code in affiliations.codes]

    principal = "".join([
        g.champ("naissance", "Année de naissance", saisie.naissance,
                type_="number", min="1900", max="2020", step="1"),
        g.liste("naissance_mois", "Mois de naissance", MOIS_NAISSANCE,
                str(saisie.naissance_mois),
                "deux générations sont coupées en cours d'année par les textes"),
        g.liste("sexe", "Sexe", [("H", "Homme"), ("F", "Femme")], saisie.sexe,
                "table de mortalité unisexe par défaut"),
        g.liste("statut", "Statut d'affiliation", statuts, saisie.statut),
        g.champ("debut", "Âge de début d'activité", en_mois(saisie.debut) // 12,
                type_="number", min="14", max="40", step="1"),
        g.liste("debut_mois", "…et mois", MOIS_AGE, str(saisie.debut_mois),
                "l'année d'entrée n'est complète que si l'on entre en janvier"),
        g.champ("liquidation", "Âge de départ à la retraite",
                en_mois(saisie.liquidation) // 12,
                "effectif si retraité, souhaité si actif",
                type_="number", min="40", max="75", step="1"),
        g.liste("liquidation_mois", "…et mois", MOIS_AGE,
                str(saisie.liquidation_mois),
                "la pension prend effet le premier du mois"),
        g.champ("salaire", "Niveau de revenu", _nombre(saisie.salaire),
                "en multiples du salaire moyen : 0,55 ≈ SMIC, 1 = salaire moyen",
                type_="number", min="0.1", max="10", step="0.05"),
    ])

    avance = "".join([
        g.liste("profil", "Profil de carrière", PROFILS, saisie.profil,
                "déformation du salaire relatif au fil de la carrière"),
        g.champ("primes", "Part de primes", _nombre(saisie.primes),
                "fonction publique : assiette du RAFP", type_="number",
                min="0", max="0.6", step="0.01"),
        g.champ("enfants", "Nombre d'enfants", saisie.enfants,
                "sans effet notionnel : les majorations sont supprimées",
                type_="number", min="0", max="12", step="1"),
        g.champ("interruptions", "Interruptions", saisie.interruptions,
                "« 1995:1999:education_enfant », séparées par des virgules"),
        g.liste("indexation", "Règle d'indexation", INDEXATIONS, saisie.indexation,
                "revalorisation des comptes et des pensions"),
        g.liste("age_reference", "Âge de référence", AGES_REFERENCE, saisie.age_reference),
        g.liste("table", "Table de conversion", TABLES, saisie.table),
        g.liste("part_cotisation", "Part de la cotisation portée au compte",
                PARTS_COTISATION, saisie.part_cotisation,
                "salariale seule, ou salariale et patronale"),
        g.liste("conversion_acquis", "Conversion des droits acquis",
                CONVERSIONS_ACQUIS, saisie.conversion_acquis,
                "âge auquel les droits figés à la bascule sont convertis"),
        g.liste("projection", "Scénario macroéconomique", PROJECTIONS, saisie.projection,
                "au-delà de la dernière observation"),
        g.champ("bascule", "Année de bascule", saisie.bascule,
                "passage au régime unique", type_="number", min="1941", max="2070"),
        g.champ("euros", "Euros constants de", saisie.euros,
                type_="number", min="1941", max="2070"),
    ])

    return f"""
<form class="carte" method="get" action="{g.lien('/')}">
  <h2 style="margin-top:0">Simuler une carrière</h2>
  <div class="grille">{principal}</div>
  <details>
    <summary>Options de modélisation (profil, indexation, âge de référence, projection)</summary>
    <div class="grille">{avance}</div>
  </details>
  <p style="margin-top:1.4rem"><button type="submit">Calculer les cinq scénarios</button></p>
</form>
"""


def _resultats(contexte: Contexte, saisie: Saisie) -> str:
    comparaison = contexte.simuler(saisie)
    carriere = comparaison.carriere
    retro = comparaison.notionnel_retroactif
    ecart = retro.ecart_age
    conversion = retro.conversion

    constants = {
        "actuel": comparaison.en_euros_constants(comparaison.actuel.pension_annuelle),
        "retroactif": comparaison.en_euros_constants(retro.pension_annuelle),
        "prospectif": comparaison.en_euros_constants(
            comparaison.notionnel_prospectif.pension_annuelle
        ),
        "retroactif-employeur": comparaison.en_euros_constants(
            comparaison.notionnel_retroactif_employeur.pension_annuelle
        ),
        "prospectif-employeur": comparaison.en_euros_constants(
            comparaison.notionnel_prospectif_employeur.pension_annuelle
        ),
    }
    reference = max(constants.values()) or 1.0

    def bloc(cle: str, titre: str, glose: str, variation: float | None,
             taux_remplacement: float) -> str:
        montant = constants[cle]
        variation_html = (
            '<span class="discret">référence</span>' if variation is None
            else f"<strong>{g.pourcentage(variation, signe=True)}</strong>"
        )
        return f"""
<div class="scenario">
  <div class="entete">
    <span class="titre">{escape(titre)}</span>
    <span class="montant">
      <span class="mensuel">{g.euros(montant / 12)}</span>
      <span class="discret">/ mois</span>
      <span class="annuel"> — {g.euros(montant)} par an</span>
    </span>
  </div>
  <div class="barre {cle}"><span style="width:{montant / reference * 100:.1f}%"></span></div>
  <div class="glose">{glose} · taux de remplacement
    {g.pourcentage(taux_remplacement)} · écart au système actuel : {variation_html}</div>
</div>"""

    scenarios = (
        bloc("actuel", "1. Système actuel",
             "droit en vigueur, minima et majorations compris",
             None, comparaison.taux_remplacement_actuel)
        + bloc("retroactif", "2. Comptes notionnels, rétroactifs depuis 1941",
               "toute la carrière recalculée sur la seule part salariale",
               comparaison.variation("notionnel_retroactif"),
               comparaison.taux_remplacement_retroactif)
        + bloc("prospectif", f"3. Comptes notionnels à compter de {saisie.bascule}",
               "droits acquis conservés, règles notionnelles ensuite",
               comparaison.variation("notionnel_prospectif"),
               comparaison.taux_remplacement_prospectif)
        + bloc("retroactif-employeur",
               "4. Comptes notionnels rétroactifs, salariale + patronale",
               "le scénario 2, la part patronale en plus",
               comparaison.variation("notionnel_retroactif_employeur"),
               comparaison.taux_remplacement("notionnel_retroactif_employeur"))
        + bloc("prospectif-employeur",
               f"5. Comptes notionnels à compter de {saisie.bascule}, "
               "salariale + patronale",
               "le scénario 3, la part patronale en plus",
               comparaison.variation("notionnel_prospectif_employeur"),
               comparaison.taux_remplacement("notionnel_prospectif_employeur"))
    )

    anticipation = (
        f"départ {g.nombre(abs(ecart.ecart), 2).rstrip('0').rstrip(',')} ans "
        + ("plus tôt" if ecart.anticipe else "plus tard")
    )
    fiches = "".join([
        g.fiche("années cotisées", str(len(carriere.annees_cotisees))),
        # La date, et pas seulement l'année : la pension prend effet le premier
        # du mois, et c'est ce mois que l'utilisateur vient de choisir.
        g.fiche("liquidation", f"{_age(carriere.age_liquidation)} "
                f'<span class="discret">en {carriere.date_liquidation}</span>'),
        g.fiche(f"âge de référence — {anticipation}",
                f"{_age(ecart.age_reference)}"),
        g.fiche("coefficient de conversion", g.nombre(conversion.diviseur, 1)),
        g.fiche("capital notionnel rétroactif", g.euros(retro.capital_notionnel)),
    ])

    capitalisation = ""
    if comparaison.actuel.pension_hors_repartition > 0:
        montant = comparaison.en_euros_constants(
            comparaison.actuel.pension_hors_repartition
        )
        capitalisation = (
            f'<p class="discret">Hors répartition, servi à part : '
            f"{g.euros(montant / 12)} par mois de RAFP. Ce régime est "
            "PROVISIONNÉ — sa rente sort d'un placement, non de la cotisation "
            "des actifs —, si bien qu'une réforme de la répartition ne "
            "l'atteint pas. Il est donc retiré des cinq totaux et servi à "
            "l'identique dans les cinq scénarios : c'est la seule façon de "
            "comparer ce qui est comparable.</p>"
        )

    minimum = ""
    if comparaison.actuel.minimum_applique:
        minimum = (
            '<p class="discret">Le minimum contributif s\'applique dans le '
            "scénario 1 ; il est supprimé dans les scénarios 2 à 5.</p>"
        )

    ouverture = ""
    if not comparaison.actuel.liquidation_ouverte:
        age = comparaison.actuel.age_ouverture_opposable
        attente = (f" — il faut attendre {g.nombre(age, 2)} ans"
                   if age is not None else "")
        ouverture = (
            '<p class="note avertissement">Le droit en vigueur <strong>n\'ouvre pas'
            "</strong> cette liquidation à "
            f"{g.nombre(comparaison.carriere.age_liquidation, 2)} ans{attente}. "
            "Ni l'âge légal du régime, ni le départ anticipé pour carrière "
            "longue ne le permettent. Le montant du scénario 1 reste calculé, "
            "parce qu'il faut bien comparer les cinq scénarios sur la même "
            "carrière, mais il ne décrit aucune pension que le système actuel "
            "servirait.</p>"
        )

    return f"""
<h2>Résultats</h2>
<div class="carte">
  <div class="fiches">{fiches}</div>
</div>
<div class="carte">
  {scenarios}
  <p class="discret" style="margin-top:1.5rem">Montants bruts mensuels, en euros
  constants de {saisie.euros} — seule unité qui permette de comparer des
  liquidations d'années différentes. Fiabilité du résultat :
  <span class="etiquette-fiabilite">{escape(str(comparaison.fiabilite))}</span></p>
  {capitalisation}
  {minimum}
  {ouverture}
</div>
{_decomposition(contexte, saisie, comparaison)}
{_contribution_employeur(comparaison)}
{_cascade(comparaison, saisie)}
{_detail(contexte, comparaison, saisie)}
"""


NATURES_PART_EMPLOYEUR = {
    "appelee": "contribution appelée par décret ou par arrêté",
    "implicite": "taux implicite reconstitué par les documents budgétaires",
    "repli": "aucune série publiée : effort du privé de la même année",
}


def _contribution_employeur(comparaison: Comparaison) -> str:
    """Qui verse la cotisation : l'assuré, son employeur, dans quelle proportion.

    C'est la mesure directe de ce qui sépare les scénarios 2 et 3 des scénarios
    4 et 5. Le bloc ne s'affiche pas pour un non-salarié, qui n'a pas
    d'employeur et pour qui les quatre scénarios se réduisent à deux.
    """
    employeur = comparaison.contribution_employeur
    if not (employeur.a_un_employeur or employeur.concerne_un_regime_public):
        return ""

    partage = ""
    if employeur.a_un_employeur:
        partage = g.tableau(
            ["Sur toute la carrière, en euros courants cumulés", "", "Montant"],
            [
                ["Part salariale", "ce que l'assuré supporte — scénarios 2 et 3",
                 g.euros(employeur.agent)],
                ["Part patronale", "ce que verse l'employeur",
                 g.euros(employeur.employeur)],
                ["Total", "scénarios 4 et 5", g.euros(employeur.total)],
            ],
            ["", "", "nombre"],
        ) + (
            f"<p>L'employeur verse ici <strong>"
            f"{g.pourcentage(employeur.part)}</strong> du total.</p>"
        )

    # La part patronale d'un agent public n'est dans aucune fiche : elle vient
    # d'une série à part, qui ne couvre pas tous les régimes ni toutes les
    # années. Le dire est le prix de s'en servir.
    public = ""
    if employeur.concerne_un_regime_public:
        origines = "".join(
            f"<li>{escape(NATURES_PART_EMPLOYEUR.get(origine, origine))} — "
            f"{nombre} année{'s' if nombre > 1 else ''}</li>"
            for origine, nombre in sorted(employeur.annees_par_origine.items())
        )
        public = f"""
<p>Les fiches de la fonction publique et des régimes spéciaux ne portent que la
<strong>retenue de l'agent</strong>. La part de l'employeur vient d'une série à
part — reconstituée par les documents budgétaires de 1995 à 2005, appelée par
décret depuis 2006 pour l'État, versée à une caisse depuis 1948 pour la fonction
publique territoriale et hospitalière. Origine, année par année :</p>
<ul class="serree">{origines}</ul>
<p class="discret">Et c'est la limite de ces deux scénarios pour un agent
public. Un taux de 82,28 % ne signifie pas qu'un fonctionnaire acquiert 82 % de
son traitement en droits nouveaux : il est fixé pour que le compte
d'affectation spéciale « Pensions » soit à l'équilibre, donc pour payer les
pensions d'aujourd'hui. Le porter au compte répond à une question précise —
« et si tout ce qui a été consacré aux pensions avait été porté au compte des
actifs ? » — et à elle seule.</p>"""

    return f"""
<h2>Qui verse la cotisation</h2>
<p>Une cotisation retraite a deux parts : ce que l'assuré supporte, et ce que
son employeur verse. Les scénarios 2 et 3 ne portent au compte que la première ;
les scénarios 4 et 5 y ajoutent la seconde, et ne changent rien d'autre.</p>
{partage}{public}"""


def _decomposition(contexte: Contexte, saisie: Saisie,
                   comparaison: Comparaison) -> str:
    """Sépare l'effet de la règle d'indexation de celui des comptes notionnels."""
    if saisie.indexation != "triple_lock_inverse":
        return ""

    lignes = []
    for code, libelle in INDEXATIONS:
        try:
            variante = (comparaison if code == saisie.indexation
                        else contexte.simuler(Saisie(**{**saisie.__dict__,
                                                        "indexation": code})))
        except (ErreurSaisie, DonneeInsuffisante, KeyError, ValueError):
            continue
        mensuel = variante.en_euros_constants(
            variante.notionnel_retroactif.pension_annuelle
        ) / 12
        lignes.append([
            escape(libelle),
            "×" + g.nombre(variante.notionnel_retroactif.compte.rendement_cumule, 2),
            g.euros(mensuel),
            g.pourcentage(variante.variation("notionnel_retroactif"), signe=True),
        ])

    return f"""
<h2>D'où vient l'écart</h2>
<p>La même carrière, le même calcul notionnel rétroactif, avec quatre règles de
revalorisation des comptes. La colonne « rendement » est le facteur par lequel les
cotisations ont été multipliées entre leur versement et la liquidation.</p>
{g.tableau(
    ["Règle d'indexation", "Rendement cumulé", "Pension mensuelle", "Écart au système actuel"],
    lignes,
    ["", "nombre", "nombre", "nombre"],
)}
<p class="discret">Le triple lock inversé compare deux taux nominaux (inflation,
salaire moyen) à un taux réel (productivité) : dès que l'inflation dépasse la
productivité — soit presque toute la période 1945-1985 — c'est la productivité
qui l'emporte, et la valeur réelle des comptes s'effondre. L'écart entre la
première ligne et la ligne « Prix » mesure l'effet de la règle d'indexation ;
l'écart entre la ligne « Prix » et le système actuel mesure l'effet propre des
comptes notionnels.</p>
"""


def _cascade(comparaison: Comparaison, saisie: Saisie) -> str:
    """Détaille le passage du scénario 1 au scénario 3, étape par étape.

    C'est la partie du modèle la moins intuitive : le scénario 3 n'est pas le
    scénario 1 diminué d'un pourcentage, c'est une autre formule appliquée à la
    même carrière. Tant qu'on ne voit pas la chaîne de calcul, l'écart affiché
    reste un chiffre à croire.
    """
    prospectif = comparaison.notionnel_prospectif
    acquis = prospectif.droits_acquis
    if acquis is None or prospectif.capital_notionnel <= 0:
        # Rien n'a été cotisé : une cascade de zéros n'explique rien, et le
        # reste de la page dit déjà que le compte est vide.
        return ""

    liquidation = comparaison.carriere.annee_liquidation
    age_liquidation = comparaison.carriere.age_liquidation or 0.0
    diviseur = prospectif.conversion.diviseur
    capital_apres = prospectif.capital_notionnel - acquis.capital
    actuel = comparaison.actuel.pension_annuelle

    lignes = [
        [f"a) Droits acquis à {saisie.bascule}",
         "carrière arrêtée à la bascule, règles actuelles, avantages non "
         "contributifs retirés, sans décote",
         g.euros(acquis.pension_figee) + " par an"],
        [f"b) × diviseur à {_age(acquis.age_conversion)}",
         f"coefficient de conversion en {saisie.bascule} : "
         f"{g.nombre(acquis.diviseur, 2)}",
         g.euros(acquis.capital_a_la_bascule)],
        [f"c) × revalorisation {saisie.bascule}-{liquidation}",
         f"règle d'indexation retenue : ×"
         f"{g.nombre(acquis.coefficient_revalorisation, 3)}",
         g.euros(acquis.capital)],
        [f"d) + cotisations {saisie.bascule}-{liquidation - 1}",
         "versées au régime unique, revalorisées de même",
         g.euros(capital_apres)],
        ["e) = capital notionnel", "ce que la carrière a effectivement financé",
         g.euros(prospectif.capital_notionnel)],
        [f"f) ÷ diviseur à {_age(age_liquidation)}",
         f"coefficient de conversion en {liquidation} : {g.nombre(diviseur, 2)}",
         g.euros(prospectif.pension_annuelle) + " par an"],
    ]

    part_acquis = acquis.capital / prospectif.capital_notionnel
    neutralite = ""
    if saisie.conversion_acquis == "reference" and acquis.age_conversion > age_liquidation:
        neutralite = (
            f"<p>Ligne b) : les droits déjà ouverts sont convertis au diviseur de "
            f"l'âge de référence ({_age(acquis.age_conversion)}), alors que la "
            f"rente sera servie depuis {_age(age_liquidation)}. L'anticipation "
            f"est donc payée une seconde fois, sur le passé. L'option « conversion "
            f"des droits acquis à l'âge de départ effectif » supprime cet "
            f"abattement, et c'est la convention qu'une réforme réelle "
            f"retiendrait.</p>"
        )

    return f"""
<h2>Du scénario 1 au scénario 3, ligne à ligne</h2>
<p>Le scénario 3 n'est pas le scénario 1 diminué d'un pourcentage : c'est une
autre formule appliquée à la même carrière. Montants en euros courants de
l'année de liquidation — la chaîne de calcul est arithmétique, la convertir en
euros constants ligne à ligne la rendrait fausse.</p>
{g.tableau(
    ["Étape", "Ce qu'elle fait", "Résultat"],
    lignes,
    ["", "", "nombre"],
)}
<p>À comparer aux {g.euros(actuel)} par an du système actuel. L'écart ne vient
d'aucun abattement appliqué au scénario 1 : il vient de ce que le capital
réellement constitué, {g.euros(prospectif.capital_notionnel)}, ne finance pas
les {g.euros(actuel * diviseur)} que le droit en vigueur promet sur
{g.nombre(diviseur, 1)} années de retraite.</p>
{neutralite}
<p class="discret">Les droits acquis avant {saisie.bascule} pèsent
{g.pourcentage(part_acquis)} du capital final. Cette part décroît de génération
en génération : c'est elle qui étale la réforme dans le temps, et non un
dispositif transitoire.</p>
"""


def _detail(contexte: Contexte, comparaison: Comparaison, saisie: Saisie) -> str:
    retro = comparaison.notionnel_retroactif
    catalogue = contexte.simulateur().catalogue
    pensions = comparaison.actuel.pensions_par_regime

    def nom_regime(code: str) -> str:
        try:
            return catalogue[code].nom
        except KeyError:
            return code

    actuel = comparaison.actuel
    lignes_actuel: list[list[str]] = [
        [escape(nom_regime(pension.regime)), g.euros(pension.montant),
         g.franciser(escape(pension.detail))]
        for pension in pensions
    ]
    if lignes_actuel and actuel.avantages_appliques:
        lignes_actuel.append([
            "<strong>Sous-total contributif</strong>",
            "<strong>" + g.euros(actuel.total_contributif) + "</strong>",
            '<span class="discret">ce que la carrière a ouvert par ses seules '
            "cotisations</span>",
        ])
    for avantage in actuel.avantages_appliques:
        lignes_actuel.append([
            "+ " + escape(avantage.libelle),
            g.euros(avantage.montant),
            f'<span class="discret">{escape(avantage.detail)}</span>',
        ])
    if lignes_actuel:
        lignes_actuel.append([
            "<strong>Pension du système actuel</strong>",
            "<strong>" + g.euros(actuel.pension_annuelle) + "</strong>",
            '<span class="discret">c\'est le montant de la ligne 1 '
            "ci-dessus</span>",
        ])

    regimes = g.tableau(
        ["Régime, puis avantage", "Pension annuelle", "Calcul"],
        lignes_actuel,
        ["", "nombre", ""],
    ) if lignes_actuel else "<p>Aucun droit liquidé dans le système actuel.</p>"

    part = ""
    if actuel.avantages_appliques and actuel.pension_annuelle > 0:
        gratuit = sum(a.montant for a in actuel.avantages_appliques)
        part = (
            f'<p>Les avantages non contributifs pèsent {g.euros(gratuit)} par an, '
            f"soit {g.pourcentage(gratuit / actuel.pension_annuelle)} de la "
            "pension. C'est exactement ce que les deux scénarios notionnels "
            "retirent : ils ne conservent que le sous-total contributif, et le "
            "recalculent sur les cotisations réellement versées.</p>"
        )

    compte = g.tableau(
        ["Poste", "Montant"],
        [
            ["Cotisations effectivement versées, en euros courants",
             g.euros(retro.compte.cotisations_versees)],
            ["Rendement cumulé appliqué à ces cotisations",
             "×" + g.nombre(retro.compte.rendement_cumule, 2)],
            ["Capital notionnel à la liquidation", g.euros(retro.capital_notionnel)],
            ["Divisé par le coefficient de conversion",
             g.nombre(retro.conversion.diviseur, 2)
             + f" ({escape(retro.conversion.table)})"],
            ["Pension annuelle en euros courants", g.euros(retro.pension_annuelle)],
        ],
        ["", "nombre"],
    )

    api = "" if g.dans_le_navigateur() else (
        f'Ces mêmes résultats sur l\'API : '
        f'<a href="/api/simuler?{escape(saisie.requete())}">/api/simuler</a>. '
    )

    return f"""
<h2>Le détail du calcul</h2>
<h3>Scénario 1 — de quoi votre pension actuelle est faite</h3>
<p>Chaque régime d'abord, puis les avantages que le droit en vigueur ajoute
par-dessus. Les lignes s'additionnent exactement : le total est la pension du
scénario 1.</p>
{regimes}
{part}
<h3>Scénario 2 — construction du compte notionnel rétroactif</h3>
{compte}
<details>
  <summary>Les résultats complets en JSON</summary>
  <pre class="json">{escape(json.dumps(comparaison.dictionnaire(), ensure_ascii=False, indent=2))}</pre>
</details>
<p class="discret">{api}L'adresse de cette page contient tous les paramètres :
elle peut être citée ou partagée telle quelle.</p>
"""


def _cas_types(contexte: Contexte) -> str:
    resultat = calculer_cas_types(contexte.simulateur())

    def grille(scenario: str) -> str:
        lignes = []
        for cas in CAS_TYPES:
            cellules: list[str | g.Cellule] = [
                f'<span title="{escape(cas.commentaire)}">{escape(cas.libelle)}</span>'
            ]
            for generation in GENERATIONS:
                comparaison = resultat.resultats.get((cas.code, generation))
                if comparaison is None:
                    cellules.append("—")
                    continue
                variation = comparaison.variation(scenario)
                cellules.append(g.Cellule(
                    g.pourcentage(variation, signe=True, decimales=0),
                    intensite=variation,
                ))
            lignes.append(cellules)
        return g.tableau(
            ["Cas type"] + [str(generation) for generation in GENERATIONS],
            lignes,
            [""] + ["nombre"] * len(GENERATIONS),
        )

    echecs = ""
    if resultat.echecs:
        elements = "".join(
            f"<li>{escape(code)} / {generation} : {escape(motif)}</li>"
            for (code, generation), motif in sorted(resultat.echecs.items())
        )
        echecs = f"<h3>Combinaisons non calculées</h3><ul class='serree'>{elements}</ul>"

    return f"""
<h2 style="margin-top:0">Le cas général</h2>
<p class="chapeau">Douze carrières représentatives × sept générations. Chaque
cellule est l'écart de pension par rapport au système actuel, à carrière
identique : négatif = pension plus faible qu'aujourd'hui.</p>

<h3>Scénario 2 — comptes notionnels rétroactifs depuis 1941</h3>
{grille("notionnel_retroactif")}
<p class="discret">Les générations anciennes sont les plus touchées : leurs
cotisations, versées quand l'inflation dépassait la productivité, ont été
revalorisées à un taux très inférieur à la hausse des prix.</p>

<h3>Scénario 3 — comptes notionnels à compter de la bascule</h3>
{grille("notionnel_prospectif")}
<p class="discret">Les générations déjà retraitées sont inchangées : leurs droits
sont intégralement acquis avant la bascule. Les indépendants et professions
libérales progressent parce que le régime unique relève leur taux de cotisation
et déplafonne leur assiette — un effort contributif accru, pas un avantage
accordé.</p>

<h3>Scénario 4 — le scénario 2, part patronale comprise</h3>
{grille("notionnel_retroactif_employeur")}
<p class="discret">Toutes les lignes bougent, sauf celles des non-salariés —
artisan, exploitant agricole, profession libérale — qui n'ont pas d'employeur et
pour qui ce scénario est le scénario 2. Les lignes publiques bougent le plus :
la contribution de leur employeur est un taux d'équilibre, sans commune mesure
avec la part patronale d'un salarié.</p>

<h3>Scénario 5 — le scénario 3, part patronale comprise</h3>
{grille("notionnel_prospectif_employeur")}
<p class="discret">Même lecture, à compter de la bascule : les droits acquis
restent ceux du scénario 3, et seul le flux postérieur change. À compter de la
bascule il n'y a plus qu'un régime, dont la répartition salarié/employeur est
celle du statut pivot privé : les écarts entre statuts s'y referment.</p>
{echecs}
"""


def _methode(contexte: Contexte) -> str:
    fusionne = contexte.simulateur().regime_fusionne
    nombre_regimes = len(contexte.simulateur().catalogue)
    return f"""
<h2 style="margin-top:0">Ce que le modèle calcule</h2>

<h3>Le compte notionnel</h3>
<p>Un compte notionnel est un compte <em>virtuel</em> : aucun capital n'est
placé, les cotisations de l'année financent les pensions de l'année, comme dans
toute répartition. Ce qui change, c'est le calcul du droit.</p>
<ol>
  <li><strong>Accumulation</strong> — la cotisation retraite effectivement
  versée chaque année est inscrite au compte ;</li>
  <li><strong>Revalorisation</strong> — le solde est revalorisé chaque année au
  taux fixé par la règle collective ;</li>
  <li><strong>Liquidation</strong> — pension annuelle = capital notionnel ÷
  espérance de vie résiduelle à l'âge de départ, lue sur une table de
  génération.</li>
</ol>
<p>Trois conséquences : la pension est strictement proportionnelle aux
cotisations ; partir tôt coûte deux fois (moins de cotisations, rente servie
plus longtemps) ; aucun droit non financé par une cotisation n'existe.</p>

<h3 id="indexation">La règle d'indexation, et pourquoi elle domine tout</h3>
<p>La règle retenue par défaut est le <strong>triple lock inversé</strong> :
<code>min(inflation, croissance du salaire moyen, productivité réelle)</code>,
appliqué aux comptes <em>et</em> aux pensions déjà liquidées. Prise à la lettre,
elle compare deux taux nominaux à un taux réel.</p>
{g.tableau(
    ["Règle appliquée 1941-2025", "Comptes", "Prix", "Pouvoir d'achat conservé"],
    [
        ["Triple lock inversé, littéral", "×4,9", "×318,6", "<strong>1,5 %</strong>"],
        ["Triple lock inversé, tout en nominal", "×243,7", "×318,6", "76,5 %"],
        ["Indexation sur les prix", "×318,6", "×318,6", "100 %"],
    ],
    ["", "nombre", "nombre", "nombre"],
)}
<p>Une cotisation de 1950 ne conserve donc que 1,5 % de sa valeur réelle. C'est
la règle telle qu'énoncée, appliquée sans correctif — et c'est de là que vient
l'essentiel de la baisse affichée par le scénario rétroactif, non du passage aux
comptes notionnels. Le tableau « D'où vient l'écart » de chaque simulation
sépare les deux effets.</p>

<h3>Ce que le scénario 1 applique du droit positif</h3>
<p>L'étalon ne vaut que par ce qu'il reproduit. Il applique la décote et la
surcote, la proratisation par la durée, le salaire de référence de chaque
régime — sur ses seules années, jamais sur toute la carrière —, et cinq
paramètres lus à la GÉNÉRATION et non à l'année de liquidation : durée requise,
âge légal, âge d'annulation de la décote, coefficient de minoration, nombre
d'années retenues au salaire de référence.</p>
<p>Il applique aussi, dans l'ordre où le droit les applique, les avantages non
contributifs que la carrière suffit à déterminer :</p>
<ul>
  <li><strong>l'assurance vieillesse des parents au foyer</strong>, qui porte au
  compte un salaire forfaitaire égal au SMIC — c'est ce qui la distingue d'une
  période assimilée, laquelle valide des trimestres sans jamais ajouter de
  salaire ;</li>
  <li><strong>les trimestres accordés au titre des enfants</strong>, datés : la
  majoration de durée d'assurance du régime général et des régimes alignés naît
  en 1972 à un an par enfant, passe à deux ans en 1975 et va à la mère ; la
  fonction publique et les régimes spéciaux servent leur bonification, un an par
  enfant né avant 2004 et deux trimestres pour les enfants nés depuis. Ils sont
  attribués DANS un régime et non au-dessus d'eux : ils comptent donc aussi dans
  sa proratisation ;</li>
  <li><strong>le minimum contributif</strong>, réservé aux pensions liquidées au
  taux plein, proratisé par la durée d'assurance acquise dans le régime, et sa
  majoration au titre des périodes cotisées proratisée par la seule durée
  cotisée, puis écrêté quand le total des pensions personnelles dépasse le
  plafond de l'article L. 173-2 ;</li>
  <li><strong>le minimum garanti</strong> de la fonction publique, barème en
  escalier sur la durée de services — 57,5 % de la référence à quinze ans, 95 %
  à trente, la totalité à quarante ;</li>
  <li><strong>la surcote parentale</strong>, créée par la loi du 14 avril 2023 :
  1,25 % par trimestre acquis entre 63 ans et l'âge légal, quatre au plus, à qui
  justifie de la durée requise à 63 ans et détient un trimestre de majoration
  pour enfants. C'est la contrepartie du recul de l'âge légal, et elle se cumule
  avec la surcote ordinaire, qui ne compte qu'au-delà de cet âge ;</li>
  <li><strong>la majoration pour trois enfants</strong>, calculée sur le montant
  déjà relevé par les minima, et plafonnée en euros à la complémentaire ;</li>
  <li><strong>le minimum vieillesse</strong>, allocation différentielle servie à
  partir de 65 ans sous le barème d'une personne seule. Ce n'est pas une
  pension : elle apparaît toujours comme une ligne séparée de la cascade.</li>
</ul>
<p>Deux barèmes propres complètent l'ensemble : la décote de la fonction
publique, dont le coefficient et l'âge d'annulation montent en charge de 2006 à
2020 et dont l'âge d'annulation est la limite d'âge du grade et non 67 ans ; et
la garantie minimale de points de l'Agirc, 120 points par an de 1989 à 2018
même quand la tranche B est nulle.</p>
<p>Enfin, le scénario dit si le droit <strong>ouvre</strong> la liquidation
demandée — âge légal du régime, ou départ anticipé pour carrière longue. Quand
il ne l'ouvre pas, le montant reste calculé, parce qu'il faut comparer les cinq
scénarios sur la même carrière, mais la page le signale : il ne décrit alors
aucune pension que le système actuel servirait.</p>

<h3>Ce qui est supprimé dans les scénarios notionnels</h3>
<p>Le principe « seules les cotisations comptent » est appliqué sans exception :
ni minimum contributif, ni minimum garanti, ni ASPA, ni majoration pour enfants,
ni majoration de durée d'assurance, ni AVPF, ni bonifications, ni catégorie
active, ni périodes assimilées, ni réversion, ni décote ni surcote. Le scénario
1 les conserve tous, puisqu'il décrit le droit en vigueur.</p>

<h3>La fusion des régimes</h3>
<p>À compter de l'année de bascule, les {nombre_regimes} régimes du catalogue sont remplacés
par un régime unique dont chaque paramètre est le plus défavorable de
l'ensemble : ouverture à {_age(fusionne.age_ouverture)}, taux plein à
{_age(fusionne.age_taux_plein)}, {fusionne.duree_requise_trimestres} trimestres
requis, cotisation de {g.pourcentage(fusionne.taux_cotisation_retraite, decimales=2)}
sur assiette déplafonnée.</p>

<h3>Périmètre</h3>
<p>Origine 1941 (allocation aux vieux travailleurs salariés), premier dispositif
où les cotisations des actifs financent les prestations des retraités. Les
assurances sociales de 1930, en capitalisation individuelle, et le RAFP sont
isolés dans un compartiment séparé, jamais converti.</p>

<p><a href="{g.DEPOT}/blob/main/docs/methodologie.md">Méthodologie complète</a> ·
<a href="{g.DEPOT}/blob/main/docs/limites.md">Limites connues</a></p>
"""


def _donnees(contexte: Contexte) -> str:
    simulateur = contexte.simulateur()
    macro = simulateur.macro

    periodes = []
    for debut in range(1940, 2030, 10):
        fin = debut + 9
        periodes.append([
            f"{debut}-{fin}",
            escape(str(macro.inflation.fiabilite_minimale_sur(debut, fin))),
            escape(str(macro.salaire_moyen.fiabilite_minimale_sur(debut, fin))),
            escape(str(macro.productivite.fiabilite_minimale_sur(debut, fin))),
            f"<strong>{escape(str(macro.fiabilite_sur(debut, fin)))}</strong>",
        ])

    par_niveau: dict[str, list[str]] = {}
    for regime in simulateur.catalogue:
        par_niveau.setdefault(str(regime.fiabilite), []).append(regime.code)
    regimes = [
        [niveau, str(len(par_niveau[niveau])),
         escape(", ".join(sorted(par_niveau[niveau])))]
        for niveau in ("certifiee", "haute", "moyenne", "estimee")
        if niveau in par_niveau
    ]

    journal = journal_certification(macro.racine)
    certifications = [
        [escape(nom), f"{trace['valeurs']}", escape(trace.get("niveau", "certifiee")),
         escape(trace["source"])]
        for nom, trace in sorted(journal.get("series", {}).items())
    ]
    if certifications:
        bandeau = f"""<div class="note"><strong>Les séries macroéconomiques sont
certifiées de 1950 à 2025</strong>, les tables de mortalité sont celles
réellement observées depuis 1986, et le plafond de la Sécurité sociale remonte à
1931 daté décret par décret — le tout recontrôlé automatiquement contre les
sources, le {escape(journal['certifie_le'])}. Ce qui précède 1950 et les
paramètres propres à chaque régime restent saisis à la main : les
<em>niveaux</em> de pension des carrières les plus anciennes gardent une marge,
les <em>écarts entre scénarios</em>, qui sont l'objet du modèle, sont plus
robustes encore.</div>"""
    else:
        bandeau = """<div class="note avertissement"><strong>Aucune série n'a
encore été recontrôlée contre sa source.</strong> Lancer <code>scripts/fetch/</code>
puis <code>scripts/verifier_donnees.py --appliquer</code>.</div>"""

    return f"""
<h2 style="margin-top:0">Ce que valent les chiffres</h2>
{bandeau}

<h3>Ce qui a été recontrôlé contre la source</h3>
{g.tableau(["Série", "Valeurs", "Niveau", "Source"], certifications,
           ["", "nombre", "", ""])}
<p class="discret">Une valeur n'est « certifiée » que si elle a été confrontée au
fichier téléchargé depuis le <em>producteur</em> de la donnée. Une transcription
tierce, même sourcée et reprise automatiquement, plafonne à « haute ». Hors de
cette liste : les séries d'avant 1950, l'espérance de vie à 65 ans d'avant 1960,
les quotients de mortalité d'avant 1986, les taux de cotisation d'avant 1967, les
montants servis du minimum contributif, du minimum garanti et du minimum
vieillesse — transcrits de leur publication, et préférés à toute projection
parce qu'ils disent ce qui a été payé —, et les âges, durées et coefficients
propres à chaque régime, repris des textes.</p>

<h3>Fiabilité des séries macroéconomiques, par décennie</h3>
{g.tableau(
    ["Période", "Inflation", "Salaire moyen", "Productivité", "Ensemble"],
    periodes,
    ["", "", "", "", ""],
)}
<p class="discret">Une projection ne se fait jamais passer pour une observation :
au-delà de la dernière année observée, la fiabilité retombe à « estimée ».</p>

<h3>Fiabilité des {len(simulateur.catalogue)} régimes</h3>
{g.tableau(["Niveau", "Nombre", "Régimes"], regimes, ["", "nombre", ""])}

<h3>Sources</h3>
<p>Dix-neuf institutions sont recensées dans
<a href="{g.DEPOT}/blob/main/data/sources.yaml">data/sources.yaml</a> : INSEE,
COR, Comité de suivi des retraites, DREES, CNAV, Service des retraites de l'État,
Caisse des dépôts, Direction de la Sécurité sociale, Cour des comptes,
Agirc-Arrco, Union Retraite, CCMSA, CNAVPL, CNBF, DGAFP, Direction du Budget,
ERAFP, Ircantec, caisses des régimes spéciaux, Urssaf.</p>
<p>Chaque valeur porte son niveau de fiabilité — <code>certifiee</code>,
<code>haute</code>, <code>moyenne</code>, <code>estimee</code> — et la fiabilité
d'un résultat est celle de son maillon le plus faible.</p>
<p><a href="{g.DEPOT}/blob/main/docs/limites.md">Limites détaillées</a></p>
"""
