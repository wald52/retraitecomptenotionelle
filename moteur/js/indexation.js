/**
 * Règle d'indexation : le « triple lock inversé ».
 *
 * Portage de ``src/retraite_notionnelle/moteur/indexation.py``. Le triple lock
 * britannique retient le MAXIMUM entre l'inflation, la croissance des salaires
 * et un plancher de 2,5 %. La règle demandée ici en est l'exact opposé : on
 * retient le MINIMUM entre l'inflation, la croissance du salaire moyen et la
 * productivité réelle. C'est une règle d'austérité structurelle, et elle
 * mélange deux taux nominaux à un taux réel — d'où l'effondrement de la valeur
 * réelle des comptes sur les périodes de forte inflation.
 *
 * Le minimum n'est pas la seule statistique possible sur ces trois séries :
 * ``MEDIANE_TROIS_TAUX`` retient celui du milieu, ``MOYENNE_TROIS_TAUX`` leur
 * moyenne arithmétique. Mêmes termes, agrégation différente.
 */

import { ModeIndexation } from "./config.js";
import { Fiabilite } from "./serie.js";

/**
 * Modes qui comparent les trois taux tels qu'ils sont publiés — deux nominaux,
 * un réel. Ils ne diffèrent que par la statistique retenue, pas par les termes.
 */
/**
 * Longueur de la fenêtre de lissage de la règle italienne, en années : c'est
 * elle, et elle seule, qui distingue la règle italienne d'une indexation sur le
 * PIB de l'année.
 */
const FENETRE_LISSAGE_ITALIENNE = 5;

const MODES_TROIS_TAUX_REELS = new Set([
  ModeIndexation.TRIPLE_LOCK_INVERSE,
  ModeIndexation.MEDIANE_TROIS_TAUX,
  ModeIndexation.MOYENNE_TROIS_TAUX,
]);

/** Calcule et compose les taux d'indexation annuels. */
export class Indexation {
  constructor(macro, parametres) {
    this.macro = macro;
    this.parametres = parametres;
    this._taux = new Map();
  }

  /** Taux retenu pour une année, avec le terme qui l'a emporté. */
  taux(annee) {
    const memorise = this._taux.get(annee);
    if (memorise !== undefined) {
      return memorise;
    }

    const inflation = this.macro.inflation.valeur(annee);
    const salaire = this.macro.salaire_moyen.valeur(annee);
    const productivite = this.macro.productivite.valeur(annee);
    const mode = this.parametres.mode_indexation;

    let candidats;
    if (MODES_TROIS_TAUX_REELS.has(mode)) {
      candidats = [
        ["inflation", inflation],
        ["salaire_moyen", salaire],
        ["productivite_reelle", productivite],
      ];
    } else if (mode === ModeIndexation.TRIPLE_LOCK_INVERSE_NOMINAL) {
      candidats = [
        ["inflation", inflation],
        ["salaire_moyen", salaire],
        ["productivite_nominale", this.macro.productiviteNominale(annee)],
      ];
    } else if (mode === ModeIndexation.PIB_NOMINAL_LISSE) {
      candidats = [["pib_nominal_lisse", this._pibLisse(annee)]];
    } else if (mode === ModeIndexation.MASSE_SALARIALE) {
      candidats = [["masse_salariale", this.macro.masse_salariale.valeur(annee)]];
    } else if (mode === ModeIndexation.REVALORISATION_PORTEE_AU_COMPTE) {
      // Le taux annuel des arrêtés, lu comme le scénario 1 le lit : le rapport
      // de deux années consécutives dans la colonne publiée.
      candidats = [[
        "revalorisation_legale",
        this.macro.coefficientRevalorisationPorteeAuCompte(annee - 1, annee) - 1,
      ]];
    } else if (mode === ModeIndexation.PRIX) {
      candidats = [["inflation", inflation]];
    } else if (mode === ModeIndexation.SALAIRES) {
      candidats = [["salaire_moyen", salaire]];
    } else {
      throw new Error(`mode d'indexation non géré : ${mode}`);
    }

    // Le mode choisit la STATISTIQUE appliquée aux candidats fixés ci-dessus :
    // minimum par défaut — la règle demandée —, médiane ou moyenne pour les
    // variantes. Les trois coïncident quand il n'y a qu'un candidat.
    let terme;
    let taux;
    if (mode === ModeIndexation.MOYENNE_TROIS_TAUX) {
      // La moyenne n'est le taux d'aucun des trois : pas de terme retenu.
      terme = "moyenne";
      taux = candidats.reduce((somme, [, valeur]) => somme + valeur, 0)
        / candidats.length;
    } else if (mode === ModeIndexation.MEDIANE_TROIS_TAUX) {
      // Nombre impair de candidats : la médiane est un candidat, pas une
      // interpolation. Le tri de JavaScript est stable, comme celui de Python :
      // à égalité, le premier terme cité l'emporte.
      const classes = [...candidats].sort((a, b) => a[1] - b[1]);
      [terme, taux] = classes[Math.floor(classes.length / 2)];
    } else {
      // Comme ``min`` en Python : à égalité, le premier terme cité l'emporte.
      [terme, taux] = candidats[0];
      for (const [nom, valeur] of candidats.slice(1)) {
        if (valeur < taux) {
          terme = nom;
          taux = valeur;
        }
      }
    }

    const plancher = this.parametres.plancher_indexation;
    if (plancher !== null && plancher !== undefined && taux < plancher) {
      taux = plancher;
      terme = "plancher";
    }

    const resultat = {
      annee,
      taux,
      terme_retenu: terme,
      inflation,
      salaire_moyen: salaire,
      productivite,
      fiabilite: Math.min(
        this.macro.inflation.fiabilite(annee),
        this.macro.salaire_moyen.fiabilite(annee),
        this.macro.productivite.fiabilite(annee),
      ),
    };
    this._taux.set(annee, resultat);
    return resultat;
  }

