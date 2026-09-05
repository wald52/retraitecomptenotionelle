#!/usr/bin/env python3
"""Recontrôle des données de référence contre les sources téléchargées.

    python scripts/fetch/insee_bdm.py            # dépose les sources
    python scripts/fetch/eurostat_esperance_vie.py
    python scripts/fetch/eurostat_hicp.py

    python scripts/verifier_donnees.py           # confronte, sans rien écrire
    python scripts/verifier_donnees.py --appliquer   # aligne et certifie

C'est ce script — et lui seul — qui a le droit de faire passer une valeur au
niveau ``certifiee``. Une valeur n'est certifiée que si elle a été confrontée
avec succès à un fichier source présent dans ``data/brut/``. Sans fichier
source, le contrôle est signalé comme impossible, jamais comme réussi.

Trois familles de contrôles
---------------------------

1. **Cohérence interne** — continuité des séries, absence de trous, plages
   plausibles. Ne dépend d'aucune source et ne certifie rien.

2. **Certification** — reconstruction de la série depuis le fichier source puis
   confrontation valeur par valeur. C'est le seul contrôle qui certifie.
   ``--appliquer`` aligne alors la série de référence sur la source : les
   valeurs qui divergent sont remplacées, les années absentes sont ajoutées, et
   toutes portent ensuite le niveau ``certifiee``. Les années hors de portée de
   la source ne sont pas touchées.

3. **Vraisemblance** — confrontation de l'inflation 1996-2025 à l'IPCH
   d'Eurostat. Ce contrôle ne certifie rien, et c'est délibéré : l'IPCH
   harmonisé et l'IPC national ne mesurent pas la même chose (traitement des
   remboursements de santé, pondérations, champ des ménages). L'écart atteint
   couramment 0,5 à 0,8 point (2022 : 5,2 % pour l'IPC, 5,9 % pour l'IPCH),
   sans qu'aucune des deux valeurs soit fausse. Le seuil d'alerte est donc fixé
   à 1,5 point, et aucune valeur ne passe au niveau ``certifiee`` par ce biais.

Ce qui reste hors de portée — inflation, salaires et productivité d'avant 1950,
plafond d'avant 2002, espérance de vie à 65 ans d'avant 1986, tables de
quotients, paramètres de régime — est énuméré dans docs/limites.md §1.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

RACINE = Path(__file__).resolve().parents[1]
DONNEES = RACINE / "data"
BRUT = DONNEES / "brut"
REFERENCE = DONNEES / "reference"

#: Première année du fichier des espérances de vie : avant elle, aucune série
#: du dépôt n'en a besoin.
PREMIERE_ANNEE_ESPERANCE = 1946
#: Première année où l'OCDE publie e65. En deçà, personne ne la publie et le
#: dépôt la dérive des quotients observés.
PREMIERE_ANNEE_OCDE = 1960
#: Âge auquel la table doit au moins monter pour qu'une espérance à 65 ans
#: dérivée d'elle ait un sens. Les tables de Vallin et Meslé vont à 104 ans.
AGE_TERMINAL_MINIMAL = 100

#: Dérive cumulée au-delà de laquelle la reconstitution d'avant 1950 mérite
#: d'être reprise. Elle est fixée au double de ce que l'instrument mesure sur la
#: période certifiée : la série des coefficients s'y écarte déjà de 2,4 % de la
#: série mensuelle, et l'on ne saurait exiger d'elle mieux qu'elle ne vaut.
SEUIL_DERIVE_PRIX_ANCIENS = 0.05

#: Seuil d'alerte du contrôle de vraisemblance IPC / IPCH, en points de taux.
#: Fixé à 1,5 point : au-dessous, l'écart s'explique par la différence de
#: méthode entre indice national et indice harmonisé ; au-dessus, il y a
#: vraisemblablement une erreur de saisie.
SEUIL_VRAISEMBLANCE = 0.015

#: Année de chaînage entre l'indice des prix base 1980 (publié jusqu'en 1992)
#: et l'indice base 2015 (publié à partir de 1990). Les deux bases se
#: chevauchent sur 1990-1992 ; on bascule au plus tôt, la base récente étant
#: celle que l'INSEE tient à jour.
ANNEE_CHAINAGE_IPC = 1990

#: Trace de la dernière certification, écrite par ``--appliquer``. Le répertoire
#: data/brut/ n'étant pas versionné, c'est ce fichier qui rend la certification
#: vérifiable après coup : il dit quelle source, quel jour, combien de valeurs.
JOURNAL = DONNEES / "derive" / "certification.json"


# ---------------------------------------------------------------------------
# Lecture et écriture des CSV de référence, en préservant leur en-tête
# ---------------------------------------------------------------------------


def _table_reference(nom: str, cle: str, colonne: str) -> dict[float, float]:
    """Une table par génération ou par année, lue dans data/reference/legislation."""
    chemin = REFERENCE / "legislation" / nom
    if not chemin.exists():
        return {}
    return {
        float(ligne[cle]): float(ligne[colonne])
        for ligne in charger_csv(chemin)
    }


def charger_csv(chemin: Path) -> list[dict[str, str]]:
    with chemin.open(encoding="utf-8") as flux:
        lignes = (l for l in flux if not l.lstrip().startswith("#"))
        return list(csv.DictReader(lignes))


def _lire(chemin: Path) -> tuple[list[str], list[str], list[dict[str, str]]]:
    """Renvoie (commentaires d'en-tête, noms de colonnes, lignes)."""
    texte = chemin.read_text(encoding="utf-8").splitlines()
    commentaires = [l for l in texte if l.lstrip().startswith("#")]
    utiles = [l for l in texte if l.strip() and not l.lstrip().startswith("#")]
    lecteur = csv.DictReader(utiles)
    return commentaires, list(lecteur.fieldnames or []), list(lecteur)


def _ecrire(chemin: Path, commentaires: list[str], champs: list[str],
            lignes: list[dict[str, str]]) -> None:
    sortie = ["\n".join(commentaires)] if commentaires else []
    tampon = []
    redacteur = csv.DictWriter(_Collecteur(tampon), fieldnames=champs, lineterminator="\n")
    redacteur.writeheader()
    redacteur.writerows(lignes)
    sortie.append("".join(tampon))
    chemin.write_text("\n".join(sortie), encoding="utf-8")


class _Collecteur:
    """Fichier minimal en mémoire, pour que csv.DictWriter écrive dans une liste."""

    def __init__(self, cible: list[str]) -> None:
        self._cible = cible

    def write(self, texte: str) -> None:
        self._cible.append(texte)


# ---------------------------------------------------------------------------
# Reconstruction des séries depuis les fichiers source
# ---------------------------------------------------------------------------


class SourceAbsente(FileNotFoundError):
    """Le fichier source nécessaire à un contrôle n'a pas été téléchargé."""


def _charge_bdm() -> dict[str, dict]:
    chemin = BRUT / "insee_bdm.json"
    if not chemin.exists():
        raise SourceAbsente(f"{chemin} absent (lancer scripts/fetch/insee_bdm.py)")
    return json.loads(chemin.read_text(encoding="utf-8"))["series"]


def _observations(nom: str) -> dict[str, float]:
    series = _charge_bdm()
    if nom not in series:
        raise SourceAbsente(
            f"série {nom!r} absente de data/brut/insee_bdm.json "
            f"(lancer scripts/fetch/insee_bdm.py --serie {nom})"
        )
    return series[nom]["observations"]


def _variations(indice: dict[str, float]) -> dict[int, float]:
    """Taux de variation annuels d'un indice de niveau."""
    annees = sorted(int(p) for p in indice)
    return {
        courante: indice[str(courante)] / indice[str(precedente)] - 1.0
        for precedente, courante in zip(annees, annees[1:])
        if courante == precedente + 1
    }


def _rapport(numerateur: str, denominateur: str) -> dict[str, float]:
    haut, bas = _observations(numerateur), _observations(denominateur)
    return {p: haut[p] / bas[p] for p in sorted(set(haut) & set(bas))}


def source_inflation() -> dict[tuple, float]:
    """Variation annuelle de l'IPC, indice base 1980 puis base 2015."""
    ancienne = _variations(_observations("ipc_base_1980"))
    recente = _variations(_observations("ipc_base_2015"))
    chainee = {a: v for a, v in ancienne.items() if a <= ANNEE_CHAINAGE_IPC}
    chainee.update({a: v for a, v in recente.items() if a > ANNEE_CHAINAGE_IPC})
    return {(str(a),): v for a, v in sorted(chainee.items())}


def source_salaire_moyen() -> dict[tuple, float]:
    """Variation nominale du salaire moyen par tête.

    SMPT = salaires et traitements bruts (D11) rapportés à l'emploi salarié
    intérieur en personnes physiques — la définition des comptes nationaux.
    """
    variations = _variations(_rapport("salaires_bruts", "emploi_salarie"))
    return {(str(a),): v for a, v in sorted(variations.items())}


def source_masse_salariale() -> dict[tuple, float]:
    """Variation nominale de la masse salariale — l'assiette des cotisations.

    Salaires et traitements bruts (D11, total des branches), en euros courants,
    pris EN NIVEAU et non par tête : c'est le produit du salaire moyen par
    l'emploi salarié, et donc la grandeur dont dépend ce que la répartition
    peut servir. Le même agrégat sert de numérateur au salaire moyen par tête ;
    la différence entre les deux séries est exactement la croissance de
    l'emploi salarié.
    """
    variations = _variations(_observations("salaires_bruts"))
    return {(str(a),): v for a, v in sorted(variations.items())}


def source_pib_nominal() -> dict[tuple, float]:
    """Variation nominale du produit intérieur brut.

    PIB approche produit, prix courant (idbank 011779992). C'est l'assiette de
    la variante italienne de l'indexation des comptes notionnels ; le lissage
    sur cinq ans qu'elle applique est une règle du moteur, pas de la série, et
    ne figure donc pas ici.
    """
    variations = _variations(_observations("pib_nominal"))
    return {(str(a),): v for a, v in sorted(variations.items())}


def source_productivite() -> dict[tuple, float]:
    """Variation réelle de la productivité par tête.

    Valeur ajoutée en volume (prix chaînés) rapportée à l'emploi intérieur
    total en personnes physiques. Le concept est bien celui **par tête** retenu
    par le modèle, et non la productivité horaire — les deux divergent
    fortement après 1982.
    """
    variations = _variations(_rapport("valeur_ajoutee_volume", "emploi_total"))
    return {(str(a),): v for a, v in sorted(variations.items())}


#: Nombre minimal d'observations mensuelles concordantes pour retenir une année.
#:
#: Le plafond est fixé par arrêté pour l'ANNÉE CIVILE : ses douze mois sont
#: égaux par construction, et la dernière année à en avoir connu plusieurs est
#: 1961. Exiger les douze revenait donc à refuser de certifier, onze mois durant,
#: une valeur que le décret a déjà fixée — le plafond de 2026 restait `estimee`
#: alors que l'arrêté du 22 décembre 2025 le porte à 4 005 € par mois, et cette
#: fiabilité sous-évaluée se propageait à tout résultat qui touche au plafond.
#:
#: Trois suffisent donc, à trois conditions : qu'elles concordent — une année
#: dont les mois divergent est écartée plutôt que moyennée —, qu'elles ne soient
#: pas une observation isolée, et que la série couvre l'année DEPUIS JANVIER.
#: Cette dernière condition n'est pas une précaution de principe : la série
#: mensuelle de l'INSEE commence en août 2001, et retenir cette année-là sur ses
#: cinq derniers mois donnait 27 348 € contre les 27 349 € que porte le décret —
#: un euro d'arrondi, mais deux certifications qui se disputent la même ligne à
#: chaque exécution.
MOIS_MINIMAUX_PLAFOND = 3


def source_plafond() -> dict[tuple, float]:
    """Plafond annuel de la Sécurité sociale, à partir du plafond mensuel.

    Le plafond est fixé pour l'année civile : les observations d'une même année
    doivent être identiques, et une année où elles ne le sont pas est écartée
    plutôt que moyennée.
    """
    mensuel = _observations("plafond_mensuel")
    par_annee: dict[int, list[float]] = {}
    for periode, valeur in mensuel.items():
        par_annee.setdefault(int(periode[:4]), []).append(valeur)
    debuts = {int(periode[:4]): periode for periode in sorted(mensuel, reverse=True)}
    return {
        (str(annee),): round(valeurs[0] * 12)
        for annee, valeurs in sorted(par_annee.items())
        if len(valeurs) >= MOIS_MINIMAUX_PLAFOND and len(set(valeurs)) == 1
        and debuts[annee].endswith("-01")
    }


def _lire_json(nom_fichier: str, script: str) -> dict:
    chemin = BRUT / nom_fichier
    if not chemin.exists():
        raise SourceAbsente(f"{chemin} absent (lancer {script})")
    return json.loads(chemin.read_text(encoding="utf-8"))


def _serie_json(nom_fichier: str, script: str) -> dict[str, float]:
    return _lire_json(nom_fichier, script)["serie"]


def source_esperances() -> dict[tuple, float]:
    """Espérances de vie : e0 et e60 par l'INSEE, e65 par l'OCDE.

    L'INSEE publie e0, e1, e20, e40 et e60 depuis 1946, **jamais e65** — dont la
    calibration a pourtant besoin pour fixer la pente de la force de mortalité.
    C'est la seule raison pour laquelle une donnée française transite ici par
    l'OCDE, qui la publie depuis 1960 et la tient de l'INSEE. Eurostat la publie
    aussi mais seulement depuis 1986 : elle sert de contrôle croisé.
    """
    valeurs: dict[tuple, float] = {}
    for mesure in ("e0", "e60"):
        for sexe in ("H", "F"):
            for periode, valeur in _observations(f"{mesure}_{sexe}").items():
                valeurs[(periode, sexe, mesure)] = valeur

    ocde = _serie_json("oecd_esperance_vie.json", "scripts/fetch/oecd_esperance_vie.py")
    for cle, valeur in ocde.items():
        annee, sexe, mesure = cle.split("|")
        if mesure == "e65":
            valeurs[(annee, sexe, mesure)] = valeur
    return dict(sorted(valeurs.items()))


def source_esperance_65_derivee() -> dict[tuple, float]:
    """Espérance de vie à 65 ans d'avant 1960, dérivée des quotients observés.

    L'OCDE ne remonte pas plus haut, et l'INSEE ne publie jamais e65 : ces
    années restaient saisies depuis les tables TD/TV, et les années qu'aucune
    saisie ne couvrait — 1947 à 1949, 1951 à 1959 — étaient simplement
    interpolées. Or le dépôt a mieux depuis qu'il porte les tables de Vallin et
    Meslé : **les quotients du moment eux-mêmes**, certifiés, de 1899 à 1985 et
    jusqu'à 104 ans. Une espérance de vie n'est rien d'autre que leur somme
    cumulée ; il n'y avait donc plus de raison de la saisir.

    La méthode se contrôle d'elle-même : appliquée à e60, que l'INSEE publie et
    que le dépôt certifie, elle retrouve la valeur publiée à moins d'un dixième
    d'année sur toute la période. Appliquée à e65 après 1960, elle retrouve
    l'OCDE dans la même marge. C'est ce double recoupement, et non la formule,
    qui autorise à s'en servir là où personne ne publie.

    Niveau ``haute`` et non ``certifiee`` : la valeur est calculée, non
    confrontée à une publication. Elle est en revanche RECALCULÉE à chaque
    exécution depuis un fichier certifié, ce qu'aucune saisie ne peut offrir.
    """
    chemin = REFERENCE / "mortalite" / "quotients_periode.csv"
    if not chemin.exists():
        raise SourceAbsente(f"{chemin} absent (lancer scripts/fetch/ined_vallin_mesle.py)")

    quotients: dict[tuple[int, str], dict[int, float]] = {}
    for ligne in charger_csv(chemin):
        quotients.setdefault(
            (int(ligne["annee"]), ligne["sexe"]), {}
        )[int(ligne["age"])] = float(ligne["qx"])

    valeurs: dict[tuple, float] = {}
    for (annee, sexe), table in quotients.items():
        if not (PREMIERE_ANNEE_ESPERANCE <= annee < PREMIERE_ANNEE_OCDE):
            continue
        if AGE_TERMINAL_MINIMAL not in table:
            # Une table tronquée trop bas rendrait une espérance trop courte.
            continue
        total, survie, age = 0.0, 1.0, 65
        while age in table:
            survie *= 1.0 - table[age]
            total += survie
            age += 1
        valeurs[(str(annee), sexe, "e65")] = round(total + 0.5, 2)
    return dict(sorted(valeurs.items()))


def source_quotients() -> dict[tuple, float]:
    """Quotients de mortalité par âge — les vraies tables du moment.

    Leur présence dispense le modèle de sa calibration paramétrique aux âges
    couverts. Les classes ouvertes (85 ans et plus, puis 95 ans et plus selon
    les millésimes) sont écartées à la récupération : au-delà du dernier âge
    publié, la loi de Gompertz-Makeham reprend la main.
    """
    serie = _serie_json("eurostat_quotients.json", "scripts/fetch/eurostat_mortalite.py")
    return {
        tuple(cle.split("|")): valeur
        for cle, valeur in sorted(serie.items(),
                                  key=lambda kv: (int(kv[0].split("|")[0]),
                                                  kv[0].split("|")[1],
                                                  int(kv[0].split("|")[2])))
    }


def source_esperances_projetees() -> dict[tuple, float]:
    """Espérances de vie d'APRÈS 2025, dérivées des quotients projetés de l'INSEE.

    Ces années étaient saisies à la main aux seules années rondes, depuis un
    exercice de projection périmé, jusqu'à une année — 2080 — qui dépassait
    l'horizon de la source dont elle se réclamait ; au-delà, la série était
    gelée, ce qui revenait à supposer l'espérance de vie arrêtée vingt ans avant
    la fin de la projection.

    Les projections de population 2026 de l'INSEE publient les quotients de
    mortalité par âge et par année jusqu'en 2125 : on en dérive e0, e60 et e65
    année par année, par la méthode qui sert déjà aux années d'avant 1960. Plus
    d'interpolation entre années rondes, plus d'extrapolation muette, plus de
    gel — la projection du modèle s'arrête en 2100, la source va vingt-cinq ans
    plus loin.

    Niveau ``projetee``, qui vaut ``estimee`` dans le modèle : la valeur vient
    du producteur, mais elle décrit un avenir. Une projection ne se fait jamais
    passer pour une observation, fût-elle publiée par l'INSEE.
    """
    serie = _serie_json("insee_projections_mortalite.json",
                        "scripts/fetch/insee_projections_mortalite.py")
    return {
        tuple(cle.split("|")): valeur
        for cle, valeur in sorted(serie.items(),
                                  key=lambda kv: (int(kv[0].split("|")[0]),
                                                  kv[0].split("|")[1],
                                                  kv[0].split("|")[2]))
    }


def source_quotients_anciens() -> dict[tuple, float]:
    """Quotients de mortalité par âge d'AVANT 1986, reconstitués par l'INED.

    Eurostat ne publie rien avant 1986, et `docs/limites.md` tenait la Human
    Mortality Database pour la seule à remonter plus haut — donc hors d'atteinte
    d'un script, puisqu'elle exige une inscription. Elle n'est pas la seule :
    les tables de Vallin et Meslé, publiées par l'INED, couvrent 1806-1997 par
    année d'âge jusqu'à 104 ans, et l'INED en sert librement le fichier.

    Les deux sources se recouvrent de 1986 à 1997 et concordent à un demi-point
    de pourcentage près ; le dépôt reprend l'INED jusqu'en 1985 et laisse à
    Eurostat, producteur de la donnée observée, tout ce qu'il publie.

    S'y ajoutent, de 1986 à 1997, les seuls âges de 95 à 104 ans : Eurostat
    s'arrête à 94 et ses classes ouvertes n'en sont pas des quotients. Ce n'est
    donc pas un panachage — c'est une source là où l'autre se tait. Ces
    240 valeurs ne déplacent aucune simulation ; elles servent à AUDITER la loi
    paramétrique qui prend le relais au-delà du dernier âge observé, et
    `tests/test_donnees.py` fige l'écart qu'elles révèlent.
    """
    serie = _serie_json("ined_vallin_mesle.json", "scripts/fetch/ined_vallin_mesle.py")
    return {
        tuple(cle.split("|")): valeur
        for cle, valeur in sorted(serie.items(),
                                  key=lambda kv: (int(kv[0].split("|")[0]),
                                                  kv[0].split("|")[1],
                                                  int(kv[0].split("|")[2])))
    }


def _charge_points() -> dict:
    chemin = BRUT / "openfisca_points.json"
    if not chemin.exists():
        raise SourceAbsente(f"{chemin} absent (lancer scripts/fetch/openfisca_points.py)")
    return json.loads(chemin.read_text(encoding="utf-8"))


def _cles_points(cle_json: str, substituees: bool) -> dict[tuple, float]:
    charge = _charge_points()
    a_part = set(charge.get("cles_substituees", []))
    return {
        tuple(cle.split("|")): valeur
        for cle, valeur in sorted(charge[cle_json].items())
        if (cle in a_part) is substituees
    }


def source_valeurs_point_ircantec() -> dict[tuple, float]:
    """Barèmes de l'Ircantec publiés par la Caisse des dépôts, qui la gère.

    Producteur de la donnée, donc seule source de ce fichier qui puisse être
    certifiée. Elle couvre 1971-2021 ; ce qui déborde reste transcrit
    d'OpenFisca.
    """
    return {
        tuple(cle.split("|")): valeur
        for cle, valeur in sorted(
            _serie_json("cdc_ircantec.json", "scripts/fetch/cdc_ircantec.py").items()
        )
    }


def source_valeurs_point_agirc_arrco() -> dict[tuple, float]:
    """Barèmes publiés par la fédération Agirc-Arrco, qui les fixe.

    Producteur de la donnée, donc seule source de ces lignes qui puisse être
    certifiée. Sa compilation porte le régime unifié depuis 2019, mais aussi les
    tables d'avant la fusion — l'Agirc de 1947 à 2018, l'Arrco de 1999 à 2018 et
    l'UNIRS de 1961 à 1998, la caisse dont le barème tient lieu de point Arrco
    avant l'unification. Ces 260 valeurs venaient d'OpenFisca ; elles viennent
    désormais de qui les a décidées, et la transcription les rendait juste, à
    cinq centièmes de millime près.

    La valeur d'achat y va un an plus loin que la valeur de service : la
    fédération la publie par année civile, quand la valeur de service dépend de
    la décision de novembre. Le récupérateur n'invente pas celle qui manque.
    """
    return {
        tuple(cle.split("|")): valeur
        for cle, valeur in sorted(
            _serie_json("agirc_arrco_valeurs_point.json",
                        "scripts/fetch/agirc_arrco_valeurs_point.py").items()
        )
    }


def source_valeurs_point_agirc_arrco_en_cours() -> dict[tuple, float]:
    """Valeur de service en vigueur dans l'année en cours, pas encore arrêtée.

    La fédération fixe cette valeur au 1er novembre ; la règle du dépôt retient
    celle du 31 décembre. L'année qui suit la dernière décision a donc une valeur
    OPPOSABLE — celle reconduite depuis le 1er janvier — sans être arrêtée.

    Ne rien écrire n'était pas neutre : faute de barème, le modèle prolongeait la
    dernière valeur par les PRIX, servant 1,46378 € pour 2026 là où la fédération
    publie un gel à 1,4386 € jusqu'au 1er novembre 2026. Entre inventer une
    décision et reconduire celle qui est en vigueur, la seconde a une source —
    d'où un niveau en retrait, et non une absence.
    """
    charge = _lire_json("agirc_arrco_valeurs_point.json",
                        "scripts/fetch/agirc_arrco_valeurs_point.py")
    return {
        tuple(cle.split("|")): valeur
        for cle, valeur in sorted(charge.get("serie_en_cours", {}).items())
    }


def source_valeurs_point_erafp() -> dict[tuple, float]:
    """Valeurs du point du RAFP, publiées par l'ERAFP qui les fixe.

    Son conseil d'administration arrête chaque année la valeur d'acquisition et
    la valeur de service : c'est le producteur, et la transcription d'OpenFisca
    s'efface devant lui — elle répétait d'ailleurs en 2021 la valeur
    d'acquisition de 2020, ce qui majorait de 0,4 % les points achetés cette
    année-là, et elle s'arrêtait cinq ans avant le tableau publié.
    """
    return {
        tuple(cle.split("|")): valeur
        for cle, valeur in sorted(
            _serie_json("erafp_valeurs_point.json",
                        "scripts/fetch/erafp_valeurs_point.py").items()
        )
    }


def source_valeurs_point() -> dict[tuple, float]:
    """Salaires de référence, valeurs de service et taux d'appel, par régime.

    Ces trois grandeurs suffisent à reconstituer exactement une pension en
    points : la cotisation d'une année divisée par le salaire de référence et
    par le taux d'appel donne les points acquis, que la valeur de service
    convertit en rente à la liquidation.

    Ce que les producteurs publient eux-mêmes est retiré d'ici — la Caisse des
    dépôts pour l'Ircantec, la fédération pour l'Agirc-Arrco, l'ERAFP pour le
    RAFP : deux contrôles ne doivent pas se disputer les mêmes lignes, et le
    producteur l'emporte sur la transcription. Si l'un de ces fichiers manque,
    OpenFisca reprend sa couverture — au niveau ``haute``, comme il se doit.
    """
    valeurs = _cles_points("serie", substituees=False)
    producteurs: set[tuple] = set()
    for source in (source_valeurs_point_ircantec, source_valeurs_point_agirc_arrco,
                   source_valeurs_point_agirc_arrco_en_cours,
                   source_valeurs_point_erafp):
        try:
            producteurs |= set(source())
        except SourceAbsente:
            continue
    return {cle: valeur for cle, valeur in valeurs.items() if cle not in producteurs}


def source_valeurs_point_substituees() -> dict[tuple, float]:
    """Valeurs de l'UNIRS servant de point Arrco avant l'unification de 1999.

    Publiées, mais pour une autre caisse que celle que le modèle appelle
    « arrco » — d'où un niveau en retrait, que la fédération publie ces valeurs
    ou non. Ce qui est certifié, c'est le barème de l'UNIRS, qui figure sous ce
    nom dans le fichier ; la SUBSTITUTION, elle, est une décision de
    modélisation, et aucune source ne la porte.

    La valeur, en revanche, est celle du producteur dès qu'il la publie : ce
    serait écrire le même franc de deux façons que de laisser la ligne
    ``arrco`` sur l'arrondi d'OpenFisca quand la ligne ``unirs`` porte la
    conversion exacte.
    """
    substituees = _cles_points("serie", substituees=True)
    try:
        producteur = source_valeurs_point_agirc_arrco()
    except SourceAbsente:
        return substituees
    return {
        cle: producteur.get(("unirs", *cle[1:]), valeur)
        for cle, valeur in substituees.items()
    }


def source_valeurs_point_cnbf() -> dict[tuple, float]:
    """Valeurs du point des avocats, dans les barèmes annuels de la CNBF.

    La caisse est le producteur : c'est son propre barème, publié chaque
    janvier. Aucune autre source ne les porte — ni OpenFisca, ni les barèmes
    IPP, ni la législation consolidée, dépouillée deux fois pour s'en assurer.
    """
    return {
        tuple(cle.split("|")): valeur
        for cle, valeur in sorted(
            _serie_json("cnbf_baremes.json", "scripts/fetch/cnbf_baremes.py").items()
        )
    }


def source_valeurs_point_cnavpl() -> dict[tuple, float]:
    """Valeur du point des professions libérales, dans les recueils CNAVPL.

    La caisse est le producteur, et la seule à publier ce nombre : le décret
    annuel ne fixe qu'un coefficient de revalorisation, jamais le montant.
    """
    return {
        tuple(cle.split("|")): valeur
        for cle, valeur in sorted(
            _serie_json("cnavpl_recueils.json", "scripts/fetch/cnavpl_recueils.py").items()
        )
    }


def source_valeurs_point_msa() -> dict[tuple, float]:
    """Valeur de service du point de la complémentaire agricole, dans le code rural.

    Fixée chaque année par décret, à l'article D. 732-166, dont la base LEGI de
    la DILA garde toutes les versions datées. C'est la publication officielle,
    non une transcription : le niveau est donc celui du producteur.
    """
    return {
        tuple(cle.split("|")): valeur
        for cle, valeur in sorted(
            _serie_json("dila_legi_msa.json", "scripts/fetch/dila_legi_msa.py").items()
        )
    }


def source_minimum_contributif() -> dict[tuple, float]:
    """Minimum contributif, minimum majoré et plafond, dans le code.

    `docs/limites.md` a longtemps écrit que ces montants ne figuraient dans
    aucune source machine ouverte, et qu'il n'y avait donc pas de chemin de
    certification à écrire. C'était la même erreur que pour la MSA : la donnée
    est dans la loi, il fallait chercher par le NUMÉRO D'ARTICLE. D. 351-2-1
    du code de la sécurité sociale porte les deux montants, D. 173-21-0-0-1 le
    plafond d'écrêtement. La base LEGI en garde toutes les versions datées.
    """
    return {
        tuple(cle.split("|")): valeur
        for cle, valeur in sorted(
            _serie_json("dila_legi_minimum_contributif.json",
                        "scripts/fetch/dila_legi_minimum_contributif.py").items()
        )
    }


def source_point_indice() -> dict[tuple, float]:
    """Traitement annuel d'un point d'indice de la fonction publique.

    Une seule grandeur en dépend, mais elle est décisive : la référence du
    MINIMUM GARANTI, que l'article L. 17 du code des pensions fixe au
    traitement de l'indice majoré 227 au 1er janvier 2004. Le recoupement se
    fait tout seul — 227 × 52,7558 = 11 975,57 € par an, soit les 997,96 € par
    mois que publie le Service des retraites de l'État.

    Transcription tierce du Journal officiel par OpenFisca-France : niveau
    `haute`, jamais `certifiee`. Elle ne garde que ce que le *Journal officiel*
    lui-même ne donne pas — les années d'avant 1996, dont la chaîne des versions
    de l'article 3 du décret de 1985 est incomplète dans le dump LEGI.
    """
    serie = _serie_json("openfisca_point_indice.json",
                        "scripts/fetch/openfisca_point_indice.py")
    try:
        journal_officiel = set(source_point_indice_jo())
    except SourceAbsente:
        journal_officiel = set()
    return {(annee,): valeur for annee, valeur in sorted(serie.items())
            if (annee,) not in journal_officiel}


def source_point_indice_jo() -> dict[tuple, float]:
    """Le même point d'indice, lu dans le décret qui le fixe.

    Article 3 du décret n° 85-1148 du 24 octobre 1985, dont la base LEGI garde
    chaque version datée : « La valeur annuelle du traitement […] afférents à
    l'indice 100 majoré […] est fixée à 5 907,34 € ». C'est le *Journal
    officiel*, non sa transcription — et la confrontation a corrigé deux
    arrondis, dont celui de 2002, que le décret de bascule fixe à 5 181,75 €
    quand la conversion des 33 990 F donne 5 181,74 €.
    """
    serie = _serie_json("dila_legi_point_indice.json",
                        "scripts/fetch/dila_legi_point_indice.py")
    return {(annee,): valeur for annee, valeur in sorted(serie.items())}


def source_smic() -> dict[tuple, float]:
    """SMIC horaire en vigueur au 1er janvier — décrets de relèvement, base LEGI.

    Le SMIC n'est pas fixé par un article de code mais par un décret annuel, et
    c'est le *Journal officiel* qui le porte : la transcription d'OpenFisca, qui
    tenait lieu de source, plafonnait à ``haute``. Les années dont le décret
    manque au dump ne sont pas rendues — voir le récupérateur, qui refuse de
    combler un trou par la valeur de l'année d'avant.
    """
    serie = _serie_json("dila_legi_smic.json", "scripts/fetch/dila_legi_smic.py")
    return {(annee,): valeur for annee, valeur in sorted(serie.items())}


def _parametres_retraite() -> dict[str, float]:
    return _serie_json("dila_legi_parametres_retraite.json",
                       "scripts/fetch/dila_legi_parametres_retraite.py")


def _table_legi(prefixe: str) -> dict[tuple, float]:
    """Une des tables par génération lues dans la loi, mise en forme de clés.

    La clé de génération peut porter des décimales : deux textes coupent une
    génération en cours d'année — le 1er juillet 1951, le 1er septembre 1961 —,
    et le récupérateur rend alors un segment par valeur, `1951.5` désignant le
    premier juillet. Le tri lisait ces clés avec ``int`` et les refusait.
    """
    return {
        (cle.split("|")[1],): valeur
        for cle, valeur in sorted(_parametres_retraite().items(),
                                  key=lambda kv: float(kv[0].split("|")[1]))
        if cle.startswith(f"{prefixe}|")
    }


def source_age_ouverture() -> dict[tuple, float]:
    """Âge d'ouverture des droits par génération — D. 161-2-1-9.

    `docs/limites.md` tenait ces tables pour hors de portée : « Légifrance
    expose une API, mais elle demande une clé et renvoie du texte juridique, non
    des paramètres. » Les deux moitiés de la phrase étaient vraies et la
    conclusion fausse. La base LEGI de la DILA est ouverte, et le texte
    juridique EST la table : « Soixante-deux ans et trois mois pour les assurés
    nés entre le 1er septembre 1961 et le 31 décembre 1961 inclus. »
    """
    return _table_legi("age_ouverture")


def source_duree_requise() -> dict[tuple, float]:
    """Durée d'assurance requise par génération — L. 161-17-3."""
    return _table_legi("duree_requise")


def source_duree_requise_decrets() -> dict[tuple, float]:
    """Durée requise des générations 1953 à 1957, dans leurs décrets.

    L'article L. 161-17-3 ne porte la table qu'à compter de la génération
    1958 ; celles d'avant relèvent de décrets pris sous l'ancien article
    L. 351-1, que `docs/limites.md` tenait pour hors de portée parce que « LEGI
    ne les expose sous aucun numéro d'article ». Ils n'ont pas de numéro utile,
    mais ils ont une phrase : « […] sont fixées à 166 trimestres pour les
    assurés nés en 1955 ». Quatre décrets couvrent 1953 à 1957.
    """
    serie = _serie_json("dila_legi_duree_requise.json",
                        "scripts/fetch/dila_legi_duree_requise.py")
    return {(generation,): valeur for generation, valeur in sorted(serie.items())}


def source_coefficient_minoration() -> dict[tuple, float]:
    """Coefficient de minoration par génération — R. 351-27 II."""
    return _table_legi("coefficient_minoration")


def source_duree_proratisation() -> dict[tuple, float]:
    """Durée maximale prise en compte par la proratisation — R. 351-6 II.

    À ne pas confondre avec la durée REQUISE, et le modèle les a confondues :
    la loi de 1993 a fait monter la première de deux trimestres par génération
    sur les seules générations 1944-1948, quand la seconde montait de dix
    trimestres sur dix générations. Un assuré né en 1945 se voyait diviser par
    160 là où l'article divise par 154.

    L'article couvre les générations d'avant 1944 à 1947 et renvoie au-delà à
    la durée du troisième alinéa de L. 351-1 : la ligne 1948 de la table du
    dépôt est cette jonction, et reste hors de portée de la certification.
    """
    return _table_legi("duree_proratisation")


def source_annees_salaire_reference() -> dict[tuple, float]:
    """Années retenues au salaire annuel moyen, par génération — R. 351-29-1.

    Dix années jusqu'à la génération 1933, vingt-cinq à partir de 1948, et une
    de plus par génération entre les deux. Le paramètre se lit à l'année de
    NAISSANCE : le lire à l'année de liquidation, comme le faisait le modèle,
    opposait vingt-cinq années à des générations auxquelles la loi n'en a jamais
    opposé plus de dix.
    """
    return _table_legi("annees_salaire_reference")


def source_heures_par_trimestre() -> dict[tuple, float]:
    """Heures de SMIC à cotiser pour valider un trimestre — R. 351-9.

    200 heures depuis 1972, 150 depuis 2014. C'est ce qui décide du nombre de
    trimestres qu'une année de petit salaire valide, donc de la décote.
    """
    return _table_legi("heures_par_trimestre")


def _decote_fonction_publique(mesure: str) -> dict[tuple, float]:
    serie = _serie_json("dila_legi_decote_fonction_publique.json",
                        "scripts/fetch/dila_legi_decote_fonction_publique.py")
    return {
        (cle.split("|")[1],): valeur
        for cle, valeur in sorted(serie.items())
        if cle.startswith(f"{mesure}|")
    }


def source_decote_fp_coefficient() -> dict[tuple, float]:
    """Coefficient de minoration de la fonction publique, année par année.

    Article 66 III de la loi du 21 août 2003, qui déroge à l'article L. 14 du
    code des pensions le temps de la montée en charge : un huitième de point
    par trimestre en 2006, un et quart à compter de 2015. Opposer la cible à
    une liquidation de 2008 décote dix fois trop.
    """
    return _decote_fonction_publique("coefficient")


def source_decote_fp_trimestres() -> dict[tuple, float]:
    """Trimestres retranchés à la limite d'âge, année par année.

    L'âge d'annulation de la décote n'est pas un âge en propre dans la fonction
    publique : c'est la limite d'âge du grade, diminuée de seize trimestres en
    2006 et d'un seul en 2019. Le même tableau les porte.
    """
    return _decote_fonction_publique("trimestres_avant_limite")


def _minimum_garanti(mesure: str) -> dict[tuple, float]:
    serie = _serie_json("dila_legi_minimum_garanti.json",
                        "scripts/fetch/dila_legi_minimum_garanti.py")
    return {
        (cle.split("|")[1],): valeur
        for cle, valeur in sorted(serie.items())
        if cle.startswith(f"{mesure}|")
    }


def source_minimum_garanti_indice() -> dict[tuple, float]:
    """Indice majoré de référence du minimum garanti, 2004-2013.

    Article 66 V de la loi du 21 août 2003, qui déroge aux a et b de l'article
    L. 17 du code des pensions le temps de la montée en charge. C'est le même
    article que celui de la décote de la fonction publique, un tableau plus bas.
    """
    return _minimum_garanti("indice_majore")


def source_minimum_garanti_part() -> dict[tuple, float]:
    """Fraction du traitement de référence servie à quinze ans de services."""
    return _minimum_garanti("part_15_ans")


def source_minimum_garanti_points_15_30() -> dict[tuple, float]:
    """Points gagnés par trimestre de services de quinze ans au seuil suivant."""
    return _minimum_garanti("points_15_30")


def source_minimum_garanti_points_30_40() -> dict[tuple, float]:
    """Points gagnés par trimestre au-delà de ce seuil, jusqu'à quarante ans."""
    return _minimum_garanti("points_30_40")


def source_minimum_garanti_seuil() -> dict[tuple, float]:
    """Borne haute de la première pente, en trimestres.

    La loi l'écrit en toutes lettres et parfois en demi-années : « Vingt-cinq
    ans et demi » fait 102 trimestres.
    """
    return _minimum_garanti("trimestres_seuil")


def source_carriere_longue() -> dict[tuple, float]:
    """Âge de départ anticipé par borne d'entrée dans la vie active.

    Articles L. 351-1-1 et D. 351-1-1, DERNIÈRE VERSION seulement : les portes
    de 2004 et de 2012 sont dans des versions abrogées que le récupérateur ne
    remonte pas, et restent des transcriptions. Ne sont donc confrontées que les
    quatre bornes en vigueur depuis le 1er septembre 2023 — 16, 18, 20 et 21
    ans pour 58, 60, 62 et 63 ans.
    """
    brut = _lire_json("dila_legi_parametres_retraite.json",
                      "scripts/fetch/dila_legi_parametres_retraite.py")
    portes = {}
    for porte in brut.get("carriere_longue", []):
        annee = int(str(porte["entree_en_vigueur"])[:4])
        portes[(str(annee), str(int(porte["age_debut_maximum"])))] = \
            float(porte["age_depart"])
    return portes


def _point_insee() -> dict[str, dict[int, float]]:
    """Valeur de service du point Agirc, Arrco et Agirc-Arrco, au 31 décembre.

    L'INSEE diffuse ces barèmes en série mensuelle. La convention du dépôt
    retient la valeur en vigueur au 31 décembre : c'est donc l'observation de
    décembre qu'on garde, et une année dont il manque n'est pas reconstituée.
    """
    par_regime: dict[str, dict[int, float]] = {}
    for nom, regime in (
        ("point_arrco", "arrco"),
        ("point_agirc", "agirc"),
        ("point_agirc_arrco", "agirc_arrco"),
    ):
        par_regime[regime] = {
            int(periode[:4]): valeur
            for periode, valeur in sorted(_observations(nom).items())
            if periode[5:7] == "12"
        }
    return par_regime


def source_valeurs_point_insee() -> dict[tuple, float]:
    """Ce que l'INSEE ajoute aux valeurs du point d'OpenFisca, et lui seul.

    L'INSEE n'est pas le producteur de ces barèmes — l'Agirc-Arrco l'est — si
    bien que cette série ne prime pas sur la transcription là où les deux se
    recouvrent : ``controle_vraisemblance_point_insee`` les y confronte, et
    c'est tout. Ce qu'elle apporte, c'est la fin de la série : OpenFisca
    s'arrête à sa dernière année publiée, l'INSEE continue.

    Elle s'efface AUSSI devant le producteur lui-même, depuis que la fédération
    Agirc-Arrco est lue directement. Sans cela, l'INSEE reprenait la valeur de
    service de 2025 — la seule qu'OpenFisca n'ait pas — et la reversait au
    niveau ``haute`` après que le producteur l'avait certifiée : la dernière
    certification écrite gagne, et c'était la moins bien placée.
    """
    connues = set(_cles_points("serie", substituees=False))
    for source in (source_valeurs_point_agirc_arrco,
                   source_valeurs_point_agirc_arrco_en_cours):
        try:
            connues |= set(source())
        except SourceAbsente:
            continue
    return {
        (regime, str(annee), "valeur_service"): valeur
        for regime, valeurs in sorted(_point_insee().items())
        for annee, valeur in sorted(valeurs.items())
        if (regime, str(annee), "valeur_service") not in connues
    }


def source_valeurs_point_texte() -> dict[tuple, float]:
    """Ce qu'aucune transcription machine ne porte, saisi depuis le texte."""
    charge = _charge_points()
    return {tuple(cle.split("|")): valeur
            for cle, valeur in sorted(charge["complements"].items())}


def source_plafond_ancien() -> dict[tuple, float]:
    """Plafond de la Sécurité sociale d'avant 2002, par OpenFisca-France.

    Bornée à 2001 : au-delà, le plafond publié par l'INSEE est une source
    primaire, qui l'emporte. Les années 2002-2026 servent de contrôle croisé
    entre les deux, sans être versées ici.
    """
    serie = _serie_json("openfisca_plafond.json", "scripts/fetch/openfisca_plafond.py")
    return {
        (annee,): round(valeur)
        for annee, valeur in sorted(serie.items())
        if int(annee) < 2002
    }


def _contributions_employeur(nom: str) -> dict[str, float]:
    """Une des quatre séries de contribution employeur publique."""
    chemin = BRUT / "contribution_employeur_public.json"
    if not chemin.exists():
        raise SourceAbsente(
            f"{chemin} absent "
            "(lancer scripts/fetch/contribution_employeur_public.py)"
        )
    return json.loads(chemin.read_text(encoding="utf-8"))["series"][nom]


def source_employeur_etat_appele() -> dict[tuple, float]:
    """Contribution employeur de l'État appelée depuis 2006, agents civils.

    Fiche « Historique des taux de cotisations » du Service des retraites de
    l'État, qui appelle la cotisation : source PRIMAIRE, donc certifiable. Le
    script de récupération la recoupe année par année contre la transcription
    OpenFisca des mêmes décrets.
    """
    return {
        (annee, "fonction_publique_etat"): taux
        for annee, taux in sorted(
            _contributions_employeur("fonction_publique_etat_explicite").items())
    }


def source_employeur_etat_implicite() -> dict[tuple, float]:
    """Taux de cotisation employeur IMPLICITE de l'État, 1995-2005.

    Reconstitution publiée par l'annexe « pensions » au projet de loi de
    finances pour 2011, transcrite par OpenFisca. Deux raisons de ne pas
    dépasser `haute` : ce n'est pas le producteur qui la sert, et ce n'est pas
    un taux appelé mais une simulation du compte du régime, sur un périmètre
    plus étroit que celui du CAS.
    """
    return {
        (annee, "fonction_publique_etat"): taux
        for annee, taux in sorted(
            _contributions_employeur("fonction_publique_etat_implicite").items())
    }


def source_employeur_public_texte() -> dict[tuple, float]:
    """Taux employeur qu'aucune transcription machine ne porte, saisis du décret.

    Le décret n° 2025-86 du 30 janvier 2025 programme quatre marches de trois
    points pour la CNRACL — 34,65 % en 2025, puis 37,65 %, 40,65 % et 43,65 % —
    quand la transcription d'OpenFisca s'arrête à la première. Les ignorer
    revenait à prolonger le taux de 2025 au niveau ``estimee``, c'est-à-dire à
    ne pas voir une hausse déjà publiée au *Journal officiel*.

    Saisies depuis le texte, ni transcrites par un tiers ni recoupées : niveau
    ``moyenne``, comme le taux d'appel Agirc-Arrco.
    """
    charge = _lire_json("contribution_employeur_public.json",
                        "scripts/fetch/contribution_employeur_public.py")
    couvertes = _annees_cnracl_du_journal_officiel()
    return {
        (annee, regime): taux
        for cle, taux in sorted(charge.get("complements", {}).items())
        for regime, annee in [cle.split("|")]
        if (annee, regime) not in couvertes
    }


def source_employeur_cnracl_jo() -> dict[tuple, float]:
    """Contribution employeur à la CNRACL, lue dans le décret qui la fixe.

    Article 5 II du décret n° 91-613 du 28 juin 1991, dont la base LEGI garde
    vingt versions datées : « Le taux de la contribution sur les traitements
    […] est fixé à 31,65 % ». Elle couvre 1993 à 2028 — y compris les trois
    marches que le décret du 30 janvier 2025 programme jusqu'en 2028, et que le
    dépôt tenait pour une saisie.

    Le I du même article porte la RETENUE de l'agent, et la contribution
    supplémentaire qui suit le II est un autre prélèvement : ni l'un ni l'autre
    n'entre ici.
    """
    serie = _serie_json("dila_legi_cnracl.json", "scripts/fetch/dila_legi_cnracl.py")
    return {(annee, "cnracl"): taux for annee, taux in sorted(serie.items())}


def _annees_cnracl_du_journal_officiel() -> set[tuple]:
    try:
        return set(source_employeur_cnracl_jo())
    except SourceAbsente:
        return set()


def source_employeur_cnracl() -> dict[tuple, float]:
    """Contribution employeur à la CNRACL, depuis 1948.

    La fonction publique territoriale et hospitalière n'a jamais eu le problème
    de l'État : ses employeurs cotisent à une caisse, dont le taux est fixé par
    décret depuis 1947. Transcription OpenFisca des décrets et des barèmes de la
    Caisse des dépôts : niveau `haute`.

    Elle ne garde que ce que le *Journal officiel* ne rend pas — les années
    d'avant 1993, dont les taux sont dans les décrets abrogés que celui de 1991
    a remplacés.
    """
    couvertes = _annees_cnracl_du_journal_officiel()
    return {
        (annee, "cnracl"): taux
        for annee, taux in sorted(_contributions_employeur("cnracl").items())
        if (annee, "cnracl") not in couvertes
    }


def source_employeur_sncf() -> dict[tuple, float]:
    """Contribution employeur de la SNCF, T1 + T2, 2007-2018.

    T1 est calée sur ce que coûteraient les mêmes salariés au régime général et
    aux complémentaires du privé ; T2 finance les droits spécifiques du régime
    et son déséquilibre démographique. Leur somme est ce que l'entreprise verse.
    """
    return {
        (annee, "sncf"): taux
        for annee, taux in sorted(_contributions_employeur("sncf").items())
    }


# ---------------------------------------------------------------------------
# Contrôles de certification
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Certification:
    """Confrontation d'une série de référence à sa source."""

    nom: str
    chemin: Path
    cles: tuple[str, ...]
    colonne: str
    source: Callable[[], dict[tuple, float]]
    origine: str
    decimales: int
    tolerance: float
    unite: str = ""
    #: colonnes fixes à renseigner sur les lignes créées de toutes pièces
    gabarit: dict[str, str] = field(default_factory=dict)
    #: Niveau accordé aux valeurs confrontées. ``certifiee`` suppose que la
    #: source soit le producteur de la donnée ; une transcription tierce, même
    #: sourcée et reprise automatiquement, ne va pas au-delà de ``haute``.
    niveau: str = "certifiee"
    #: en-tête à écrire si le fichier de référence n'existe pas encore
    entete: tuple[str, ...] = ()
    #: Source d'APPOINT : elle ne comble que ce que les autres ne couvrent pas,
    #: et peut donc légitimement n'avoir rien à dire. Sans ce drapeau, une telle
    #: source vide serait indiscernable d'un récupérateur cassé — et le contrôle
    #: qui exige qu'une série certifiée apporte au moins une valeur doit rester
    #: sévère pour toutes les autres.
    complementaire: bool = False

    def format(self, valeur: float) -> str:
        return f"{valeur:.{self.decimales}f}" if self.decimales else f"{valeur:.0f}"

    def confronter(self, appliquer: bool) -> tuple[list[str], dict | None]:
        """Confronte la série à sa source.

        Rend les messages et la trace à consigner : un dictionnaire vide quand
        il n'y a rien à consigner, et ``None`` quand la trace existante doit au
        contraire être RETIRÉE du journal.
        """
        try:
            attendu = self.source()
        except SourceAbsente as erreur:
            return [f"IGNORÉ  {self.nom} : {erreur}"], {}

        if not attendu and self.complementaire:
            # ``None`` et non ``{}`` : le journal se complète d'ordinaire, mais
            # une trace qui affirme une certification qui n'a plus lieu doit
            # être RETIRÉE, pas conservée.
            return [
                f"RIEN    {self.nom} : {self.origine} n'ajoute rien, tout ce "
                "qu'elle couvre l'est déjà par une source mieux placée"
            ], None

        if not self.chemin.exists():
            if not appliquer:
                return [
                    f"ABSENT  {self.nom} : {self.chemin.name} n'existe pas encore, "
                    f"{len(attendu)} valeurs à créer — relancer avec --appliquer"
                ], {}
            self.chemin.parent.mkdir(parents=True, exist_ok=True)
            champs = [*self.cles, self.colonne, "fiabilite"]
            self.chemin.write_text(
                "\n".join(self.entete) + "\n" + ",".join(champs) + "\n",
                encoding="utf-8",
            )

        commentaires, champs, lignes = _lire(self.chemin)
        par_cle = {tuple(l[c] for c in self.cles): l for l in lignes}

        identiques, corrigees, ajoutees, ecarts = 0, [], [], []
        for cle, valeur in attendu.items():
            texte = self.format(valeur)
            ligne = par_cle.get(cle)
            if ligne is None:
                ajoutees.append(cle)
                if appliquer:
                    neuve = {c: "" for c in champs}
                    neuve.update(self.gabarit)
                    neuve.update(dict(zip(self.cles, cle)))
                    neuve[self.colonne] = texte
                    neuve["fiabilite"] = self.niveau
                    lignes.append(neuve)
                continue
            ancienne = float(ligne[self.colonne])
            if abs(ancienne - valeur) > self.tolerance:
                corrigees.append((cle, ancienne, valeur, ligne["fiabilite"]))
                ecarts.append(
                    f"ÉCART   {self.nom} {'/'.join(cle)} : référence "
                    f"{self.format(ancienne)}{self.unite}, source {texte}{self.unite} "
                    f"(niveau {ligne['fiabilite']})"
                )
            else:
                identiques += 1
            if appliquer:
                ligne[self.colonne] = texte
                ligne["fiabilite"] = self.niveau

        if appliquer:
            lignes.sort(key=lambda l: tuple(
                (int(l[c]) if c == "annee"
                 else float(l[c]) if c == "generation" else l[c])
                for c in self.cles
            ))
            _ecrire(self.chemin, commentaires, champs, lignes)

        verbe = ("versées au niveau " + self.niveau) if appliquer else "confrontables"
        messages = [
            f"OK      {self.nom} : {len(attendu)} valeurs {verbe} depuis {self.origine} "
            f"— {identiques} identiques, {len(corrigees)} corrigées, "
            f"{len(ajoutees)} ajoutées"
        ]
        messages.extend(ecarts[:12])
        if len(ecarts) > 12:
            messages.append(f"        … et {len(ecarts) - 12} autres écarts")

        journal = {
            "source": self.origine,
            "niveau": self.niveau,
            # Deux contrôles peuvent porter sur les mêmes LIGNES et des COLONNES
            # différentes — la décote de la fonction publique, dont un article
            # fixe le coefficient et l'âge d'annulation dans le même tableau.
            # Sans le nom de la colonne, on ne saurait pas si deux traces
            # comptent deux fois les mêmes lignes.
            "colonne": self.colonne,
            "valeurs": len(attendu),
            "identiques": identiques,
            "corrigees": len(corrigees),
            "ajoutees": len(ajoutees),
            "empreinte": hashlib.sha256(
                "".join(f"{'/'.join(c)}={self.format(v)};"
                        for c, v in attendu.items()).encode()
            ).hexdigest()[:16],
        }
        return messages, journal


CERTIFICATIONS = (
    Certification(
        nom="inflation",
        chemin=REFERENCE / "macro" / "ipc_annuel.csv",
        cles=("annee",),
        colonne="variation",
        source=source_inflation,
        origine="INSEE BDM, idbanks 000008965 et 001764363",
        decimales=5,
        tolerance=5e-4,
        unite="",
    ),
    Certification(
        nom="salaire_moyen",
        chemin=REFERENCE / "macro" / "salaire_moyen.csv",
        cles=("annee",),
        colonne="variation_nominale",
        source=source_salaire_moyen,
        origine="INSEE BDM, idbanks 011785411 et 011793486",
        decimales=5,
        tolerance=5e-4,
    ),
    Certification(
        nom="masse_salariale",
        chemin=REFERENCE / "macro" / "masse_salariale.csv",
        cles=("annee",),
        colonne="variation_nominale",
        source=source_masse_salariale,
        origine="INSEE BDM, idbank 011785411",
        decimales=5,
        tolerance=5e-4,
        entete=(
            "# Masse salariale — variation annuelle nominale, ensemble de l'économie",
            "# source_id: insee_bdm_masse_salariale (comptes nationaux annuels, base 2020)",
            "# unite: taux de variation annuel nominal, en fraction",
            "# fiabilite:",
            "#   certifiee (1950-2025) : salaires et traitements bruts (D11, total des",
            "#             branches, idbank 011785411) pris EN NIVEAU, recontrôlés par",
            "#             scripts/verifier_donnees.py.",
            "#   estimee   (1930-1949) : les comptes nationaux ne remontent pas avant",
            "#             1949, et aucune série d'emploi salarié ne couvre la guerre.",
            "#             Ces vingt années reprennent donc la variation du SALAIRE",
            "#             MOYEN, c'est-à-dire supposent l'emploi salarié constant.",
            "#             L'hypothèse est fausse — l'emploi s'est effondré puis",
            "#             reconstitué — mais elle est la seule qui n'invente rien, et",
            "#             la fiabilité `estimee` se propage jusqu'au résultat.",
            "#",
            "# C'est l'assiette des cotisations : le taux de rendement qu'un système en",
            "# répartition peut servir sans changer son taux de cotisation (Samuelson",
            "# 1958, Aaron 1966). La différence avec salaire_moyen.csv est exactement la",
            "# croissance de l'emploi salarié : ×2,14 sur 1950-2025.",
            "#",
            "# Ne pas modifier les années certifiées à la main : elles seraient écrasées",
            "# au prochain scripts/verifier_donnees.py --appliquer.",
        ),
    ),
    Certification(
        nom="pib_nominal",
        chemin=REFERENCE / "macro" / "pib_nominal.csv",
        cles=("annee",),
        colonne="variation_nominale",
        source=source_pib_nominal,
        origine="INSEE BDM, idbank 011779992",
        decimales=5,
        tolerance=5e-4,
        entete=(
            "# Produit intérieur brut — variation annuelle nominale, France",
            "# source_id: insee_bdm_pib (comptes nationaux annuels, base 2020)",
            "# unite: taux de variation annuel nominal, en fraction",
            "# fiabilite:",
            "#   certifiee (1950-2025) : PIB approche produit, prix courant",
            "#             (idbank 011779992), recontrôlé par",
            "#             scripts/verifier_donnees.py.",
            "#   estimee   (1930-1949) : les comptes nationaux ne remontent pas avant",
            "#             1949. Ces vingt années reprennent la variation du salaire",
            "#             moyen, faute de mieux — même convention que",
            "#             masse_salariale.csv, et même réserve.",
            "#",
            "# Sert la variante « à l'italienne » de l'indexation : l'Italie revalorise",
            "# les comptes notionnels sur la moyenne géométrique du PIB nominal des cinq",
            "# dernières années. Le LISSAGE est appliqué par le moteur, pas ici : cette",
            "# série est la variation annuelle brute, seule grandeur que l'INSEE publie",
            "# et donc seule grandeur certifiable.",
            "#",
            "# Ne pas modifier les années certifiées à la main : elles seraient écrasées",
            "# au prochain scripts/verifier_donnees.py --appliquer.",
        ),
    ),
    Certification(
        nom="productivite",
        chemin=REFERENCE / "macro" / "productivite.csv",
        cles=("annee",),
        colonne="variation_reelle",
        source=source_productivite,
        origine="INSEE BDM, idbanks 011785223 et 011793334",
        decimales=5,
        tolerance=5e-4,
    ),
    Certification(
        nom="plafond",
        chemin=REFERENCE / "macro" / "plafond_securite_sociale.csv",
        cles=("annee",),
        colonne="pass_eur",
        source=source_plafond,
        origine="INSEE BDM, idbank 000822494",
        decimales=0,
        tolerance=0.5,
        unite=" €",
    ),
    Certification(
        nom="plafond_ancien",
        chemin=REFERENCE / "macro" / "plafond_securite_sociale.csv",
        cles=("annee",),
        colonne="pass_eur",
        source=source_plafond_ancien,
        origine="OpenFisca-France, plafond_securite_sociale_annuel.yaml",
        decimales=0,
        tolerance=0.5,
        unite=" €",
        niveau="haute",
    ),
    Certification(
        nom="esperances_vie",
        chemin=REFERENCE / "mortalite" / "esperances_vie.csv",
        cles=("annee", "sexe", "mesure"),
        colonne="valeur",
        source=source_esperances,
        origine="INSEE BDM (e0, e60) et OCDE DSD_HEALTH_STAT@DF_LE (e65)",
        decimales=2,
        tolerance=0.05,
        unite=" ans",
    ),
    Certification(
        nom="valeurs_point",
        chemin=REFERENCE / "regimes" / "valeurs_point.csv",
        cles=("regime", "annee", "mesure"),
        colonne="valeur",
        source=source_valeurs_point,
        origine="OpenFisca-France-Pension, paramètres des régimes en points",
        decimales=6,
        tolerance=5e-7,
        niveau="haute",
        entete=(
            "# Valeurs d'achat et de service du point, régime par régime",
            "# source_id: openfisca_points (Agirc depuis 1947, Ircantec depuis 1949)",
            "#",
            "# mesure :",
            "#   salaire_reference : prix d'achat du point, en euros courants de l'année.",
            "#                       cotisation / (taux_appel × salaire_reference) = points acquis",
            "#   valeur_service    : rente annuelle servie par un point, euros courants",
            "#   taux_appel        : écart entre ce qui est prélevé et ce qui ouvre des",
            "#                       droits. 1,25 depuis 1995 : cotiser 125 € n'acquiert",
            "#                       que 100 € de points.",
            "#",
            "# Règle annuelle : valeur en vigueur au 31 décembre de l'année. Le salaire",
            "# de référence change au 1er janvier, la valeur de service au 1er avril",
            "# autrefois et au 1er novembre aujourd'hui.",
            "#",
            "# fiabilite :",
            "#   haute   : transcription OpenFisca du texte de la circulaire",
            "#   moyenne : valeurs de l'UNIRS tenant lieu de point Arrco avant son",
            "#             unification de 1999, ou valeur saisie depuis le texte légal",
            "#",
            "# Repère de contrôle : Agirc-Arrco 2025, salaire de référence 20,1877 €,",
            "# valeur de service 1,4386 €, taux d'appel 1,27 — soit un rendement",
            "# instantané de 5,61 %, la valeur que publie le régime.",
            "#",
            "# Fichier écrit par scripts/verifier_donnees.py --appliquer : ne pas",
            "# modifier à la main.",
        ),
    ),
    Certification(
        nom="valeurs_point_ircantec",
        chemin=REFERENCE / "regimes" / "valeurs_point.csv",
        cles=("regime", "annee", "mesure"),
        colonne="valeur",
        source=source_valeurs_point_ircantec,
        origine="Caisse des dépôts, barèmes Ircantec (IRC_BAR_01 et IRC_BAR_02)",
        decimales=6,
        tolerance=5e-7,
    ),
    Certification(
        nom="valeurs_point_agirc_arrco",
        chemin=REFERENCE / "regimes" / "valeurs_point.csv",
        cles=("regime", "annee", "mesure"),
        colonne="valeur",
        source=source_valeurs_point_agirc_arrco,
        origine="Fédération Agirc-Arrco, compilation des valeurs de point "
                "(régime unifié, Agirc, Arrco et UNIRS)",
        decimales=6,
        tolerance=5e-7,
    ),
    Certification(
        nom="valeurs_point_agirc_arrco_en_cours",
        chemin=REFERENCE / "regimes" / "valeurs_point.csv",
        cles=("regime", "annee", "mesure"),
        colonne="valeur",
        source=source_valeurs_point_agirc_arrco_en_cours,
        origine="Fédération Agirc-Arrco, valeur en vigueur dans l'année en cours",
        decimales=6,
        tolerance=5e-7,
        niveau="haute",
    ),
    Certification(
        nom="valeurs_point_rafp",
        chemin=REFERENCE / "regimes" / "valeurs_point.csv",
        cles=("regime", "annee", "mesure"),
        colonne="valeur",
        source=source_valeurs_point_erafp,
        origine="ERAFP, évolution des valeurs du point depuis la création du RAFP",
        decimales=6,
        tolerance=5e-7,
    ),
    Certification(
        nom="valeurs_point_cnbf",
        chemin=REFERENCE / "regimes" / "valeurs_point.csv",
        cles=("regime", "annee", "mesure"),
        colonne="valeur",
        source=source_valeurs_point_cnbf,
        origine="CNBF, barèmes annuels des cotisations et prestations",
        decimales=6,
        tolerance=5e-7,
    ),
    Certification(
        nom="valeurs_point_cnavpl",
        chemin=REFERENCE / "regimes" / "valeurs_point.csv",
        cles=("regime", "annee", "mesure"),
        colonne="valeur",
        source=source_valeurs_point_cnavpl,
        origine="CNAVPL, recueils statistiques annuels",
        decimales=6,
        tolerance=5e-7,
    ),
    Certification(
        nom="valeurs_point_msa",
        chemin=REFERENCE / "regimes" / "valeurs_point.csv",
        cles=("regime", "annee", "mesure"),
        colonne="valeur",
        source=source_valeurs_point_msa,
        origine="DILA, base LEGI, code rural D. 732-166",
        decimales=6,
        tolerance=5e-7,
    ),
    Certification(
        nom="minimum_contributif",
        chemin=REFERENCE / "legislation" / "minimum_contributif.csv",
        cles=("mesure", "annee"),
        colonne="valeur",
        source=source_minimum_contributif,
        origine="DILA, base LEGI, code de la sécurité sociale D. 351-2-1 et "
                "D. 173-21-0-0-1",
        decimales=6,
        tolerance=5e-3,
        unite=" €/an",
    ),
    Certification(
        nom="valeurs_point_insee",
        chemin=REFERENCE / "regimes" / "valeurs_point.csv",
        cles=("regime", "annee", "mesure"),
        colonne="valeur",
        source=source_valeurs_point_insee,
        origine="INSEE BDM, idbanks 000849395, 000822495 et 010593202",
        decimales=6,
        tolerance=5e-7,
        niveau="haute",
        # Elle ne sert que la fin de la série, là où ni OpenFisca ni la
        # fédération ne vont : depuis que celle-ci est lue directement, elle
        # peut n'avoir plus rien à ajouter.
        complementaire=True,
    ),
    Certification(
        nom="valeurs_point_unirs",
        chemin=REFERENCE / "regimes" / "valeurs_point.csv",
        cles=("regime", "annee", "mesure"),
        colonne="valeur",
        source=source_valeurs_point_substituees,
        origine="UNIRS tenant lieu de point Arrco avant 1999 — barème de la "
                "fédération Agirc-Arrco, substitution du dépôt",
        decimales=6,
        tolerance=5e-7,
        niveau="moyenne",
    ),
    Certification(
        nom="valeurs_point_texte",
        chemin=REFERENCE / "regimes" / "valeurs_point.csv",
        cles=("regime", "annee", "mesure"),
        colonne="valeur",
        source=source_valeurs_point_texte,
        origine="Accord national interprofessionnel du 17 novembre 2017",
        decimales=6,
        tolerance=5e-7,
        niveau="moyenne",
    ),
    Certification(
        nom="age_ouverture_requis",
        chemin=REFERENCE / "legislation" / "age_ouverture_requis.csv",
        cles=("generation",),
        colonne="age",
        source=source_age_ouverture,
        origine="DILA, base LEGI, code de la sécurité sociale D. 161-2-1-9",
        decimales=2,
        tolerance=0.005,
        unite=" ans",
    ),
    Certification(
        nom="duree_assurance_requise",
        chemin=REFERENCE / "legislation" / "duree_assurance_requise.csv",
        cles=("generation",),
        colonne="trimestres",
        source=source_duree_requise,
        origine="DILA, base LEGI, code de la sécurité sociale L. 161-17-3",
        decimales=0,
        tolerance=0.5,
        unite=" trimestres",
    ),
    Certification(
        nom="duree_assurance_requise_decrets",
        chemin=REFERENCE / "legislation" / "duree_assurance_requise.csv",
        cles=("generation",),
        colonne="trimestres",
        source=source_duree_requise_decrets,
        origine="DILA, base LEGI, décrets pris pour l'application de la loi du "
                "21 août 2003 et de celle du 9 novembre 2010",
        decimales=0,
        tolerance=0.5,
        unite=" trimestres",
    ),
    Certification(
        nom="coefficient_minoration",
        chemin=REFERENCE / "legislation" / "coefficient_minoration.csv",
        cles=("generation",),
        colonne="coefficient",
        source=source_coefficient_minoration,
        origine="DILA, base LEGI, code de la sécurité sociale R. 351-27",
        decimales=5,
        tolerance=5e-6,
    ),
    Certification(
        nom="carriere_longue",
        chemin=REFERENCE / "legislation" / "carriere_longue.csv",
        cles=("annee", "age_debut_maximum"),
        colonne="age_depart",
        source=source_carriere_longue,
        origine="DILA, base LEGI, code de la sécurité sociale L. 351-1-1 "
                "et D. 351-1-1",
        decimales=0,
        tolerance=0.5,
        unite=" ans",
    ),
    Certification(
        nom="duree_proratisation",
        chemin=REFERENCE / "legislation" / "duree_proratisation.csv",
        cles=("generation",),
        colonne="trimestres",
        source=source_duree_proratisation,
        origine="DILA, base LEGI, code de la sécurité sociale R. 351-6 II",
        decimales=0,
        tolerance=0.5,
        unite=" trimestres",
    ),
    Certification(
        nom="annees_salaire_reference",
        chemin=REFERENCE / "legislation" / "annees_salaire_reference.csv",
        cles=("generation",),
        colonne="annees",
        source=source_annees_salaire_reference,
        origine="DILA, base LEGI, code de la sécurité sociale R. 351-29-1",
        decimales=0,
        tolerance=0.5,
        unite=" années",
    ),
    Certification(
        nom="validation_trimestres",
        chemin=REFERENCE / "legislation" / "validation_trimestres.csv",
        cles=("annee",),
        colonne="heures",
        source=source_heures_par_trimestre,
        origine="DILA, base LEGI, code de la sécurité sociale R. 351-9",
        decimales=0,
        tolerance=0.5,
        unite=" heures",
    ),
    Certification(
        nom="smic_horaire",
        chemin=REFERENCE / "macro" / "smic_horaire.csv",
        cles=("annee",),
        colonne="smic_horaire",
        source=source_smic,
        origine="DILA, base LEGI, décrets portant relèvement du salaire minimum "
                "de croissance",
        decimales=6,
        tolerance=5e-7,
        unite=" €",
    ),
    Certification(
        nom="decote_fonction_publique_coefficient",
        chemin=REFERENCE / "legislation" / "decote_fonction_publique.csv",
        cles=("annee",),
        colonne="coefficient",
        source=source_decote_fp_coefficient,
        origine="DILA, base LEGI, loi n° 2003-775 du 21 août 2003, article 66 III",
        decimales=5,
        tolerance=5e-6,
    ),
    Certification(
        nom="decote_fonction_publique_trimestres",
        chemin=REFERENCE / "legislation" / "decote_fonction_publique.csv",
        cles=("annee",),
        colonne="trimestres_avant_limite",
        source=source_decote_fp_trimestres,
        origine="DILA, base LEGI, loi n° 2003-775 du 21 août 2003, article 66 III",
        decimales=0,
        tolerance=0.5,
        unite=" trimestres",
    ),
    Certification(
        nom="minimum_garanti_indice",
        chemin=REFERENCE / "legislation" / "minimum_garanti.csv",
        cles=("annee",),
        colonne="indice_majore",
        source=source_minimum_garanti_indice,
        origine="DILA, base LEGI, loi n° 2003-775 du 21 août 2003, article 66 V",
        decimales=0,
        tolerance=0.5,
        unite="",
    ),
    Certification(
        nom="minimum_garanti_part",
        chemin=REFERENCE / "legislation" / "minimum_garanti.csv",
        cles=("annee",),
        colonne="part_15_ans",
        source=source_minimum_garanti_part,
        origine="DILA, base LEGI, loi n° 2003-775 du 21 août 2003, article 66 V",
        decimales=3,
        tolerance=0.0005,
        unite="",
    ),
    Certification(
        nom="minimum_garanti_points_15_30",
        chemin=REFERENCE / "legislation" / "minimum_garanti.csv",
        cles=("annee",),
        colonne="points_15_30",
        source=source_minimum_garanti_points_15_30,
        origine="DILA, base LEGI, loi n° 2003-775 du 21 août 2003, article 66 V",
        decimales=6,
        tolerance=5e-07,
        unite="",
    ),
    Certification(
        nom="minimum_garanti_points_30_40",
        chemin=REFERENCE / "legislation" / "minimum_garanti.csv",
        cles=("annee",),
        colonne="points_30_40",
        source=source_minimum_garanti_points_30_40,
        origine="DILA, base LEGI, loi n° 2003-775 du 21 août 2003, article 66 V",
        decimales=6,
        tolerance=5e-07,
        unite="",
    ),
    Certification(
        nom="minimum_garanti_seuil",
        chemin=REFERENCE / "legislation" / "minimum_garanti.csv",
        cles=("annee",),
        colonne="trimestres_seuil",
        source=source_minimum_garanti_seuil,
        origine="DILA, base LEGI, loi n° 2003-775 du 21 août 2003, article 66 V",
        decimales=0,
        tolerance=0.5,
        unite=" trimestres",
    ),
    Certification(
        nom="point_indice_fonction_publique",
        chemin=REFERENCE / "legislation" / "point_indice_fonction_publique.csv",
        cles=("annee",),
        colonne="valeur",
        source=source_point_indice,
        origine="OpenFisca-France, point_indice_en_euros.yaml",
        decimales=4,
        tolerance=5e-5,
        niveau="haute",
    ),
    Certification(
        nom="point_indice_journal_officiel",
        chemin=REFERENCE / "legislation" / "point_indice_fonction_publique.csv",
        cles=("annee",),
        colonne="valeur",
        source=source_point_indice_jo,
        origine="DILA, base LEGI, décret n° 85-1148 du 24 octobre 1985, article 3",
        decimales=4,
        tolerance=5e-5,
    ),
    Certification(
        nom="esperances_projetees",
        chemin=REFERENCE / "mortalite" / "esperances_vie.csv",
        cles=("annee", "sexe", "mesure"),
        colonne="valeur",
        source=source_esperances_projetees,
        origine="dérivée des quotients projetés de l'INSEE, projections 2026",
        decimales=2,
        tolerance=0.005,
        unite=" ans",
        niveau="projetee",
    ),
    Certification(
        nom="esperance_65_derivee",
        chemin=REFERENCE / "mortalite" / "esperances_vie.csv",
        cles=("annee", "sexe", "mesure"),
        colonne="valeur",
        source=source_esperance_65_derivee,
        origine="dérivée des quotients INED de Vallin et Meslé",
        decimales=2,
        tolerance=0.005,
        unite=" ans",
        niveau="haute",
    ),
    Certification(
        nom="quotients_mortalite_anciens",
        chemin=REFERENCE / "mortalite" / "quotients_periode.csv",
        cles=("annee", "sexe", "age"),
        colonne="qx",
        source=source_quotients_anciens,
        origine="INED, tables de Vallin et Meslé, quotients du moment par âge",
        decimales=6,
        tolerance=5e-7,
    ),
    Certification(
        nom="quotients_mortalite",
        chemin=REFERENCE / "mortalite" / "quotients_periode.csv",
        cles=("annee", "sexe", "age"),
        colonne="qx",
        source=source_quotients,
        origine="Eurostat demo_mlifetable, quotients de mortalité par âge",
        decimales=6,
        tolerance=5e-7,
        entete=(
            "# Quotients de mortalité par âge — tables du moment, France",
            "# source_id: eurostat_mlifetable",
            "# unite: probabilité de décès dans l'année, entre 0 et 1",
            "#",
            "# Ce fichier PRIME sur la calibration paramétrique : dès qu'un couple",
            "# (année, sexe, âge) y figure, le moteur l'utilise tel quel et n'appelle",
            "# pas la loi de Gompertz-Makeham. Au-delà du dernier âge publié — 84 ans",
            "# jusqu'en 2011, 94 ans ensuite — et hors des années couvertes, la loi",
            "# paramétrique reprend la main : c'est un raccord assumé, pas un oubli.",
            "#",
            "# Champ : France métropolitaine jusqu'en 1997, France entière ensuite.",
            "# Avant 1986, Eurostat ne publie pas de table française ; les tables TD/TV",
            "# de l'INSEE, seules à remonter plus haut, ne sont diffusées qu'en tableurs.",
            "#",
            "# Fichier écrit par scripts/verifier_donnees.py --appliquer : ne pas",
            "# modifier à la main.",
        ),
    ),
    # -- contribution employeur des régimes publics --------------------------
    # Quatre séries dans un seul fichier, de trois niveaux différents : le taux
    # appelé par l'État depuis 2006 vient de son producteur et se certifie ; le
    # taux implicite d'avant 2006 est une reconstitution budgétaire transcrite
    # par un tiers ; la CNRACL et la SNCF sont des transcriptions de décrets et
    # d'arrêtés. Le fichier est créé par la première d'entre elles.
    Certification(
        nom="employeur_public_etat",
        chemin=REFERENCE / "legislation" / "contribution_employeur_public.csv",
        cles=("annee", "regime"),
        colonne="taux",
        source=source_employeur_etat_appele,
        origine="Service des retraites de l'État, fiche « Historique des taux "
                "de cotisations »",
        decimales=6,
        tolerance=5e-7,
        gabarit={"nature": "appelee"},
    ),
    Certification(
        nom="employeur_public_etat_implicite",
        chemin=REFERENCE / "legislation" / "contribution_employeur_public.csv",
        cles=("annee", "regime"),
        colonne="taux",
        source=source_employeur_etat_implicite,
        origine="OpenFisca-France, taux implicite du jaune « pensions » du PLF 2011",
        decimales=6,
        tolerance=5e-7,
        niveau="haute",
        gabarit={"nature": "implicite"},
    ),
    Certification(
        nom="employeur_public_texte",
        chemin=REFERENCE / "legislation" / "contribution_employeur_public.csv",
        cles=("annee", "regime"),
        colonne="taux",
        source=source_employeur_public_texte,
        origine="Décret n° 2025-86 du 30 janvier 2025 (montée en charge CNRACL)",
        decimales=6,
        tolerance=5e-7,
        niveau="moyenne",
        gabarit={"nature": "appelee"},
        # Elle ne comble que ce qu'aucune autre source ne porte : depuis que le
        # décret est lu dans la base LEGI, la saisie n'a plus rien à ajouter.
        complementaire=True,
    ),
    Certification(
        nom="employeur_public_cnracl_journal_officiel",
        chemin=REFERENCE / "legislation" / "contribution_employeur_public.csv",
        cles=("annee", "regime"),
        colonne="taux",
        source=source_employeur_cnracl_jo,
        origine="DILA, base LEGI, décret n° 91-613 du 28 juin 1991, article 5 II",
        decimales=6,
        tolerance=5e-7,
        gabarit={"nature": "appelee"},
    ),
    Certification(
        nom="employeur_public_cnracl",
        chemin=REFERENCE / "legislation" / "contribution_employeur_public.csv",
        cles=("annee", "regime"),
        colonne="taux",
        source=source_employeur_cnracl,
        origine="OpenFisca-France, décrets CNRACL et barèmes de la Caisse des dépôts",
        decimales=6,
        tolerance=5e-7,
        niveau="haute",
        gabarit={"nature": "appelee"},
    ),
    Certification(
        nom="employeur_public_sncf",
        chemin=REFERENCE / "legislation" / "contribution_employeur_public.csv",
        cles=("annee", "regime"),
        colonne="taux",
        source=source_employeur_sncf,
        origine="OpenFisca-France, arrêtés annuels fixant les composantes T1 et T2",
        decimales=6,
        tolerance=5e-7,
        niveau="haute",
        gabarit={"nature": "appelee"},
    ),
)


# ---------------------------------------------------------------------------
# Contrôles sans source : cohérence interne
# ---------------------------------------------------------------------------


def controle_coherence_interne() -> list[str]:
    """Vérifications qui ne dépendent d'aucune source externe."""
    messages: list[str] = []

    fichiers = {
        "ipc_annuel.csv": ("variation", -0.15, 0.70),
        "salaire_moyen.csv": ("variation_nominale", -0.15, 0.70),
        "masse_salariale.csv": ("variation_nominale", -0.15, 0.70),
        "pib_nominal.csv": ("variation_nominale", -0.15, 0.70),
        "productivite.csv": ("variation_reelle", -0.15, 0.20),
    }
    for nom, (colonne, mini, maxi) in fichiers.items():
        lignes = charger_csv(REFERENCE / "macro" / nom)
        annees = [int(l["annee"]) for l in lignes]
        trous = set(range(min(annees), max(annees) + 1)) - set(annees)
        if trous:
            messages.append(f"TROU    {nom} : années manquantes {sorted(trous)}")
        for ligne in lignes:
            valeur = float(ligne[colonne])
            if not mini <= valeur <= maxi:
                messages.append(
                    f"SUSPECT {nom} {ligne['annee']} : {valeur:.3%} hors plage plausible"
                )
        certifiees = sum(1 for l in lignes if l["fiabilite"] == "certifiee")
        messages.append(
            f"OK      {nom} : {len(lignes)} années, {min(annees)}-{max(annees)}, "
            f"{certifiees} certifiées"
        )

    plafond = charger_csv(REFERENCE / "macro" / "plafond_securite_sociale.csv")
    precedent = None
    for ligne in plafond:
        valeur = float(ligne["pass_eur"])
        if precedent is not None and valeur < precedent:
            messages.append(
                f"SUSPECT plafond {ligne['annee']} : recul de {precedent:.0f} à {valeur:.0f} €"
            )
        precedent = valeur
    messages.append(f"OK      plafond : {len(plafond)} années")

    esperances = charger_csv(REFERENCE / "mortalite" / "esperances_vie.csv")
    par_mesure: dict[str, list[int]] = {}
    table: dict[tuple[int, str], dict[str, float]] = {}
    for ligne in esperances:
        annee, sexe = int(ligne["annee"]), ligne["sexe"]
        par_mesure.setdefault(ligne["mesure"], []).append(annee)
        table.setdefault((annee, sexe), {})[ligne["mesure"]] = float(ligne["valeur"])
    for mesure, annees in sorted(par_mesure.items()):
        certifiees = sum(1 for l in esperances
                         if l["mesure"] == mesure and l["fiabilite"] == "certifiee")
        messages.append(
            f"OK      esperances_vie {mesure} : {len(annees)} lignes, "
            f"{min(annees)}-{max(annees)}, {certifiees} certifiées"
        )

    # Le rapport e65/e60 est le seul contrôle qui détecte une valeur cohérente
    # prise isolément mais incompatible avec sa voisine : c'est lui qui pilote
    # la pente de la force de mortalité calibrée.
    for (annee, sexe), valeurs in sorted(table.items()):
        if "e60" in valeurs and "e65" in valeurs:
            rapport = valeurs["e65"] / valeurs["e60"]
            if not 0.6 < rapport < 0.95:
                messages.append(
                    f"SUSPECT esperances_vie {annee}/{sexe} : rapport e65/e60 "
                    f"de {rapport:.3f}, hors plage plausible"
                )
    return messages


#: Familles de régimes dont les assurés ONT un employeur : leur
#: `taux_cotisation_retraite` est un total, et la fiche doit dire qui en paie
#: quelle part. Les autres familles — non-salariés, libéraux — n'ont pas
#: d'employeur, et le défaut `part_salariale: 1.0` y est le bon.
FAMILLES_AVEC_EMPLOYEUR = {
    "base_prive", "complementaire_prive", "additionnel_capitalise",
}

#: Régimes de familles mixtes dont les assurés sont des salariés. `agricole`
#: réunit la MSA des salariés, qui a un employeur, et celle des non-salariés,
#: qui n'en a pas.
REGIMES_SALARIES_HORS_FAMILLE = {"msa_salaries"}


def controle_part_salariale() -> list[str]:
    """Aucune période de salariés ne doit oublier sa répartition.

    Le défaut `part_salariale: 1.0` dit « toute la cotisation est personnelle ».
    C'est vrai d'un artisan et d'une période `agent_seul`, dont le taux est déjà
    la seule retenue de l'agent. C'est faux de toute période dont le taux est un
    total employeur compris : l'oublier ferait porter au compte, sous le
    scénario 2, une part patronale qui n'a rien à y faire — sans que rien ne le
    signale.

    Ce contrôle ne dépend d'aucune source et ne certifie rien : il vérifie que
    la fiche dit ce qu'elle doit dire, et que la valeur est plausible.
    """
    import yaml

    anomalies: list[str] = []
    verifiees = 0
    for chemin in sorted((REFERENCE / "regimes").glob("*.yaml")):
        if chemin.name.startswith("_"):
            continue
        for fiche in (yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}).get(
            "regimes", []
        ):
            attendue = (fiche["famille"] in FAMILLES_AVEC_EMPLOYEUR
                        or fiche["code"] in REGIMES_SALARIES_HORS_FAMILLE)
            for periode in fiche.get("periodes", []):
                borne = f"{fiche['code']} {periode['debut']}-{periode.get('fin')}"
                part = periode.get("part_salariale")
                if periode.get("perimetre_taux") == "agent_seul":
                    if part is not None:
                        anomalies.append(
                            f"SUSPECT part salariale {borne} : période `agent_seul`, "
                            "dont le taux est déjà la seule retenue de l'agent — "
                            "`part_salariale` n'y a pas de sens"
                        )
                    continue
                if attendue and part is None:
                    anomalies.append(
                        f"MANQUE  part salariale {borne} : période de salariés sans "
                        "`part_salariale`, le compte y porterait la part patronale"
                    )
                    continue
                if part is None:
                    continue
                verifiees += 1
                if not 0.0 < float(part) <= 1.0:
                    anomalies.append(
                        f"SUSPECT part salariale {borne} : {part}, hors de ]0, 1]"
                    )
    messages = [
        f"OK      part salariale : {verifiees} périodes renseignées, "
        f"{len(anomalies)} anomalie(s)"
    ]
    messages.extend(anomalies)
    return messages


