"""Interface en ligne de commande.

    retraite-notionnelle simuler --naissance 1960 --statut salarie_prive_non_cadre \\
                                 --debut 20 --liquidation 60
    retraite-notionnelle cas-types
    retraite-notionnelle regimes
    retraite-notionnelle indexation --de 1960 --a 2025
    retraite-notionnelle fusion
    retraite-notionnelle donnees
    retraite-notionnelle web
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .castypes import CAS_TYPES, GENERATIONS, calculer_cas_types
from .config import (
    AgeConversionDroitsAcquis,
    PartCotisation,
    ModeAgeReference,
    ModeIndexation,
    Parametres,
    SourceCotisations,
    TableConversion,
)
from .donnees.chargement import DonneeInsuffisante, journal_certification
from .simulateur import Simulateur


def _parametres(arguments: argparse.Namespace) -> Parametres:
    modifications = {}
    if getattr(arguments, "indexation", None):
        modifications["mode_indexation"] = ModeIndexation(arguments.indexation)
    if getattr(arguments, "age_reference", None):
        modifications["mode_age_reference"] = ModeAgeReference(arguments.age_reference)
    if getattr(arguments, "conversion_acquis", None):
        modifications["age_conversion_droits_acquis"] = AgeConversionDroitsAcquis(
            arguments.conversion_acquis
        )
    if getattr(arguments, "part_cotisation", None):
        modifications["part_cotisation"] = (
            PartCotisation(arguments.part_cotisation)
        )
    if getattr(arguments, "table", None):
        modifications["table_conversion"] = TableConversion(arguments.table)
    if getattr(arguments, "cotisations", None):
        modifications["source_cotisations"] = SourceCotisations(arguments.cotisations)
    if getattr(arguments, "projection", None):
        modifications["scenario_projection"] = arguments.projection
    if getattr(arguments, "bascule", None):
        modifications["annee_bascule"] = arguments.bascule
    if getattr(arguments, "euros", None):
        modifications["annee_euros_constants"] = arguments.euros
    if getattr(arguments, "fiabilite_min", None):
        modifications["fiabilite_minimale"] = arguments.fiabilite_min
    if getattr(arguments, "donnees", None):
        modifications["racine_donnees"] = Path(arguments.donnees)
    return Parametres(**modifications)


# -- commandes ---------------------------------------------------------------


def commande_simuler(arguments: argparse.Namespace) -> int:
    simulateur = Simulateur(_parametres(arguments))
    interruptions = {}
    for plage in arguments.interruption or []:
        try:
            debut, fin, motif = plage.split(":")
            for annee in range(int(debut), int(fin) + 1):
                interruptions[annee] = motif
        except ValueError:
            print(
                f"Interruption mal formée : {plage!r}. Attendu "
                "« annee_debut:annee_fin:motif », par exemple 1995:1999:education_enfant",
                file=sys.stderr,
            )
            return 2

    carriere = simulateur.carriere_simple(
        annee_naissance=arguments.naissance,
        sexe=arguments.sexe,
        affiliation=arguments.statut,
        age_debut=arguments.debut,
        age_liquidation=arguments.liquidation,
        niveau_salaire=arguments.salaire,
        profil_carriere=arguments.profil,
        interruptions=interruptions,
        nombre_enfants=arguments.enfants,
        part_primes=arguments.primes,
        identifiant=arguments.nom or "assuré",
    )
    comparaison = simulateur.simuler(carriere)

    if arguments.json:
        print(json.dumps(comparaison.dictionnaire(), ensure_ascii=False, indent=2))
    else:
        print(comparaison.tableau())
        if arguments.detail:
            print()
            print("Pensions par régime dans le système actuel :")
            for pension in comparaison.actuel.pensions_par_regime:
                print(f"  {pension.regime:<28} {pension.montant:>10,.0f} €   {pension.detail}")
    return 0


def commande_cas_types(arguments: argparse.Namespace) -> int:
    simulateur = Simulateur(_parametres(arguments))
    generations = tuple(arguments.generations) if arguments.generations else GENERATIONS
    cas = CAS_TYPES
    if arguments.cas:
        selection = set(arguments.cas)
        cas = tuple(c for c in CAS_TYPES if c.code in selection)
        if not cas:
            print(
                "Aucun cas type ne correspond. Disponibles : "
                + ", ".join(c.code for c in CAS_TYPES),
                file=sys.stderr,
            )
            return 2
    resultat = calculer_cas_types(simulateur, cas, generations)
    if arguments.json:
        print(json.dumps(resultat.dictionnaire(), ensure_ascii=False, indent=2))
    else:
        print(resultat.tableau(cas, generations))
    return 0


def commande_regimes(arguments: argparse.Namespace) -> int:
    simulateur = Simulateur(_parametres(arguments))
    catalogue = simulateur.catalogue
    print(f"{len(catalogue)} régimes au catalogue\n")
    entete = f"{'code':<26} {'famille':<22} {'créé':>5} {'fermé':>6} {'fiab.':<9} nom"
    print(entete)
    print("-" * len(entete))
    for regime in sorted(catalogue, key=lambda r: (r.famille, r.code)):
        fermeture = str(regime.fermeture) if regime.fermeture else "—"
        print(
            f"{regime.code:<26} {regime.famille:<22} {regime.creation:>5} "
            f"{fermeture:>6} {str(regime.fiabilite):<9} {regime.nom[:44]}"
        )
    print("\nStatuts d'affiliation disponibles pour `simuler --statut` :")
    for code in simulateur.affiliations.codes:
        print(f"  {code:<40} {simulateur.affiliations.libelle(code)}")
    return 0


def commande_indexation(arguments: argparse.Namespace) -> int:
    simulateur = Simulateur(_parametres(arguments))
    indexation = simulateur.indexation
    debut, fin = arguments.de, arguments.a
    print(f"Indexation « {simulateur.parametres.mode_indexation.value} », {debut}-{fin}\n")
    entete = (
        f"{'année':>6} {'retenu':>8} {'terme':<22} {'inflation':>10} "
        f"{'salaires':>10} {'productiv.':>11} {'réel':>8}"
    )
    print(entete)
    print("-" * len(entete))
    cumul = 1.0
    cumul_prix = 1.0
    for taux in indexation.historique(debut, fin):
        cumul *= 1 + taux.taux
        cumul_prix *= 1 + taux.inflation
        print(
            f"{taux.annee:>6} {taux.taux:>7.2%} {taux.terme_retenu:<22} "
            f"{taux.inflation:>9.2%} {taux.salaire_moyen:>9.2%} "
            f"{taux.productivite:>10.2%} {taux.taux_reel:>7.2%}"
        )
    print("-" * len(entete))
    print(f"Revalorisation cumulée {debut}-{fin} : ×{cumul:.3f}")
    print(f"Niveau des prix sur la même période  : ×{cumul_prix:.3f}")
    print(f"Soit, en pouvoir d'achat             : ×{cumul / cumul_prix:.3f}")
    return 0


def commande_fusion(arguments: argparse.Namespace) -> int:
    simulateur = Simulateur(_parametres(arguments))
    fusionne = simulateur.regime_fusionne
    print(fusionne.resume())
    print("\nRégimes fusionnés :")
    for code in fusionne.regimes_fusionnes:
        print(f"  {code:<26} {simulateur.catalogue[code].nom[:60]}")
    return 0


def commande_donnees(arguments: argparse.Namespace) -> int:
    """Rapport de fiabilité : qui doit être certifié avant tout usage sérieux."""
    simulateur = Simulateur(_parametres(arguments))
    macro = simulateur.macro
    print("Fiabilité des séries macroéconomiques par période\n")
    entete = f"{'période':<14} {'inflation':<11} {'salaires':<11} {'productivité':<13} {'ensemble':<10}"
    print(entete)
    print("-" * len(entete))
    for debut in range(1930, 2030, 10):
        fin = debut + 9
        print(
            f"{debut}-{fin:<9} "
            f"{str(macro.inflation.fiabilite_minimale_sur(debut, fin)):<11} "
            f"{str(macro.salaire_moyen.fiabilite_minimale_sur(debut, fin)):<11} "
            f"{str(macro.productivite.fiabilite_minimale_sur(debut, fin)):<13} "
            f"{str(macro.fiabilite_sur(debut, fin)):<10}"
        )

    print("\nFiabilité des régimes\n")
    par_niveau: dict[str, list[str]] = {}
    for regime in simulateur.catalogue:
        par_niveau.setdefault(str(regime.fiabilite), []).append(regime.code)
    for niveau in ("certifiee", "haute", "moyenne", "estimee"):
        codes = sorted(par_niveau.get(niveau, []))
        if codes:
            print(f"  {niveau:<10} ({len(codes):>2}) : {', '.join(codes)}")

    print(
        "\nTables de mortalité : "
        + ("quotients observés par âge, complétés par une calibration de "
           "Gompertz-Makeham hors de leur portée"
           if simulateur.mortalite.utilise_tables_reelles
           else "calibration paramétrique de Gompertz-Makeham sur e60 et e65")
    )
    journal = journal_certification(simulateur.macro.racine)
    if journal:
        print(f"\nDernier recontrôle contre les sources : {journal['certifie_le']}\n")
        for nom, trace in sorted(journal["series"].items()):
            print(f"  {nom:<23} {trace['valeurs']:>5} valeurs  {trace['niveau']:<10}"
                  f" {trace['source']}")
        print(
            "\nCe qui n'y figure pas n'a pas de source automatisable : les séries "
            "d'avant 1950, l'espérance de vie à 65 ans d'avant 1960, les quotients "
            "de mortalité d'avant 1986, les taux de cotisation d'avant 1967, le "
            "barème de points du régime de base agricole, et les âges et durées "
            "propres à chaque régime. Voir docs/limites.md."
        )
    else:
        print(
            "\nAucune série n'a encore été recontrôlée : lancer scripts/fetch/ "
            "puis scripts/verifier_donnees.py --appliquer. Voir docs/limites.md."
        )
    return 0


def commande_web(arguments: argparse.Namespace) -> int:
    """Sert l'interface web. Dépendances optionnelles : pip install -e ".[web]"."""
    try:
        import uvicorn
    except ModuleNotFoundError:
        print(
            "L'interface web demande deux dépendances supplémentaires. "
            'Les installer avec :\n\n    pip install -e ".[web]"\n',
            file=sys.stderr,
        )
        return 4

    from .web import creer_application

    application = creer_application(_parametres(arguments))
    print(f"Simulateur disponible sur http://{arguments.hote}:{arguments.port}")
    uvicorn.run(application, host=arguments.hote, port=arguments.port, log_level="warning")
    return 0


