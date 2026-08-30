/**
 * Simulateur : assemble les données, le moteur et les cinq scénarios.
 *
 * Portage de ``src/retraite_notionnelle/simulateur.py``. C'est le point d'entrée
 * unique : une instance charge les données une fois et simule ensuite autant de
 * carrières que voulu.
 */

import { Carriere } from "./carriere.js";
import {
  ContributionEmployeurPublic, PARAMETRES_DEFAUT, SourceCotisations,
} from "./config.js";
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
 */
export const SCENARIOS_NOTIONNELS = Object.freeze([
  ["notionnel_retroactif", 2, "Notionnel rétroactif (depuis l'origine)"],
  ["notionnel_prospectif", 3, "Notionnel à compter de {bascule}"],
  ["notionnel_financement_public", 4, "Notionnel, financement public réel"],
  ["notionnel_acquisition_commune", 5, "Notionnel, taux d'acquisition commun"],
]);

/** Les cinq résultats, côte à côte, pour une même carrière. */
export class Comparaison {
  constructor({
    carriere, actuel, notionnelRetroactif, notionnelProspectif,
    notionnelFinancementPublic, notionnelAcquisitionCommune,
    regimeFusionne, parametres, coefficientEurosConstants = 1.0,
  }) {
    this.carriere = carriere;
    this.actuel = actuel;
    this.notionnel_retroactif = notionnelRetroactif;
    this.notionnel_prospectif = notionnelProspectif;
    this.notionnel_financement_public = notionnelFinancementPublic;
    this.notionnel_acquisition_commune = notionnelAcquisitionCommune;
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
   * et 5 en sont exclus à dessein : chacun porte la sienne, et les laisser
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

  /** Versé, acquisitif, transition — les trois colonnes du financement. */
  get partageFinancement() {
    const versee = this.notionnel_financement_public.compte.cotisations_versees;
    const acquisitive = this.notionnel_acquisition_commune.compte.cotisations_versees;
    const annees = this.notionnel_financement_public.compte.annees_part_employeur;
    return {
      versee,
      acquisitive,
      transition: versee - acquisitive,
      part_transition: versee ? (versee - acquisitive) / versee : 0.0,
      annees_par_origine: annees,
      concerne_un_regime_public: Object.keys(annees).length > 0,
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
        sexe: carriere.sexe,
        age_liquidation: carriere.age_liquidation,
        annee_liquidation: carriere.anneeLiquidation,
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
      financement: {
        versee: this.partageFinancement.versee,
        acquisitive: this.partageFinancement.acquisitive,
        transition: this.partageFinancement.transition,
        part_transition: this.partageFinancement.part_transition,
        taux_acquisition_commun: this.parametres.taux_cotisation_uniforme,
        annees_par_origine: Object.fromEntries(
          Object.entries(this.partageFinancement.annees_par_origine).sort(
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
function tauxRemplacement(carriere, pension) {
  const derniers = carriere.lignes.filter((ligne) => ligne.cotise);
  if (derniers.length === 0 || pension <= 0) {
    return 0.0;
  }
  return pension / derniers[derniers.length - 1].revenu;
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
    const variante = (modifications) => new ScenarioNotionnel(
      new ConstructeurCompte(
        this.macro, this.catalogue, this.affiliations, this.indexation,
        { ...parametres, ...modifications },
      ),
      this.convertisseur, this.ageReference, this.scenarioActuel, parametres,
    );
    this.scenarioFinancementPublic = variante({
      traitement_contribution_employeur_etat:
        ContributionEmployeurPublic.FINANCEMENT_HISTORIQUE,
    });
    this.scenarioAcquisitionCommune = variante({
      source_cotisations: SourceCotisations.TAUX_UNIFORME,
    });
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
      notionnelFinancementPublic: this.scenarioFinancementPublic.retroactif(
        carriere, fusionne,
        "Comptes notionnels rétroactifs, financement public réel",
      ),
      notionnelAcquisitionCommune: this.scenarioAcquisitionCommune.retroactif(
        carriere, fusionne,
        "Comptes notionnels rétroactifs, taux d'acquisition commun",
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
