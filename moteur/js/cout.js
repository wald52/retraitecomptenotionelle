/**
 * Le coût agrégé des cinq systèmes, année par année, depuis 1959.
 *
 * Portage de ``src/retraite_notionnelle/cout.py``. La méthode tient en une
 * ligne, et c'est ce qui la rend contrôlable :
 *
 *     coût du système S en t = dépense OBSERVÉE en t × (masse S / masse actuelle)
 *
 * La dépense observée vient de la DREES et n'est pas modélisée. Seul le RAPPORT
 * l'est : la moyenne des écarts de pension entre systèmes, pondérée par le poids
 * de chaque génération dans la masse de l'année — poids lus dans les tables de
 * mortalité du dépôt, pensions tirées des douze cas types.
 *
 * Les trois limites sont énoncées dans le module Python et rappelées par la
 * page : population supposée stationnaire, cas types de poids égal,
 * reconstitution mince avant 1975.
 */

import { CAS_TYPES, calculerCasTypes } from "./castypes.js";
import { Fiabilite } from "./serie.js";

/** Les cinq systèmes, dans l'ordre du tableau de comparaison. */
export const SCENARIOS = [
  ["actuel", "1. Système actuel"],
  ["notionnel_retroactif", "2. Notionnel rétroactif, part salariale"],
  ["notionnel_prospectif", "3. Notionnel dès la bascule, part salariale"],
  ["notionnel_retroactif_employeur",
    "4. Notionnel rétroactif, avec la part patronale"],
  ["notionnel_prospectif_employeur",
    "5. Notionnel dès la bascule, avec la part patronale"],
];

/**
 * Première génération dont une liquidation puisse tomber après le début de la
 * répartition (1941). En deçà, le modèle refuse — à juste titre — de calculer.
 */
export const PREMIERE_GENERATION = 1880;

/** Dernière génération retenue : née en 1970, elle liquide au plus tôt en 2022. */
export const DERNIERE_GENERATION = 1970;

/** Pas de la grille de générations : il commande le temps de calcul de la page. */
export const PAS_GENERATIONS = 5;

/** Année à partir de laquelle la reconstitution repose sur tous les cas types. */
export const PREMIERE_ANNEE_ROBUSTE = 1975;

export function generations() {
  const liste = [];
  for (let g = PREMIERE_GENERATION; g <= DERNIERE_GENERATION; g += PAS_GENERATIONS) {
    liste.push(g);
  }
  return liste;
}

/** Simule la grille et en tire, pour chaque couple, son poids dans le temps. */
function pensionnes(simulateur, casTypes) {
  const grille = calculerCasTypes(simulateur, casTypes, generations());
  const mortalite = simulateur.mortalite;
  const liste = [];
  for (const comparaison of grille.resultats.values()) {
    const carriere = comparaison.carriere;
    const pensions = {};
    for (const [scenario] of SCENARIOS) {
      pensions[scenario] = comparaison.enEurosConstants(
        comparaison[scenario].pension_annuelle,
      );
    }
    liste.push({
      anneeLiquidation: carriere.anneeLiquidation,
      survie: mortalite.courbe(
        carriere.age_liquidation, carriere.anneeLiquidation, null,
      ),
      pensions,
    });
  }
  const motifs = new Map();
  for (const motif of grille.echecs.values()) {
    motifs.set(motif, (motifs.get(motif) || 0) + 1);
  }
  return { liste, motifs };
}

/** Le coût d'une année, observé puis recalculé pour chaque système. */
class CoutAnnuel {
  constructor(annee, observee, coefficientConstants, partPib, rapports, nombre) {
    this.annee = annee;
    this.observee = observee;
    this.coefficientConstants = coefficientConstants;
    this.partPib = partPib;
    this.rapports = rapports;
    this.pensionnes = nombre;
  }

  /** Coût du système, en millions d'euros courants de l'année. */
  cout(scenario) {
    return this.observee * this.rapports[scenario];
  }

  coutConstants(scenario) {
    return this.cout(scenario) * this.coefficientConstants;
  }