# -- assemblage --------------------------------------------------------------


def _ajouter_options_communes(analyseur: argparse.ArgumentParser) -> None:
    analyseur.add_argument("--donnees", help="racine du répertoire de données")
    analyseur.add_argument(
        "--indexation", choices=[m.value for m in ModeIndexation],
        help="règle d'indexation (défaut : triple_lock_inverse)",
    )
    analyseur.add_argument(
        "--age-reference", dest="age_reference",
        choices=[m.value for m in ModeAgeReference],
        help="construction de l'âge de référence (défaut : cliquet_legal)",
    )
    analyseur.add_argument(
        "--conversion-acquis", dest="conversion_acquis",
        choices=[a.value for a in AgeConversionDroitsAcquis],
        help="âge de conversion des droits acquis à la bascule "
        "(défaut : reference)",
    )
    analyseur.add_argument(
        "--part-cotisation", dest="part_cotisation",
        choices=[c.value for c in PartCotisation],
        help="part de la cotisation portée au compte : salariale seule "
        "(défaut, scénarios 2 et 3), totale, ou totale avec la part patronale "
        "du public empruntée au privé",
    )
    analyseur.add_argument(
        "--table", choices=[t.value for t in TableConversion],
        help="table de conversion (défaut : unisexe)",
    )
    analyseur.add_argument(
        "--cotisations", choices=[s.value for s in SourceCotisations],
        help="source des taux de cotisation (défaut : taux_historiques)",
    )
    analyseur.add_argument(
        "--projection", help="scénario macroéconomique au-delà de 2025 "
        "(cor_central, cor_favorable, cor_defavorable, stagnation)",
    )
    analyseur.add_argument("--bascule", type=int, help="année de bascule (défaut : 2026)")
    analyseur.add_argument(
        "--euros", type=int, help="année des euros constants (défaut : 2026)"
    )
    analyseur.add_argument(
        "--fiabilite-min", dest="fiabilite_min",
        choices=["estimee", "moyenne", "haute", "certifiee"],
        help="refuse de calculer si les données sont moins fiables",
    )
    analyseur.add_argument("--json", action="store_true", help="sortie JSON")


