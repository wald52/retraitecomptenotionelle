"""Primitives de chargement, avec suivi de la fiabilité des données.

Principe directeur : aucune valeur ne circule dans le modèle sans son niveau de
fiabilité. Une simulation qui repose sur des séries reconstituées doit le dire,
et doit pouvoir refuser de s'exécuter si l'utilisateur exige mieux.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Iterator

import yaml


class Fiabilite(IntEnum):
    """Niveau de certification d'une donnée, du plus faible au plus fort."""

    ESTIMEE = 0     # reconstitution, ordre de grandeur
    MOYENNE = 1     # valeur publiée mais champ ou base incertains
    HAUTE = 2       # valeur publiée, recopiée, non recontrôlée
    CERTIFIEE = 3   # valeur recontrôlée automatiquement contre la source

    @classmethod
    def depuis_texte(cls, texte: str) -> "Fiabilite":
        cle = (texte or "").strip().lower()
        correspondance = {
            "estimee": cls.ESTIMEE,
            "estimée": cls.ESTIMEE,
            "projetee": cls.ESTIMEE,
            "projetée": cls.ESTIMEE,
            "moyenne": cls.MOYENNE,
            "haute": cls.HAUTE,
            "certifiee": cls.CERTIFIEE,
            "certifiée": cls.CERTIFIEE,
        }
        if cle not in correspondance:
            raise ValueError(f"niveau de fiabilité inconnu : {texte!r}")
        return correspondance[cle]

    def __str__(self) -> str:  # pragma: no cover - confort d'affichage
        return self.name.lower()


class DonneeInsuffisante(RuntimeError):
    """Levée quand la fiabilité disponible est inférieure à celle exigée."""


@dataclass(frozen=True)
class ValeurAnnuelle:
    annee: int
    valeur: float
    fiabilite: Fiabilite


class SerieAnnuelle:
    """Série indexée par année, avec fiabilité et interpolation contrôlée.

    Deux comportements sont distingués :

    * ``escalier`` (défaut) — la valeur d'une année absente est celle de la
      dernière année renseignée. C'est le comportement correct pour des
      paramètres juridiques : un taux reste en vigueur jusqu'à sa modification.
    * ``lineaire`` — interpolation entre les deux années encadrantes. Correct
      pour des grandeurs continues : l'espérance de vie à 60 ans est désormais
      renseignée chaque année, celle à 65 ans ne l'est qu'avant 1986 par points
      espacés, et c'est là que l'interpolation sert encore.
    """

    def __init__(
        self,
        valeurs: dict[int, ValeurAnnuelle],
        nom: str,
        interpolation: str = "escalier",
    ) -> None:
        self.nom = nom
        self.interpolation = interpolation
        self._valeurs = dict(sorted(valeurs.items()))
        if not self._valeurs:
            raise ValueError(f"série {nom!r} vide")
        self._annees = list(self._valeurs)

    # -- accès ---------------------------------------------------------------

    @property
    def premiere_annee(self) -> int:
        return self._annees[0]

    @property
    def derniere_annee(self) -> int:
        return self._annees[-1]

    def brut(self, annee: int) -> ValeurAnnuelle:
        """Valeur avec sa fiabilité, en appliquant la règle d'interpolation."""
        if annee in self._valeurs:
            return self._valeurs[annee]

        if annee < self.premiere_annee:
            base = self._valeurs[self.premiere_annee]
            return ValeurAnnuelle(annee, base.valeur, Fiabilite.ESTIMEE)
        if annee > self.derniere_annee:
            base = self._valeurs[self.derniere_annee]
            return ValeurAnnuelle(annee, base.valeur, Fiabilite.ESTIMEE)

        precedente = max(a for a in self._annees if a < annee)
        suivante = min(a for a in self._annees if a > annee)
        avant, apres = self._valeurs[precedente], self._valeurs[suivante]

        if self.interpolation == "escalier":
            return ValeurAnnuelle(annee, avant.valeur, avant.fiabilite)

        poids = (annee - precedente) / (suivante - precedente)
        valeur = avant.valeur + poids * (apres.valeur - avant.valeur)
        # L'interpolation ne peut pas être plus fiable que ses bornes, et une
        # valeur interpolée n'est jamais « certifiée ».
        fiabilite = min(avant.fiabilite, apres.fiabilite, Fiabilite.HAUTE)
        return ValeurAnnuelle(annee, valeur, fiabilite)

    def __call__(self, annee: int, fiabilite_minimale: Fiabilite = Fiabilite.ESTIMEE) -> float:
        v = self.brut(annee)
        if v.fiabilite < fiabilite_minimale:
            raise DonneeInsuffisante(
                f"série {self.nom!r}, année {annee} : fiabilité {v.fiabilite} "
                f"< minimum exigé {fiabilite_minimale}"
            )
        return v.valeur

    def fiabilite(self, annee: int) -> Fiabilite:
        return self.brut(annee).fiabilite

    def annees(self) -> Iterator[int]:
        return iter(self._annees)

    def prolongee(self, valeur: float, jusqu_a: int,
                  fiabilite: Fiabilite = Fiabilite.ESTIMEE) -> "SerieAnnuelle":
        """Nouvelle série prolongée par une valeur constante jusqu'à ``jusqu_a``.

        Sert à projeter au-delà de la dernière observation. La série d'origine
        n'est pas modifiée, et les années ajoutées portent la fiabilité
        indiquée — jamais celle des années observées.
        """
        valeurs = dict(self._valeurs)
        for annee in range(self.derniere_annee + 1, jusqu_a + 1):
            valeurs[annee] = ValeurAnnuelle(annee, valeur, fiabilite)
        return SerieAnnuelle(valeurs, self.nom, self.interpolation)

    def fiabilite_minimale_sur(self, debut: int, fin: int) -> Fiabilite:
        """Maillon le plus faible sur une plage — c'est lui qui qualifie un résultat."""
        return min((self.brut(a).fiabilite for a in range(debut, fin + 1)), default=Fiabilite.ESTIMEE)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"SerieAnnuelle({self.nom!r}, {self.premiere_annee}-{self.derniere_annee}, "
            f"{len(self._valeurs)} points, {self.interpolation})"
        )