def controle_vraisemblance_inflation() -> list[str]:
    """Confronte la série d'inflation à l'IPCH d'Eurostat.

    Contrôle de vraisemblance uniquement : les deux indices divergent
    légitimement, seul un écart important trahit une erreur de saisie.
    """
    source = BRUT / "eurostat_hicp.json"
    if not source.exists():
        return [
            f"IGNORÉ  vraisemblance inflation : {source} absent "
            "(lancer scripts/fetch/eurostat_hicp.py)"
        ]

    reference = {
        int(annee): valeur
        for annee, valeur in json.loads(source.read_text(encoding="utf-8"))["serie"].items()
    }
    saisi = {
        int(ligne["annee"]): float(ligne["variation"])
        for ligne in charger_csv(REFERENCE / "macro" / "ipc_annuel.csv")
    }

    communes = sorted(set(reference) & set(saisi))
    anomalies = []
    ecart_moyen = 0.0
    for annee in communes:
        ecart = reference[annee] - saisi[annee]
        ecart_moyen += ecart
        if abs(ecart) > SEUIL_VRAISEMBLANCE:
            anomalies.append(
                f"SUSPECT inflation {annee} : référence {saisi[annee]:.2%}, "
                f"IPCH {reference[annee]:.2%} — écart de {abs(ecart):.2%}, "
                "trop élevé pour la seule différence IPC/IPCH"
            )
    if communes:
        ecart_moyen /= len(communes)

    messages = [
        f"OK      vraisemblance inflation : {len(communes)} années comparées à l'IPCH, "
        f"{len(anomalies)} au-delà du seuil de {SEUIL_VRAISEMBLANCE:.1%}",
        f"        écart moyen IPCH − IPC : {ecart_moyen:+.2%} "
        "(positif attendu, l'IPCH est structurellement au-dessus)",
    ]
    return messages + anomalies