  get observeeConstants() {
    return this.observee * this.coefficientConstants;
  }
}

/** La série complète, et les cumuls qu'on en tire. */
class Cout {
  constructor(annees, anneeEuros, generationsRetenues, echecs, fiabilite) {
    this.annees = annees;
    this.anneeEuros = anneeEuros;
    this.generations = generationsRetenues;
    this.echecs = echecs;
    this.fiabilite = fiabilite;
    this.premiereAnnee = annees[0].annee;
    this.derniereAnnee = annees[annees.length - 1].annee;
  }

  /**
   * Cumul depuis la première année, en millions d'euros CONSTANTS. Sommer des
   * euros courants de 1959 et de 2024 n'aurait aucun sens.
   */
  cumul(scenario) {
    let somme = 0;
    for (const ligne of this.annees) somme += ligne.coutConstants(scenario);
    return somme;
  }

  cumulObserve() {
    let somme = 0;
    for (const ligne of this.annees) somme += ligne.observeeConstants;
    return somme;
  }

  /**
   * Scénarios dont le coût ne s'écarte JAMAIS de celui du système actuel.
   *
   * Sur la fenêtre observée, ce sont les scénarios prospectifs : leur bascule
   * est postérieure à la dernière année publiée, si bien qu'aucune pension n'en
   * est modifiée et que le rapport vaut exactement un. L'égalité est stricte —
   * le scénario prospectif RECOPIE la pension du scénario actuel pour qui a
   * liquidé avant la bascule. Le calcul est fait, et non écrit en dur : une
   * bascule avancée séparerait les courbes, et la page le montrerait.
   */
  confondusAvecActuel() {
    return SCENARIOS
      .map(([scenario]) => scenario)
      .filter((scenario) => scenario !== "actuel"
        && this.annees.every((ligne) => ligne.rapports[scenario] === 1.0));
  }

  annee(millesime) {
    for (const ligne of this.annees) {
      if (ligne.annee === millesime) return ligne;
    }
    return null;
  }
}

/**
 * Le coût observé et les quatre contrefactuels, année par année. Les années où
 * le modèle ne sert aucune pension sont écartées : un rapport y serait une
 * division par zéro, et non un résultat.
 */
export function calculerCout(simulateur, depenses, casTypes = CAS_TYPES) {
  const { liste, motifs } = pensionnes(simulateur, casTypes);
  const macro = simulateur.macro;
  const anneeEuros = simulateur.parametres.annee_euros_constants;

  const lignes = [];
  for (const annee of depenses.annees()) {
    const masses = {};
    for (const [scenario] of SCENARIOS) masses[scenario] = 0;
    let vivants = 0;
    for (const pensionne of liste) {
      const duree = annee - pensionne.anneeLiquidation;
      if (duree < 0 || duree >= pensionne.survie.length) continue;
      const poids = pensionne.survie[duree];
      if (poids <= 0) continue;
      vivants += 1;
      for (const [scenario] of SCENARIOS) {
        masses[scenario] += poids * pensionne.pensions[scenario];
      }
    }
    if (masses.actuel <= 0) continue;
    const rapports = {};
    for (const [scenario] of SCENARIOS) {
      rapports[scenario] = masses[scenario] / masses.actuel;
    }
    lignes.push(new CoutAnnuel(
      annee,
      depenses.depense(annee),
      macro.coefficientPrix(annee, anneeEuros),
      depenses.partPib(annee),
      rapports,
      vivants,
    ));
  }

  let fiabilite = Fiabilite.ESTIMEE;
  for (const ligne of lignes) {
    fiabilite = Math.min(fiabilite, depenses.fiabilite(ligne.annee));
  }
  // Le contrefactuel ne peut jamais valoir mieux qu'« estimé » : la dépense
  // observée est certifiée, le rapport qui la corrige ne l'est pas et ne peut
  // pas l'être — aucune institution ne publie ce qu'un système qui n'a pas
  // existé aurait coûté.
  return new Cout(
    lignes, anneeEuros, generations(), motifs,
    Math.min(fiabilite, Fiabilite.ESTIMEE),
  );
}
