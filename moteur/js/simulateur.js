/**
 * Simulateur : assemble les données, le moteur et les cinq scénarios.
 *
 * Portage de ``src/retraite_notionnelle/simulateur.py``. C'est le point d'entrée
 * unique : une instance charge les données une fois et simule ensuite autant de
 * carrières que voulu.
 */

import { Carriere } from "./carriere.js";
import { PARAMETRES_DEFAUT, PartCotisation } from "./config.js";
import { ConstructeurCompte } from "./compte.js";
import { Convertisseur } from "./conversion.js";
import { AgeReference } from "./age-reference.js";
import { DonneesMacro } from "./macro.js";
import { DonneesMortalite } from "./mortalite.js";
import { Indexation } from "./indexation.js";
import { ScenarioActuel } from "./scenario-actuel.js";
import { ScenarioNotionnel } from "./scenario-notionnel.js";
import { Affiliations, CatalogueRegimes } from "./regimes.js";
import { fusionner } from "./fusion.js";
import {
  DonneeInsuffisante, Fiabilite, fiabiliteDepuisTexte, nomFiabilite,
} from "./serie.js";

/**
 * Les quatre scénarios notionnels, dans l'ordre où ils s'affichent, avec le
 * numéro et le titre sous lesquels le tableau, la page et l'API les citent.
 *
 * Deux paires : 2 et 3 ne portent au compte que la part SALARIALE de la
 * cotisation, 4 et 5 y ajoutent la part PATRONALE. À l'intérieur de chaque
 * paire, l'un est rétroactif et l'autre prospectif. Le 4 se lit contre le 2, le
 * 5 contre le 3, et l'écart mesure exactement ce que l'employeur verse.
 */
export const SCENARIOS_NOTIONNELS = Object.freeze([
  ["notionnel_retroactif", 2, "Notionnel rétroactif, part salariale"],
  ["notionnel_prospectif", 3, "Notionnel dès {bascule}, part salariale"],
  ["notionnel_retroactif_employeur", 4,
    "Notionnel rétroactif, salariale + patronale"],
  ["notionnel_prospectif_employeur", 5,
    "Notionnel dès {bascule}, salariale + patronale"],
]);

/** Les cinq résultats, côte à côte, pour une même carrière. */
export class Comparaison {
  constructor({
    carriere, actuel, notionnelRetroactif, notionnelProspectif,
    notionnelRetroactifEmployeur, notionnelProspectifEmployeur,
    regimeFusionne, parametres, coefficientEurosConstants = 1.0,
  }) {
    this.carriere = carriere;
    this.actuel = actuel;
    this.notionnel_retroactif = notionnelRetroactif;
    this.notionnel_prospectif = notionnelProspectif;
    this.notionnel_retroactif_employeur = notionnelRetroactifEmployeur;
    this.notionnel_prospectif_employeur = notionnelProspectifEmployeur;
    this.regime_fusionne = regimeFusionne;
    this.parametres = parametres;
    //: Coefficient de passage des euros de l'année de liquidation aux euros
    //: constants de ``parametres.annee_euros_constants``.
    this.coefficient_euros_constants = coefficientEurosConstants;
  }

  enEurosConstants(montant) {
    return montant * this.coefficient_euros_constants;
  }

  /**
   * Fiabilité de l'étalon et des deux scénarios de référence. Les scénarios 4
   * et 5 en sont exclus à dessein : ils reposent sur une série employeur qui
   * n'existe pas pour tous les régimes ni sur toutes les années, et les laisser
   * qualifier l'ensemble ferait retomber toute simulation publique à
   * « estimée » alors que les trois premiers ne se sont pas dégradés. La sortie
   * JSON donne celle de chaque scénario, une à une.
   */
  get fiabilite() {
    return Math.min(
      this.actuel.fiabilite,
      this.notionnel_retroactif.fiabilite,
      this.notionnel_prospectif.fiabilite,
    );
  }