def construire_analyseur() -> argparse.ArgumentParser:
    analyseur = argparse.ArgumentParser(
        prog="retraite-notionnelle",
        description=(
            "Simulateur de retraite en comptes notionnels — système actuel, "
            "comptes notionnels rétroactifs et prospectifs, avec et sans les "
            "cotisations employeur des régimes publics."
        ),
    )
    sous = analyseur.add_subparsers(dest="commande", required=True)

    simuler = sous.add_parser("simuler", help="simuler une carrière individuelle")
    simuler.add_argument("--naissance", type=int, required=True, help="année de naissance")
    simuler.add_argument("--sexe", choices=["H", "F"], default="H")
    simuler.add_argument("--statut", required=True, help="statut d'affiliation (voir `regimes`)")
    simuler.add_argument("--debut", type=float, required=True, help="âge de début d'activité")
    simuler.add_argument(
        "--liquidation", type=float, required=True,
        help="âge de liquidation, effectif pour un retraité, souhaité pour un actif",
    )
    simuler.add_argument(
        "--salaire", type=float, default=1.0,
        help="niveau de revenu en multiples du salaire moyen (1.0 = salaire moyen)",
    )
    simuler.add_argument(
        "--profil", default="ascendant",
        choices=["plat", "ascendant", "fortement_ascendant"],
        help="déformation du salaire au cours de la carrière",
    )
    simuler.add_argument("--enfants", type=int, default=0)
    simuler.add_argument(
        "--primes", type=float, default=0.0,
        help="part de primes dans la rémunération (fonction publique)",
    )
    simuler.add_argument(
        "--interruption", action="append",
        help="période sans cotisation, format « debut:fin:motif », répétable",
    )
    simuler.add_argument("--nom", help="libellé de l'assuré dans le rapport")
    simuler.add_argument("--detail", action="store_true", help="détail par régime")
    _ajouter_options_communes(simuler)
    simuler.set_defaults(fonction=commande_simuler)

    cas = sous.add_parser("cas-types", help="grille cas type × génération (cas général)")
    cas.add_argument("--generations", type=int, nargs="+")
    cas.add_argument("--cas", nargs="+", help="codes de cas types à retenir")
    _ajouter_options_communes(cas)
    cas.set_defaults(fonction=commande_cas_types)

    regimes = sous.add_parser("regimes", help="catalogue des régimes et statuts")
    _ajouter_options_communes(regimes)
    regimes.set_defaults(fonction=commande_regimes)

    indexation = sous.add_parser("indexation", help="série des taux d'indexation")
    indexation.add_argument("--de", type=int, default=1941)
    indexation.add_argument("--a", type=int, default=2025)
    _ajouter_options_communes(indexation)
    indexation.set_defaults(fonction=commande_indexation)

    fusion = sous.add_parser("fusion", help="régime unique issu de la fusion")
    _ajouter_options_communes(fusion)
    fusion.set_defaults(fonction=commande_fusion)

    donnees = sous.add_parser("donnees", help="rapport de fiabilité des données")
    _ajouter_options_communes(donnees)
    donnees.set_defaults(fonction=commande_donnees)

    web = sous.add_parser("web", help="servir l'interface web sur un navigateur")
    web.add_argument("--hote", default="127.0.0.1", help="adresse d'écoute")
    web.add_argument("--port", type=int, default=8000)
    _ajouter_options_communes(web)
    web.set_defaults(fonction=commande_web)

    return analyseur


def main(argv: list[str] | None = None) -> int:
    arguments = construire_analyseur().parse_args(argv)
    try:
        return arguments.fonction(arguments)
    except DonneeInsuffisante as erreur:
        print(f"Données insuffisantes : {erreur}", file=sys.stderr)
        return 3
    except (KeyError, ValueError, FileNotFoundError) as erreur:
        print(f"Erreur : {erreur}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
