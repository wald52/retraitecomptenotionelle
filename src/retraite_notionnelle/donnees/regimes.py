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
    taux_plein: float | None
    salaire_reference: str
    assiette: str
    taux_cotisation_retraite: float
    decote_par_trimestre: float | None
    surcote_par_trimestre: float | None
    avantages_non_contributifs: tuple[str, ...]
    notes: str = ""

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
                taux_plein=None if p.get("taux_plein") is None else float(p["taux_plein"]),
                salaire_reference=p.get("salaire_reference", "sans_objet"),
                assiette=p.get("assiette", "deplafonnee"),
                taux_cotisation_retraite=float(p["taux_cotisation_retraite"]),
                decote_par_trimestre=(
                    None if p.get("decote_par_trimestre") is None
                    else float(p["decote_par_trimestre"])
                ),
                surcote_par_trimestre=(
                    None if p.get("surcote_par_trimestre") is None
                    else float(p["surcote_par_trimestre"])
                ),
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
