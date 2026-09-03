#!/usr/bin/env python3
"""Fabrique les cas-témoins qui contrôlent le portage JavaScript.

Le modèle Python reste la **référence** : c'est lui qui a été écrit contre les
sources, testé et documenté. Le moteur JavaScript qui fait tourner le site doit
en reproduire les chiffres, pas les réinventer. Ce script fige donc, depuis le
Python, ce que le JavaScript doit retrouver :

* ``tests/temoins/simulations.json`` — un jeu de carrières et de réglages, avec
  la sortie complète de ``Comparaison.dictionnaire()`` pour chacun ;
* ``tests/temoins/pages.json`` — le HTML rendu de chaque page du site.

Les deux fichiers sont versionnés : une différence de chiffre entre les deux
implémentations apparaît alors dans ``node --test``, et une modification voulue
du modèle apparaît en diff dans le dépôt, chiffre par chiffre. C'est ce qui
rend le portage vérifiable plutôt que crédible.

    python scripts/construire_temoins.py            # régénère les témoins
    python scripts/construire_temoins.py --verifier # échoue s'ils sont périmés
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from retraite_notionnelle.web import gabarit as g  # noqa: E402
from retraite_notionnelle.web.pages import Contexte, Saisie, rendre  # noqa: E402

# Les témoins servent à contrôler le site, qui tourne entièrement dans le
# navigateur : c'est donc ce mode-là qu'on fige, liens en ancre compris.
g.MODE = "navigateur"

DOSSIER = RACINE / "tests" / "temoins"
SIMULATIONS = DOSSIER / "simulations.json"
PAGES = DOSSIER / "pages.json"

#: Réglages du cas de base. Chaque cas ci-dessous en dérive.
BASE = {
    "naissance": "1975", "sexe": "H", "statut": "salarie_prive_non_cadre",
    "debut": "21", "liquidation": "64", "salaire": "1", "profil": "ascendant",
    "primes": "0", "enfants": "0", "interruptions": "",
    "indexation": "triple_lock_inverse", "age_reference": "cliquet_legal",
    "table": "unisexe", "conversion_acquis": "reference",
    "projection": "cor_central",
    "bascule": "2026", "euros": "2026",
}

#: Statuts couverts par le balayage « un statut, une génération ».
STATUTS = (
    "salarie_prive_non_cadre", "salarie_prive_cadre", "fonctionnaire_etat",
    "fonctionnaire_territorial_hospitalier", "contractuel_public", "agent_sncf",
    "agent_ratp", "agent_ieg", "artisan", "commercant", "profession_liberale",
    "exploitant_agricole", "salarie_agricole", "avocat", "marin",
    "agent_banque_de_france", "clerc_de_notaire", "mineur", "ouvrier_etat",
    "personnel_opera", "personnel_comedie_francaise", "sans_activite",
)


def _cas() -> list[dict]:
    """Jeu de cas couvrant chaque branche du moteur au moins une fois."""
    cas: list[tuple[str, dict]] = [("base", {})]

    # Un statut d'affiliation après l'autre : c'est le catalogue des régimes,
    # les assiettes à tranches et les régimes en points qui sont balayés ici.
    for statut in STATUTS:
        cas.append((f"statut_{statut}", {"statut": statut}))

    # Générations : la même carrière déplacée dans le temps traverse toutes les
    # ruptures législatives, et l'écart d'indexation entre époques.
    for naissance in (1930, 1940, 1950, 1960, 1970, 1980, 1990, 2000, 2005):
        cas.append((f"generation_{naissance}", {"naissance": str(naissance)}))

    # Âges de liquidation : départ très anticipé, à l'heure, très différé.
    for age in ("52", "57", "60", "62", "64", "67", "70"):
        cas.append((f"liquidation_{age}", {"liquidation": age}))
    cas.append(("liquidation_demi", {"liquidation": "64.5", "debut": "20.5"}))

    # LE MOIS. Douze départs séparés d'un mois, pour que le diff montre ce que
    # chaque mois déplace — et surtout qu'il ne montre plus la marche de six à
    # sept pour cent que l'arrondi à l'année creusait au milieu de celle-ci.
    for mois in range(12):
        cas.append((f"liquidation_mois_{mois:02d}", {
            "liquidation": "64", "liquidation_mois": str(mois),
        }))
    # Une année d'entrée elle aussi incomplète, et un mois de naissance qui
    # décale tout : la carrière ne commence ni ne finit au 1er janvier.
    cas.append(("mois_carriere_decalee", {
        "naissance_mois": "9", "debut": "22", "debut_mois": "3",
        "liquidation": "64", "liquidation_mois": "7",
    }))
    # Les deux générations que les textes coupent en cours d'année, de part et
    # d'autre de la coupure : 1er juillet 1951, 1er septembre 1961.
    for mois, cote in (("6", "avant"), ("8", "apres")):
        cas.append((f"generation_coupee_1951_{cote}", {
            "naissance": "1951", "naissance_mois": mois, "liquidation": "62",
        }))
    for mois, cote in (("8", "avant"), ("10", "apres")):
        cas.append((f"generation_coupee_1961_{cote}", {
            "naissance": "1961", "naissance_mois": mois, "liquidation": "62",
        }))
    # La revalorisation exceptionnelle du 1er juillet 2022 : deux liquidations
    # de la même année, de part et d'autre de la circulaire.
    for mois, cote in (("2", "avant"), ("8", "apres")):
        cas.append((f"revalorisation_juillet_2022_{cote}", {
            "naissance": "1958", "liquidation": "64", "liquidation_mois": mois,
        }))

    # Règles de modélisation, une par une.
    for mode in ("triple_lock_inverse_nominal", "mediane_trois_taux",
                 "moyenne_trois_taux", "revalorisation_portee_au_compte",
                 "prix", "salaires", "masse_salariale"):
        cas.append((f"indexation_{mode}", {"indexation": mode}))
    for mode in ("cliquet_puis_esperance_vie", "legal_sans_cliquet"):
        cas.append((f"age_reference_{mode}", {"age_reference": mode}))
    cas.append(("table_par_sexe", {"table": "par_sexe"}))
    # Conversion des droits acquis : à l'âge de référence (défaut) ou à l'âge de
    # départ effectif, seul endroit du modèle où le passage aux comptes
    # notionnels peut retirer quelque chose à des droits déjà ouverts.
    cas.append(("conversion_acquis_liquidation", {"conversion_acquis": "liquidation"}))
    cas.append(("conversion_acquis_liquidation_tardive", {
        "conversion_acquis": "liquidation", "liquidation": "70",
    }))
    cas.append(("table_par_sexe_femme", {"table": "par_sexe", "sexe": "F"}))
    for projection in ("cor_favorable", "cor_defavorable", "stagnation"):
        cas.append((f"projection_{projection}", {"projection": projection}))
    for bascule in ("1980", "2000", "2026", "2040", "2060"):
        cas.append((f"bascule_{bascule}", {"bascule": bascule, "naissance": "1990"}))
    for euros in ("1980", "2000", "2050"):
        cas.append((f"euros_{euros}", {"euros": euros}))

    # Profils de rémunération et niveaux de revenu, y compris au-dessus du
    # plafond de la Sécurité sociale et sous le SMIC.
    for profil in ("plat", "fortement_ascendant"):
        cas.append((f"profil_{profil}", {"profil": profil}))
    for salaire in ("0.2", "0.55", "1.5", "3", "8"):
        cas.append((f"salaire_{salaire}", {"salaire": salaire}))

    # Interruptions de carrière, primes, enfants — ce que les scénarios
    # notionnels neutralisent.
    cas.append(("interruption_simple", {"interruptions": "2000:2004:education_enfant"}))
    cas.append(("interruption_multiple", {
        "interruptions": "1999:2001:chomage_indemnise, 2008:2009:maladie",
        "naissance": "1970",
    }))
    cas.append(("primes_fonction_publique", {
        "statut": "fonctionnaire_etat", "primes": "0.22",
    }))
    cas.append(("enfants", {"enfants": "3", "sexe": "F"}))

    # Les trimestres accordés au titre des enfants ne dépendent pas du seul
    # nombre d'enfants : la MDA n'existe pas avant 1972, elle vaut un an par
    # enfant jusqu'en 1974, elle va à la mère, et la fonction publique sert sa
    # propre bonification — un an par enfant né avant 2004, deux trimestres
    # ensuite. Un cas par branche, pour que la table se lise dans les témoins.
    # La carrière commence à trente ans : une carrière complète est au taux
    # plein et proratisée à un, et ces trimestres n'y déplacent rien — ils ne se
    # voient que sur une carrière incomplète, qui est aussi le cas où le droit
    # les a voulus.
    enfants = {"enfants": "3", "sexe": "F", "debut": "30"}
    cas.append(("enfants_carriere_incomplete", dict(enfants)))
    cas.append(("enfants_pere", {**enfants, "sexe": "H"}))
    cas.append(("enfants_avant_1972", {
        **enfants, "naissance": "1910", "liquidation": "60",
    }))
    cas.append(("enfants_loi_boulin", {
        **enfants, "naissance": "1913", "liquidation": "60",
    }))
    cas.append(("enfants_fonction_publique_nes_avant_2004", {
        **enfants, "statut": "fonctionnaire_etat", "naissance": "1960",
    }))
    cas.append(("enfants_fonction_publique_nes_depuis_2004", {
        **enfants, "statut": "fonctionnaire_etat", "naissance": "1985",
    }))
    # Artisane liquidant avant l'absorption du RSI par la CNAV : c'est bien son
    # régime aligné qui porte les trimestres, comme l'article L. 634-2 le veut.
    cas.append(("enfants_regime_aligne", {
        **enfants, "statut": "artisan", "naissance": "1950",
    }))
    # La loi Boulin ne visait que les mères d'AU MOINS DEUX enfants : le même
    # départ, avec un enfant, ne donne rien.
    cas.append(("enfants_loi_boulin_enfant_unique", {
        **enfants, "enfants": "1", "naissance": "1913", "liquidation": "60",
    }))

    # Surcote parentale : durée requise atteinte à 63 ans, trimestres pour
    # enfants, et une année de travail de plus que la loi de 2023 a imposée.
    parentale = {"enfants": "2", "sexe": "F", "debut": "18",
                 "naissance": "1968", "liquidation": "64"}
    cas.append(("surcote_parentale", dict(parentale)))
    cas.append(("surcote_parentale_pere", {**parentale, "sexe": "H"}))
    cas.append(("surcote_parentale_duree_incomplete", {**parentale, "debut": "30"}))
    cas.append(("surcote_parentale_fonction_publique", {
        **parentale, "statut": "fonctionnaire_etat",
    }))
    cas.append(("surcote_parentale_avec_surcote_ordinaire", {
        **parentale, "liquidation": "67",
    }))

    # Retraité de longue date : la bascule est postérieure à sa liquidation.
    cas.append(("deja_liquide", {"naissance": "1935", "liquidation": "60"}))
    cas.append(("liquidation_a_la_bascule", {"naissance": "1962", "liquidation": "64"}))

    return [{"nom": nom, "requete": {**BASE, **modifications}}
            for nom, modifications in cas]


def _fini(valeur):
    """Remplace NaN et les infinis par ``null``.

    ``json.dumps`` les écrit ``NaN`` et ``Infinity``, que la norme JSON ignore
    et que ``JSON.parse`` refuse. Le modèle en produit — l'écart au système
    actuel n'est pas défini quand ce système ne verse rien — et le témoin doit
    rester lisible des deux côtés.
    """
    if isinstance(valeur, float) and (valeur != valeur or valeur in (float("inf"), float("-inf"))):
        return None
    if isinstance(valeur, dict):
        return {cle: _fini(v) for cle, v in valeur.items()}
    if isinstance(valeur, list):
        return [_fini(v) for v in valeur]
    return valeur


def _simulations(contexte: Contexte) -> dict:
    resultats = {}
    for cas in _cas():
        saisie = Saisie.depuis_requete(cas["requete"])
        resultats[cas["nom"]] = {
            "requete": cas["requete"],
            "resultat": _fini(contexte.simuler(saisie).dictionnaire()),
        }
    return resultats


#: Le bloc JSON de la page reprend les mêmes chiffres que les témoins
#: numériques, mais formatés par ``json.dumps`` : sa comparaison ne dirait rien
#: du rendu et ne ferait que constater que Python et JavaScript n'écrivent pas
#: les flottants de la même façon. On le retire des deux côtés.
_BLOC_JSON = re.compile(r'(<pre class="json">).*?(</pre>)', re.DOTALL)


def sans_bloc_json(html: str) -> str:
    return _BLOC_JSON.sub(r"\1\2", html)


def _pages(contexte: Contexte) -> dict:
    demandes = [
        ("accueil", "/", {}),
        ("accueil_calcul", "/", BASE),
        ("accueil_femme_interrompue", "/", {
            **BASE, "sexe": "F", "naissance": "1968", "statut": "salarie_prive_non_cadre",
            "interruptions": "1995:1999:education_enfant", "enfants": "2",
            "salaire": "0.9",
        }),
        ("accueil_regime_special", "/", {
            **BASE, "statut": "agent_sncf", "naissance": "1960", "liquidation": "52",
        }),
        ("accueil_indexation_prix", "/", {**BASE, "indexation": "prix"}),
        ("accueil_conversion_acquis", "/", {
            **BASE, "conversion_acquis": "liquidation",
        }),
        # Carrière entièrement interrompue : capital notionnel nul, donc aucune
        # cascade à afficher — et surtout aucune division par zéro.
        ("accueil_carriere_vide", "/", {
            **BASE, "interruptions": "1996:2038:chomage_indemnise",
        }),
        ("accueil_saisie_refusee", "/", {**BASE, "liquidation": "12"}),
        ("cas_types", "/cas-types", {}),
        ("methode", "/methode", {}),
        ("donnees", "/donnees", {}),
    ]
    pages = {}
    for nom, chemin, parametres in demandes:
        titre, corps = rendre(contexte, chemin, parametres)
        pages[nom] = {
            "chemin": chemin,
            "parametres": parametres,
            "titre": titre,
            "corps": sans_bloc_json(corps),
        }
    return pages


def construire() -> dict[Path, bytes]:
    contexte = Contexte()
    fichiers = {
        SIMULATIONS: _simulations(contexte),
        PAGES: _pages(contexte),
    }
    return {
        chemin: (json.dumps(contenu, ensure_ascii=False, sort_keys=True, indent=1) + "\n")
        .encode("utf-8")
        for chemin, contenu in fichiers.items()
    }


def main(argv: list[str] | None = None) -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument(
        "--verifier", action="store_true",
        help="ne rien écrire ; échouer si les témoins versionnés sont périmés",
    )
    arguments = analyseur.parse_args(argv)

    attendus = construire()

    if arguments.verifier:
        for chemin, contenu in attendus.items():
            if not chemin.exists() or chemin.read_bytes() != contenu:
                print(f"{chemin.relative_to(RACINE)} est périmé — lancer "
                      "python scripts/construire_temoins.py", file=sys.stderr)
                return 1
        print("témoins à jour")
        return 0

    DOSSIER.mkdir(parents=True, exist_ok=True)
    for chemin, contenu in attendus.items():
        chemin.write_bytes(contenu)
        print(f"{chemin.relative_to(RACINE)} : {len(contenu) / 1024:.0f} Ko")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
