"""Cas types — le « cas général », par opposition au cas particulier.

Une simulation individuelle répond à « et moi ? ». Les cas types répondent à
« et globalement ? ». On croise un jeu de carrières représentatives avec un jeu
de générations, et l'on regarde comment la réforme déplace chacune d'elles.

Les carrières retenues suivent l'esprit des cas types du Conseil d'orientation
des retraites : elles ne prétendent pas décrire un individu réel, mais isoler
l'effet des règles à comportement donné. Elles couvrent volontairement les cas
extrêmes du système — le régime spécial à départ précoce et la carrière
interrompue — parce que ce sont eux que la réforme simulée déplace le plus.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .carriere import Carriere
from .simulateur import Comparaison, Simulateur


@dataclass(frozen=True)
class CasType:
    """Une carrière de référence, indépendante de la génération."""

    code: str
    libelle: str
    affiliation: str
    age_debut: float
    age_liquidation: float
    niveau_salaire: float
    profil_carriere: str = "ascendant"
    sexe: str = "H"
    nombre_enfants: int = 0
    part_primes: float = 0.0
    interruptions_relatives: tuple[tuple[int, str], ...] = ()
    commentaire: str = ""

    def construire(self, simulateur: Simulateur, generation: int) -> Carriere:
        interruptions = {
            int(generation + self.age_debut + decalage): motif
            for decalage, motif in self.interruptions_relatives
        }
        return simulateur.carriere_simple(
            annee_naissance=generation,
            sexe=self.sexe,
            affiliation=self.affiliation,
            age_debut=self.age_debut,
            age_liquidation=self.age_liquidation,
            niveau_salaire=self.niveau_salaire,
            profil_carriere=self.profil_carriere,
            interruptions=interruptions,
            nombre_enfants=self.nombre_enfants,
            part_primes=self.part_primes,
            identifiant=f"{self.libelle} (génération {generation})",
        )


#: Jeu de cas types couvrant les principales configurations du système.
CAS_TYPES: tuple[CasType, ...] = (
    CasType(
        code="smic_carriere_complete",
        libelle="Salarié au niveau du SMIC, carrière complète",
        affiliation="salarie_prive_non_cadre",
        age_debut=18, age_liquidation=64, niveau_salaire=0.55,
        profil_carriere="plat",
        commentaire="Carrière longue à bas salaire : le cas où les minima pèsent le plus.",
    ),
    CasType(
        code="salaire_moyen",
        libelle="Salarié au salaire moyen",
        affiliation="salarie_prive_non_cadre",
        age_debut=21, age_liquidation=64, niveau_salaire=1.0,
        commentaire="Référence centrale.",
    ),
    CasType(
        code="cadre",
        libelle="Cadre du privé",
        affiliation="salarie_prive_cadre",
        age_debut=23, age_liquidation=64, niveau_salaire=2.2,
        profil_carriere="fortement_ascendant",
        commentaire="Forte part de rémunération au-dessus du plafond.",
    ),
    CasType(
        code="carriere_interrompue",
        libelle="Carrière interrompue (5 ans hors emploi)",
        affiliation="salarie_prive_non_cadre",
        age_debut=21, age_liquidation=64, niveau_salaire=0.9,
        sexe="F", nombre_enfants=2,
        interruptions_relatives=tuple((decalage, "education_enfant") for decalage in range(8, 13)),
        commentaire=(
            "Cinq années sans cotisation. Le système actuel les couvre par des "
            "trimestres assimilés, par l'AVPF — qui porte au compte un salaire "
            "au SMIC — et par la majoration de durée d'assurance ; le compte "
            "notionnel ne couvre rien. Les deux premiers ne se voient guère ici : "
            "sur une carrière de plus de vingt-cinq années portées au compte, "
            "les années au SMIC n'entrent pas dans les vingt-cinq meilleures, et "
            "les trimestres assimilés ne servent que si la durée requise n'est "
            "pas atteinte. C'est un résultat, pas une omission."
        ),
    ),
    CasType(
        code="fonctionnaire_sedentaire",
        libelle="Fonctionnaire sédentaire (catégorie B)",
        affiliation="fonctionnaire_etat",
        age_debut=22, age_liquidation=64, niveau_salaire=1.2,
        part_primes=0.18,
        commentaire="Traitement indiciaire hors primes ; les primes relèvent du RAFP.",
    ),
    CasType(
        code="fonctionnaire_actif",
        libelle="Fonctionnaire de catégorie active (départ à 57 ans)",
        affiliation="fonctionnaire_territorial_hospitalier",
        age_debut=22, age_liquidation=57, niveau_salaire=1.1,
        part_primes=0.22,
        commentaire="Départ anticipé de dix ans par rapport à l'âge de référence.",
    ),
    CasType(
        code="agent_sncf_conduite",
        libelle="Agent de conduite SNCF (départ à 52 ans)",
        affiliation="agent_sncf",
        age_debut=20, age_liquidation=52, niveau_salaire=1.1,
        commentaire="Écart à l'âge de référence parmi les plus élevés du système.",
    ),
    CasType(
        code="agent_ieg",
        libelle="Agent des industries électriques et gazières",
        affiliation="agent_ieg",
        age_debut=21, age_liquidation=57, niveau_salaire=1.4,
        commentaire="Régime spécial fermé aux embauches depuis 2023.",
    ),
    CasType(
        code="artisan",
        libelle="Artisan",
        affiliation="artisan",
        age_debut=24, age_liquidation=64, niveau_salaire=0.9,
        commentaire="Assiette de cotisation plus faible que celle d'un salarié.",
    ),
    CasType(
        code="exploitant_agricole",
        libelle="Chef d'exploitation agricole",
        affiliation="exploitant_agricole",
        age_debut=20, age_liquidation=64, niveau_salaire=0.5,
        commentaire=(
            "Retraite majoritairement forfaitaire aujourd'hui : la part non "
            "contributive disparaît intégralement dans les scénarios notionnels."
        ),
    ),
    CasType(
        code="profession_liberale",
        libelle="Profession libérale",
        affiliation="profession_liberale",
        age_debut=27, age_liquidation=66, niveau_salaire=2.5,
        profil_carriere="fortement_ascendant",
        commentaire="Régime complémentaire de section non paramétré : résultat incomplet.",
    ),
    CasType(
        code="contractuel_public",
        libelle="Agent contractuel de la fonction publique",
        affiliation="contractuel_public",
        age_debut=24, age_liquidation=64, niveau_salaire=0.85,
        commentaire="Régime général + Ircantec.",
    ),
)

#: Générations couvertes par défaut : de la première génération entièrement
#: couverte par la Sécurité sociale aux actifs entrés récemment.
GENERATIONS = (1940, 1950, 1960, 1970, 1980, 1990, 2000)


@dataclass
class ResultatCasTypes:
    """Grille cas type × génération."""

    resultats: dict[tuple[str, int], Comparaison] = field(default_factory=dict)
    echecs: dict[tuple[str, int], str] = field(default_factory=dict)

    #: Les quatre grilles, dans l'ordre, avec le titre qui les introduit.
    GRILLES = (
        ("notionnel_retroactif",
         "scénario 2, notionnel RÉTROACTIF"),
        ("notionnel_prospectif",
         "scénario 3, notionnel PROSPECTIF (bascule à l'année courante)"),
        ("notionnel_financement_public",
         "scénario 4, FINANCEMENT PUBLIC RÉEL porté au compte"),
        ("notionnel_acquisition_commune",
         "scénario 5, TAUX D'ACQUISITION COMMUN à tous"),
    )

    def tableau(self, cas_types=CAS_TYPES, generations=GENERATIONS) -> str:
        lignes = [
            "Écart de pension par rapport au système actuel, par scénario",
            "(en euros constants ; négatif = pension plus faible qu'aujourd'hui)",
        ]
        for scenario, titre in self.GRILLES:
            lignes += [
                "",
                f"Écart de pension — {titre}",
                "",
                f"{'Cas type':<46} " + " ".join(f"{g:>7}" for g in generations),
                "-" * (46 + 8 * len(generations)),
            ]
            for cas in cas_types:
                cellules = []
                for generation in generations:
                    comparaison = self.resultats.get((cas.code, generation))
                    if comparaison is None:
                        cellules.append(f"{'—':>7}")
                    else:
                        cellules.append(f"{comparaison.variation(scenario):>+7.0%}")
                lignes.append(f"{cas.libelle[:45]:<46} " + " ".join(cellules))

        if self.echecs:
            lignes += ["", "Cas non calculés :"]
            for (code, generation), motif in sorted(self.echecs.items()):
                lignes.append(f"  {code} / {generation} : {motif}")
        return "\n".join(lignes)

    def dictionnaire(self) -> dict:
        return {
            f"{code}|{generation}": comparaison.dictionnaire()
            for (code, generation), comparaison in self.resultats.items()
        }


def calculer_cas_types(
    simulateur: Simulateur,
    cas_types: tuple[CasType, ...] = CAS_TYPES,
    generations: tuple[int, ...] = GENERATIONS,
) -> ResultatCasTypes:
    """Calcule la grille complète cas type × génération.

    Les combinaisons impossibles — un régime qui n'existait pas encore, une
    liquidation avant l'origine de la répartition — sont écartées avec leur
    motif plutôt que de faire échouer l'ensemble.
    """
    resultat = ResultatCasTypes()
    for cas in cas_types:
        for generation in generations:
            cle = (cas.code, generation)
            try:
                carriere = cas.construire(simulateur, generation)
                if carriere.annee_liquidation <= simulateur.parametres.annee_debut_repartition:
                    resultat.echecs[cle] = "liquidation antérieure à la répartition"
                    continue
                regimes_connus = any(
                    simulateur.affiliations.regimes(cas.affiliation, ligne.annee)
                    for ligne in carriere.lignes
                )
                if not regimes_connus:
                    resultat.echecs[cle] = "aucun régime actif sur la période"
                    continue
                resultat.resultats[cle] = simulateur.simuler(carriere)
            except (ValueError, KeyError) as erreur:
                resultat.echecs[cle] = str(erreur)
    return resultat
