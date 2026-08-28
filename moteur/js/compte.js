/**
 * Compte notionnel : accumulation des cotisations et liquidation.
 *
 * Portage de ``src/retraite_notionnelle/moteur/compte.py``. Le compte notionnel
 * est un compte virtuel : on y inscrit chaque année les cotisations retraite
 * réellement versées, on le revalorise au taux d'indexation retenu, et on
 * divise le solde final par un coefficient de conversion actuariel. Aucun
 * capital n'est placé — le système reste intégralement en répartition.
 *
 * Trois principes tiennent tout le reste : seules les cotisations comptent ;
 * l'année du versement fixe la valeur du droit ; l'âge de liquidation fixe le
 * partage.
 */

import { SourceCotisations } from "./config.js";
import { Fiabilite } from "./serie.js";

/** Construit un compte notionnel à partir d'une carrière. */
export class ConstructeurCompte {
  constructor(macro, catalogue, affiliations, indexation, parametres) {
    this.macro = macro;
    this.catalogue = catalogue;
    this.affiliations = affiliations;
    this.indexation = indexation;
    this.parametres = parametres;
  }

  // -- assiette --------------------------------------------------------------

  /** Part du revenu comprise entre deux bornes exprimées en plafonds. */
  _assiette(revenu, annee, borneBasse, borneHaute) {
    const pass = this.macro.plafond_securite_sociale.valeur(annee);
    const plancher = borneBasse * pass;
    const plafondGlobal = this.parametres.plafond_assiette_en_pass;
    let plafond;
    if (borneHaute === null) {
      plafond = plafondGlobal === null ? revenu : plafondGlobal * pass;
    } else {
      plafond = borneHaute * pass;
      if (plafondGlobal !== null) {
        plafond = Math.min(plafond, plafondGlobal * pass);
      }
    }
    return Math.max(0.0, Math.min(revenu, plafond) - plancher);
  }

  // -- cotisation d'une année ------------------------------------------------

  cotisationAnnuelle(carriere, annee, regimeFusionne = null) {
    const ligne = carriere.ligne(annee);
    if (ligne === null || !ligne.cotise) {
      return {
        annee, revenu: 0.0, assiette_retenue: 0.0, cotisation: 0.0,
        regimes: [], taux_effectif: 0.0, hors_repartition: 0.0,
        fiabilite: Fiabilite.CERTIFIEE, nulle: true,
      };
    }

    // Après la bascule, un seul régime : le régime fusionné.
    if (regimeFusionne !== null && annee >= regimeFusionne.annee_bascule) {
      const assiette = this._assiette(ligne.revenu, annee, 0.0, null);
      const taux = this.parametres.source_cotisations === SourceCotisations.TAUX_HISTORIQUES
        ? regimeFusionne.taux_cotisation_retraite
        : this.parametres.taux_cotisation_uniforme;
      const cotisation = assiette * taux;
      return {
        annee, revenu: ligne.revenu, assiette_retenue: assiette, cotisation,
        regimes: ["regime_unifie"], taux_effectif: taux, hors_repartition: 0.0,
        fiabilite: regimeFusionne.fiabilite, nulle: cotisation <= 0,
      };
    }

    const codes = this.affiliations.regimes(ligne.affiliation, annee);
    let cotisation = 0.0;
    let assietteTotale = 0.0;
    let horsRepartition = 0.0;
    let fiabilite = Fiabilite.CERTIFIEE;
    const retenus = [];

    for (const code of codes) {
      if (!this.catalogue.contient(code)) {
        continue;
      }
      const regime = this.catalogue.obtenir(code);
      fiabilite = Math.min(fiabilite, regime.fiabilite);
      for (const periode of regime.periodesActives(annee)) {
        const [borneBasse, borneHaute] = periode.bornesAssietteEnPass();

        let base;
        if (periode.assiette === "primes_uniquement") {
          base = ligne.revenu * ligne.part_primes;
        } else if (periode.assiette === "hors_primes") {
          base = ligne.revenu * (1.0 - ligne.part_primes);
        } else {
          base = ligne.revenu;
        }

        const assiette = this._assiette(base, annee, borneBasse, borneHaute);
        if (assiette <= 0) {
          continue;
        }

        const taux = this.parametres.source_cotisations === SourceCotisations.TAUX_HISTORIQUES
          ? periode.taux_cotisation_retraite
          : this.parametres.taux_cotisation_uniforme;
        const montant = assiette * taux;

        if (regime.hors_repartition && this.parametres.isoler_capitalisation) {
          // RAFP, assurances sociales d'avant-guerre : ces droits sont
          // provisionnés, ils ne rejoignent pas le compte notionnel.
          horsRepartition += montant;
        } else {
          cotisation += montant;
          assietteTotale += assiette;
        }
        retenus.push(code);
      }
    }

    return {
      annee,
      revenu: ligne.revenu,
      assiette_retenue: assietteTotale,
      cotisation,
      regimes: [...new Set(retenus)],
      taux_effectif: ligne.revenu ? cotisation / ligne.revenu : 0.0,
      hors_repartition: horsRepartition,
      fiabilite,
      nulle: cotisation <= 0,
    };
  }

  // -- accumulation ----------------------------------------------------------

  /**
   * Accumule les cotisations de ``anneeDebut`` à la liquidation.
   *
   * ``anneeDebut`` permet de n'ouvrir le compte qu'à partir d'une date — c'est
   * ce qui distingue le scénario notionnel prospectif (compte ouvert à l'année
   * de bascule) du scénario rétroactif (compte ouvert à l'entrée dans la vie
   * active).
   */
  construire(carriere, anneeLiquidation, anneeDebut = null, regimeFusionne = null) {
    const debut = Math.max(
      anneeDebut !== null ? anneeDebut : carriere.premiereAnnee,
      this.parametres.annee_debut_repartition,
    );
    const fin = Math.min(anneeLiquidation - 1, carriere.derniereAnnee);

    let capital = 0.0;
    let capitalHors = 0.0;
    const cotisations = [];
    let fiabilite = Fiabilite.CERTIFIEE;

    for (let annee = debut; annee <= fin; annee += 1) {
      const detail = this.cotisationAnnuelle(carriere, annee, regimeFusionne);
      cotisations.push(detail);
      if (detail.nulle && detail.hors_repartition === 0) {
        continue;
      }
      fiabilite = Math.min(fiabilite, detail.fiabilite);
      const coefficient = this.indexation.coefficient(annee, anneeLiquidation);
      capital += detail.cotisation * coefficient;
      capitalHors += detail.hors_repartition * coefficient;
    }

    if (cotisations.length > 0) {
      fiabilite = Math.min(fiabilite, this.indexation.fiabiliteSur(debut, anneeLiquidation));
    }

    const cotisationsVersees = cotisations.reduce((total, c) => total + c.cotisation, 0.0);
    return {
      capital,
      capital_hors_repartition: capitalHors,
      annee_liquidation: anneeLiquidation,
      cotisations,
      fiabilite,
      /** Somme des cotisations en euros courants, sans revalorisation. */
      cotisations_versees: cotisationsVersees,
      annees_cotisees: cotisations.filter((c) => !c.nulle).length,
      /** Rapport entre capital revalorisé et cotisations versées. */
      rendement_cumule: cotisationsVersees ? capital / cotisationsVersees : 0.0,
    };
  }
}
