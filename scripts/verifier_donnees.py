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


def source_productivite() -> dict[tuple, float]:
    """Variation réelle de la productivité par tête.

    Valeur ajoutée en volume (prix chaînés) rapportée à l'emploi intérieur
    total en personnes physiques. Le concept est bien celui **par tête** retenu
    par le modèle, et non la productivité horaire — les deux divergent
    fortement après 1982.
    """
    variations = _variations(_rapport("valeur_ajoutee_volume", "emploi_total"))
    return {(str(a),): v for a, v in sorted(variations.items())}


def source_plafond() -> dict[tuple, float]:
    """Plafond annuel de la Sécurité sociale, à partir du plafond mensuel.

    Le plafond est fixé pour l'année civile : les douze observations d'une même
    année doivent être identiques, et une année où elles ne le sont pas est
    écartée plutôt que moyennée.
    """
    mensuel = _observations("plafond_mensuel")
    par_annee: dict[int, list[float]] = {}
    for periode, valeur in mensuel.items():
        par_annee.setdefault(int(periode[:4]), []).append(valeur)
    return {
        (str(annee),): round(valeurs[0] * 12)
        for annee, valeurs in sorted(par_annee.items())
        if len(valeurs) == 12 and len(set(valeurs)) == 1
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


def source_valeurs_point() -> dict[tuple, float]:
    """Salaires de référence, valeurs de service et taux d'appel, par régime.

    Ces trois grandeurs suffisent à reconstituer exactement une pension en
    points : la cotisation d'une année divisée par le salaire de référence et
    par le taux d'appel donne les points acquis, que la valeur de service
    convertit en rente à la liquidation.

    Ce que la Caisse des dépôts publie elle-même est retiré d'ici : deux
    contrôles ne doivent pas se disputer les mêmes lignes, et le producteur
    l'emporte sur la transcription. Si son fichier manque, OpenFisca reprend
    toute la couverture — au niveau ``haute``, comme il se doit.
    """
    valeurs = _cles_points("serie", substituees=False)
    try:
        producteur = set(source_valeurs_point_ircantec())
    except SourceAbsente:
        return valeurs
    return {cle: valeur for cle, valeur in valeurs.items() if cle not in producteur}


def source_valeurs_point_substituees() -> dict[tuple, float]:
    """Valeurs de l'UNIRS servant de point Arrco avant l'unification de 1999.

    Publiées, mais pour une autre caisse que celle que le modèle appelle
    « arrco » — d'où un niveau en retrait.
    """
    return _cles_points("serie", substituees=True)


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
    `haute`, jamais `certifiee`.
    """
    serie = _serie_json("openfisca_point_indice.json",
                        "scripts/fetch/openfisca_point_indice.py")
    return {(annee,): valeur for annee, valeur in sorted(serie.items())}


def _parametres_retraite() -> dict[str, float]:
    return _serie_json("dila_legi_parametres_retraite.json",
                       "scripts/fetch/dila_legi_parametres_retraite.py")


def _table_legi(prefixe: str) -> dict[tuple, float]:
    """Une des tables par génération lues dans la loi, mise en forme de clés."""
    return {
        (cle.split("|")[1],): valeur
        for cle, valeur in sorted(_parametres_retraite().items(),
                                  key=lambda kv: int(kv[0].split("|")[1]))
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


def source_coefficient_minoration() -> dict[tuple, float]:
    """Coefficient de minoration par génération — R. 351-27 II."""
    return _table_legi("coefficient_minoration")


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
    """
    connues = set(_cles_points("serie", substituees=False))
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


def source_employeur_cnracl() -> dict[tuple, float]:
    """Contribution employeur à la CNRACL, depuis 1948.

    La fonction publique territoriale et hospitalière n'a jamais eu le problème
    de l'État : ses employeurs cotisent à une caisse, dont le taux est fixé par
    décret depuis 1947. Transcription OpenFisca des décrets et des barèmes de la
    Caisse des dépôts : niveau `haute`.
    """
    return {
        (annee, "cnracl"): taux
        for annee, taux in sorted(_contributions_employeur("cnracl").items())
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

    def format(self, valeur: float) -> str:
        return f"{valeur:.{self.decimales}f}" if self.decimales else f"{valeur:.0f}"

    def confronter(self, appliquer: bool) -> tuple[list[str], dict]:
        try:
            attendu = self.source()
        except SourceAbsente as erreur:
            return [f"IGNORÉ  {self.nom} : {erreur}"], {}

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
                (int(l[c]) if c == "annee" else l[c]) for c in self.cles
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
    ),
    Certification(
        nom="valeurs_point_unirs",
        chemin=REFERENCE / "regimes" / "valeurs_point.csv",
        cles=("regime", "annee", "mesure"),
        colonne="valeur",
        source=source_valeurs_point_substituees,
        origine="OpenFisca-France-Pension, UNIRS tenant lieu de point Arrco avant 1999",
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
        publie = sum(serie[str(a)]["total"] for a in annees) / len(annees)
        saisi = float(periode["taux_cotisation_retraite"])
        if abs(publie - saisi) > 0.002:
            anomalies.append(
                f"SUSPECT cotisations regime_general {periode['debut']}-{periode['fin']} : "
                f"fiche {saisi:.2%}, OpenFisca {publie:.2%} en moyenne sur "
                f"{annees[0]}-{annees[-1]}"
            )
    messages.append(
        f"OK      vraisemblance cotisations : {comparees} périodes du régime général "
        f"comparées à OpenFisca, {len(anomalies)} au-delà de 0,2 point"
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
    for certification in CERTIFICATIONS:
        lignes, trace = certification.confronter(arguments.appliquer)
        messages.extend(lignes)
        if trace:
            journal[certification.nom] = trace

    messages.append("")
    messages.extend(controle_coherence_interne())
    messages.append("")
    messages.extend(controle_vraisemblance_inflation())
    messages.extend(controle_vraisemblance_prix_anciens())
    messages.extend(controle_vraisemblance_esperance_65())
    messages.extend(controle_vraisemblance_plafond())
    messages.extend(controle_vraisemblance_cotisations())
    messages.extend(controle_vraisemblance_rendements())
    messages.extend(controle_vraisemblance_ircantec())
    messages.extend(controle_vraisemblance_point_insee())

    for message in messages:
        print(message)

    if arguments.appliquer and journal:
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

    anomalies = [m for m in messages if m.startswith(("ÉCART", "TROU", "SUSPECT"))]
    if anomalies:
        print(f"\n{len(anomalies)} point(s) à examiner", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