def controle_vraisemblance_esperance_65() -> list[str]:
    """Confronte l'espérance de vie à 65 ans de l'OCDE à celle d'Eurostat.

    Les deux organisations rediffusent le chiffre INSEE : elles doivent
    coïncider. Un désaccord signalerait que l'une des deux a changé de champ —
    France métropolitaine contre France entière, par exemple — et donc que la
    série retenue n'est plus homogène avec les espérances à 60 ans, qui viennent
    directement de l'INSEE.
    """
    try:
        ocde = _serie_json("oecd_esperance_vie.json", "scripts/fetch/oecd_esperance_vie.py")
        eurostat = _serie_json("eurostat_esperance_vie.json",
                               "scripts/fetch/eurostat_mortalite.py")
    except SourceAbsente as erreur:
        return [f"IGNORÉ  vraisemblance espérance à 65 ans : {erreur}"]

    communes = [c for c in set(ocde) & set(eurostat) if c.endswith("|e65")]
    ecarts = {c: abs(ocde[c] - eurostat[c]) for c in communes}
    depassements = [
        f"SUSPECT espérance à 65 ans {cle.replace('|', '/')} : OCDE {ocde[cle]}, "
        f"Eurostat {eurostat[cle]} — les deux devraient rediffuser le même chiffre INSEE"
        for cle, ecart in sorted(ecarts.items()) if ecart > 0.05
    ]
    maximum = max(ecarts.values()) if ecarts else 0.0
    return [
        f"OK      vraisemblance espérance à 65 ans : {len(communes)} valeurs "
        f"comparées OCDE / Eurostat, écart maximal {maximum:.2f} an",
    ] + depassements


