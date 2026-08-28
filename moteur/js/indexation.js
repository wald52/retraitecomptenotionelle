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
 */

import { ModeIndexation } from "./config.js";
import { Fiabilite } from "./serie.js";

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
    if (mode === ModeIndexation.TRIPLE_LOCK_INVERSE) {
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
    } else if (mode === ModeIndexation.PRIX) {
      candidats = [["inflation", inflation]];
    } else if (mode === ModeIndexation.SALAIRES) {
      candidats = [["salaire_moyen", salaire]];
    } else {
      throw new Error(`mode d'indexation non géré : ${mode}`);
    }

    // Comme ``min`` en Python : à égalité, le premier terme cité l'emporte.
    let [terme, taux] = candidats[0];
    for (const [nom, valeur] of candidats.slice(1)) {
      if (valeur < taux) {
        terme = nom;
        taux = valeur;
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
