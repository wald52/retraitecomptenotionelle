"""Séries macroéconomiques : prix, salaires, productivité, plafond."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from .chargement import Fiabilite, SerieAnnuelle, charger_serie_annuelle, charger_yaml


@dataclass
class DonneesMacro:
    """Accès unifié aux séries annuelles servant à l'indexation et aux assiettes.

    Au-delà de la dernière année observée, les séries sont prolongées par le
    scénario de projection choisi (``reference/macro/hypotheses_projection.yaml``)
    et non par la dernière valeur connue. Les années projetées portent la
    fiabilité la plus basse, ce qui se propage jusqu'au résultat final.
    """

    racine: Path
    scenario_projection: str | None = None

    @cached_property
    def _hypotheses(self) -> dict:
        return charger_yaml(
            self.racine / "reference" / "macro" / "hypotheses_projection.yaml"
        )

    @cached_property
    def projection(self) -> dict:
        hypotheses = self._hypotheses
        nom = self.scenario_projection or hypotheses.get("scenario_par_defaut")
        scenarios = hypotheses.get("scenarios", {})
        if nom not in scenarios:
            raise KeyError(
                f"scénario de projection inconnu : {nom!r}. Disponibles : "
                + ", ".join(sorted(scenarios))
            )
        return {**scenarios[nom], "code": nom,
                "fin": int(hypotheses.get("annee_fin_projection", 2100))}

    def _prolonger(self, serie: SerieAnnuelle, cle: str) -> SerieAnnuelle:
        return serie.prolongee(float(self.projection[cle]), self.projection["fin"])

    @cached_property
    def inflation(self) -> SerieAnnuelle:
        """Variation annuelle de l'indice des prix à la consommation."""
        serie = charger_serie_annuelle(
            self.racine / "reference" / "macro" / "ipc_annuel.csv",
            colonne_valeur="variation",
            nom="inflation",
        )
        return self._prolonger(serie, "inflation")

    @cached_property
    def salaire_moyen(self) -> SerieAnnuelle:
        """Variation annuelle NOMINALE du salaire moyen par tête."""
        serie = charger_serie_annuelle(
            self.racine / "reference" / "macro" / "salaire_moyen.csv",
            colonne_valeur="variation_nominale",
            nom="salaire_moyen_nominal",
        )
        return self._prolonger(serie, "salaire_moyen_nominal")

    @cached_property
    def productivite(self) -> SerieAnnuelle:
        """Variation annuelle RÉELLE de la productivité du travail par tête."""
        serie = charger_serie_annuelle(
            self.racine / "reference" / "macro" / "productivite.csv",
            colonne_valeur="variation_reelle",
            nom="productivite_reelle",
        )
        return self._prolonger(serie, "productivite_reelle")

    @cached_property
    def smic_horaire(self) -> SerieAnnuelle:
        """SMIC horaire brut, en euros courants, barème du 1er janvier.

        Sert à la validation des trimestres : un trimestre s'acquiert par un
        montant cotisé, pas par le temps qui passe. Au-delà de la dernière
        valeur publiée, le SMIC suit la croissance du salaire moyen — c'est son
        indexation légale, à laquelle s'ajoutent des coups de pouce que le
        modèle ne prétend pas anticiper.
        """
        from .chargement import ValeurAnnuelle

        serie = charger_serie_annuelle(
            self.racine / "reference" / "macro" / "smic_horaire.csv",
            colonne_valeur="smic_horaire",
            nom="smic_horaire",
        )
        valeurs = {a: serie.brut(a) for a in serie.annees()}
        courant = serie(serie.derniere_annee)
        croissance = float(self.projection["salaire_moyen_nominal"])
        for annee in range(serie.derniere_annee + 1, self.projection["fin"] + 1):
            courant *= 1 + croissance
            valeurs[annee] = ValeurAnnuelle(annee, courant, Fiabilite.ESTIMEE)
        return SerieAnnuelle(valeurs, "smic_horaire", "escalier")

    @cached_property
    def heures_par_trimestre(self) -> SerieAnnuelle:
        """Heures de SMIC à cotiser pour valider un trimestre, par année.

        200 heures depuis 1972, 150 depuis 2014. Avant 1972 la validation ne
        dépendait pas du montant : la série ne commence donc qu'en 1972, et
        l'appelant valide quatre trimestres par année travaillée en deçà.
        """
        return charger_serie_annuelle(
            self.racine / "reference" / "legislation" / "validation_trimestres.csv",
            colonne_valeur="heures",
            nom="heures_par_trimestre",
        )

    def trimestres_valides(self, revenu: float, annee: int) -> int:
        """Trimestres qu'un revenu d'activité valide dans l'année.

        Quatre au plus, et zéro si le revenu n'atteint pas le seuil du premier.
        Avant 1972, aucun seuil de montant n'existait : une année travaillée
        vaut quatre trimestres.
        """
        if revenu <= 0:
            return 0
        heures = self.heures_par_trimestre
        if annee < heures.premiere_annee:
            return 4
        seuil = heures(annee) * self.smic_horaire(annee)
        if seuil <= 0:
            return 4
        return max(0, min(4, int(revenu // seuil)))

    @cached_property
    def plafond_securite_sociale(self) -> SerieAnnuelle:
        """Plafond annuel de la Sécurité sociale, en euros courants.

        Au-delà de la dernière valeur publiée, le plafond suit la croissance du
        salaire moyen, conformément à l'article L. 241-3 du code de la sécurité
        sociale.
        """
        from .chargement import ValeurAnnuelle

        serie = charger_serie_annuelle(
            self.racine / "reference" / "macro" / "plafond_securite_sociale.csv",
            colonne_valeur="pass_eur",
            nom="pass",
        )
        if not self._hypotheses.get("plafond_suit_salaire_moyen", True):
            return serie

        valeurs = {a: serie.brut(a) for a in serie.annees()}
        courant = serie(serie.derniere_annee)
        croissance = float(self.projection["salaire_moyen_nominal"])
        for annee in range(serie.derniere_annee + 1, self.projection["fin"] + 1):
            courant *= 1 + croissance
            valeurs[annee] = ValeurAnnuelle(annee, courant, Fiabilite.ESTIMEE)
        return SerieAnnuelle(valeurs, "pass", "escalier")

    # -- grandeurs dérivées --------------------------------------------------

    def salaire_moyen_reel(self, annee: int) -> float:
        """Croissance réelle du salaire moyen : (1+w)/(1+π) - 1."""
        return (1 + self.salaire_moyen(annee)) / (1 + self.inflation(annee)) - 1

    def productivite_nominale(self, annee: int) -> float:
        """Productivité réelle ramenée en nominal : (1+ρ)(1+π) - 1."""
        return (1 + self.productivite(annee)) * (1 + self.inflation(annee)) - 1

    def coefficient_prix(self, annee_depart: int, annee_arrivee: int) -> float:
        """Coefficient de passage d'euros de ``annee_depart`` en euros de ``annee_arrivee``.

        Sert à exprimer tous les résultats dans une unité comparable — sans quoi
        confronter une pension liquidée en 1975 à une pension de 2026 n'a aucun
        sens.
        """
        if annee_arrivee == annee_depart:
            return 1.0
        if annee_arrivee > annee_depart:
            coefficient = 1.0
            for annee in range(annee_depart + 1, annee_arrivee + 1):
                coefficient *= 1 + self.inflation(annee)
            return coefficient
        return 1.0 / self.coefficient_prix(annee_arrivee, annee_depart)

    def fiabilite_sur(self, debut: int, fin: int) -> Fiabilite:
        """Fiabilité du maillon le plus faible des séries macro sur la plage."""
        return min(
            self.inflation.fiabilite_minimale_sur(debut, fin),
            self.salaire_moyen.fiabilite_minimale_sur(debut, fin),
            self.productivite.fiabilite_minimale_sur(debut, fin),
        )
