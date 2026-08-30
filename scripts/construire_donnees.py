#!/usr/bin/env python3
"""Fabrique ce que le site charge : ``moteur/donnees.json`` et ``moteur/style.css``.

Le site s'exécute en JavaScript ; les données, elles, restent écrites en YAML et
en CSV dans ``data/``, où elles sont lisibles, commentées et recontrôlées contre
leurs sources. Ce script fait le pont : il charge les données **par les
chargeurs Python du modèle** — donc avec exactement les mêmes conversions,
valeurs par défaut et niveaux de fiabilité — et les écrit en un seul fichier
JSON que le navigateur récupère en une requête.

Faire passer les données par le modèle Python plutôt que de relire les fichiers
à la main est délibéré : la normalisation (champs absents, ``None``, familles de
régimes, niveaux de fiabilité) n'existe qu'à un seul endroit, et le paquet ne
peut pas diverger de ce que calcule la référence.

La feuille de style suit le même chemin : elle est écrite une seule fois, dans
``web/gabarit.py``, et extraite ici vers ``moteur/style.css`` que la page charge
directement. Le serveur Python et le site en JavaScript ne peuvent donc pas
diverger d'apparence.

    python scripts/construire_donnees.py            # reconstruit les deux fichiers
    python scripts/construire_donnees.py --verifier # échoue s'ils sont périmés

Ils sont versionnés dans le dépôt, pour que le site n'ait aucune étape de
construction : ouvrir l'adresse suffit. Il faut donc les reconstruire après toute
modification des données ou du style — le test ``test_le_paquet_est_a_jour`` y
veille.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from retraite_notionnelle.carriere import Affiliations  # noqa: E402
from retraite_notionnelle.donnees.chargement import (  # noqa: E402
    SerieAnnuelle,
    charger_serie_annuelle,
    charger_yaml,
    journal_certification,
)
from retraite_notionnelle.donnees.mortalite import DonneesMortalite  # noqa: E402
from retraite_notionnelle.donnees.regimes import CatalogueRegimes  # noqa: E402
from retraite_notionnelle.scenarios.actuel import (  # noqa: E402
    AgesAnnulationDecote,
    AgesOuverture,
    AnneesSalaireReference,
    CoefficientsMinoration,
    DureesRequises,
    MajorationsPourEnfants,
    Rendements,
    SurcoteParentale,
    ValeursPoint,
)

DONNEES = RACINE / "data"
PAQUET = RACINE / "moteur" / "donnees.json"
STYLE = RACINE / "moteur" / "style.css"

#: Version du format. À incrémenter si la structure du paquet change, pour
#: qu'un site en cache ne lise pas un paquet qu'il ne comprend pas.
VERSION = 5


def _serie(serie: SerieAnnuelle) -> dict:
    """Série annuelle en trois tableaux parallèles — compact et sans ambiguïté."""
    annees = list(serie.annees())
    return {
        "interpolation": serie.interpolation,
        "annees": annees,
        "valeurs": [serie.brut(a).valeur for a in annees],
        "fiabilites": [int(serie.brut(a).fiabilite) for a in annees],
    }


def _series() -> dict:
    macro = DONNEES / "reference" / "macro"
    mortalite = DONNEES / "reference" / "mortalite" / "esperances_vie.csv"
    ages = DONNEES / "reference" / "legislation" / "ages_reference.csv"

    series = {
        "inflation": charger_serie_annuelle(
            macro / "ipc_annuel.csv", "variation", nom="inflation"),
        "salaire_moyen": charger_serie_annuelle(
            macro / "salaire_moyen.csv", "variation_nominale", nom="salaire_moyen_nominal"),
        "productivite": charger_serie_annuelle(
            macro / "productivite.csv", "variation_reelle", nom="productivite_reelle"),
        "pass": charger_serie_annuelle(
            macro / "plafond_securite_sociale.csv", "pass_eur", nom="pass"),
        "smic_horaire": charger_serie_annuelle(
            macro / "smic_horaire.csv", "smic_horaire", nom="smic_horaire"),
        "heures_par_trimestre": charger_serie_annuelle(
            DONNEES / "reference" / "legislation" / "validation_trimestres.csv",
            "heures", nom="heures_par_trimestre"),
    }
    for sexe in ("H", "F"):
        for mesure in ("e60", "e65"):
            series[f"{mesure}_{sexe}"] = charger_serie_annuelle(
                mortalite, "valeur", nom=f"{mesure}_{sexe}", interpolation="lineaire",
                filtre={"sexe": sexe, "mesure": mesure},
            )
    # Les âges légaux n'ont pas de colonne de fiabilité : le modèle les qualifie
    # de « haute ». On passe par le même chargeur que lui pour ne pas diverger.
    from retraite_notionnelle.moteur.age_reference import _charger_ages

    series["age_taux_plein_legal"] = _charger_ages(ages, "age_taux_plein_legal")
    series["age_reference"] = _charger_ages(ages, "age_reference")

    return {nom: _serie(serie) for nom, serie in sorted(series.items())}


def _quotients() -> dict:
    """Quotients de mortalité observés, indexés « année|sexe » puis par âge."""
    donnees = DonneesMortalite(DONNEES, cache_disque=False)
    observes = donnees._quotients_observes or {}
    return {
        f"{annee}|{sexe}": {str(age): qx for age, qx in sorted(table.items())}
        for (annee, sexe), table in sorted(observes.items())
    }


def _calibrations() -> dict:
    """Paramètres de Makeham pour TOUTES les années utiles, pas seulement celles
    déjà rencontrées.

    Le modèle borne l'année aux extrémités de la série d'espérances de vie : le
    domaine est donc fini et connu. En le calibrant intégralement ici, le
    navigateur n'a plus qu'à lire une table — il ne refait aucune bissection, et
    les deux implémentations partent des mêmes paramètres au bit près.
    """
    donnees = DonneesMortalite(DONNEES)
    for sexe in DonneesMortalite.SEXES:
        serie = donnees._e60[sexe]
        for annee in range(serie.premiere_annee, serie.derniere_annee + 1):
            donnees.loi(annee, sexe)
    donnees.enregistrer_cache()
    return {cle: list(valeur) for cle, valeur in sorted(donnees._cache.items())}


def _regimes() -> list[dict]:
    catalogue = CatalogueRegimes(DONNEES)
    fiches = []
    # Ordre de chargement, et non ordre alphabétique : la fusion des régimes
    # départage les ex æquo par le premier rencontré, et c'est ce régime-là que
    # le rapport de simulation cite comme origine du paramètre retenu.
    for regime in catalogue:
        fiches.append({
            "code": regime.code,
            "nom": regime.nom,
            "famille": regime.famille,
            "source_id": regime.source_id,
            "fiabilite": int(regime.fiabilite),
            "creation": regime.creation,
            "fermeture": regime.fermeture,
            "extinction": regime.extinction,
            "succede_a": list(regime.succede_a),
            "integre_dans": regime.integre_dans,
            "population": regime.population,
            "hors_repartition": regime.hors_repartition,
            "periodes": [
                {
                    "debut": p.debut,
                    "fin": p.fin,
                    "type_calcul": p.type_calcul,
                    "age_ouverture": p.age_ouverture,
                    "age_taux_plein": p.age_taux_plein,
                    "duree_requise_trimestres": p.duree_requise_trimestres,
                    "duree_requise_par_generation": p.duree_requise_par_generation,
                    "age_ouverture_par_generation": p.age_ouverture_par_generation,
                    "taux_plein": p.taux_plein,
                    "salaire_reference": p.salaire_reference,
                    "assiette": p.assiette,
                    "taux_cotisation_retraite": p.taux_cotisation_retraite,
                    "perimetre_taux": p.perimetre_taux,
                    "part_salariale": p.part_salariale,
                    "age_taux_plein_par_generation": p.age_taux_plein_par_generation,
                    "decote_par_generation": p.decote_par_generation,
                    "salaire_reference_par_generation": p.salaire_reference_par_generation,
                    "decote_par_trimestre": p.decote_par_trimestre,
                    "bareme_decote": p.bareme_decote,
                    "decote_annulee_par_la_duree": p.decote_annulee_par_la_duree,
                    "decote_trimestres_maximum": p.decote_trimestres_maximum,
                    "surcote_par_trimestre": p.surcote_par_trimestre,
                    "abattement_points": p.abattement_points,
                    "plafond_majoration_enfants": p.plafond_majoration_enfants,
                    "plafond_majoration_annee": p.plafond_majoration_annee,
                    "points_maximum": p.points_maximum,
                    "points_minimum_annuels": p.points_minimum_annuels,
                    "borne_basse_euros": p.borne_basse_euros,
                    "borne_haute_euros": p.borne_haute_euros,
                    "pension_forfaitaire_annuelle": p.pension_forfaitaire_annuelle,
                    "pension_forfaitaire_annee": p.pension_forfaitaire_annee,
                    "assiette_repere_smic": p.assiette_repere_smic,
                    "assiette_plancher": p.assiette_plancher,
                    "avantages_non_contributifs": list(p.avantages_non_contributifs),
                    "notes": p.notes,
                }
                for p in regime.periodes
            ],
        })
    return fiches


def _affiliations() -> dict:
    affiliations = Affiliations(DONNEES)
    return {
        code: {
            "libelle": affiliations.libelle(code),
            "sans_employeur": affiliations.sans_employeur(code),
            "periodes": affiliations._profils[code].get("periodes", []),
        }
        for code in affiliations.codes
    }


def _valeurs_point() -> dict:
    valeurs = ValeursPoint(DONNEES)
    return {
        f"{regime}|{mesure}": {
            str(annee): [valeur, int(fiabilite)]
            for annee, (valeur, fiabilite) in sorted(table.items())
        }
        for (regime, mesure), table in sorted(valeurs._table.items())
    }


def _rendements() -> list:
    rendements = Rendements(DONNEES)
    return [
        [regime, debut, fin, valeur, int(fiabilite)]
        for regime, debut, fin, valeur, fiabilite in rendements._table
    ]





def _contribution_employeur_public() -> dict:
    """Part employeur des régimes publics, indexée « régime|année »."""
    from retraite_notionnelle.donnees.regimes import ContributionsEmployeurPubliques

    table = ContributionsEmployeurPubliques(DONNEES)._table
    return {
        f"{regime}|{annee}": [
            contribution.taux, contribution.nature, int(contribution.fiabilite)
        ]
        for regime, annees in sorted(table.items())
        for annee, contribution in sorted(annees.items())
    }


def _periodes_non_travaillees() -> dict:
    """Ce qu'ouvre chaque motif d'interruption."""
    from retraite_notionnelle.donnees.chargement import charger_periodes_non_travaillees

    return {
        motif: [regle.trimestres_assimiles,
                regle.ouvre_droits_complementaires, int(regle.fiabilite),
                regle.avpf]
        for motif, regle in sorted(charger_periodes_non_travaillees(DONNEES).items())
    }


def _table_par_generation(classe) -> dict:
    """Paramètre législatif indexé sur l'année de naissance."""
    return {str(generation): [valeur, int(fiabilite)]
            for generation, (valeur, fiabilite) in sorted(classe(DONNEES)._table.items())}