  /** Agent, employeur, total — la décomposition du scénario 4. */
  get contributionEmployeur() {
    const compte = this.notionnel_retroactif_employeur.compte;
    const total = compte.cotisations_versees;
    const employeur = compte.cotisations_employeur;
    const annees = compte.annees_part_employeur;
    return {
      total,
      employeur,
      agent: total - employeur,
      part: total ? employeur / total : 0.0,
      annees_par_origine: annees,
      a_un_employeur: employeur > 0,
      concerne_un_regime_public: Object.keys(annees).length > 0,
      annees_trouvees: Object.entries(annees)
        .filter(([origine]) => origine !== "repli")
        .reduce((somme, [, nombre]) => somme + nombre, 0),
      annees_repli: annees.repli ?? 0,
    };
  }

  /** Écart relatif d'un scénario notionnel au système actuel. */
  variation(scenario) {
    const reference = this.actuel.pension_annuelle;
    if (reference <= 0) {
      return NaN;
    }
    return this[scenario].pension_annuelle / reference - 1.0;
  }

  get tauxRemplacementActuel() {
    return tauxRemplacement(this.carriere, this.actuel.pension_annuelle);
  }

  get tauxRemplacementRetroactif() {
    return tauxRemplacement(this.carriere, this.notionnel_retroactif.pension_annuelle);
  }

  get tauxRemplacementProspectif() {
    return tauxRemplacement(this.carriere, this.notionnel_prospectif.pension_annuelle);
  }

  /** Taux de remplacement de n'importe lequel des scénarios notionnels. */
  tauxRemplacement(scenario) {
    return tauxRemplacement(this.carriere, this[scenario].pension_annuelle);
  }

  /** Forme sérialisable, pour un export ou une comparaison. */
  dictionnaire() {
    const carriere = this.carriere;
    const ecart = this.notionnel_retroactif.ecart_age;
    const conversion = this.notionnel_retroactif.conversion;
    return {
      assure: {
        identifiant: carriere.identifiant,
        annee_naissance: carriere.annee_naissance,
        mois_naissance: carriere.mois_naissance,
        sexe: carriere.sexe,
        age_liquidation: carriere.age_liquidation,
        annee_liquidation: carriere.anneeLiquidation,
        mois_liquidation: carriere.moisLiquidation,
        annees_cotisees: carriere.anneesCotisees.length,
        trimestres_actuels: carriere.trimestresActuels,
        affiliations: carriere.affiliationsUtilisees(),
      },
      age_reference: {
        age: ecart.age_reference,
        ecart_annees: ecart.ecart,
        anticipe: ecart.anticipe,
      },
      conversion: {
        diviseur: conversion.diviseur,
        esperance_residuelle: conversion.esperance_residuelle,
        table: conversion.table,
      },
      scenarios: {
        actuel: {
          pension_annuelle: this.actuel.pension_annuelle,
          pension_annuelle_euros_constants: this.enEurosConstants(
            this.actuel.pension_annuelle,
          ),
          pension_mensuelle: this.actuel.pension_mensuelle,
          taux_remplacement: this.tauxRemplacementActuel,
          par_regime: this.actuel.pensions_par_regime.map((p) => ({
            regime: p.regime, montant: p.montant, detail: p.detail,
          })),
          minimum_applique: this.actuel.minimum_applique,
          liquidation_ouverte: this.actuel.liquidation_ouverte,
          motif_ouverture: this.actuel.motif_ouverture,
          age_ouverture_opposable: this.actuel.age_ouverture_opposable,
          total_contributif: this.actuel.total_contributif,
          pension_hors_repartition: this.actuel.pension_hors_repartition,
          avantages_appliques: this.actuel.avantages_appliques.map((a) => ({
            code: a.code, libelle: a.libelle, montant: a.montant, detail: a.detail,
          })),
        },
        ...Object.fromEntries(SCENARIOS_NOTIONNELS.map(([cle]) => [
          cle,
          resumeNotionnel(
            this[cle], this.tauxRemplacement(cle), this.variation(cle),
            this.coefficient_euros_constants,
          ),
        ])),
      },
      contribution_employeur: {
        total: this.contributionEmployeur.total,
        employeur: this.contributionEmployeur.employeur,
        agent: this.contributionEmployeur.agent,
        part: this.contributionEmployeur.part,
        annees_par_origine: Object.fromEntries(
          Object.entries(this.contributionEmployeur.annees_par_origine).sort(
            (a, b) => (a[0] < b[0] ? -1 : 1),
          ),
        ),
      },
      unite: {
        euros_constants_de: this.parametres.annee_euros_constants,
        coefficient: this.coefficient_euros_constants,
        scenario_projection: this.parametres.scenario_projection,
      },
      regime_fusionne: {
        annee_bascule: this.regime_fusionne.annee_bascule,
        age_ouverture: this.regime_fusionne.age_ouverture,
        age_taux_plein: this.regime_fusionne.age_taux_plein,
        duree_requise_trimestres: this.regime_fusionne.duree_requise_trimestres,
        taux_cotisation: this.regime_fusionne.taux_cotisation_retraite,
        regimes_fusionnes: [...this.regime_fusionne.regimes_fusionnes],
        origines: { ...this.regime_fusionne.origines },
      },
      fiabilite: nomFiabilite(this.fiabilite),
    };
  }
}

