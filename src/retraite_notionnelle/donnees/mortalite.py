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
ne prétend pas décrire la mortalité aux âges jeunes.

**La calibration porte sur la table raccordée, pas sur la loi seule.** C'est ce
qui a longtemps manqué : ajustée sur elle-même, la loi donnait une queue trop
généreuse, et la table raccordée — quotients observés jusqu'à 84 ans pour les
millésimes 1998-2013, loi au-delà — rendait une espérance à 60 ans jusqu'à
2,5 ans supérieure à celle que publie l'INSEE. Le diviseur de conversion s'en
trouvait surestimé de 5 %, et les pensions notionnelles minorées d'autant. Les
paramètres sont désormais ajustés pour que la table telle que le modèle la LIT
reproduise les espérances publiées ; là où la queue n'a pas prise sur la cible —
millésimes dont les quotients vont jusqu'à 104 ans —, la table observée décide
seule et l'écart résiduel avec l'INSEE, au plus 0,7 an, est celui des deux
chaînes de production.

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


def _survie_makeham_un_an(a: float, b: float, k: float, age: float) -> float:
    """Probabilité de passer de ``age`` à ``age + 1`` sous la loi paramétrique."""
    u = math.exp(k * (age - 60.0))
    return math.exp(-(a + (b / k) * u * (math.exp(k) - 1.0)))


def _esperance_raccordee(a: float, b: float, k: float, age: float,
                         quotients: dict[int, float] | None) -> float:
    """Espérance de vie du moment de la table RACCORDÉE, année par année.

    C'est exactement ce que rend le modèle : les quotients observés là où ils
    existent, la loi paramétrique partout ailleurs. Sans ``quotients``, elle se
    réduit à l'espérance de la loi seule, au pas d'un an.
    """
    total = 0.0
    survie = 1.0
    courant = float(age)
    while courant < AGE_TERMINAL and survie > 1e-12:
        quotient = quotients.get(int(courant)) if quotients else None
        facteur = ((1.0 - quotient) if quotient is not None
                   else _survie_makeham_un_an(a, b, k, courant))
        prochaine = survie * facteur
        total += 0.5 * (survie + prochaine)
        survie = prochaine
        courant += 1.0
    return total


#: Tolérance sur les espérances reproduites par la calibration, en années.
#: Au-delà, la queue paramétrique n'a pas prise sur la cible — c'est le cas des
#: millésimes dont les quotients observés vont jusqu'à 104 ans, où la table
#: décide seule — et la calibration retombe sur la loi pure.
TOLERANCE_CALIBRATION = 0.05