#: L'article L. 351-8 1° définit l'âge d'annulation de la décote par rapport à
#: l'âge d'ouverture : « augmenté de cinq années » jusqu'à la réforme de 2023,
#: « de trois années » depuis — et la cible est la même, 67 ans.
ANNULATION_APRES_OUVERTURE = 5.0
AGE_ANNULATION_CIBLE = 67.0


def controle_vraisemblance_age_annulation() -> list[str]:
    """Recalcule l'âge d'annulation de la décote depuis l'âge d'ouverture.

    Cette table-là n'est pas certifiable : aucun texte ne l'écrit génération par
    génération. Ce que le code écrit, c'est une RÈGLE — l'article L. 351-8 1°
    donne « l'âge prévu à l'article L. 161-17-2 augmenté de cinq années »,
    devenu trois années quand la réforme de 2023 a porté l'âge d'ouverture à
    64 ans, la cible restant 67. La table du dépôt est donc la table certifiée
    des âges d'ouverture, décalée et plafonnée.

    On ne la certifie pas pour autant — une valeur calculée n'est pas une valeur
    confrontée, et c'est la règle qui vaut pour l'espérance de vie dérivée. Mais
    on la recontrôle : si une réforme déplaçait l'âge d'ouverture sans que
    celui-ci suive, l'écart se verrait ici plutôt que dans une pension.
    """
    ouverture = _table_reference("age_ouverture_requis.csv", "generation", "age")
    annulation = _table_reference("age_annulation_decote.csv", "generation", "age")
    if not ouverture or not annulation:
        return ["IGNORÉ  vraisemblance âge d'annulation : table absente"]

    bornes = sorted(ouverture)
    ecarts = []
    for generation, age in sorted(annulation.items()):
        applicables = [b for b in bornes if b <= generation]
        if not applicables:
            continue
        attendu = min(ouverture[applicables[-1]] + ANNULATION_APRES_OUVERTURE,
                      AGE_ANNULATION_CIBLE)
        if abs(attendu - age) > 0.01:
            ecarts.append(
                f"SUSPECT âge d'annulation, génération {generation:g} : table "
                f"{age:g} ans, règle de L. 351-8 {attendu:g} ans"
            )
    return [
        f"OK      vraisemblance âge d'annulation : {len(annulation)} générations "
        f"comparées à l'âge d'ouverture certifié majoré de "
        f"{ANNULATION_APRES_OUVERTURE:g} ans, {len(ecarts)} en désaccord",
    ] + ecarts


