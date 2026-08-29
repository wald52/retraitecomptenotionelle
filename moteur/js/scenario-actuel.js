/**
 * Scénario 1 — le système actuel, tel qu'il est.
 *
 * Portage de ``src/retraite_notionnelle/scenarios/actuel.py``. Ce scénario sert
 * d'étalon : c'est la pension que l'assuré perçoit ou percevra en droit
 * constant. Il conserve tout ce que les scénarios notionnels retirent — minima,
 * majorations, trimestres gratuits, décote et surcote, bonifications.
 *
 * C'est une approximation documentée, pas un simulateur officiel : régimes en
 * annuités par la formule taux × salaire de référence × durée / durée requise ;
 * régimes en points calculés en points quand le barème est connu, au rendement
 * instantané sinon ; montée en charge des réformes ignorée. Un écart de
 * quelques pour cent avec la pension réelle est attendu — ce que le modèle
 * mesure de façon robuste, ce sont les écarts ENTRE SCÉNARIOS.
 */

import { formatFixe, formatPourcentage } from "./format.js";
import {
  AgesOuverture, DureesRequises, MinimumContributif, Rendements, ValeursPoint,
} from "./regimes.js";
import { Fiabilite } from "./serie.js";

export class ScenarioActuel {
  constructor(paquet, macro, catalogue, affiliations, parametres) {
    this.macro = macro;
    this.catalogue = catalogue;
    this.affiliations = affiliations;
    this.parametres = parametres;
    this.rendements = new Rendements(paquet);
    this.valeursPoint = new ValeursPoint(paquet);
    this.dureesRequises = new DureesRequises(paquet);
    this.agesOuverture = new AgesOuverture(paquet);
    this.minimumContributif = new MinimumContributif(paquet, macro);
  }

  // -- valorisation des points -----------------------------------------------

  /**
   * Ce que vaut, à la liquidation, un point acquis dans ``code``.
   *
   * Un régime fermé ne sert plus ses points : ils ont été convertis dans son
   * successeur, au rapport des deux valeurs de service à la date de la reprise
   * — c'est ce rapport, et lui seul, qui préserve le niveau des pensions le
   * jour de la fusion. La méthode remonte donc la chaîne des successions en
   * cumulant les conversions. Quand la chaîne s'arrête avant l'année de
   * liquidation, la dernière valeur publiée est ramenée en euros de la
   * liquidation par l'indice des prix — approximation signalée par la fiabilité.
   */
  valeurDuPoint(code, anneeLiquidation) {
    let conversion = 1.0;
    let courant = code;
    let fiabilite = Fiabilite.CERTIFIEE;
    for (let garde = 0; garde < this.catalogue.taille + 1; garde += 1) {
      const derniere = this.valeursPoint.derniereAnneeServie(courant);
      if (derniere === null) {
        return null;
      }
      if (anneeLiquidation <= derniere) {
        const valeur = this.valeursPoint.service(courant, anneeLiquidation);
        return [conversion * valeur[0], Math.min(fiabilite, valeur[1])];
      }

      const successeur = this.catalogue.contient(courant)
        ? this.catalogue.obtenir(courant).integre_dans
        : null;
      const premiere = successeur
        ? this.valeursPoint.premiereAnneeServie(successeur)
        : null;
      if (premiere === null) {
        const ancienne = this.valeursPoint.service(courant, derniere);
        return [
          conversion * ancienne[0]
            * this.macro.coefficientPrix(derniere, anneeLiquidation),
          Math.min(fiabilite, ancienne[1], Fiabilite.MOYENNE),
        ];
      }

      const avant = this.valeursPoint.service(courant, derniere);
      const apres = this.valeursPoint.service(successeur, premiere);
      conversion *= avant[0] / apres[0];
      fiabilite = Math.min(fiabilite, avant[1], apres[1]);
      courant = successeur;
    }
    return null;
  }

  // -- salaire de référence --------------------------------------------------