def _calibrer(e60_cible: float, e65_cible: float, annee: int, sexe: str,
              fiabilite: Fiabilite,
              quotients: dict[int, float] | None = None) -> LoiMortalite:
    """Ajuste (b, k) pour que la table RACCORDÉE reproduise e60 et e65.

    Deux temps. La FORME de la queue — le paramètre k — vient de la calibration
    classique sur la loi seule, où e60 et e65 portent sur toute la plage d'âges
    et le déterminent sans ambiguïté. Son NIVEAU — le paramètre b — est ensuite
    recalé, à forme constante, pour que la table RACCORDÉE reproduise e60.

    Les deux bissections portent sur des fonctions monotones : à k fixé,
    l'espérance décroît quand b croît ; une fois b calé sur e60, le rapport
    e65/e60 décroît quand k croît.

    **La cible porte sur la table telle que le modèle la lit**, quotients
    observés compris, et non sur la loi paramétrique seule. C'est ce qui a
    longtemps manqué : calibrée sur elle-même, la loi produisait une queue trop
    généreuse — 11,3 ans d'espérance résiduelle à 85 ans pour une femme en 2010,
    là où la cible en implique 7,5 — et le raccord au-dessus du dernier âge
    publié faisait remonter l'espérance à 60 ans de 2,5 ans au-dessus de celle
    que l'INSEE publie. Le diviseur de conversion s'en trouvait surestimé
    jusqu'à 5 % pour les liquidations de 1998 à 2013.

    Quand la queue n'a pas prise sur la cible — millésimes dont les quotients
    vont jusqu'à 104 ans, où l'espérance est déterminée par les données —, la
    calibration retombe sur la loi seule : forcer l'accord reviendrait alors à
    déformer une table observée pour la faire coïncider avec une espérance
    produite par une tout autre chaîne.
    """

    def b_pour(k: float, cible: float,
               observes: dict[int, float] | None) -> float:
        bas, haut = 1e-9, 5.0
        for _ in range(50):
            milieu = math.sqrt(bas * haut)
            if _esperance_raccordee(MORTALITE_ACCIDENTELLE, milieu, k, 60.0,
                                    observes) > cible:
                bas = milieu
            else:
                haut = milieu
        return math.sqrt(bas * haut)

    # 1. La FORME de la queue vient de la calibration classique, sur la loi
    #    seule : e60 et e65 y portent sur toute la plage d'âges, et déterminent
    #    k sans ambiguïté. C'est ce que faisait le module, et c'est bien fait.
    ratio_cible = e65_cible / e60_cible
    bas_k, haut_k = 0.02, 0.30
    for _ in range(30):
        k = 0.5 * (bas_k + haut_k)
        b = b_pour(k, e60_cible, None)
        e60 = _esperance_makeham(MORTALITE_ACCIDENTELLE, b, k, 60.0)
        e65 = _esperance_makeham(MORTALITE_ACCIDENTELLE, b, k, 65.0)
        if e65 / e60 > ratio_cible:
            bas_k = k
        else:
            haut_k = k
    k = 0.5 * (bas_k + haut_k)
    b = b_pour(k, e60_cible, None)

    # 2. Le NIVEAU de la queue est ensuite recalé, à forme constante, pour que
    #    la table telle que le modèle la lit — quotients observés compris —
    #    reproduise l'espérance publiée. C'est ce qui manquait.
    if quotients:
        recale = b_pour(k, e60_cible, quotients)
        atteint = _esperance_raccordee(MORTALITE_ACCIDENTELLE, recale, k, 60.0,
                                       quotients)
        if abs(atteint - e60_cible) <= TOLERANCE_CALIBRATION:
            b = recale
        # Sinon, la queue n'a pas prise sur la cible : la table observée décide
        # seule, et l'on conserve la forme et le niveau de la loi pure.

    return LoiMortalite(MORTALITE_ACCIDENTELLE, b, k, annee, sexe, fiabilite)


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

        loi = _calibrer(
            e60.valeur, e65.valeur, annee, sexe, fiabilite,
            quotients=(self._quotients_observes or {}).get((annee_bornee, sexe)),
        )
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

    def _survie_cellule(self, age: int, annee: int, sexe: str) -> float:
        """Survie d'un âge ENTIER au suivant, quotient observé s'il existe."""
        if self._quotients_observes is not None:
            cle = (annee, sexe)
            if cle in self._quotients_observes:
                qx = self._quotients_observes[cle].get(age)
                if qx is not None:
                    return 1.0 - qx
        return self.loi(annee, sexe).survie(float(age), 1.0)

    def survie_annuelle(self, age: float, annee: float, sexe: str) -> float:
        """Probabilité de survivre un an à partir de ``age`` en ``annee``.

        **L'âge et la date sont fractionnaires, et tous deux comptent.** La
        méthode lisait ``quotients[int(age)]`` : la part OBSERVÉE de la table —
        1986-2024 — était aveugle aux mois, et le diviseur d'un départ à 60 ans
        et onze mois était celui d'un départ à 60 ans tout rond. La sanction du
        départ anticipé, qui est la moitié du modèle, s'appliquait par marches
        d'un an : 1,7 % de pension d'un coup à chaque anniversaire, et rien
        entre deux.

        **La force de mortalité est supposée constante dans chaque cellule**
        (âge entier × millésime) — l'hypothèse actuarielle usuelle, et la seule
        qui rende la survie continue. Un assuré parti en juillet 2038 à 63 ans
        et 4 mois passe son année de rente dans quatre cellules successives : il
        franchit son anniversaire, puis le 1er janvier. Le trajet est donc
        découpé à ces deux franchissements, et chaque tronçon reçoit la force de
        la cellule qu'il traverse.

        Ce n'est pas lisser entre deux millésimes : c'est répartir l'EXPOSITION
        entre eux. Une table de mortalité reste publiée par millésime, et aucune
        tendance infra-annuelle n'est inventée — on dit seulement combien de
        mois de l'année le cohorte a vécus sous chacune. Sans ce découpage,
        l'année civile sautait d'un bloc au 1er janvier quand l'âge, lui,
        avançait mois par mois : le diviseur REMONTAIT à cette date, et partir
        un mois plus tard rallongeait la durée de service attendue.
        """
        age_entier, part_age = math.floor(age), age - math.floor(age)
        annee_entiere, part_annee = math.floor(annee), annee - math.floor(annee)
        if part_age <= 1e-9 and part_annee <= 1e-9:
            return self._survie_cellule(int(age_entier), int(annee_entiere), sexe)

        # Les deux coordonnées avancent à la même vitesse : le trajet franchit
        # l'âge entier suivant en ``1 - part_age`` et le 1er janvier suivant en
        # ``1 - part_annee``. D'où deux coupures au plus, et trois tronçons.
        coupures = sorted(
            {borne for borne in (1.0 - part_age, 1.0 - part_annee)
             if 1e-9 < borne < 1.0 - 1e-9}
        )
        bornes = [0.0, *coupures, 1.0]
        cumul = 0.0
        for debut, fin in zip(bornes, bornes[1:]):
            milieu = 0.5 * (debut + fin)
            cellule = self._survie_cellule(
                int(age_entier + math.floor(part_age + milieu)),
                int(annee_entiere + math.floor(part_annee + milieu)),
                sexe,
            )
            # Force de mortalité de la cellule, appliquée sur la durée du
            # tronçon : -ln p, puis somme, puis exponentielle.
            cumul += (fin - debut) * -math.log(max(cellule, 1e-300))
        return math.exp(-cumul)

    # -- tables de génération ------------------------------------------------

    @lru_cache(maxsize=4096)
    def courbe_survie(self, age_debut: float, annee_debut: float, sexe: str,
                      generation: bool = True) -> tuple[float, ...]:
        """Survie cumulée année par année à partir de ``age_debut``.

        ``annee_debut`` peut porter une fraction : c'est la position de la
        liquidation dans son année civile, ``(mois - 1) / 12``. Elle dit sous
        quel millésime le rentier passe chaque tronçon de son année de rente.

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
            # Table du moment : la mortalité de l'année de liquidation est
            # appliquée à tous les âges. Table de génération : chaque année
            # vécue reçoit celle de l'année civile correspondante. Dans les
            # deux cas les quotients OBSERVÉS priment là où ils existent — la
            # table du moment les ignorait, si bien qu'elle ne décrivait pas la
            # même mortalité que celle du calcul par défaut, et qu'un test
            # censé confronter les deux chaînes comparait la calibration à sa
            # propre cible.
            annee = annee_debut + duree if generation else annee_debut
            facteur = self.survie_annuelle(age_debut + duree, annee, sexe)
            courante *= facteur
            probabilites.append(courante)
            duree += 1
        return tuple(probabilites)

    def courbe_survie_unisexe(self, age_debut: float, annee_debut: float,
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

    def courbe(self, age_debut: float, annee_debut: float, sexe: str | None,
               generation: bool = True) -> tuple[float, ...]:
        """Courbe de survie, unisexe si ``sexe`` vaut ``None``."""
        if sexe is None:
            return self.courbe_survie_unisexe(age_debut, annee_debut, generation)
        return self.courbe_survie(age_debut, annee_debut, sexe, generation)

    def survie(self, age_debut: float, annee_debut: int, duree: int, sexe: str,
               generation: bool = True) -> float:
        courbe = self.courbe_survie(age_debut, annee_debut, sexe, generation)
        return courbe[duree] if duree < len(courbe) else 0.0

    def esperance_residuelle(self, age: float, annee: float, sexe: str | None = None,
                             generation: bool = True) -> float:
        """Espérance de vie résiduelle en années, table de génération par défaut."""
        courbe = self.courbe(age, annee, sexe, generation)
        return sum(0.5 * (courbe[t] + courbe[t + 1]) for t in range(len(courbe) - 1))

    def fiabilite(self, annee: float) -> Fiabilite:
        millesime = int(math.floor(annee))
        return min(self.loi(millesime, "H").fiabilite,
                   self.loi(millesime, "F").fiabilite)
