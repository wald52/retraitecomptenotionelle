/**
 * Scénarios 2 et 3 — les comptes notionnels.
 *
 * Portage de ``src/retraite_notionnelle/scenarios/notionnel.py``.
 *
 * **Scénario 2, rétroactif.** Le compte est ouvert à l'entrée dans la vie
 * active, ou à l'année d'origine de la répartition si la carrière a commencé
 * avant. Toute la carrière est recalculée sur les seules cotisations versées.
 * Un départ à 55 ans dans un régime spécial en 1985 est traité comme ce qu'il
 * est : douze années de cotisations en moins et douze années de rente en plus.
 *
 * **Scénario 3, prospectif.** Les droits acquis jusqu'à la bascule sont figés
 * selon les règles actuelles, convertis en capital notionnel d'ouverture, puis
 * le compte fonctionne en notionnel au-delà. C'est la variante qui respecte les
 * droits acquis — celle qu'une réforme réelle retiendrait. La conversion inverse
 * la formule de liquidation : K_ouverture = P_acquise × G(a_c, B).
 *
 * Le choix de l'âge a_c est le seul endroit du modèle où le passage aux comptes
 * notionnels peut, à lui seul, retirer quelque chose à des droits déjà ouverts.
 * Voir ``AgeConversionDroitsAcquis``.
 */

import { Carriere } from "./carriere.js";
import { AgeConversionDroitsAcquis, TableConversion } from "./config.js";

/** Produit les deux variantes de comptes notionnels. */
export class ScenarioNotionnel {
  constructor(constructeur, convertisseur, ageReference, scenarioActuel, parametres) {
    this.constructeur = constructeur;
    this.convertisseur = convertisseur;
    this.ageReference = ageReference;
    this.scenarioActuel = scenarioActuel;
    this.parametres = parametres;
  }

  _sexe(carriere) {
    if (this.parametres.table_conversion === TableConversion.UNISEXE) {
      return null;
    }
    return carriere.sexe;
  }

  // -- scénario 2 ------------------------------------------------------------

  /** Comptes notionnels appliqués depuis l'origine de la répartition. */
  retroactif(carriere, regimeFusionne = null) {
    const anneeLiquidation = carriere.anneeLiquidation;
    const ageLiquidation = carriere.age_liquidation || 0.0;

    const compte = this.constructeur.construire(
      carriere, anneeLiquidation, carriere.premiereAnnee, regimeFusionne,
    );
    const conversion = this.convertisseur.coefficient(
      ageLiquidation, anneeLiquidation, this._sexe(carriere),
    );

    return resultat({
      pension_annuelle: compte.capital / conversion.diviseur,
      capital_notionnel: compte.capital,
      capital_droits_acquis: 0.0,
      compte,
      conversion,
      ecart_age: this.ageReference.ecart(ageLiquidation, anneeLiquidation),
      capital_capitalisation: compte.capital_hors_repartition,
      fiabilite: Math.min(compte.fiabilite, conversion.fiabilite),
      libelle: "Comptes notionnels rétroactifs",
    });
  }

  // -- scénario 3 ------------------------------------------------------------

  /**
   * Droits figés à la bascule, comptes notionnels au-delà.
   *
   * Pour un assuré dont la retraite est déjà liquidée à la bascule, ce scénario
   * ne peut rien changer : ses droits sont intégralement acquis. On renvoie
   * alors sa pension actuelle, de sorte que le tableau comparatif reste lisible.
   */
  prospectif(carriere, regimeFusionne) {
    const anneeLiquidation = carriere.anneeLiquidation;
    const ageLiquidation = carriere.age_liquidation || 0.0;
    const bascule = this.parametres.annee_bascule;

    if (anneeLiquidation <= bascule) {
      return this._dejaLiquide(carriere);
    }

    const droitsAcquis = this._droitsAcquis(carriere, bascule);
    const capitalAcquis = droitsAcquis === null ? 0.0 : droitsAcquis.capital;

    const compte = this.constructeur.construire(
      carriere, anneeLiquidation, bascule, regimeFusionne,
    );
    const conversion = this.convertisseur.coefficient(
      ageLiquidation, anneeLiquidation, this._sexe(carriere),
    );
    const capitalTotal = compte.capital + capitalAcquis;

    return resultat({
      pension_annuelle: capitalTotal / conversion.diviseur,
      capital_notionnel: capitalTotal,
      capital_droits_acquis: capitalAcquis,
      compte,
      conversion,
      ecart_age: this.ageReference.ecart(ageLiquidation, anneeLiquidation),
      capital_capitalisation: compte.capital_hors_repartition,
      fiabilite: Math.min(compte.fiabilite, conversion.fiabilite),
      libelle: "Comptes notionnels à compter de la bascule",
      droits_acquis: droitsAcquis,
    });
  }

