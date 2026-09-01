"""Séries macroéconomiques : prix, salaires, productivité, plafond."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from .chargement import Fiabilite, SerieAnnuelle, charger_serie_annuelle, charger_yaml

#: Première année où les salaires portés au compte sont revalorisés sur les
#: PRIX et non plus sur les salaires. Avant elle, les arrêtés annuels de
#: revalorisation suivaient l'évolution des salaires ; à partir de 1987 ils
#: suivent celle des prix, ce que la loi du 22 juillet 1993 a ensuite inscrit
#: dans le code en retenant l'indice hors tabac. C'est une date de droit, pas
#: un choix de modélisation : elle est isolée ici pour être lisible d'un coup
#: d'œil et déplaçable d'un seul geste si la source venait à la préciser.
ANNEE_REVALORISATION_SUR_LES_PRIX = 1987


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

    def coefficient_smic(self, annee_depart: int, annee_arrivee: int) -> float:
        """Coefficient de passage par le SMIC, d'une année à l'autre.

        Plusieurs montants du droit positif ne suivent ni les prix ni les
        salaires mais **le salaire minimum de croissance** : le plafond
        d'écrêtement du minimum contributif depuis février 2014, les deux
        montants du minimum lui-même depuis la réforme du 14 avril 2023. Les
        revaloriser sur les prix, comme le faisait le modèle, les décrochait
        d'autant que le SMIC a progressé plus vite.
        """
        depart = self.smic_horaire(annee_depart)
        return self.smic_horaire(annee_arrivee) / depart if depart > 0 else 1.0

    @cached_property
    def revalorisation_portee_au_compte(self) -> tuple[dict[int, float], int | None]:
        """Indices de revalorisation publiés par la Cnav, et leur année de référence.

        UN indice par année de perception, et non une table à deux entrées : le
        coefficient entre deux années quelconques est le RAPPORT de leurs
        indices, parce que l'arrêté annuel applique un coefficient unique à tous
        les salaires déjà portés au compte quelle que soit leur année de
        perception. Reconstruire ainsi les colonnes publiées pour d'autres
        années de liquidation les retrouve à 0,13 % — l'arrondi à trois
        décimales de la table —, et
        ``scripts/fetch/cnav_revalorisation_salaires.py`` le revérifie à chaque
        exécution contre une circulaire plus ancienne.
        """
        import csv

        chemin = (self.racine / "reference" / "legislation"
                  / "revalorisation_salaires.csv")
        if not chemin.exists():
            return {}, None
        indices: dict[int, float] = {}
        reference: int | None = None
        with chemin.open(encoding="utf-8") as flux:
            lignes = (l for l in flux if not l.lstrip().startswith("#"))
            for ligne in csv.DictReader(lignes):
                indices[int(ligne["annee_perception"])] = float(ligne["coefficient"])
                reference = int(ligne["annee_reference"])
        return indices, reference

    def coefficient_revalorisation_portee_au_compte(self, annee_depart: int,
                                                    annee_arrivee: int) -> float:
        """Revalorisation d'un salaire PORTÉ AU COMPTE, telle que l'arrêté la fixe.

        C'est la grandeur qui commande le salaire annuel moyen : la moyenne
        porte sur les N MEILLEURES années, et « meilleures » se juge sur des
        salaires revalorisés — changer les coefficients ne déplace donc pas
        seulement le niveau de chaque année, cela change lesquelles sont
        retenues. Le modèle l'approchait par « les salaires jusqu'en 1986, les
        prix depuis », ce qui SUR-revalorisait les salaires anciens de 12 % sur
        quarante ans.

        Les indices viennent de la circulaire annuelle de la Cnav : c'est la
        caisse qui les applique qui les publie. Hors de la plage — perceptions
        antérieures à 1930, liquidations postérieures à l'année de référence —
        le modèle ancre sur la borne connue et prolonge par l'approximation, et
        ``docs/limites.md`` dit dans quel sens elle joue.
        """
        if annee_arrivee == annee_depart:
            return 1.0
        if annee_arrivee < annee_depart:
            return 1.0 / self.coefficient_revalorisation_portee_au_compte(
                annee_arrivee, annee_depart
            )
        indices, reference = self.revalorisation_portee_au_compte
        depart = indices.get(annee_depart)
        if depart is None:
            return self.coefficient_revalorisation_salaires(annee_depart, annee_arrivee)
        arrivee = indices.get(annee_arrivee)
        if arrivee is not None:
            return depart / arrivee
        # Au-delà de l'année de référence, on ANCRE sur elle et on n'approche
        # que le bout du chemin : une liquidation en 2030 lit les arrêtés
        # jusqu'en 2026 et n'approche que quatre années, au lieu de tout
        # approcher. En deçà de la première année publiée, il n'y a rien sur
        # quoi ancrer.
        if reference is not None and annee_arrivee > reference:
            return (depart / indices[reference]) * self.coefficient_revalorisation_salaires(
                reference, annee_arrivee
            )
        return self.coefficient_revalorisation_salaires(annee_depart, annee_arrivee)

    @cached_property
    def derniere_liquidation_revalorisee(self) -> int | None:
        """Dernière année de liquidation que les circulaires publiées couvrent."""
        return self.revalorisation_portee_au_compte[1]

    def coefficient_revalorisation_salaires(self, annee_depart: int,
                                            annee_arrivee: int) -> float:
        """Revalorisation d'un salaire porté au compte, de ``annee_depart`` à
        ``annee_arrivee``.

        Ce n'est pas l'indice des prix. Les salaires inscrits au compte d'un
        assuré sont revalorisés chaque année par un coefficient fixé par
        arrêté, et cet arrêté n'a pas toujours suivi les prix : jusqu'au milieu
        des années 1980, il suivait **l'évolution des salaires**. La bascule
        date de 1987, la loi du 22 juillet 1993 l'ayant ensuite inscrite dans
        la loi et rattachée à l'indice des prix hors tabac.

        L'écart n'est pas un détail de méthode. Sur les Trente Glorieuses, les
        salaires ont crû nettement plus vite que les prix : appliquer la règle
        des prix à ces années-là, comme le faisait le modèle, ramenait au
        compte des salaires anciens très en dessous de ce que le droit y a
        réellement inscrit, et minorait d'autant le salaire de référence des
        carrières commencées avant 1987.

        **Cette règle n'est plus qu'un REPLI.** Les coefficients des arrêtés
        eux-mêmes sont désormais dans le dépôt, et
        :meth:`coefficient_revalorisation_portee_au_compte` les sert là où ils
        existent — c'est-à-dire partout où le salaire de référence est calculé
        sur des années réellement portées au compte. Cette approximation ne vaut
        plus que hors de leur plage, et pour les régimes qui ne portent pas de
        salaire à un compte.
        """
        if annee_arrivee == annee_depart:
            return 1.0
        if annee_arrivee < annee_depart:
            return 1.0 / self.coefficient_revalorisation_salaires(
                annee_arrivee, annee_depart
            )
        coefficient = 1.0
        for annee in range(annee_depart + 1, annee_arrivee + 1):
            if annee >= ANNEE_REVALORISATION_SUR_LES_PRIX:
                coefficient *= 1 + self.inflation(annee)
            else:
                coefficient *= 1 + self.salaire_moyen(annee)
        return coefficient

    def fiabilite_sur(self, debut: int, fin: int) -> Fiabilite:
        """Fiabilité du maillon le plus faible des séries macro sur la plage."""
        return min(
            self.inflation.fiabilite_minimale_sur(debut, fin),
            self.salaire_moyen.fiabilite_minimale_sur(debut, fin),
            self.productivite.fiabilite_minimale_sur(debut, fin),
        )