#: L'article L. 17 du code des pensions fixe la référence du minimum garanti à
#: « la valeur du traitement brut afférent à l'indice majoré 227 au 1er janvier
#: 2004 ».
INDICE_REFERENCE_MINIMUM_GARANTI = 227
ANNEE_REFERENCE_MINIMUM_GARANTI = 2004


def controle_vraisemblance_minimum_garanti() -> list[str]:
    """Recalcule la référence du minimum garanti depuis le point d'indice.

    L'article L. 17 la définit comme le traitement de l'indice majoré 227 au
    1er janvier 2004, et le dépôt porte le montant que l'État publie —
    997,96 € par mois, soit 11 975,57 € l'an. Le point d'indice de 2004 étant
    désormais lu dans son décret, les deux chemins doivent se rejoindre :
    227 × 52,7558 = 11 975,57.

    Le montant reste `haute`, parce qu'il est transcrit d'une publication et non
    confronté à un fichier du producteur. Mais un écart entre les deux chemins
    signalerait qu'une des deux séries a bougé sans l'autre.
    """
    points = _table_reference("point_indice_fonction_publique.csv", "annee", "valeur")
    montants = _table_reference("minimum_garanti_montants.csv", "annee", "valeur")
    annee = float(ANNEE_REFERENCE_MINIMUM_GARANTI)
    if annee not in points or annee not in montants:
        return ["IGNORÉ  vraisemblance minimum garanti : ancre de 2004 absente"]

    calcule = INDICE_REFERENCE_MINIMUM_GARANTI * points[annee]
    ecart = abs(calcule - montants[annee])
    messages = [
        f"OK      vraisemblance minimum garanti : référence de 2004 publiée "
        f"{montants[annee]:.2f} €, recalculée {calcule:.2f} € "
        f"({INDICE_REFERENCE_MINIMUM_GARANTI} × {points[annee]:.4f})",
    ]
    if ecart > 0.01:
        messages.append(
            f"SUSPECT minimum garanti : les deux chemins s'écartent de "
            f"{ecart:.2f} € — le point d'indice ou le montant publié a bougé"
        )
    return messages