def _minimum_contributif() -> dict:
    """Ancres datées du minimum contributif, de sa majoration et du plafond."""
    from retraite_notionnelle.donnees.macro import DonneesMacro
    from retraite_notionnelle.scenarios.actuel import MinimumContributif

    table = MinimumContributif(DONNEES, DonneesMacro(DONNEES))._table
    return {f"{mesure}|{annee}": [valeur, int(fiabilite)]
            for (mesure, annee), (valeur, fiabilite) in sorted(table.items())}


def _decote_fonction_publique() -> dict:
    """Barème de décote de l'article L. 14, par année de liquidation."""
    from retraite_notionnelle.scenarios.actuel import DecoteFonctionPublique

    return {
        str(annee): [trimestres, coefficient, int(fiabilite)]
        for annee, (trimestres, coefficient, fiabilite)
        in sorted(DecoteFonctionPublique(DONNEES)._table.items())
    }


def _minimum_garanti() -> dict:
    """Barème de l'article L. 17, point d'indice et montants servis."""
    from retraite_notionnelle.donnees.macro import DonneesMacro
    from retraite_notionnelle.scenarios.actuel import MinimumGaranti

    minimum = MinimumGaranti(DONNEES, DonneesMacro(DONNEES))
    return {
        "bareme": {
            str(annee): [indice, part, bas, haut, seuil, int(fiabilite)]
            for annee, (indice, part, bas, haut, seuil, fiabilite)
            in sorted(minimum._bareme.items())
        },
        "point_indice": {str(annee): [valeur, int(fiabilite)]
                         for annee, (valeur, fiabilite)
                         in sorted(minimum._point.items())},
        "montants": {str(annee): [valeur, int(fiabilite)]
                     for annee, (valeur, fiabilite)
                     in sorted(minimum._montants.items())},
    }


