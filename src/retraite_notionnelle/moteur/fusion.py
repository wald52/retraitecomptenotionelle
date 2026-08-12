"""Fusion de tous les régimes sur le cas le plus défavorable.

À compter de l'année de bascule, les régimes disparaissent au profit d'un
régime unique. La consigne est de retenir, paramètre par paramètre, la valeur
la **plus défavorable à l'assuré** parmi celles observées dans l'ensemble des
régimes en vigueur.

Ce que « le plus défavorable » veut dire, paramètre par paramètre :

===========================  ==========================  ===================================
Paramètre                    Sens défavorable            Justification
===========================  ==========================  ===================================
âge d'ouverture              le plus **élevé**           interdit les départs précoces
âge du taux plein            le plus **élevé**           repousse l'annulation de la décote
durée requise                la plus **longue**          exige plus de carrière
salaire de référence         le moins avantageux         carrière entière > 25 ans > 6 mois
avantages non contributifs   aucun                       tous supprimés
assiette                     la plus **large**           tout revenu cotise
===========================  ==========================  ===================================

Le **taux de cotisation** est traité à part, et c'est le seul paramètre du
module qui ne suive pas la règle littérale. Le retenir « au plus défavorable »
n'aurait pas de sens : un taux plus faible réduit les droits, mais réduit tout
autant les prélèvements, et déséquilibrerait le régime sans rien démontrer.
Retenir le taux le plus élevé n'est pas meilleur : le maximum tombe sur le taux
de tranche 2 de l'Agirc-Arrco (21,59 %), qui ne s'applique aujourd'hui qu'à la
part de rémunération supérieure au plafond.

Le régime fusionné retient donc, par défaut, la **somme des taux d'un statut
pivot** — régime général plus Agirc-Arrco pour un salarié du privé — c'est-à-dire
l'effort contributif réellement consenti aujourd'hui pour une retraite complète.
Ce taux est ensuite appliqué à une assiette déplafonnée, ce qui est bien le sens
défavorable de l'assiette. Les autres conventions restent disponibles via
:attr:`RegleFusion.critere_taux`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..donnees.chargement import Fiabilite
from ..donnees.regimes import CatalogueRegimes, PeriodeRegime, Regime

#: Ordre des assiettes de salaire de référence, du plus avantageux pour
#: l'assuré au moins avantageux. La carrière entière est la moins avantageuse :
#: elle intègre les années de début de carrière, les plus faibles.
ORDRE_SALAIRE_REFERENCE = [
    "derniers_6_mois",
    "dernier_salaire",
    "10_meilleures_annees",
    "25_meilleures_annees",
    "carriere_entiere",
    "sans_objet",
]


class CritereTaux(str, Enum):
    #: Somme des taux du statut pivot (base + complémentaire) : l'effort
    #: contributif réel d'un salarié pour une retraite complète.
    SOMME_PIVOT = "somme_pivot"
    LE_PLUS_ELEVE = "le_plus_eleve"
    LE_PLUS_FAIBLE = "le_plus_faible"
    MOYENNE_PONDEREE = "moyenne_ponderee"


@dataclass(frozen=True)
class RegleFusion:
    critere_taux: CritereTaux = CritereTaux.SOMME_PIVOT
    #: Régimes dont les taux sont additionnés en mode ``SOMME_PIVOT``.
    regimes_pivot: tuple[str, ...] = ("regime_general", "agirc_arrco")
    #: Familles exclues de la fusion. La capitalisation reste à part.
    familles_exclues: tuple[str, ...] = ("additionnel_capitalise",)


@dataclass(frozen=True)
class RegimeFusionne:
    """Régime unique issu de la fusion, et traçabilité de chaque paramètre."""

    annee_bascule: int
    age_ouverture: float
    age_taux_plein: float
    duree_requise_trimestres: int
    salaire_reference: str
    assiette: str
    taux_cotisation_retraite: float
    avantages_non_contributifs: tuple[str, ...]
    origines: dict[str, str]
    regimes_fusionnes: tuple[str, ...]
    fiabilite: Fiabilite

    def resume(self) -> str:
        lignes = [
            f"Régime unique à compter de {self.annee_bascule}",
            f"  {len(self.regimes_fusionnes)} régimes fusionnés",
            f"  âge d'ouverture     : {self.age_ouverture:g} ans   (le plus élevé — {self.origines['age_ouverture']})",
            f"  âge du taux plein   : {self.age_taux_plein:g} ans   (le plus élevé — {self.origines['age_taux_plein']})",
            f"  durée requise       : {self.duree_requise_trimestres} trimestres   ({self.origines['duree_requise_trimestres']})",
            f"  salaire de référence: {self.salaire_reference}   ({self.origines['salaire_reference']})",
            f"  assiette            : {self.assiette}",
            f"  taux de cotisation  : {self.taux_cotisation_retraite:.2%}   ({self.origines['taux_cotisation_retraite']})",
            f"  avantages non contributifs : aucun",
        ]
        return "\n".join(lignes)


def fusionner(catalogue: CatalogueRegimes, annee: int,
              regle: RegleFusion | None = None) -> RegimeFusionne:
    """Construit le régime unique applicable à compter de ``annee``."""
    regle = regle or RegleFusion()

    candidats: list[tuple[Regime, PeriodeRegime]] = []
    for regime in catalogue:
        if regime.famille in regle.familles_exclues or regime.hors_repartition:
            continue
        if not regime.vivant(annee):
            continue
        for periode in regime.periodes_actives(annee):
            candidats.append((regime, periode))

    if not candidats:
        raise ValueError(f"aucun régime vivant en {annee} : fusion impossible")

    def extremum(cle, choix):
        retenu = choix(candidats, key=lambda couple: cle(couple[1]))
        return cle(retenu[1]), retenu[0].code

    age_ouverture, origine_ouverture = extremum(lambda p: p.age_ouverture, max)
    age_taux_plein, origine_taux_plein = extremum(lambda p: p.age_taux_plein, max)

    avec_duree = [c for c in candidats if c[1].duree_requise_trimestres is not None]
    if avec_duree:
        retenu = max(avec_duree, key=lambda c: c[1].duree_requise_trimestres)
        duree, origine_duree = retenu[1].duree_requise_trimestres, retenu[0].code
    else:  # pragma: no cover - le catalogue en contient toujours
        duree, origine_duree = 172, "défaut"

    # Salaire de référence le moins avantageux : le plus loin dans l'ordre.
    def rang(periode: PeriodeRegime) -> int:
        try:
            return ORDRE_SALAIRE_REFERENCE.index(periode.salaire_reference)
        except ValueError:
            return len(ORDRE_SALAIRE_REFERENCE)

    # `sans_objet` n'est pas un désavantage, c'est une absence d'information :
    # on ne le retient que si aucun autre régime n'a de salaire de référence.
    exploitables = [c for c in candidats if c[1].salaire_reference != "sans_objet"]
    base_salaire = exploitables or candidats
    retenu = max(base_salaire, key=lambda c: rang(c[1]))
    salaire_reference, origine_salaire = retenu[1].salaire_reference, retenu[0].code

    if regle.critere_taux is CritereTaux.SOMME_PIVOT:
        taux = 0.0
        composantes: list[str] = []
        for code in regle.regimes_pivot:
            if code not in catalogue:
                continue
            actives = catalogue[code].periodes_actives(annee)
            if not actives:
                continue
            # Pour un régime à tranches, on retient la tranche 1 : c'est celle
            # qui s'applique à l'ensemble des rémunérations.
            pivot = min(actives, key=lambda p: p.bornes_assiette_en_pass()[0])
            taux += pivot.taux_cotisation_retraite
            composantes.append(f"{code} {pivot.taux_cotisation_retraite:.2%}")
        if taux <= 0:
            raise ValueError(
                f"aucun régime pivot exploitable en {annee} parmi {regle.regimes_pivot}"
            )
        origine_taux = "somme " + " + ".join(composantes)
    elif regle.critere_taux is CritereTaux.LE_PLUS_ELEVE:
        taux, origine_taux = extremum(lambda p: p.taux_cotisation_retraite, max)
    elif regle.critere_taux is CritereTaux.LE_PLUS_FAIBLE:
        taux, origine_taux = extremum(lambda p: p.taux_cotisation_retraite, min)
    else:
        taux = sum(p.taux_cotisation_retraite for _, p in candidats) / len(candidats)
        origine_taux = "moyenne des régimes"

    fiabilite = min(regime.fiabilite for regime, _ in candidats)

    return RegimeFusionne(
        annee_bascule=annee,
        age_ouverture=age_ouverture,
        age_taux_plein=age_taux_plein,
        duree_requise_trimestres=duree,
        salaire_reference=salaire_reference,
        assiette="deplafonnee",
        taux_cotisation_retraite=taux,
        avantages_non_contributifs=(),
        origines={
            "age_ouverture": origine_ouverture,
            "age_taux_plein": origine_taux_plein,
            "duree_requise_trimestres": origine_duree,
            "salaire_reference": origine_salaire,
            "taux_cotisation_retraite": origine_taux,
        },
        regimes_fusionnes=tuple(sorted({regime.code for regime, _ in candidats})),
        fiabilite=fiabilite,
    )