function resumeNotionnel(resultat, tauxRemplacementScenario, variation, coefficient = 1.0) {
  return {
    pension_annuelle: resultat.pension_annuelle,
    pension_annuelle_euros_constants: resultat.pension_annuelle * coefficient,
    pension_mensuelle: resultat.pension_mensuelle,
    taux_remplacement: tauxRemplacementScenario,
    variation_vs_actuel: variation,
    capital_notionnel: resultat.capital_notionnel,
    capital_droits_acquis: resultat.capital_droits_acquis,
    droits_acquis: resultat.droits_acquis === null ? null : {
      pension_figee: resultat.droits_acquis.pension_figee,
      age_conversion: resultat.droits_acquis.age_conversion,
      diviseur: resultat.droits_acquis.diviseur,
      capital_a_la_bascule: resultat.droits_acquis.capital_a_la_bascule,
      coefficient_revalorisation: resultat.droits_acquis.coefficient_revalorisation,
      capital: resultat.droits_acquis.capital,
    },
    cotisations_versees: resultat.compte.cotisations_versees,
    rendement_cumule: resultat.compte.rendement_cumule,
    cotisations_employeur: resultat.compte.cotisations_employeur,
    annees_part_employeur: Object.fromEntries(
      Object.entries(resultat.compte.annees_part_employeur).sort(
        (a, b) => (a[0] < b[0] ? -1 : 1),
      ),
    ),
    rente_capitalisation: resultat.rente_capitalisation_annuelle,
    fiabilite: nomFiabilite(resultat.fiabilite),
  };
}

/** Pension rapportée au dernier revenu d'activité. */
/**
 * Pension rapportée au dernier revenu d'activité, ANNUALISÉ.
 *
 * L'année du départ est incomplète — six mois de salaire pour qui liquide au
 * 1er juillet —, et la rapporter telle quelle doublait le taux de remplacement.
 * Ce que le taux compare, c'est une pension annuelle au traitement ANNUEL que
 * l'assuré percevait en partant.
 */
function tauxRemplacement(carriere, pension) {
  const derniers = carriere.lignes.filter((ligne) => ligne.cotise);
  if (derniers.length === 0 || pension <= 0) {
    return 0.0;
  }
  const dernier = derniers[derniers.length - 1].revenuAnnualise;
  return dernier > 0 ? pension / dernier : 0.0;
}