def charger_serie_annuelle(
    chemin: Path,
    colonne_valeur: str,
    nom: str | None = None,
    interpolation: str = "escalier",
    filtre: dict[str, str] | None = None,
) -> SerieAnnuelle:
    """Charge un CSV ``annee,<colonne_valeur>,fiabilite`` en série annuelle.

    Les lignes commençant par ``#`` sont des commentaires : elles portent la
    documentation de provenance et sont ignorées à la lecture.
    """
    valeurs: dict[int, ValeurAnnuelle] = {}
    with chemin.open(encoding="utf-8") as flux:
        lignes = (ligne for ligne in flux if not ligne.lstrip().startswith("#"))
        for enregistrement in csv.DictReader(lignes):
            if filtre and any(enregistrement.get(k) != v for k, v in filtre.items()):
                continue
            annee = int(enregistrement["annee"])
            valeurs[annee] = ValeurAnnuelle(
                annee=annee,
                valeur=float(enregistrement[colonne_valeur]),
                fiabilite=Fiabilite.depuis_texte(enregistrement["fiabilite"]),
            )
    if not valeurs:
        raise ValueError(f"aucune ligne exploitable dans {chemin} (filtre={filtre})")
    return SerieAnnuelle(valeurs, nom or f"{chemin.stem}.{colonne_valeur}", interpolation)


def charger_yaml(chemin: Path) -> dict:
    with chemin.open(encoding="utf-8") as flux:
        return yaml.safe_load(flux) or {}


def journal_certification(racine: Path) -> dict:
    """Trace du dernier recontrôle des séries contre leurs sources.

    Écrite par ``scripts/verifier_donnees.py --appliquer``. Les téléchargements
    bruts ne sont pas versionnés : ce journal est la seule pièce qui, sur un
    dépôt cloné, dise d'où viennent les valeurs marquées ``certifiee``. Son
    absence n'est pas une erreur — elle signifie qu'aucune certification n'a
    encore eu lieu.
    """
    chemin = racine / "derive" / "certification.json"
    if not chemin.exists():
        return {}
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):  # pragma: no cover - fichier abîmé
        return {}


@dataclass(frozen=True)
class PeriodeNonTravaillee:
    """Ce qu'ouvre une période non travaillée, selon son motif."""

    motif: str
    trimestres_assimiles: int
    ouvre_droits_complementaires: bool
    #: Le parent est-il affilié à l'assurance vieillesse des parents au foyer
    #: pendant cette période ? La CNAF cotise alors au régime général sur une
    #: assiette forfaitaire égale au SMIC, et ce salaire est PORTÉ AU COMPTE :
    #: c'est ce qui distingue l'AVPF d'une période assimilée, laquelle valide
    #: des trimestres sans jamais ajouter de salaire.
    avpf: bool = False
    fiabilite: Fiabilite = Fiabilite.ESTIMEE


def charger_periodes_non_travaillees(racine: Path) -> dict[str, PeriodeNonTravaillee]:
    """Table des motifs d'interruption et de ce que chacun ouvre."""
    chemin = racine / "reference" / "legislation" / "periodes_non_travaillees.csv"
    table: dict[str, PeriodeNonTravaillee] = {}
    if not chemin.exists():
        return table
    with chemin.open(encoding="utf-8") as flux:
        lignes = (l for l in flux if not l.lstrip().startswith("#"))
        for ligne in csv.DictReader(lignes):
            table[ligne["motif"]] = PeriodeNonTravaillee(
                motif=ligne["motif"],
                trimestres_assimiles=int(ligne["trimestres_assimiles"]),
                ouvre_droits_complementaires=(
                    ligne["ouvre_droits_complementaires"].strip().lower() == "oui"
                ),
                avpf=ligne.get("avpf", "non").strip().lower() == "oui",
                fiabilite=Fiabilite.depuis_texte(ligne["fiabilite"]),
            )
    return table
