/**
 * Coefficient de conversion du capital notionnel en rente viagère.
 *
 * Portage de ``src/retraite_notionnelle/moteur/conversion.py``. La pension
 * annuelle vaut ``capital_notionnel / diviseur``, où le diviseur est
 * l'espérance de vie résiduelle actualisée :
 *
 *     G(a, L) = Σ_t  t·p_a  (1 + ν)^(−t)
 *
 * lue sur une table de génération. Le taux de préfinancement ν vaut 0 par
 * défaut : la rente est actualisée au taux auquel elle sera revalorisée, les
 * deux se compensent, et le diviseur se réduit à l'espérance de vie résiduelle.
 *
 * Ce que le diviseur sanctionne tout seul : partir cinq ans plus tôt l'augmente
 * de quatre à cinq années, soit une pension inférieure de 15 à 20 % — avant
 * même de compter les cinq années de cotisations manquantes.
 */

import { TableConversion } from "./config.js";

export class Convertisseur {
  constructor(mortalite, parametres) {
    this.mortalite = mortalite;
    this.parametres = parametres;
  }

  _sexeTable(sexe) {
    if (this.parametres.table_conversion === TableConversion.UNISEXE) {
      return null;
    }
    if (sexe === null || sexe === undefined) {
      throw new Error("table de conversion par sexe demandée mais sexe non renseigné");
    }
    return sexe;
  }

  /** Diviseur annuitaire et éléments qui l'expliquent. */
  coefficient(ageLiquidation, anneeLiquidation, sexe = null) {
    const sexeTable = this._sexeTable(sexe);
    const generation = this.parametres.table_generation;
    const courbe = this.mortalite.courbe(
      ageLiquidation, anneeLiquidation, sexeTable, generation,
    );

    const nu = this.parametres.taux_anticipe_conversion;
    let diviseur = 0.0;
    for (let t = 0; t < courbe.length - 1; t += 1) {
      // Rente supposée servie en continu sur l'année : on prend la survie
      // moyenne de début et de fin de période.
      const survieMoyenne = 0.5 * (courbe[t] + courbe[t + 1]);
      diviseur += survieMoyenne / ((1.0 + nu) ** (t + 0.5));
    }

    if (diviseur <= 0) {
      throw new Error(
        `diviseur nul à ${ageLiquidation} ans en ${anneeLiquidation} : `
        + "âge de liquidation hors des bornes de la table",
      );
    }

    let esperance = 0.0;
    for (let t = 0; t < courbe.length - 1; t += 1) {
      esperance += 0.5 * (courbe[t] + courbe[t + 1]);
    }

    return {
      diviseur,
      age_liquidation: ageLiquidation,
      annee_liquidation: anneeLiquidation,
      esperance_residuelle: esperance,
      table: (sexeTable === null ? "unisexe" : sexeTable)
        + (generation ? "_generation" : "_moment"),
      taux_anticipe: nu,
      fiabilite: this.mortalite.fiabilite(anneeLiquidation),
      /** Fraction du capital notionnel servie chaque année. */
      get taux_de_rente() {
        return this.diviseur ? 1.0 / this.diviseur : 0.0;
      },
    };
  }

  /**
   * Rapport des pensions à capital notionnel donné, anticipé / à l'heure.
   * Isole la seule sanction due à l'allongement de la durée de service.
   */
  effetAnticipation(ageAnticipe, ageReference, anneeLiquidation, sexe = null) {
    const anticipe = this.coefficient(ageAnticipe, anneeLiquidation, sexe);
    const reference = this.coefficient(ageReference, anneeLiquidation, sexe);
    return reference.diviseur / anticipe.diviseur;
  }
}