def _minimum_vieillesse() -> dict:
    """Barème de l'ASPA, personne seule, par année."""
    from retraite_notionnelle.donnees.macro import DonneesMacro
    from retraite_notionnelle.scenarios.actuel import MinimumVieillesse

    table = MinimumVieillesse(DONNEES, DonneesMacro(DONNEES))._table
    return {str(annee): [valeur, int(fiabilite)]
            for annee, (valeur, fiabilite) in sorted(table.items())}


def _majorations_enfants() -> list:
    """Trimestres accordés au titre des enfants, dispositif par dispositif."""
    return [
        [dispositif, reference, debut, fin, trimestres, enfants_minimum,
         beneficiaire, int(fiabilite)]
        for dispositif, reference, debut, fin, trimestres, enfants_minimum,
        beneficiaire, fiabilite in MajorationsPourEnfants(DONNEES)._table
    ]


def _surcote_parentale() -> list:
    """Surcote parentale : âge d'ouverture, taux, plafond, par période."""
    return [
        [debut, fin, age, taux, maximum, int(fiabilite)]
        for debut, fin, age, taux, maximum, fiabilite
        in SurcoteParentale(DONNEES)._table
    ]


def _carriere_longue() -> dict:
    """Portes du départ anticipé pour carrière longue, par année."""
    from retraite_notionnelle.scenarios.actuel import CarriereLongue

    return {
        str(annee): [[age_max, trimestres, age_depart, supplement, int(fiabilite)]
                     for age_max, trimestres, age_depart, supplement, fiabilite
                     in portes]
        for annee, portes in sorted(CarriereLongue(DONNEES)._table.items())
    }


