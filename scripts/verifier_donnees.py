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


def source_esperances() -> dict[tuple, float]:
    """Espérances de vie : e0 et e60 par l'INSEE, e65 par Eurostat.

    L'INSEE ne publie pas l'espérance de vie à 65 ans en série longue ; c'est la
    seule raison pour laquelle une donnée française transite ici par Eurostat.
    """
    valeurs: dict[tuple, float] = {}
    for mesure in ("e0", "e60"):
        for sexe in ("H", "F"):
            for periode, valeur in _observations(f"{mesure}_{sexe}").items():
                valeurs[(periode, sexe, mesure)] = valeur

    chemin = BRUT / "eurostat_esperance_vie.json"
    if not chemin.exists():
        raise SourceAbsente(
            f"{chemin} absent (lancer scripts/fetch/eurostat_esperance_vie.py)"
        )
    eurostat = json.loads(chemin.read_text(encoding="utf-8"))["serie"]
    for cle, valeur in eurostat.items():
        annee, sexe, mesure = cle.split("|")
        if mesure == "e65":
            valeurs[(annee, sexe, mesure)] = valeur
    return dict(sorted(valeurs.items()))


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

    def format(self, valeur: float) -> str:
        return f"{valeur:.{self.decimales}f}" if self.decimales else f"{valeur:.0f}"

    def confronter(self, appliquer: bool) -> tuple[list[str], dict]:
        try:
            attendu = self.source()
        except SourceAbsente as erreur:
            return [f"IGNORÉ  {self.nom} : {erreur}"], {}

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
                    neuve["fiabilite"] = "certifiee"
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
                ligne["fiabilite"] = "certifiee"

        if appliquer:
            lignes.sort(key=lambda l: tuple(
                (int(l[c]) if c == "annee" else l[c]) for c in self.cles
            ))
            _ecrire(self.chemin, commentaires, champs, lignes)

        verbe = "certifiées" if appliquer else "certifiables"
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
        nom="esperances_vie",
        chemin=REFERENCE / "mortalite" / "esperances_vie.csv",
        cles=("annee", "sexe", "mesure"),
        colonne="valeur",
        source=source_esperances,
        origine="INSEE BDM (e0, e60) et Eurostat demo_mlexpec (e65)",
        decimales=2,
        tolerance=0.05,
        unite=" ans",
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

    for message in messages:
        print(message)

    if arguments.appliquer and journal:
        JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        JOURNAL.write_text(
            json.dumps({"certifie_le": date.today().isoformat(), "series": journal},
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
