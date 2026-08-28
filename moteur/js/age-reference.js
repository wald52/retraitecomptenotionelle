/**
 * Âge de référence à cliquet et écart d'anticipation.
 *
 * Portage de ``src/retraite_notionnelle/moteur/age_reference.py``. Règle
 * demandée : chaque fois que l'âge de départ a été abaissé, la pension est
 * calculée comme si l'assuré était parti trop tôt. L'âge de référence ne
 * redescend donc jamais — c'est un cliquet sur l'âge du taux plein du régime
 * général — et l'abaissement de 65 à 60 ans en 1982 ne le fait pas baisser :
 * une liquidation à 60 ans en 1990 est une anticipation de cinq ans.
 *
 * Cet écart n'est pas sanctionné une seconde fois : dans un système notionnel,
 * l'anticipation l'est déjà deux fois, mécaniquement — les années non
 * travaillées n'ont pas produit de cotisations, et la rente est servie plus
 * longtemps donc le diviseur est plus élevé.
 */

import { ModeAgeReference } from "./config.js";
import { SerieAnnuelle } from "./serie.js";

/** Position d'une liquidation par rapport à l'âge de référence. */
export function ecartAge(ageLiquidation, ageReference, anneeLiquidation) {
  const ecart = ageReference - ageLiquidation;
  return {
    age_liquidation: ageLiquidation,
    age_reference: ageReference,
    annee_liquidation: anneeLiquidation,
    /** Positif = départ anticipé, négatif = départ différé. */
    ecart,
    anticipe: ecart > 0,
  };
}

/** Série d'âges de référence, construite à cliquet. */
export class AgeReference {
  constructor(paquet, parametres, mortalite = null) {
    this.parametres = parametres;
    this.mortalite = mortalite;
    this._legal = SerieAnnuelle.depuisPaquet(
      "age_taux_plein_legal", paquet.series.age_taux_plein_legal,
    );
    this._cliquet = SerieAnnuelle.depuisPaquet(
      "age_reference", paquet.series.age_reference,
    );
  }

  /** Âge de référence applicable à une liquidation de l'année ``annee``. */
  age(annee) {
    const mode = this.parametres.mode_age_reference;

    if (mode === ModeAgeReference.LEGAL_SANS_CLIQUET) {
      return this._legal.valeur(annee);
    }

    const base = this._appliqueCliquet(annee);

    if (mode === ModeAgeReference.CLIQUET_PUIS_ESPERANCE_VIE
        && annee > this.parametres.annee_bascule) {
      return Math.max(base, this._ageIndexeEsperanceVie(annee));
    }
    return base;
  }

  /**
   * Maximum des âges de taux plein observés jusqu'à l'année considérée.
   *
   * On ne se contente pas de lire la colonne pré-calculée : on la recalcule, de
   * sorte qu'une correction du fichier législatif se propage sans risque
   * d'incohérence entre les deux colonnes.
   */
  _appliqueCliquet(annee) {
    const debut = Math.min(this._legal.premiereAnnee, annee);
    let maximum = this._legal.valeur(debut);
    for (let a = debut + 1; a <= annee; a += 1) {
      maximum = Math.max(maximum, this._legal.valeur(a));
    }
    return maximum;
  }

  /**
   * Âge stabilisant le ratio durée de retraite / durée de carrière : le plus
   * petit âge dont l'espérance de vie résiduelle, rapportée à la carrière
   * depuis 22 ans, ne dépasse pas le ratio cible.
   */
  _ageIndexeEsperanceVie(annee) {
    if (this.mortalite === null) {
      return this._appliqueCliquet(annee);
    }
    const ancrage = this._appliqueCliquet(this.parametres.annee_bascule);
    const cible = this.parametres.ratio_cible_retraite_carriere;
    let age = ancrage;
    while (age < 75) {
      const esperance = this.mortalite.esperanceResiduelle(age, annee);
      const carriere = age - 22.0;
      if (carriere > 0 && esperance / carriere <= cible) {
        return age;
      }
      age += 0.25;
    }
    return 75.0;
  }

  ecart(ageLiquidation, anneeLiquidation) {
    return ecartAge(ageLiquidation, this.age(anneeLiquidation), anneeLiquidation);
  }

  fiabilite(annee) {
    return this._legal.fiabilite(annee);
  }
}