def controle_vraisemblance_cotisations() -> list[str]:
    """Confronte les taux du régime général saisis à ceux d'OpenFisca-France.

    Ce contrôle ne corrige rien : les fiches de régime sont des YAML structurés
    par périodes législatives, où un taux résume plusieurs années. Le rapprocher
    d'une série annuelle demande un arbitrage — quelle moyenne, sur quelles
    bornes — qui doit rester une décision explicite, prise à la main et tracée
    dans les notes de la fiche. Le rôle du contrôle est de dire quand l'écart
    devient assez grand pour appeler cette décision.
    """
    chemin = BRUT / "openfisca_cotisations.json"
    if not chemin.exists():
        return [
            f"IGNORÉ  vraisemblance cotisations : {chemin} absent "
            "(lancer scripts/fetch/openfisca_cotisations.py)"
        ]

    import yaml

    serie = json.loads(chemin.read_text(encoding="utf-8"))["serie"]
    couverture = {int(a) for a in serie}
    fiches = yaml.safe_load(
        (REFERENCE / "regimes" / "base_prive.yaml").read_text(encoding="utf-8")
    )
    regime = next(r for r in fiches["regimes"] if r["code"] == "regime_general")

    messages, anomalies = [], []
    comparees = 0
    for periode in regime["periodes"]:
        debut = max(int(periode["debut"]), min(couverture))
        fin = min(int(periode["fin"] or max(couverture)), max(couverture))
        annees = [a for a in range(debut, fin + 1) if a in couverture]
        if not annees:
            continue
        comparees += 1

        # PLAFONNÉE ET DÉPLAFONNÉE SÉPARÉMENT. La fiche porte les deux taux :
        # celui qui s'arrête au plafond et celui qui court sur la totalité du
        # salaire. Les confronter un par un — plutôt que leur somme au `total`
        # d'OpenFisca — attrape la faute que la somme masque : deux erreurs de
        # sens contraire qui se compensent, et qui ne portent pourtant pas sur
        # la même assiette.
        def _moyenne(*cles: str) -> float:
            return sum(
                sum(serie[str(a)][cle] for cle in cles) for a in annees
            ) / len(annees)

        for libelle, cles, champ in (
            ("cotisations", ("salarie_plafonnee", "employeur_plafonnee"),
             "taux_cotisation_retraite"),
            ("cotisation déplafonnée",
             ("salarie_deplafonnee", "employeur_deplafonnee"),
             "taux_cotisation_deplafonnee"),
        ):
            publie = _moyenne(*cles)
            saisi = float(periode.get(champ) or 0.0)
            if abs(publie - saisi) > 0.002:
                anomalies.append(
                    f"SUSPECT {libelle} regime_general "
                    f"{periode['debut']}-{periode['fin']} : "
                    f"fiche {saisi:.2%}, OpenFisca {publie:.2%} en moyenne sur "
                    f"{annees[0]}-{annees[-1]}"
                )

        # La RÉPARTITION salarié/employeur, sur les mêmes années. C'est elle qui
        # sépare les scénarios 2 et 3 des scénarios 4 et 5 : une erreur d'un
        # dixième s'y voit autant qu'une erreur de taux. Elle se contrôle sur
        # chaque taux, et non sur leur somme : la déplafonnée est presque
        # entièrement patronale, la plafonnée se partage à peu près par moitié.
        for libelle, part_cle, total_cles, champ in (
            ("part salariale", "salarie_plafonnee",
             ("salarie_plafonnee", "employeur_plafonnee"), "part_salariale"),
            ("part salariale déplafonnée", "salarie_deplafonnee",
             ("salarie_deplafonnee", "employeur_deplafonnee"),
             "part_salariale_deplafonnee"),
        ):
            parts = [
                serie[str(a)][part_cle] / sum(serie[str(a)][cle] for cle in total_cles)
                for a in annees
                if sum(serie[str(a)][cle] for cle in total_cles) > 0
            ]
            if not parts or periode.get(champ) is None:
                continue
            publiee = sum(parts) / len(parts)
            saisie = float(periode[champ])
            if abs(publiee - saisie) > 0.01:
                anomalies.append(
                    f"SUSPECT {libelle} regime_general "
                    f"{periode['debut']}-{periode['fin']} : fiche {saisie:.2%}, "
                    f"OpenFisca {publiee:.2%} en moyenne sur "
                    f"{annees[0]}-{annees[-1]}"
                )
    messages.append(
        f"OK      vraisemblance cotisations : {comparees} périodes du régime général "
        f"comparées à OpenFisca — taux et répartition salarié/employeur —, "
        f"{len(anomalies)} au-delà du seuil"
    )
    messages.append(
        "        avant 1967 aucune transcription n'existe : les taux y restent saisis"
    )

    # Les COMPLÉMENTAIRES pèsent, dans la pension d'un salarié du privé, plus
    # lourd que tous les autres régimes réunis après le régime général. Leurs
    # taux étaient au niveau `estimee` faute de série ; OpenFisca en porte une,
    # dated depuis 1962, et par TRANCHE — ce qui permet enfin de confronter
    # chaque période de fiche à la sienne.
    tranches = {
        "tranche_1": "tranche_1", "tranche_a": "tranche_1",
        "tranche_2_arrco": "tranche_2", "tranche_2": "tranche_2",
        "tranche_b": "tranche_2", "tranche_c": "tranche_3",
    }
    par_regime = json.loads(chemin.read_text(encoding="utf-8")).get(
        "complementaires", {})
    fiches = yaml.safe_load(
        (REFERENCE / "regimes" / "complementaires_prive.yaml").read_text(
            encoding="utf-8")
    )
    complementaires = 0
    for regime in fiches["regimes"]:
        annuel = par_regime.get(regime["code"])
        if not annuel:
            continue
        couverture = {int(a) for a in annuel}
        for periode in regime["periodes"]:
            tranche = tranches.get(periode.get("assiette"))
            if tranche is None:
                continue
            debut = max(int(periode["debut"]), min(couverture))
            fin = min(int(periode["fin"] or max(couverture)), max(couverture))
            annees = [a for a in range(debut, fin + 1)
                      if a in couverture and annuel[str(a)].get(tranche)]
            if not annees:
                continue
            complementaires += 1
            publie = sum(annuel[str(a)][tranche] for a in annees) / len(annees)
            saisi = float(periode["taux_cotisation_retraite"])
            if abs(publie - saisi) > 0.005:
                anomalies.append(
                    f"SUSPECT cotisations {regime['code']} {periode['debut']}-"
                    f"{periode['fin']} {periode['assiette']} : fiche {saisi:.2%}, "
                    f"OpenFisca {publie:.2%} en moyenne sur "
                    f"{annees[0]}-{annees[-1]}"
                )
    messages.append(
        f"OK      vraisemblance cotisations : {complementaires} périodes des "
        f"complémentaires du privé comparées à leurs taux effectifs par tranche"
    )
    return messages + anomalies