  /**
   * Moyenne géométrique du PIB nominal sur la fenêtre italienne.
   *
   * Fenêtre tronquée au début de la série plutôt qu'indisponible : la première
   * année publiée n'a pas quatre années derrière elle. Deux écarts assumés avec
   * la règle italienne — l'Italie décale la fenêtre de deux ans, le temps que
   * les comptes nationaux soient arrêtés, et l'applique à un système dont ce
   * modèle ne reprend ni les coefficients de transformation ni les planchers.
   */
  _pibLisse(annee) {
    const serie = this.macro.pib_nominal;
    const debut = Math.max(annee - FENETRE_LISSAGE_ITALIENNE + 1, serie.premiereAnnee);
    let produit = 1.0;
    for (let a = debut; a <= annee; a += 1) {
      produit *= 1 + serie.valeur(a);
    }
    return produit ** (1 / (annee - debut + 1)) - 1;
  }

  /**
   * Coefficient de revalorisation cumulée entre deux années.
   *
   * Convention : une cotisation versée en ``depart`` est revalorisée à partir
   * de l'année SUIVANTE. Elle ne l'est ni l'année même de son versement, ni
   * l'année de la liquidation — sans quoi on offrirait une année de rendement
   * gratuite.
   */
  coefficient(depart, arrivee) {
    if (arrivee <= depart) {
      return 1.0;
    }
    let coefficient = 1.0;
    for (let annee = depart + 1; annee <= arrivee; annee += 1) {
      coefficient *= 1 + this.taux(annee).taux;
    }
    return coefficient;
  }

  historique(debut, fin) {
    const taux = [];
    for (let annee = debut; annee <= fin; annee += 1) {
      taux.push(this.taux(annee));
    }
    return taux;
  }

  fiabiliteSur(debut, fin) {
    let minimum = null;
    for (let annee = debut; annee <= fin; annee += 1) {
      const niveau = this.taux(annee).fiabilite;
      minimum = minimum === null ? niveau : Math.min(minimum, niveau);
    }
    return minimum === null ? Fiabilite.ESTIMEE : minimum;
  }
}

/** Taux d'indexation net d'inflation. */
export function tauxReel(taux) {
  return (1 + taux.taux) / (1 + taux.inflation) - 1;
}