  /** Cas d'un assuré déjà retraité à la bascule : rien ne change. */
  _dejaLiquide(carriere) {
    const anneeLiquidation = carriere.anneeLiquidation;
    const ageLiquidation = carriere.age_liquidation || 0.0;
    const actuel = this.scenarioActuel.calculer(carriere);
    const conversion = this.convertisseur.coefficient(
      ageLiquidation, anneeLiquidation, this._sexe(carriere),
    );
    const compte = this.constructeur.construire(
      carriere, anneeLiquidation, anneeLiquidation, // aucune cotisation postérieure
    );
    return resultat({
      pension_annuelle: actuel.pension_annuelle,
      capital_notionnel: actuel.pension_annuelle * conversion.diviseur,
      capital_droits_acquis: actuel.pension_annuelle * conversion.diviseur,
      compte,
      conversion,
      ecart_age: this.ageReference.ecart(ageLiquidation, anneeLiquidation),
      capital_capitalisation: 0.0,
      fiabilite: actuel.fiabilite,
      libelle: "Retraite déjà liquidée à la bascule — droits inchangés",
    });
  }

  /**
   * Convertit les droits figés à la bascule en capital notionnel.
   *
   * Les droits sont ceux qu'aurait produits la carrière si elle s'était
   * arrêtée à la bascule, calculés selon les règles actuelles mais DÉBARRASSÉS
   * des avantages non contributifs. La valorisation se fait à l'année de
   * bascule, sans décote ni surcote : on mesure des droits déjà ouverts, pas
   * une liquidation anticipée.
   *
   * Reste l'âge auquel prendre le diviseur, et c'est le paramètre
   * ``age_conversion_droits_acquis`` qui tranche : l'âge de référence fait
   * payer l'anticipation une seconde fois, sur des droits pourtant déjà
   * ouverts ; l'âge effectif de liquidation rend la conversion neutre. Dans les
   * deux cas, l'écart de longévité entre la bascule et la liquidation subsiste.
   *
   * Renvoie les étapes de la cascade, ou ``null`` si rien n'a été acquis.
   */
  _droitsAcquis(carriere, bascule) {
    const lignesAvant = carriere.lignes.filter((ligne) => ligne.annee < bascule);
    if (lignesAvant.length === 0) {
      return null;
    }

    const carriereTronquee = new Carriere({
      annee_naissance: carriere.annee_naissance,
      sexe: carriere.sexe,
      lignes: lignesAvant,
      // L'année de liquidation de cette carrière fictive doit être l'année de
      // bascule : c'est en euros de cette année-là que les droits sont valorisés.
      age_liquidation: bascule - carriere.annee_naissance,
      nombre_enfants: 0, // avantages familiaux neutralisés
      identifiant: `${carriere.identifiant} (droits figés ${bascule})`,
    });
    const droits = this.scenarioActuel.calculer(carriereTronquee, true);

    const ageConversion = this.parametres.age_conversion_droits_acquis
        === AgeConversionDroitsAcquis.REFERENCE
      ? this.ageReference.age(bascule)
      : (carriere.age_liquidation || this.ageReference.age(bascule));
    const conversion = this.convertisseur.coefficient(
      ageConversion, bascule, this._sexe(carriere),
    );
    const capitalALaBascule = droits.pension_annuelle * conversion.diviseur;

    // Le capital d'ouverture se revalorise ensuite comme tout compte notionnel.
    const coefficient = this.constructeur.indexation.coefficient(
      bascule, carriere.anneeLiquidation,
    );
    return {
      pension_figee: droits.pension_annuelle,
      age_conversion: ageConversion,
      diviseur: conversion.diviseur,
      capital_a_la_bascule: capitalALaBascule,
      coefficient_revalorisation: coefficient,
      capital: capitalALaBascule * coefficient,
    };
  }
}

/** Pension issue d'un compte notionnel, et tout ce qui l'explique. */
function resultat(champs) {
  return {
    // Le détail de la conversion des droits figés n'existe qu'en prospectif ;
    // ailleurs il vaut null, comme du côté Python.
    droits_acquis: null,
    ...champs,
    pension_mensuelle: champs.pension_annuelle / 12.0,
    /**
     * Rente issue du compartiment de capitalisation, servie à part. Le RAFP et
     * les droits des anciennes assurances sociales ne sont pas convertis en
     * capital notionnel : ils restent dans un compartiment distinct, converti
     * au même coefficient actuariel.
     */
    rente_capitalisation_annuelle: champs.conversion.diviseur <= 0
      ? 0.0
      : champs.capital_capitalisation / champs.conversion.diviseur,
  };
}