def controle_vraisemblance_prix_anciens() -> list[str]:
    """Confronte l'inflation reconstituée d'avant 1950 à la seule série de
    l'INSEE qui remonte plus haut.

    `docs/limites.md` a longtemps écrit que le tableau « IPC depuis 1901 »
    n'existait qu'en fichier tableur, et que ce n'était « plus le format qui
    bloque, c'est l'adresse ». L'adresse est un IDBANK : `010605954`, le
    coefficient de transformation du franc et de l'euro, que la Banque de
    données macroéconomiques sert depuis 1901 par la même API que tout le
    reste.

    **Elle ne remplace pas la série saisie, et c'est mesurable.** Publiée à
    deux décimales sur une base 100 en 2015, elle vaut 0,20 en 1935 : un
    centième y pèse cinq points de taux, et les variations annuelles qu'on en
    tirerait seraient du bruit — la série donne +3,9 % pour 1930 quand le dépôt
    porte −2,5 %, et 0,0 % pour 1934 quand il porte −5,7 %. Le contrôle porte
    donc sur la DÉRIVE CUMULÉE, seule grandeur que cette précision autorise.

    L'étalonnage du contrôle est donné par la période où le dépôt est certifié :
    sur 1949-2025, la série des coefficients s'écarte déjà de 2,4 % de la série
    mensuelle certifiée. Un écart du même ordre sur 1930-1949 ne dit donc rien
    d'autre que la précision de l'instrument.
    """
    chemin = BRUT / "insee_bdm.json"
    if not chemin.exists():
        return [f"IGNORÉ  vraisemblance prix anciens : {chemin} absent "
                "(lancer scripts/fetch/insee_bdm.py)"]

    series = json.loads(chemin.read_text(encoding="utf-8"))["series"]
    coefficients = series.get("coefficient_prix_1901", {}).get("observations")
    if not coefficients:
        return ["IGNORÉ  vraisemblance prix anciens : série 010605954 absente "
                "du téléchargement"]
    indice = {int(a): float(v) for a, v in coefficients.items() if len(a) == 4}

    saisi = {int(l["annee"]): float(l["variation"])
             for l in charger_csv(REFERENCE / "macro" / "ipc_annuel.csv")}

    messages = []
    for debut, fin, etiquette in ((1930, 1949, "reconstituée"),
                                  (1949, 2025, "certifiée")):
        if debut not in indice or fin not in indice:
            continue
        publiee = indice[fin] / indice[debut]
        cumulee = 1.0
        for annee in range(debut + 1, fin + 1):
            cumulee *= 1.0 + saisi.get(annee, 0.0)
        ecart = cumulee / publiee - 1.0
        messages.append(
            f"OK      vraisemblance prix anciens {debut}-{fin} ({etiquette}) : "
            f"dépôt ×{cumulee:.2f}, INSEE 010605954 ×{publiee:.2f}, "
            f"écart cumulé {ecart:+.1%}"
        )
        if abs(ecart) > SEUIL_DERIVE_PRIX_ANCIENS:
            messages.append(
                f"SUSPECT prix anciens {debut}-{fin} : {ecart:+.1%} de dérive "
                f"cumulée, au-delà du seuil de "
                f"{SEUIL_DERIVE_PRIX_ANCIENS:.0%}"
            )
    return messages