  /**
   * Salaire de référence, exprimé en euros de l'année de liquidation.
   *
   * Les salaires portés au compte sont revalorisés sur les prix, règle en
   * vigueur depuis la réforme de 1993. Avant 1993 ils l'étaient sur les
   * salaires ; l'approximation retenue applique la règle des prix sur toute la
   * période, ce qui minore le salaire de référence des carrières anciennes.
   *
   * Le salaire retenu est celui de l'assiette du régime, et pas la
   * rémunération entière : la pension civile porte sur le seul traitement
   * indiciaire, primes exclues.
   */
  salaireDeReference(carriere, periode, anneeLiquidation, plafonner) {
    const revenus = [];
    for (const ligne of carriere.lignes) {
      if (!ligne.cotise || ligne.annee >= anneeLiquidation) {
        continue;
      }
      let revenu = assietteDeReference(periode, ligne);
      if (plafonner) {
        revenu = Math.min(revenu, this.macro.plafond_securite_sociale.valeur(ligne.annee));
      }
      revenus.push(revenu * this.macro.coefficientPrix(ligne.annee, anneeLiquidation));
    }

    if (revenus.length === 0) {
      return 0.0;
    }

    const reference = periode.salaire_reference;
    let retenus;
    if (reference === "25_meilleures_annees") {
      retenus = [...revenus].sort((a, b) => b - a).slice(0, 25);
    } else if (reference === "10_meilleures_annees") {
      retenus = [...revenus].sort((a, b) => b - a).slice(0, 10);
    } else if (reference === "derniers_6_mois" || reference === "dernier_salaire") {
      return revenus[revenus.length - 1];
    } else {
      retenus = revenus;
    }
    return retenus.reduce((total, valeur) => total + valeur, 0.0) / retenus.length;
  }

  // -- calcul ----------------------------------------------------------------

  /**
   * Pension servie par le système en vigueur.
   *
   * ``ignorerPenaliteAge`` neutralise la décote et la surcote liées à l'âge. On
   * ne l'utilise que pour VALORISER DES DROITS ACQUIS à une date donnée — la
   * question n'est alors pas « que toucherait cet assuré s'il liquidait
   * aujourd'hui à 40 ans », qui n'a pas de sens, mais « quels droits sa carrière
   * lui a-t-elle déjà ouverts ». La proratisation par la durée continue de
   * s'appliquer.
   */
  /** @returns {[number, number|null]} durée requise opposable, et fiabilité. */
  dureeRequise(periode, carriere) {
    if (periode.duree_requise_par_generation) {
      const parGeneration = this.dureesRequises.trimestres(carriere.annee_naissance);
      if (parGeneration !== null) {
        return parGeneration;
      }
    }
    return [periode.duree_requise_trimestres || 160, null];
  }

  /** Âge légal opposable à cet assuré dans ce régime. */
  ageOuverture(periode, carriere) {
    if (periode.age_ouverture_par_generation) {
      const parGeneration = this.agesOuverture.age(carriere.annee_naissance);
      if (parGeneration !== null) {
        return parGeneration[0];
      }
    }
    return periode.age_ouverture;
  }