def _hypotheses() -> dict:
    contenu = charger_yaml(DONNEES / "reference" / "macro" / "hypotheses_projection.yaml")
    return {
        "annee_fin_projection": int(contenu.get("annee_fin_projection", 2100)),
        "scenario_par_defaut": contenu.get("scenario_par_defaut"),
        "plafond_suit_salaire_moyen": bool(contenu.get("plafond_suit_salaire_moyen", True)),
        "scenarios": contenu.get("scenarios", {}),
    }


def construire() -> bytes:
    """Paquet complet, à contenu identique pour des données identiques."""
    paquet = {
        "version": VERSION,
        "series": _series(),
        "hypotheses": _hypotheses(),
        "quotients": _quotients(),
        "calibrations": _calibrations(),
        "regimes": _regimes(),
        "affiliations": _affiliations(),
        "valeurs_point": _valeurs_point(),
        "rendements_points": _rendements(),
        "durees_requises": _table_par_generation(DureesRequises),
        "ages_ouverture": _table_par_generation(AgesOuverture),
        "ages_annulation_decote": _table_par_generation(AgesAnnulationDecote),
        "coefficients_minoration": _table_par_generation(CoefficientsMinoration),
        "annees_salaire_reference": _table_par_generation(AnneesSalaireReference),
        "periodes_non_travaillees": _periodes_non_travaillees(),
        "contribution_employeur_public": _contribution_employeur_public(),
        "minimum_contributif": _minimum_contributif(),
        "minimum_garanti": _minimum_garanti(),
        "minimum_vieillesse": _minimum_vieillesse(),
        "decote_fonction_publique": _decote_fonction_publique(),
        "carriere_longue": _carriere_longue(),
        "majorations_enfants": _majorations_enfants(),
        "surcote_parentale": _surcote_parentale(),
        "certification": journal_certification(DONNEES),
    }
    texte = json.dumps(paquet, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"))
    return (texte + "\n").encode("utf-8")


def construire_style() -> bytes:
    """Feuille de style extraite du module Python, seule source du style."""
    from retraite_notionnelle.web import gabarit

    entete = (
        "/* Extrait de src/retraite_notionnelle/web/gabarit.py par\n"
        "   scripts/construire_donnees.py — ne pas modifier ici. */\n"
    )
    return (entete + gabarit.FEUILLE_DE_STYLE.lstrip("\n")).encode("utf-8")


def sorties() -> dict[Path, bytes]:
    return {PAQUET: construire(), STYLE: construire_style()}


def main(argv: list[str] | None = None) -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument(
        "--verifier", action="store_true",
        help="ne rien écrire ; échouer si les fichiers versionnés sont périmés",
    )
    arguments = analyseur.parse_args(argv)

    attendus = sorties()

    if arguments.verifier:
        for chemin, contenu in attendus.items():
            if not chemin.exists():
                print(f"{chemin.relative_to(RACINE)} est absent — lancer "
                      "python scripts/construire_donnees.py", file=sys.stderr)
                return 1
            if chemin.read_bytes() != contenu:
                print(f"{chemin.relative_to(RACINE)} est périmé — lancer "
                      "python scripts/construire_donnees.py", file=sys.stderr)
                return 1
        print("paquet et feuille de style à jour")
        return 0

    for chemin, contenu in attendus.items():
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_bytes(contenu)
        print(f"{chemin.relative_to(RACINE)} : {len(contenu) / 1024:.0f} Ko")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