def controle_vraisemblance_rendements() -> list[str]:
    """Confronte les rendements saisis aux valeurs du point désormais connues.

    ``rendements_points.csv`` n'est plus la source principale : le moteur
    accumule des points là où il a le prix d'achat. Le fichier reste utilisé
    pour les régimes que la série ne couvre pas, et ce contrôle mesure de
    combien ses estimations s'écartaient de la réalité — le rendement
    instantané n'étant rien d'autre que
    ``valeur_service / (taux_appel × salaire_reference)``.
    """
    try:
        valeurs = _charge_points()
    except SourceAbsente as erreur:
        return [f"IGNORÉ  vraisemblance rendements : {erreur}"]

    serie = {**valeurs["serie"], **valeurs["complements"]}

    def au(regime: str, annee: int, mesure: str, defaut: float | None = None):
        candidates = [
            cle for cle in serie
            if cle.startswith(f"{regime}|") and cle.endswith(f"|{mesure}")
            and int(cle.split("|")[1]) <= annee
        ]
        if not candidates:
            return defaut
        return serie[max(candidates, key=lambda cle: int(cle.split("|")[1]))]

    lignes = charger_csv(REFERENCE / "regimes" / "rendements_points.csv")
    comparees, ecarts = 0, []
    for ligne in lignes:
        regime, debut, fin = ligne["regime"], int(ligne["debut"]), int(ligne["fin"])
        publies = []
        for annee in range(debut, min(fin, 2026) + 1):
            reference = au(regime, annee, "salaire_reference")
            service = au(regime, annee, "valeur_service")
            if reference and service:
                publies.append(service / (reference * au(regime, annee, "taux_appel", 1.0)))
        if not publies:
            continue
        comparees += 1
        calcule = sum(publies) / len(publies)
        saisi = float(ligne["rendement"])
        if abs(calcule - saisi) > 0.005:
            ecarts.append(
                f"SUSPECT rendement {regime} {debut}-{fin} : fiche {saisi:.2%}, "
                f"valeurs du point {calcule:.2%} en moyenne"
            )
    return [
        f"OK      vraisemblance rendements : {comparees} périodes confrontées aux "
        f"valeurs du point, {len(ecarts)} au-delà de 0,5 point",
        "        les régimes sans valeur du point publiée restent calculés au rendement",
    ] + ecarts


def controle_vraisemblance_ircantec() -> list[str]:
    """Confronte les barèmes Ircantec du producteur à ceux d'OpenFisca.

    C'est le seul régime pour lequel le dépôt dispose des deux : la Caisse des
    dépôts, qui gère l'Ircantec, et OpenFisca, qui la transcrit. Mesurer leur
    écart, c'est mesurer ce que vaut la transcription là où on ne peut pas la
    confronter — c'est-à-dire pour tous les autres régimes en points.
    """
    try:
        producteur = _serie_json("cdc_ircantec.json", "scripts/fetch/cdc_ircantec.py")
        transcription = _charge_points()["serie"]
    except SourceAbsente as erreur:
        return [f"IGNORÉ  vraisemblance Ircantec : {erreur}"]

    communes = sorted(set(producteur) & set(transcription))
    ecarts = [
        f"        écart {cle.replace('|', '/')} : Caisse des dépôts "
        f"{producteur[cle]}, OpenFisca {transcription[cle]}"
        for cle in communes
        if abs(producteur[cle] - transcription[cle]) > 1e-4
    ]
    return [
        f"OK      vraisemblance Ircantec : {len(communes)} valeurs comparées "
        f"producteur / transcription, {len(ecarts)} en désaccord",
    ] + ecarts[:6]


def controle_vraisemblance_point_insee() -> list[str]:
    """Confronte les valeurs du point d'OpenFisca à celles que l'INSEE publie.

    L'Ircantec mise à part, aucun producteur ne diffuse ses barèmes en série :
    la transcription d'OpenFisca était donc invérifiable pour les régimes qui
    pèsent le plus lourd, l'Agirc et l'Arrco. L'INSEE en diffuse la valeur de
    service depuis 2001, mensuelle, sous trois idbanks. Ce n'est pas le
    producteur, mais c'est une seconde transcription publique et indépendante :
    leur accord dit ce que vaut la première là où on ne peut pas remonter à la
    caisse.

    La tolérance est plus large que partout ailleurs — l'INSEE arrondit à quatre
    décimales, quand OpenFisca garde la conversion exacte depuis les francs.
    """
    try:
        insee = _point_insee()
        transcription = _cles_points("serie", substituees=False)
    except SourceAbsente as erreur:
        return [f"IGNORÉ  vraisemblance point Agirc-Arrco : {erreur}"]

    comparees, ecarts, ajoutees = 0, [], 0
    for regime, valeurs in sorted(insee.items()):
        for annee, valeur in sorted(valeurs.items()):
            cle = (regime, str(annee), "valeur_service")
            if cle not in transcription:
                ajoutees += 1
                continue
            comparees += 1
            if abs(transcription[cle] - valeur) > 1e-4:
                ecarts.append(
                    f"        écart {regime}/{annee} : INSEE {valeur}, "
                    f"OpenFisca {transcription[cle]}"
                )

    messages = [
        f"OK      vraisemblance point Agirc-Arrco : {comparees} années comparées "
        f"INSEE / OpenFisca, {len(ecarts)} en désaccord",
    ]
    if ajoutees:
        messages.append(
            f"        {ajoutees} année(s) que seul l'INSEE couvre, versées au "
            f"niveau haute : la transcription s'arrête avant lui"
        )
    return messages + ecarts[:6]


def controle_vraisemblance_plafond() -> list[str]:
    """Confronte le plafond d'OpenFisca à celui publié par l'INSEE, sur 2002-2026.

    C'est ce recoupement qui autorise à se servir d'OpenFisca pour les années
    anciennes : là où les deux sources se recouvrent, elles doivent tomber
    d'accord au centime près, faute de quoi la transcription est suspecte.
    """
    try:
        openfisca = _serie_json("openfisca_plafond.json",
                                "scripts/fetch/openfisca_plafond.py")
        insee = {cle[0]: valeur for cle, valeur in source_plafond().items()}
    except SourceAbsente as erreur:
        return [f"IGNORÉ  vraisemblance plafond : {erreur}"]

    communes = sorted(set(openfisca) & set(insee))
    anomalies = [
        f"SUSPECT plafond {annee} : OpenFisca {openfisca[annee]:.0f} €, "
        f"INSEE {insee[annee]:.0f} € — transcription à revoir"
        for annee in communes if abs(openfisca[annee] - insee[annee]) > 1.0
    ]
    return [
        f"OK      vraisemblance plafond : {len(communes)} années comparées "
        f"OpenFisca / INSEE, {len(anomalies)} en désaccord",
    ] + anomalies


# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    analyseur = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    analyseur.add_argument(
        "--appliquer", action="store_true",
        help="aligne les séries de référence sur les sources et les certifie",
    )
    arguments = analyseur.parse_args(argv)

    messages: list[str] = []
    journal: dict[str, dict] = {}
    retires: set[str] = set()
    for certification in CERTIFICATIONS:
        lignes, trace = certification.confronter(arguments.appliquer)
        messages.extend(lignes)
        if trace is None:
            retires.add(certification.nom)
        elif trace:
            journal[certification.nom] = trace

    messages.append("")
    messages.extend(controle_coherence_interne())
    messages.extend(controle_part_salariale())
    messages.append("")
    messages.extend(controle_vraisemblance_inflation())
    messages.extend(controle_vraisemblance_prix_anciens())
    messages.extend(controle_vraisemblance_esperance_65())
    messages.extend(controle_vraisemblance_age_annulation())
    messages.extend(controle_vraisemblance_minimum_garanti())
    messages.extend(controle_vraisemblance_plafond())
    messages.extend(controle_vraisemblance_cotisations())
    messages.extend(controle_vraisemblance_rendements())
    messages.extend(controle_vraisemblance_ircantec())
    messages.extend(controle_vraisemblance_point_insee())

    for message in messages:
        print(message)

    if arguments.appliquer and (journal or retires):
        # Le journal se COMPLÈTE, il ne se remplace pas. Les récupérateurs sont
        # indépendants et lents : on lance rarement les onze d'un coup, et
        # réécrire le fichier à partir des seules sources présentes ce jour-là
        # effacerait la trace de toutes les autres — c'est-à-dire la seule
        # pièce qui, sur un dépôt fraîchement cloné, dise d'où viennent les
        # valeurs certifiées.
        JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        consigne = {}
        if JOURNAL.exists():
            consigne = json.loads(JOURNAL.read_text(encoding="utf-8")).get("series", {})
        consigne.update(journal)
        for nom in retires:
            consigne.pop(nom, None)
        JOURNAL.write_text(
            json.dumps({"certifie_le": date.today().isoformat(), "series": consigne},
                       ensure_ascii=False, indent=1, sort_keys=True),
            encoding="utf-8",
        )
        print(f"\nCertification consignée dans {JOURNAL.relative_to(RACINE)}")
    elif not arguments.appliquer:
        print(
            "\nAucune valeur n'a été écrite : relancer avec --appliquer pour "
            "aligner les séries sur les sources et les faire passer au niveau "
            "certifiee. Ce qui reste hors de portée d'une source automatisable "
            "est énuméré dans docs/limites.md §1."
        )

    anomalies = [m for m in messages
                 if m.startswith(("ÉCART", "TROU", "SUSPECT", "MANQUE"))]
    if anomalies:
        print(f"\n{len(anomalies)} point(s) à examiner", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