  calculer(carriere, ignorerPenaliteAge = false, avantagesNonContributifs = true) {
    const anneeLiquidation = carriere.anneeLiquidation;
    const ageLiquidation = carriere.age_liquidation || 0.0;

    let trimestres = carriere.trimestresActuels;
    if (avantagesNonContributifs) {
      trimestres += 8 * carriere.nombre_enfants; // MDA, régime général
    }

    const pensions = [];
    let fiabiliteGlobale = Fiabilite.CERTIFIEE;
    let trimestresRequis = 0;
    let tauxRetenu = 0.0;

    // Indice dans `pensions` et prorata de durée des régimes de base qui
    // portent le minimum contributif.
    const eligiblesMinimum = [];

    // Cotisations cumulées par régime, pour les régimes en points dont on n'a
    // pas le prix d'achat du point ; points acquis pour les autres.
    const cumulCotisations = new Map();
    const pointsAcquis = new Map();
    const fiabilitePoints = new Map();
    // Durée d'assurance validée dans chaque régime, PÉRIODES ASSIMILÉES
    // COMPRISES : le coefficient de proratisation porte sur la durée
    // d'assurance, pas sur les seules années cotisées.
    const trimestresParRegime = new Map();
    for (const ligne of carriere.lignes) {
      if (ligne.annee >= anneeLiquidation) {
        continue;
      }
      for (const code of this.affiliations.regimes(ligne.affiliation, ligne.annee)) {
        if (!this.catalogue.contient(code)) {
          continue;
        }
        trimestresParRegime.set(
          code, (trimestresParRegime.get(code) ?? 0) + ligne.trimestres_valides,
        );
      }
    }

    for (const ligne of carriere.lignes) {
      if (!ligne.cotise) {
        continue;
      }
      for (const code of this.affiliations.regimes(ligne.affiliation, ligne.annee)) {
        if (!this.catalogue.contient(code)) {
          continue;
        }
        const regime = this.catalogue.obtenir(code);
        for (const periode of regime.periodesActives(ligne.annee)) {
          const [borneBasse, borneHaute] = periode.bornesAssietteEnPass();
          const pass = this.macro.plafond_securite_sociale.valeur(ligne.annee);
          let base = ligne.revenu;
          if (periode.assiette === "primes_uniquement") {
            base = ligne.revenu * ligne.part_primes;
          } else if (periode.assiette === "hors_primes") {
            base = ligne.revenu * (1.0 - ligne.part_primes);
          }
          const plafond = borneHaute === null ? base : borneHaute * pass;
          const assiette = Math.max(0.0, Math.min(base, plafond) - borneBasse * pass);
          const cotisation = assiette * periode.taux_cotisation_retraite;
          const achat = (periode.type_calcul === "points" || periode.type_calcul === "mixte")
            ? this.valeursPoint.achat(code, ligne.annee)
            : null;
          if (achat !== null) {
            const [reference, tauxAppel, fiabiliteAchat] = achat;
            pointsAcquis.set(code,
              (pointsAcquis.get(code) ?? 0.0) + cotisation / (tauxAppel * reference));
            fiabilitePoints.set(code, Math.min(
              fiabilitePoints.get(code) ?? Fiabilite.CERTIFIEE, fiabiliteAchat,
            ));
          } else {
            cumulCotisations.set(code, (cumulCotisations.get(code) ?? 0.0)
              + cotisation * this.macro.coefficientPrix(ligne.annee, anneeLiquidation));
          }
        }
      }
    }

    const codes = [...new Set([...cumulCotisations.keys(), ...pointsAcquis.keys()])].sort();

    // Durée requise de référence : celle du régime de base. C'est elle qui
    // commande le taux plein, donc aussi l'abattement des complémentaires —
    // un assuré au taux plein liquide sa complémentaire sans abattement, quel
    // que soit son âge.
    let requisReference = 0;
    for (const code of codes) {
      const regime = this.catalogue.obtenir(code);
      const periode = regime.periode(Math.min(anneeLiquidation, derniereAnnee(regime)));
      if (periode === null || periode.type_calcul !== "annuites") {
        continue;
      }
      requisReference = Math.max(requisReference, this.dureeRequise(periode, carriere)[0]);
    }
    requisReference = requisReference || 160;

    for (const code of codes) {
      const cumul = cumulCotisations.get(code) ?? 0.0;
      const regime = this.catalogue.obtenir(code);
      const periode = regime.periode(Math.min(anneeLiquidation, derniereAnnee(regime)));
      if (periode === null) {
        continue;
      }
      fiabiliteGlobale = Math.min(fiabiliteGlobale, regime.fiabilite);

      if (periode.type_calcul === "points" || periode.type_calcul === "mixte") {
        let montant = 0.0;
        let fiabiliteRegime = regime.fiabilite;
        const details = [];

        const points = pointsAcquis.get(code) ?? 0.0;
        if (points) {
          const valeur = this.valeurDuPoint(code, anneeLiquidation);
          if (valeur !== null) {
            const [service, fiabiliteService] = valeur;
            montant += points * service;
            fiabiliteRegime = Math.min(
              fiabiliteRegime, fiabiliteService, fiabilitePoints.get(code),
            );
            details.push(
              `${formatFixe(points, 0, true)} points × valeur de service `
              + `${formatFixe(service, 4)} €`,
            );
          }
        }

        // Années sans prix d'achat connu : le rendement instantané prend le
        // relais, régime par régime et année par année.
        if (cumul) {
          const [rendement, fiabiliteRendement] = this.rendements.rendement(
            code, Math.min(anneeLiquidation, derniereAnnee(regime)),
          );
          montant += cumul * rendement;
          fiabiliteRegime = Math.min(fiabiliteRegime, fiabiliteRendement);
          details.push(
            `cotisations revalorisées ${formatFixe(cumul, 0, true)} € `
            + `× rendement ${formatPourcentage(rendement, 2)}`,
          );
        }

        fiabiliteGlobale = Math.min(fiabiliteGlobale, fiabiliteRegime);
        if (!ignorerPenaliteAge) {
          montant *= ajustementAgePoints(
            periode, ageLiquidation, trimestres, requisReference,
          );
        }
        pensions.push({
          regime: code,
          montant,
          type_calcul: periode.type_calcul,
          detail: details.join(" + ") || "aucun droit",
          fiabilite: fiabiliteRegime,
        });
        continue;
      }

      // Régimes en annuités.
      const plafonner = ["plafonnee", "tranche_1", "tranche_a"].includes(periode.assiette);
      const indicePension = pensions.length;
      const salaireReference = this.salaireDeReference(
        carriere, periode, anneeLiquidation, plafonner,
      );
      const [requis, fiabiliteDuree] = this.dureeRequise(periode, carriere);
      if (fiabiliteDuree !== null) {
        fiabiliteGlobale = Math.min(fiabiliteGlobale, fiabiliteDuree);
      }
      trimestresRequis = Math.max(trimestresRequis, requis);
      const trimestresRegime = Math.min(trimestresParRegime.get(code) ?? 0, requis);

      let taux = periode.taux_plein || 0.5;
      if (!ignorerPenaliteAge) {
        const manquants = Math.max(0, requis - trimestres);
        const manquantsAge = Math.max(0.0, (periode.age_taux_plein - ageLiquidation) * 4);
        // La décote retient le plus favorable des deux décomptes : trimestres
        // manquants pour la durée requise, ou trimestres manquants jusqu'à
        // l'âge d'annulation de la décote.
        const trimestresDecote = Math.min(manquants, manquantsAge);
        if (periode.decote_par_trimestre && trimestresDecote > 0) {
          // Les régimes sans décote (fonction publique avant 2004, régimes
          // spéciaux avant 2008) ne subissent que la proratisation.
          taux *= Math.max(0.0, 1.0 - periode.decote_par_trimestre * trimestresDecote);
        }
        // La surcote ne récompense que les trimestres COTISÉS APRÈS l'âge
        // légal ET au-delà de la durée requise.
        let supplementaires = Math.max(0, trimestres - requis);
        const ageOuverture = this.ageOuverture(periode, carriere);
        if (periode.surcote_par_trimestre && supplementaires > 0
            && ageLiquidation >= ageOuverture) {
          supplementaires = Math.min(
            supplementaires,
            trimestresCotisesApres(carriere, ageOuverture, anneeLiquidation),
          );
          if (supplementaires > 0) {
            taux *= 1.0 + periode.surcote_par_trimestre * supplementaires;
          }
        }
      }

      tauxRetenu = Math.max(tauxRetenu, taux);
      if (periode.avantages_non_contributifs.includes("minimum_contributif")) {
        // Le minimum ne relève que les régimes de base qui le portent, et au
        // prorata de la durée acquise DANS CE régime.
        eligiblesMinimum.push([indicePension, trimestresRegime / requis]);
      }
      pensions.push({
        regime: code,
        montant: salaireReference * taux * (trimestresRegime / requis),
        type_calcul: "annuites",
        detail: `SR ${formatFixe(salaireReference, 0, true)} € `
          + `× taux ${formatPourcentage(taux, 2)} × ${trimestresRegime}/${requis}`,
        fiabilite: regime.fiabilite,
      });
    }

    let total = pensions.reduce((somme, p) => somme + p.montant, 0.0);

    // Avantages non contributifs du droit positif.
    let totalContributif = total;
    const avantages = [];

    // Avantages non contributifs du droit positif, dans l'ordre où le droit les
    // applique : durée d'assurance, puis majoration, puis minimum.
    let minimumApplique = false;

    if (avantagesNonContributifs && carriere.nombre_enfants > 0) {
      // Effet de la MDA : la même carrière sans les huit trimestres par enfant.
      const sansMda = this.calculer(carriere, ignorerPenaliteAge, false);
      const effet = total - sansMda.total_contributif;
      // La MDA est déjà incorporée aux pensions de régime : la base
      // contributive de la cascade est celle d'AVANT.
      totalContributif = sansMda.total_contributif;
      if (Math.abs(effet) > 1e-9) {
        const nombre = 8 * carriere.nombre_enfants;
        avantages.push({
          code: "majoration_duree_assurance",
          libelle: "Majoration de durée d'assurance",
          montant: effet,
          detail: `${nombre} trimestres pour ${carriere.nombre_enfants} enfant`
            + `${carriere.nombre_enfants > 1 ? "s" : ""}`,
        });
      }
    }

    if (avantagesNonContributifs && carriere.nombre_enfants >= 3) {
      let majoration = 0.0;
      let tauxCite = 0.0;
      for (const pension of pensions) {
        const regime = this.catalogue.obtenir(pension.regime);
        const periode = regime.periode(Math.min(anneeLiquidation, derniereAnnee(regime)));
        if (periode === null
            || !periode.avantages_non_contributifs.includes("majoration_enfants")) {
          continue;
        }
        const taux = tauxMajorationEnfants(regime, carriere.nombre_enfants);
        majoration += pension.montant * taux;
        tauxCite = Math.max(tauxCite, taux);
      }
      if (majoration > 0) {
        total += majoration;
        avantages.push({
          code: "majoration_enfants",
          libelle: "Majoration pour trois enfants et plus",
          montant: majoration,
          detail: `jusqu'à ${formatPourcentage(tauxCite, 0)} selon le régime`,
        });
      }
    }
    if (avantagesNonContributifs && eligiblesMinimum.length > 0) {
      const [montantMinimum, plafond, fiabiliteMinimum] = this.minimumContributif
        .valeurs(anneeLiquidation);
      let releve = 0.0;
      for (const [indice, prorata] of eligiblesMinimum) {
        const plancher = montantMinimum * Math.min(1.0, prorata);
        if (pensions[indice].montant > 0 && pensions[indice].montant < plancher) {
          releve += plancher - pensions[indice].montant;
        }
      }
      if (releve > 0) {
        // Écrêtement : le complément est rogné de ce qui dépasse le plafond,
        // tous régimes confondus, et jamais au-delà.
        releve = Math.max(0.0, Math.min(releve, plafond - total));
      }
      if (releve > 0) {
        total += releve;
        minimumApplique = true;
        fiabiliteGlobale = Math.min(fiabiliteGlobale, fiabiliteMinimum);
        avantages.push({
          code: "minimum_contributif",
          libelle: "Minimum contributif",
          montant: releve,
          detail: "portée au plancher, au prorata de la durée acquise",
        });
      }
    }

    return {
      pension_annuelle: total,
      pensions_par_regime: pensions,
      trimestres_valides: trimestres,
      trimestres_requis: trimestresRequis,
      taux_liquidation: tauxRetenu,
      minimum_applique: minimumApplique,
      avantages_appliques: avantages,
      total_contributif: totalContributif,
      fiabilite: fiabiliteGlobale,
      pension_mensuelle: total / 12.0,
    };
  }
}