/** Façade : charge les données une fois, simule autant de carrières que voulu. */
export class Simulateur {
  constructor(paquet, parametres = PARAMETRES_DEFAUT) {
    this.paquet = paquet;
    this.parametres = parametres;

    this.macro = new DonneesMacro(paquet, parametres.scenario_projection);
    this.mortalite = new DonneesMortalite(paquet);
    this.catalogue = new CatalogueRegimes(paquet);
    this.affiliations = new Affiliations(paquet);

    this.indexation = new Indexation(this.macro, parametres);
    this.convertisseur = new Convertisseur(this.mortalite, parametres);
    this.ageReference = new AgeReference(paquet, parametres, this.mortalite);
    this.constructeur = new ConstructeurCompte(
      this.macro, this.catalogue, this.affiliations, this.indexation, parametres,
    );
    this.scenarioActuel = new ScenarioActuel(
      paquet, this.macro, this.catalogue, this.affiliations, parametres,
    );
    this.scenarioNotionnel = new ScenarioNotionnel(
      this.constructeur, this.convertisseur, this.ageReference,
      this.scenarioActuel, parametres,
    );

    // Les scénarios 4 et 5 ne diffèrent du scénario 2 que par leur flux de
    // cotisations : mêmes données, même indexation, même liquidation. Ils se
    // construisent donc en dérivant les paramètres, ce qui garantit qu'aucune
    // autre différence ne peut s'y glisser à l'insu du lecteur.
    // Scénarios 4 et 5 : un seul scénario pour les deux, comme
    // `scenarioNotionnel` sert aux scénarios 2 et 3.
    this.scenarioEmployeur = new ScenarioNotionnel(
      new ConstructeurCompte(
        this.macro, this.catalogue, this.affiliations, this.indexation,
        { ...parametres, part_cotisation: PartCotisation.TOTALE },
      ),
      this.convertisseur, this.ageReference, this.scenarioActuel, parametres,
    );
    this._regimeFusionne = null;
  }

  get regimeFusionne() {
    if (this._regimeFusionne === null) {
      this._regimeFusionne = fusionner(this.catalogue, this.parametres.annee_bascule);
    }
    return this._regimeFusionne;
  }

  /**
   * Construit une carrière à partir de cinq informations. C'est le chemin le
   * plus court pour qu'un assuré se simule sans rien connaître de la mécanique
   * des régimes.
   */
  carriereSimple(options) {
    if (!this.affiliations.contient(options.affiliation)) {
      throw new Error(
        `affiliation inconnue : ${options.affiliation}. Disponibles : `
        + this.affiliations.codes.join(", "),
      );
    }
    return Carriere.depuisProfil({ ...options, macro: this.macro });
  }

  /** Calcule les cinq scénarios pour une carrière. */
  simuler(carriere) {
    this._verifierFiabilite(carriere);

    const fusionne = this.parametres.fusion_au_plus_defavorable ? this.regimeFusionne : null;

    return new Comparaison({
      carriere,
      actuel: this.scenarioActuel.calculer(carriere),
      notionnelRetroactif: this.scenarioNotionnel.retroactif(carriere, fusionne),
      notionnelProspectif: this.scenarioNotionnel.prospectif(carriere, this.regimeFusionne),
      notionnelRetroactifEmployeur: this.scenarioEmployeur.retroactif(
        carriere, fusionne,
        "Comptes notionnels rétroactifs, cotisation salariale et patronale",
      ),
      notionnelProspectifEmployeur: this.scenarioEmployeur.prospectif(
        carriere, this.regimeFusionne,
        "Comptes notionnels à compter de la bascule, cotisation salariale et patronale",
      ),
      regimeFusionne: this.regimeFusionne,
      parametres: this.parametres,
      coefficientEurosConstants: this.macro.coefficientPrix(
        carriere.anneeLiquidation, this.parametres.annee_euros_constants,
      ),
    });
  }

  _verifierFiabilite(carriere) {
    const exigee = fiabiliteDepuisTexte(this.parametres.fiabilite_minimale);
    if (exigee === Fiabilite.ESTIMEE) {
      return;
    }
    const disponible = this.macro.fiabiliteSur(
      carriere.premiereAnnee, carriere.anneeLiquidation,
    );
    if (disponible < exigee) {
      throw new DonneeInsuffisante(
        "les séries macroéconomiques couvrant "
        + `${carriere.premiereAnnee}-${carriere.anneeLiquidation} sont de fiabilité `
        + `« ${nomFiabilite(disponible)} », inférieure au minimum exigé `
        + `« ${nomFiabilite(exigee)} ». Certifier les données ou abaisser `
        + "Parametres.fiabilite_minimale.",
      );
    }
  }
}
