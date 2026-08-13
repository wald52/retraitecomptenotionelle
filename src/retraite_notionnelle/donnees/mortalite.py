"""Tables de mortalité : chargement, calibration, tables de génération.

Deux sources, dans cet ordre de priorité, arbitrées **couple par couple**
(année, sexe, âge) et non en bloc :

1. ``data/reference/mortalite/quotients_periode.csv`` (colonnes
   ``annee,sexe,age,qx``) — les quotients réellement observés. Ils couvrent
   1986-2024, des âges 0 à 84 puis 0 à 94 selon les millésimes ;
2. partout ailleurs — avant 1986, au-delà du dernier âge publié, et pour les
   années projetées — une table paramétrique de **Gompertz-Makeham** calibrée
   pour reproduire les espérances de vie publiées à 60 et 65 ans.

Le point 2 est une approximation assumée : elle donne la bonne espérance de vie
aux âges qui comptent pour la retraite (celle qui pilote le diviseur), mais elle
ne prétend pas décrire la mortalité aux âges jeunes. Le raccord entre les deux
sources est contrôlé par les tests : l'espérance de vie à 60 ans recalculée à
partir des seuls quotients observés retombe à 0,4 an près sur celle que publie
l'INSEE, qui vient d'une tout autre chaîne de production.

Force de mortalité retenue :  μ(x) = A + B · exp(k · (x − 60))
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .chargement import Fiabilite, SerieAnnuelle, charger_serie_annuelle

#: Mortalité « accidentelle », indépendante de l'âge (terme de Makeham).
MORTALITE_ACCIDENTELLE = 0.0005

#: Pas d'intégration numérique, en années. 0,25 an suffit : l'écart avec un pas
#: mensuel est inférieur à 0,01 an sur les espérances calculées, très en deçà de
#: l'incertitude des données d'entrée.
PAS = 0.25

#: Âge terminal des tables.
AGE_TERMINAL = 120.0


@dataclass(frozen=True)
class LoiMortalite:
    """Paramètres de Makeham pour une année et un sexe donnés."""

    a: float
    b: float
    k: float
    annee: int
    sexe: str
    fiabilite: Fiabilite

    def force(self, age: float) -> float:
        return self.a + self.b * math.exp(self.k * (age - 60.0))

    def survie(self, age_debut: float, duree: float) -> float:
        """Probabilité de survivre ``duree`` années à partir de ``age_debut``."""
        if duree <= 0:
            return 1.0
        u = math.exp(self.k * (age_debut - 60.0))
        integrale = self.a * duree + (self.b / self.k) * u * (math.exp(self.k * duree) - 1.0)
        return math.exp(-integrale)

    def esperance(self, age: float) -> float:
        """Espérance de vie résiduelle complète à ``age``, table du moment.

        Intégration incrémentale : la survie cumulée est propagée d'un pas à
        l'autre, ce qui coûte une exponentielle par pas au lieu de deux.
        """
        return _esperance_makeham(self.a, self.b, self.k, age)


def _esperance_makeham(a: float, b: float, k: float, age: float) -> float:
    total = 0.0
    survie = 1.0
    u = math.exp(k * (age - 60.0))
    facteur_pas = math.exp(k * PAS)
    borne = int((AGE_TERMINAL - age) / PAS)
    for _ in range(max(borne, 0)):
        prochaine = survie * math.exp(-(a * PAS + (b / k) * u * (facteur_pas - 1.0)))
        total += 0.5 * (survie + prochaine) * PAS
        survie = prochaine
        u *= facteur_pas
        if survie < 1e-12:
            break
    return total


def _calibrer(e60_cible: float, e65_cible: float, annee: int, sexe: str,
              fiabilite: Fiabilite) -> LoiMortalite:
    """Ajuste (b, k) pour reproduire simultanément e60 et e65.

    Deux bissections emboîtées, toutes deux sur des fonctions monotones :
    * à k fixé, e60 décroît quand b croît ;
    * une fois b calé sur e60, le rapport e65/e60 décroît quand k croît.
    """

    def b_pour_e60(k: float) -> float:
        bas, haut = 1e-7, 1.0
        for _ in range(45):
            milieu = math.sqrt(bas * haut)
            if _esperance_makeham(MORTALITE_ACCIDENTELLE, milieu, k, 60.0) > e60_cible:
                bas = milieu
            else:
                haut = milieu
        return math.sqrt(bas * haut)

    ratio_cible = e65_cible / e60_cible
    bas_k, haut_k = 0.02, 0.30
    for _ in range(30):
        k = 0.5 * (bas_k + haut_k)
        b = b_pour_e60(k)
        e60 = _esperance_makeham(MORTALITE_ACCIDENTELLE, b, k, 60.0)
        e65 = _esperance_makeham(MORTALITE_ACCIDENTELLE, b, k, 65.0)
        if e65 / e60 > ratio_cible:
            bas_k = k
        else:
            haut_k = k
    k = 0.5 * (bas_k + haut_k)
    return LoiMortalite(MORTALITE_ACCIDENTELLE, b_pour_e60(k), k, annee, sexe, fiabilite)


class DonneesMortalite:
    """Tables du moment et tables de génération pour les deux sexes."""

    SEXES = ("H", "F")

    def __init__(self, racine: Path, poids_unisexe: tuple[float, float] = (0.5, 0.5),
                 cache_disque: bool = True) -> None:
        self.racine = racine
        self.poids_unisexe = poids_unisexe
        self._chemin_cache = racine / "derive" / "calibrations_mortalite.json"
        self._cache_disque = cache_disque
        self._cache: dict[str, list[float]] = {}
        self._cache_modifie = False
        if cache_disque and self._chemin_cache.exists():
            try:
                self._cache = json.loads(self._chemin_cache.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._cache = {}
        chemin = racine / "reference" / "mortalite" / "esperances_vie.csv"
        self._e60: dict[str, SerieAnnuelle] = {}
        self._e65: dict[str, SerieAnnuelle] = {}
        for sexe in self.SEXES:
            self._e60[sexe] = charger_serie_annuelle(
                chemin, "valeur", nom=f"e60_{sexe}", interpolation="lineaire",
                filtre={"sexe": sexe, "mesure": "e60"},
            )
            self._e65[sexe] = charger_serie_annuelle(
                chemin, "valeur", nom=f"e65_{sexe}", interpolation="lineaire",
                filtre={"sexe": sexe, "mesure": "e65"},
            )
        self._quotients_observes = self._charger_quotients_observes()

    # -- tables réelles, si présentes ---------------------------------------

    def _charger_quotients_observes(self) -> dict[tuple[int, str], dict[int, float]] | None:
        chemin = self.racine / "reference" / "mortalite" / "quotients_periode.csv"
        if not chemin.exists():
            return None
        table: dict[tuple[int, str], dict[int, float]] = {}
        with chemin.open(encoding="utf-8") as flux:
            lignes = (l for l in flux if not l.lstrip().startswith("#"))
            for ligne in csv.DictReader(lignes):
                cle = (int(ligne["annee"]), ligne["sexe"])
                table.setdefault(cle, {})[int(ligne["age"])] = float(ligne["qx"])
        return table or None

    @property
    def utilise_tables_reelles(self) -> bool:
        return self._quotients_observes is not None

    # -- tables du moment ----------------------------------------------------

    @lru_cache(maxsize=None)
    def loi(self, annee: int, sexe: str) -> LoiMortalite:
        """Loi de mortalité du moment pour une année civile et un sexe.

        Les paramètres calibrés sont mémorisés sur disque
        (``data/derive/calibrations_mortalite.json``) : la calibration est
        déterministe, la refaire à chaque exécution ne coûterait que du temps.
        """
        annee_bornee = max(
            self._e60[sexe].premiere_annee,
            min(annee, self._e60[sexe].derniere_annee),
        )
        e60 = self._e60[sexe].brut(annee_bornee)
        e65 = self._e65[sexe].brut(annee_bornee)
        fiabilite = min(e60.fiabilite, e65.fiabilite)
        if annee != annee_bornee:
            fiabilite = Fiabilite.ESTIMEE

        cle = f"{annee_bornee}|{sexe}"
        memorise = self._cache.get(cle)
        if memorise is not None:
            b, k = memorise
            return LoiMortalite(MORTALITE_ACCIDENTELLE, b, k, annee, sexe, fiabilite)

        loi = _calibrer(e60.valeur, e65.valeur, annee, sexe, fiabilite)
        self._cache[cle] = [loi.b, loi.k]
        self._cache_modifie = True
        return loi

    def enregistrer_cache(self) -> None:
        """Écrit les calibrations sur disque. Sans effet si rien n'a changé."""
        if not (self._cache_disque and self._cache_modifie):
            return
        self._chemin_cache.parent.mkdir(parents=True, exist_ok=True)
        self._chemin_cache.write_text(
            json.dumps(self._cache, indent=0, sort_keys=True), encoding="utf-8"
        )
        self._cache_modifie = False

    def survie_annuelle(self, age: float, annee: int, sexe: str) -> float:
        """Probabilité de passer de ``age`` à ``age+1`` pendant l'année ``annee``."""
        if self._quotients_observes is not None:
            cle = (annee, sexe)
            if cle in self._quotients_observes:
                qx = self._quotients_observes[cle].get(int(age))
                if qx is not None:
                    return 1.0 - qx
        return self.loi(annee, sexe).survie(age, 1.0)

    # -- tables de génération ------------------------------------------------

    @lru_cache(maxsize=4096)
    def courbe_survie(self, age_debut: float, annee_debut: int, sexe: str,
                      generation: bool = True) -> tuple[float, ...]:
        """Survie cumulée année par année à partir de ``age_debut``.

        L'élément d'indice ``t`` est la probabilité d'être encore en vie
        ``t`` années après la liquidation. En table de génération, chaque année
        vécue se voit appliquer la mortalité de l'année civile correspondante,
        et non celle de l'année de liquidation — c'est la définition même d'une
        table de génération. L'ignorer surestime la pension des générations
        récentes, dont la longévité continue de progresser.
        """
        probabilites = [1.0]
        courante = 1.0
        duree = 0
        while age_debut + duree < AGE_TERMINAL and courante > 1e-10:
            if generation:
                facteur = self.survie_annuelle(age_debut + duree, annee_debut + duree, sexe)
            else:
                loi = self.loi(annee_debut, sexe)
                facteur = loi.survie(age_debut + duree, 1.0)
            courante *= facteur
            probabilites.append(courante)
            duree += 1
        return tuple(probabilites)

    def courbe_survie_unisexe(self, age_debut: float, annee_debut: int,
                              generation: bool = True) -> tuple[float, ...]:
        """Courbe de survie moyenne pondérée des deux sexes.

        On moyenne les FONCTIONS DE SURVIE, pas les espérances : c'est la
        pondération correcte pour une rente servie indifféremment aux hommes et
        aux femmes à partir d'un même capital notionnel.
        """
        poids_h, poids_f = self.poids_unisexe
        ch = self.courbe_survie(age_debut, annee_debut, "H", generation)
        cf = self.courbe_survie(age_debut, annee_debut, "F", generation)
        longueur = max(len(ch), len(cf))
        return tuple(
            poids_h * (ch[t] if t < len(ch) else 0.0)
            + poids_f * (cf[t] if t < len(cf) else 0.0)
            for t in range(longueur)
        )

    def courbe(self, age_debut: float, annee_debut: int, sexe: str | None,
               generation: bool = True) -> tuple[float, ...]:
        """Courbe de survie, unisexe si ``sexe`` vaut ``None``."""
        if sexe is None:
            return self.courbe_survie_unisexe(age_debut, annee_debut, generation)
        return self.courbe_survie(age_debut, annee_debut, sexe, generation)

    def survie(self, age_debut: float, annee_debut: int, duree: int, sexe: str,
               generation: bool = True) -> float:
        courbe = self.courbe_survie(age_debut, annee_debut, sexe, generation)
        return courbe[duree] if duree < len(courbe) else 0.0

    def esperance_residuelle(self, age: float, annee: int, sexe: str | None = None,
                             generation: bool = True) -> float:
        """Espérance de vie résiduelle en années, table de génération par défaut."""
        courbe = self.courbe(age, annee, sexe, generation)
        return sum(0.5 * (courbe[t] + courbe[t + 1]) for t in range(len(courbe) - 1))

    def fiabilite(self, annee: int) -> Fiabilite:
        return min(self.loi(annee, "H").fiabilite, self.loi(annee, "F").fiabilite)