/** Dernière année pour laquelle le régime a des paramètres. */
function derniereAnnee(regime) {
  if (regime.periodes.length === 0) {
    return 2100;
  }
  const annees = regime.periodes.map((p) => (p.fin === null ? 9999 : p.fin));
  return Math.min(Math.max(...annees), 2100);
}

/** Abattement des régimes en points pour liquidation avant le taux plein. */
function ajustementAgePoints(periode, ageLiquidation, trimestres, requis) {
  if (periode.decote_par_trimestre === null) {
    return 1.0;
  }
  // « Avant le taux plein » est une condition de DURÉE autant que d'âge : une
  // complémentaire est servie sans abattement dès que l'assuré a le taux plein
  // au régime de base, même s'il liquide avant l'âge d'annulation de la décote.
  const manquants = Math.max(0, requis - trimestres);
  const manquantsAge = Math.max(0.0, (periode.age_taux_plein - ageLiquidation) * 4);
  return Math.max(
    0.0, 1.0 - periode.decote_par_trimestre * Math.min(manquants, manquantsAge),
  );
}

/**
 * Taux de majoration pour enfants, régime par régime. Le régime général et les
 * régimes spéciaux servent 10 % à partir de trois enfants ; la fonction
 * publique y ajoute 5 % par enfant au-delà du troisième.
 */
function tauxMajorationEnfants(regime, nombreEnfants) {
  if (nombreEnfants < 3) {
    return 0.0;
  }
  if (regime.famille === "fonction_publique") {
    return 0.1 + 0.05 * (nombreEnfants - 3);
  }
  return 0.1;
}

/** Part de la rémunération que ce régime prend en compte. */
function assietteDeReference(periode, ligne) {
  if (periode.assiette === "primes_uniquement") {
    return ligne.revenu * ligne.part_primes;
  }
  if (periode.assiette === "hors_primes") {
    return ligne.revenu * (1.0 - ligne.part_primes);
  }
  return ligne.revenu;
}

/**
 * Trimestres cotisés à partir de l'année où l'assuré atteint ``age``. Seuls
 * ceux-là ouvrent droit à la surcote : c'est une récompense du travail
 * prolongé, pas de l'entrée précoce dans la vie active.
 */
function trimestresCotisesApres(carriere, age, anneeLiquidation) {
  let total = 0;
  for (const ligne of carriere.lignes) {
    if (ligne.cotise && ligne.annee < anneeLiquidation
        && ligne.annee - carriere.annee_naissance >= age) {
      total += ligne.trimestres_valides;
    }
  }
  return total;
}
