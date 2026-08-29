"""Catalogue des régimes de retraite, de 1930 à aujourd'hui."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from .chargement import Fiabilite, charger_yaml

#: Familles de régimes reconnues.
FAMILLES = {
    "base_prive",
    "complementaire_prive",
    "fonction_publique",
    "special",
    "non_salarie",
    "agricole",
    "liberal",
    "additionnel_capitalise",
}

#: Assiettes reconnues et leur borne exprimée en plafonds de la Sécurité sociale.
#: ``None`` signifie « pas de borne supérieure ».
BORNES_ASSIETTE: dict[str, tuple[float, float | None]] = {
    "plafonnee": (0.0, 1.0),
    "deplafonnee": (0.0, None),
    "tranche_1": (0.0, 1.0),
    "tranche_a": (0.0, 1.0),
    "tranche_2": (1.0, 8.0),
    "tranche_b": (1.0, 4.0),
    "tranche_c": (4.0, 8.0),
    # Tranches propres au régime de base des professions libérales : la
    # première s'arrêtait à 0,85 plafond avant 2015, la seconde part de zéro
    # depuis — les deux se recouvrent donc, et c'est bien la règle du régime.
    "plafonnee_085_pass": (0.0, 0.85),
    "tranche_085_5_pass": (0.85, 5.0),
    "plafonnee_5_pass": (0.0, 5.0),
    "hors_primes": (0.0, None),
    "primes_uniquement": (0.0, None),
    "forfaitaire": (0.0, None),
    "sans_objet": (0.0, None),
}


@dataclass(frozen=True)
class PeriodeRegime:
    """Jeu de paramètres d'un régime sur une plage d'années."""

    debut: int
    fin: int | None
    type_calcul: str
    age_ouverture: float
    age_taux_plein: float
    duree_requise_trimestres: int | None
    #: La durée requise suit-elle la génération plutôt que l'année de
    #: liquidation ? Vrai depuis la loi Balladur pour les régimes alignés, la
    #: loi Fillon pour la fonction publique, leurs réformes propres pour les
    #: régimes spéciaux. La valeur ci-dessus sert alors de repli.
    duree_requise_par_generation: bool
    #: L'âge d'ouverture suit-il la génération plutôt que l'année de
    #: liquidation ? Vrai pour les régimes alignés sur l'âge légal général.
    age_ouverture_par_generation: bool
    #: L'âge d'annulation de la décote suit-il la génération ? Vrai depuis la
    #: loi du 9 novembre 2010 pour les régimes alignés (65 -> 67 ans).
    age_taux_plein_par_generation: bool
    #: Le coefficient de minoration suit-il la génération ? Vrai pour les
    #: régimes alignés : la table de l'article R. 351-27 vaut aussi bien pour
    #: l'ancien droit (2,5 %) que pour la montée en charge de la loi Fillon.
    decote_par_generation: bool
    #: Le nombre d'années retenues au salaire de référence suit-il la
    #: génération ? Vrai depuis la loi Balladur (dix à vingt-cinq années).
    salaire_reference_par_generation: bool
    taux_plein: float | None
    salaire_reference: str
    assiette: str
    taux_cotisation_retraite: float
    #: Périmètre du taux ci-dessus : ``total`` (salarié + employeur, cas du
    #: privé) ou ``agent_seul`` (retenue de l'agent seule, cas de la fonction
    #: publique et des régimes spéciaux).
    perimetre_taux: str
    decote_par_trimestre: float | None
    #: Barème de décote applicable. ``regime_aligne`` (défaut) applique le
    #: coefficient ci-dessus, éventuellement lu à la génération ;
    #: ``fonction_publique`` applique celui de l'article L. 14 du code des
    #: pensions, dont le coefficient ET l'âge d'annulation montent en charge de
    #: 2006 à 2020 (``legislation/decote_fonction_publique.csv``).
    bareme_decote: str
    #: La durée d'assurance annule-t-elle la décote ? Vrai depuis l'ordonnance
    #: du 26 mars 1982, qui ouvre le taux plein à 60 ans à qui a la durée
    #: requise. Avant elle, le taux ne dépendait QUE de l'âge : 20 % à 60 ans
    #: majorés de 4 points par année différée jusqu'en 1971, 50 % à 65 ans
    #: diminués de 5 points par année anticipée ensuite. Une carrière longue
    #: n'y changeait rien.
    decote_annulee_par_la_duree: bool
    #: Nombre maximal de trimestres de décote opposables. Vingt dans tous les
    #: régimes qui en appliquent une : au-delà, le taux ne descend plus.
    #: ``None`` lève le plafond.
    decote_trimestres_maximum: int | None
    surcote_par_trimestre: float | None
    #: Barème d'abattement des régimes en points. ``decote_du_regime_de_base``
    #: applique le coefficient de minoration ci-dessus ; ``agirc_arrco``
    #: applique les coefficients d'anticipation propres à ce régime.
    abattement_points: str
    #: Plafond en euros de la majoration pour enfants, et année à laquelle il
    #: est publié. Le plafond suit ensuite la valeur de service du point.
    plafond_majoration_enfants: float | None
    plafond_majoration_annee: int | None
    #: Nombre de points attribués quand l'assiette atteint le repère
    #: ci-dessous. Sert aux régimes dont le barème est écrit en POINTS et non
    #: en prix d'achat — le régime de base des libéraux, la complémentaire
    #: agricole. ``None`` : les points s'achètent, cf. ``valeurs_point.csv``.
    points_maximum: float | None
    #: Nombre de points garantis chaque année à qui cotise au régime, quelle
    #: que soit son assiette. C'est la garantie minimale de points de l'Agirc :
    #: 120 points par an de 1989 à 2018, y compris pour un cadre dont la
    #: tranche B est nulle. Droit GRATUIT, sans contrepartie de cotisation.
    points_minimum_annuels: float | None
    #: Repère d'assiette, exprimé en heures de SMIC. ``None`` : le repère est
    #: la borne haute de l'assiette, en plafonds de la Sécurité sociale.
    assiette_repere_smic: float | None
    #: L'assiette est-elle relevée au repère quand elle lui est inférieure ?
    #: C'est l'assiette minimale de la complémentaire agricole.
    assiette_plancher: bool
    avantages_non_contributifs: tuple[str, ...]
    notes: str = ""

    def repere_assiette(self, pass_annuel: float, smic_horaire: float) -> float:
        """Assiette qui ouvre droit à ``points_maximum`` points."""
        if self.assiette_repere_smic is not None:
            return self.assiette_repere_smic * smic_horaire
        borne_basse, borne_haute = self.bornes_assiette_en_pass()
        if borne_haute is None:
            return 0.0
        return (borne_haute - borne_basse) * pass_annuel

    def couvre(self, annee: int) -> bool:
        return self.debut <= annee and (self.fin is None or annee <= self.fin)

    def bornes_assiette_en_pass(self) -> tuple[float, float | None]:
        return BORNES_ASSIETTE.get(self.assiette, (0.0, None))


@dataclass
class Regime:
    code: str
    nom: str
    famille: str
    source_id: str
    fiabilite: Fiabilite
    creation: int
    fermeture: int | None
    extinction: int | None
    succede_a: tuple[str, ...]
    integre_dans: str | None
    population: str
    hors_repartition: bool
    periodes: tuple[PeriodeRegime, ...] = field(default_factory=tuple)

    def periode(self, annee: int) -> PeriodeRegime | None:
        """Paramètres applicables une année donnée.

        Quand plusieurs périodes couvrent la même année — cas des régimes à
        tranches, où deux fiches coexistent pour la tranche 1 et la tranche 2 —
        la première est retournée ; utiliser :meth:`periodes_actives` pour les
        obtenir toutes.
        """
        for p in self.periodes:
            if p.couvre(annee):
                return p
        return None

    def periodes_actives(self, annee: int) -> tuple[PeriodeRegime, ...]:
        return tuple(p for p in self.periodes if p.couvre(annee))

    def ouvert(self, annee: int) -> bool:
        """Le régime accepte-t-il de nouveaux affiliés cette année-là ?"""
        if annee < self.creation:
            return False
        if self.fermeture is not None and annee >= self.fermeture:
            return False
        return True

    def vivant(self, annee: int) -> bool:
        """Le régime sert-il encore des droits cette année-là ?"""
        if annee < self.creation:
            return False
        return self.extinction is None or annee < self.extinction


class CatalogueRegimes:
    """Ensemble des régimes chargés depuis ``data/reference/regimes/*.yaml``."""

    def __init__(self, racine: Path) -> None:
        self.racine = racine
        self._regimes: dict[str, Regime] = {}
        dossier = racine / "reference" / "regimes"
        for chemin in sorted(dossier.glob("*.yaml")):
            if chemin.name.startswith("_"):
                continue
            contenu = charger_yaml(chemin)
            for fiche in contenu.get("regimes", []):
                regime = self._construire(fiche, chemin)
                if regime.code in self._regimes:
                    raise ValueError(f"code de régime dupliqué : {regime.code}")
                self._regimes[regime.code] = regime
        if not self._regimes:
            raise ValueError(f"aucun régime chargé depuis {dossier}")

    @staticmethod
    def _construire(fiche: dict, chemin: Path) -> Regime:
        manquants = {"code", "nom", "famille", "fiabilite"} - set(fiche)
        if manquants:
            raise ValueError(f"{chemin.name} : champs manquants {sorted(manquants)}")
        if fiche["famille"] not in FAMILLES:
            raise ValueError(
                f"{chemin.name} / {fiche['code']} : famille inconnue {fiche['famille']!r}"
            )
        periodes = tuple(
            PeriodeRegime(
                debut=int(p["debut"]),
                fin=None if p.get("fin") is None else int(p["fin"]),
                type_calcul=p["type_calcul"],
                age_ouverture=float(p["age_ouverture"]),
                age_taux_plein=float(p["age_taux_plein"]),
                duree_requise_trimestres=(
                    None if p.get("duree_requise_trimestres") is None
                    else int(p["duree_requise_trimestres"])
                ),
                duree_requise_par_generation=bool(
                    p.get("duree_requise_par_generation", False)
                ),
                age_ouverture_par_generation=bool(
                    p.get("age_ouverture_par_generation", False)
                ),
                age_taux_plein_par_generation=bool(
                    p.get("age_taux_plein_par_generation", False)
                ),
                decote_par_generation=bool(p.get("decote_par_generation", False)),
                salaire_reference_par_generation=bool(
                    p.get("salaire_reference_par_generation", False)
                ),
                taux_plein=None if p.get("taux_plein") is None else float(p["taux_plein"]),
                salaire_reference=p.get("salaire_reference", "sans_objet"),
                assiette=p.get("assiette", "deplafonnee"),
                taux_cotisation_retraite=float(p["taux_cotisation_retraite"]),
                perimetre_taux=p.get("perimetre_taux", "total"),
                decote_par_trimestre=(
                    None if p.get("decote_par_trimestre") is None
                    else float(p["decote_par_trimestre"])
                ),
                bareme_decote=p.get("bareme_decote", "regime_aligne"),
                decote_annulee_par_la_duree=bool(
                    p.get("decote_annulee_par_la_duree", True)
                ),
                decote_trimestres_maximum=(
                    None if "decote_trimestres_maximum" in p
                    and p["decote_trimestres_maximum"] is None
                    else int(p.get("decote_trimestres_maximum", 20))
                ),
                surcote_par_trimestre=(
                    None if p.get("surcote_par_trimestre") is None
                    else float(p["surcote_par_trimestre"])
                ),
                abattement_points=p.get("abattement_points", "decote_du_regime_de_base"),
                plafond_majoration_enfants=(
                    None if p.get("plafond_majoration_enfants") is None
                    else float(p["plafond_majoration_enfants"])
                ),
                plafond_majoration_annee=(
                    None if p.get("plafond_majoration_annee") is None
                    else int(p["plafond_majoration_annee"])
                ),
                points_maximum=(
                    None if p.get("points_maximum") is None
                    else float(p["points_maximum"])
                ),
                points_minimum_annuels=(
                    None if p.get("points_minimum_annuels") is None
                    else float(p["points_minimum_annuels"])
                ),
                assiette_repere_smic=(
                    None if p.get("assiette_repere_smic") is None
                    else float(p["assiette_repere_smic"])
                ),
                assiette_plancher=bool(p.get("assiette_plancher", False)),
                avantages_non_contributifs=tuple(p.get("avantages_non_contributifs") or ()),
                notes=(p.get("notes") or "").strip(),
            )
            for p in fiche.get("periodes", [])
        )
        return Regime(
            code=fiche["code"],
            nom=fiche["nom"],
            famille=fiche["famille"],
            source_id=fiche.get("source_id", ""),
            fiabilite=Fiabilite.depuis_texte(fiche["fiabilite"]),
            creation=int(fiche["creation"]),
            fermeture=None if fiche.get("fermeture") is None else int(fiche["fermeture"]),
            extinction=None if fiche.get("extinction") is None else int(fiche["extinction"]),
            succede_a=tuple(fiche.get("succede_a") or ()),
            integre_dans=fiche.get("integre_dans"),
            population=(fiche.get("population") or "").strip(),
            hors_repartition=bool(fiche.get("hors_repartition", False)),
            periodes=periodes,
        )

    # -- accès ---------------------------------------------------------------

    def __getitem__(self, code: str) -> Regime:
        if code not in self._regimes:
            raise KeyError(
                f"régime inconnu : {code!r}. Régimes disponibles : "
                + ", ".join(sorted(self._regimes))
            )
        return self._regimes[code]

    def __contains__(self, code: str) -> bool:
        return code in self._regimes

    def __iter__(self):
        return iter(self._regimes.values())

    def __len__(self) -> int:
        return len(self._regimes)

    @cached_property
    def codes(self) -> tuple[str, ...]:
        return tuple(sorted(self._regimes))

    def par_famille(self, famille: str) -> tuple[Regime, ...]:
        return tuple(r for r in self if r.famille == famille)

    def en_repartition(self) -> tuple[Regime, ...]:
        return tuple(r for r in self if not r.hors_repartition)

    def ouverts(self, annee: int) -> tuple[Regime, ...]:
        return tuple(r for r in self if r.ouvert(annee))

    def resoudre_succession(self, code: str, annee: int) -> str:
        """Suit la chaîne d'absorption jusqu'au régime réellement compétent.

        Exemple : ``organic`` en 2010 renvoie ``rsi`` ; en 2020, ``regime_general``.
        """
        vu = {code}
        courant = self[code]
        while courant.extinction is not None and annee >= courant.extinction:
            suivant = courant.integre_dans
            if suivant is None or suivant in vu:
                break
            vu.add(suivant)
            courant = self[suivant]
        return courant.code
