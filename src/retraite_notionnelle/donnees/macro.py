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
    def revalorisation_portee_au_compte(self) -> list[tuple[int, int, dict[int, float]]]:
        """Colonnes de revalorisation publiées par la Cnav, par date d'effet.

        Une colonne par circulaire : année de la date d'effet, MOIS de cette
        date, et le coefficient par année de perception. Triées par date.

        Le mois n'était pas conservé — seul un drapeau disait si la date était
        le 1er janvier. Or les circulaires ne prennent pas toutes effet au
        1er janvier, et deux d'entre elles portent la même année : la
        revalorisation exceptionnelle du 1er juillet 2022 dépasse celle du
        1er janvier de 3,9 %. Sans le mois, toutes les liquidations de 2022
        lisaient la colonne de janvier, y compris celles du second semestre,
        auxquelles la caisse oppose celle de juillet.

        Le coefficient entre deux années se lit dans UNE colonne, par rapport de
        deux de ses valeurs. Une seule colonne suffirait donc en théorie ; en
        pratique la caisse arrondit sa table à trois décimales et repart chaque
        année de la précédente, si bien que reconstruire une colonne depuis une
        autre dérive avec la distance — 0,02 % à deux ans, 0,16 % à sept.
        """
        import csv

        chemin = (self.racine / "reference" / "legislation"
                  / "revalorisation_salaires.csv")
        if not chemin.exists():
            return []
        colonnes: dict[str, dict[int, float]] = {}
        with chemin.open(encoding="utf-8") as flux:
            lignes = (l for l in flux if not l.lstrip().startswith("#"))
            for ligne in csv.DictReader(lignes):
                colonnes.setdefault(ligne["date_effet"], {})[
                    int(ligne["annee_perception"])
                ] = float(ligne["coefficient"])
        return sorted(
            (int(effet[:4]), int(effet[5:7]), table)
            for effet, table in colonnes.items()
        )

    def coefficient_revalorisation_portee_au_compte(self, annee_depart: int,
                                                    annee_arrivee: int,
                                                    mois_arrivee: int = 1) -> float:
        """Revalorisation d'un salaire PORTÉ AU COMPTE, telle que l'arrêté la fixe.

        C'est la grandeur qui commande le salaire annuel moyen : la moyenne
        porte sur les N MEILLEURES années, et « meilleures » se juge sur des
        salaires revalorisés — changer les coefficients ne déplace donc pas
        seulement le niveau de chaque année, cela change lesquelles sont
        retenues. Le modèle l'approchait par « les salaires jusqu'en 1986, les
        prix depuis », ce qui SUR-revalorisait les salaires anciens de 12 % sur
        quarante ans.

        Trois chemins, du plus sûr au moins sûr :

        1. la colonne PUBLIÉE en vigueur À LA DATE DE LIQUIDATION — la plus
           récente dont la date d'effet ne lui est pas postérieure, dans son
           année. Le coefficient est alors celui que la caisse oppose, sans
           calcul. C'est le mois qui désigne la colonne : un départ du
           1er août 2022 relève de la circulaire du 1er juillet, un départ du
           1er mars 2022 de celle du 1er janvier, et les deux diffèrent de
           3,9 % ;
        2. sinon la colonne publiée la PLUS PROCHE, par rapport de deux de ses
           valeurs. Ancrer sur la plus proche plutôt que sur la plus récente
           divise la dérive par dix : 0,01 % au lieu de 0,16 % ;
        3. hors de toute colonne, l'ancienne approximation, ancrée sur la borne
           connue quand il y en a une.

        ``docs/limites.md`` dit ce que chacun coûte.
        """
        if annee_arrivee == annee_depart:
            return 1.0
        if annee_arrivee < annee_depart:
            return 1.0 / self.coefficient_revalorisation_portee_au_compte(
                annee_arrivee, annee_depart
            )
        colonnes = self.revalorisation_portee_au_compte
        if not colonnes:
            return self.coefficient_revalorisation_salaires(annee_depart, annee_arrivee)

        en_vigueur = [
            table for annee, mois, table in colonnes
            if annee == annee_arrivee and mois <= mois_arrivee
            and annee_depart in table
        ]
        if en_vigueur:
            return en_vigueur[-1][annee_depart]

        # La colonne la plus proche qui porte les deux années. Une colonne dont
        # la date d'effet est POSTÉRIEURE à la liquidation ne peut pas servir
        # pour l'année de celle-ci : son millésime porte déjà une revalorisation
        # que l'assuré n'a pas connue.
        candidates = [
            (abs(annee - annee_arrivee), table)
            for annee, mois, table in colonnes
            if annee_depart in table and annee_arrivee in table
            and (annee != annee_arrivee or mois <= mois_arrivee)
        ]
        if candidates:
            _, table = min(candidates, key=lambda c: c[0])
            return table[annee_depart] / table[annee_arrivee]

        # Au-delà de la dernière colonne, on ANCRE sur elle et on n'approche que
        # le bout du chemin : une liquidation en 2030 lit les circulaires
        # jusqu'en 2026 et n'approche que quatre années, au lieu de tout
        # approcher. En deçà de la première année publiée, il n'y a rien sur
        # quoi ancrer.
        derniere, _, table = colonnes[-1]
        if annee_arrivee > derniere and annee_depart in table:
            return table[annee_depart] * self.coefficient_revalorisation_salaires(
                derniere, annee_arrivee
            )
        return self.coefficient_revalorisation_salaires(annee_depart, annee_arrivee)

    @cached_property
    def derniere_liquidation_revalorisee(self) -> int | None:
        """Dernière année de liquidation que les circulaires publiées couvrent."""
        colonnes = self.revalorisation_portee_au_compte
        return colonnes[-1][0] if colonnes else None

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
