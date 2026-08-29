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
 * régimes en points calculés en points quand le barème est connu — prix d'achat
 * publié, ou nombre de points par tranche d'assiette —, au rendement instantané
 * sinon ; montée en charge des réformes lue à la génération pour cinq
 * paramètres, à l'année de liquidation pour les autres. Un écart de quelques
 * pour cent avec la pension réelle est attendu — ce que le modèle mesure de
 * façon robuste, ce sont les écarts ENTRE SCÉNARIOS.
 */

import { formatFixe, formatPourcentage } from "./format.js";
import {
  AgesAnnulationDecote, AgesOuverture, AnneesSalaireReference,
  CoefficientsMinoration, DureesRequises, MinimumContributif, Rendements,
  ValeursPoint,
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
    this.agesAnnulationDecote = new AgesAnnulationDecote(paquet);
    this.coefficientsMinoration = new CoefficientsMinoration(paquet);
    this.anneesSalaireReference = new AnneesSalaireReference(paquet);
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
        if (valeur === null) {
          // Liquidation antérieure au premier barème publié. Symétrique du cas
          // ci-dessous : la première valeur connue est ramenée en euros de la
          // liquidation par l'indice des prix, et la fiabilité tombe pour le dire.
          const premiereConnue = this.valeursPoint.premiereAnneeServie(courant);
          const ancienne = this.valeursPoint.service(courant, premiereConnue);
          return [
            conversion * ancienne[0]
              * this.macro.coefficientPrix(premiereConnue, anneeLiquidation),
            Math.min(fiabilite, ancienne[1], Fiabilite.MOYENNE),
          ];
        }
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
   * Deux règles de droit commandent ce calcul. La REVALORISATION des salaires
   * portés au compte, d'abord : les arrêtés annuels ont suivi les salaires
   * jusqu'en 1986 et suivent les prix depuis 1987. Le NOMBRE D'ANNÉES retenues
   * ensuite, que la loi du 22 juillet 1993 fait passer de dix à vingt-cinq à
   * raison d'une par génération — lu à l'année de naissance, donc, et non à
   * celle de la liquidation.
   *
   * Le salaire retenu est celui de l'assiette du régime, et pas la
   * rémunération entière : la pension civile porte sur le seul traitement
   * indiciaire, primes exclues.
   */
  salaireDeReference(carriere, periode, anneeLiquidation, plafonner, generation = null) {
    const revenus = [];
    for (const ligne of carriere.lignes) {
      if (!ligne.cotise || ligne.annee >= anneeLiquidation) {
        continue;
      }
      let revenu = assietteDeReference(periode, ligne);
      if (plafonner) {
        revenu = Math.min(revenu, this.macro.plafond_securite_sociale.valeur(ligne.annee));
      }
      revenus.push(revenu * this.macro.coefficientRevalorisationSalaires(
        ligne.annee, anneeLiquidation,
      ));
    }

    if (revenus.length === 0) {
      return 0.0;
    }

    const reference = periode.salaire_reference;
    let retenus;
    if (reference === "25_meilleures_annees" || reference === "10_meilleures_annees") {
      let annees = reference === "25_meilleures_annees" ? 25 : 10;
      if (periode.salaire_reference_par_generation && generation !== null) {
        const parGeneration = this.anneesSalaireReference.annees(generation);
        if (parGeneration !== null) {
          annees = parGeneration[0];
        }
      }
      retenus = [...revenus].sort((a, b) => b - a).slice(0, annees);
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

  /** Âge d'annulation de la décote opposable à cet assuré. */
  ageTauxPlein(periode, carriere) {
    if (periode.age_taux_plein_par_generation) {
      const parGeneration = this.agesAnnulationDecote.age(carriere.annee_naissance);
      if (parGeneration !== null) {
        return parGeneration[0];
      }
    }
    return periode.age_taux_plein;
  }

  /**
   * Coefficient de minoration opposable à cet assuré dans ce régime.
   *
   * @returns {[number|null, number|null]} coefficient et fiabilité.
   */
  decote(periode, carriere) {
    if (periode.decote_par_trimestre === null) {
      return [null, null];
    }
    if (periode.decote_par_generation) {
      const parGeneration = this.coefficientsMinoration.coefficient(
        carriere.annee_naissance,
      );
      if (parGeneration !== null) {
        return parGeneration;
      }
    }
    return [periode.decote_par_trimestre, null];
  }

  /**
   * Trimestres de décote opposables, plafond compris.
   *
   * Le décompte retient le plus favorable des deux : trimestres manquants pour
   * la durée requise, ou trimestres manquants jusqu'à l'âge d'annulation de la
   * décote. Et il est PLAFONNÉ — vingt trimestres partout où une décote
   * s'applique. Sans ce plafond, un départ dix ans avant l'heure retirait la
   * moitié de la pension là où le droit n'en retire que le quart.
   */
  trimestresDeDecote(periode, carriere, trimestres, requis, ageLiquidation) {
    const manquants = Math.max(0, requis - trimestres);
    const manquantsAge = Math.max(
      0.0, (this.ageTauxPlein(periode, carriere) - ageLiquidation) * 4,
    );
    let trimestresDecote = Math.min(manquants, manquantsAge);
    if (periode.decote_trimestres_maximum !== null) {
      trimestresDecote = Math.min(trimestresDecote, periode.decote_trimestres_maximum);
    }
    return trimestresDecote;
  }

  /**
   * Abattement d'un régime en points liquidé avant le taux plein.
   *
   * « Avant le taux plein » est une condition de DURÉE autant que d'âge : une
   * complémentaire est servie sans abattement dès que l'assuré a le taux plein
   * au régime de base. L'Agirc-Arrco, elle, ne reprend pas la décote du régime
   * de base : elle publie ses propres COEFFICIENTS D'ANTICIPATION, en deux
   * tables — trimestres manquants, et âge — et retient la plus avantageuse.
   */
  abattementPoints(periode, carriere, trimestres, requis, ageLiquidation) {
    if (periode.abattement_points === "agirc_arrco") {
      if (trimestres >= requis) {
        return 1.0;
      }
      const parDuree = coefficientAnticipation(requis - trimestres, 20);
      const ecartAge = Math.max(
        0.0, (this.ageTauxPlein(periode, carriere) - ageLiquidation) * 4,
      );
      let parAge = coefficientAnticipation(ecartAge, 40);
      if (parAge === null) {
        parAge = COEFFICIENT_ANTICIPATION_PLANCHER;
      }
      const candidats = [parDuree, parAge].filter((c) => c !== null);
      return candidats.length ? Math.max(...candidats) : 1.0;
    }

    if (periode.decote_par_trimestre === null) {
      return 1.0;
    }
    const [decote] = this.decote(periode, carriere);
    const trimestresDecote = this.trimestresDeDecote(
      periode, carriere, trimestres, requis, ageLiquidation,
    );
    return Math.max(0.0, 1.0 - (decote || 0.0) * trimestresDecote);
  }

  /**
   * Plafond en euros de la majoration pour enfants, ou ``null``.
   *
   * Les régimes de base servent 10 % sans plafond ; l'Agirc-Arrco borne la
   * majoration en euros — 2 367 € par an depuis le 1er novembre 2025 — et le
   * plafond suit la valeur de service du point. Il ne s'oppose qu'aux assurés
   * nés à compter du 2 août 1951 ; le modèle ne connaît que l'année de
   * naissance et retient les générations à partir de 1952.
   */
  plafondMajoration(code, periode, carriere, anneeLiquidation) {
    if (periode.plafond_majoration_enfants === null
        || periode.plafond_majoration_enfants === undefined) {
      return null;
    }
    if (carriere.annee_naissance < 1952) {
      return null;
    }
    const plafond = periode.plafond_majoration_enfants;
    const anneeReference = periode.plafond_majoration_annee;
    if (anneeReference === null || anneeReference === anneeLiquidation) {
      return plafond;
    }
    const servie = this.valeurDuPoint(code, anneeLiquidation);
    const publiee = this.valeurDuPoint(code, anneeReference);
    if (servie === null || publiee === null || publiee[0] <= 0) {
      return plafond * this.macro.coefficientPrix(anneeReference, anneeLiquidation);
    }
    return plafond * servie[0] / publiee[0];
  }

  /**
   * Régime auquel sont attribués les trimestres de la MDA : celui, parmi les
   * régimes en annuités dont la fiche porte l'avantage ``mda``, où l'assuré a
   * validé le plus de trimestres. Départage par le code, pour que le résultat
   * ne dépende pas de l'ordre d'une table de hachage.
   */
  regimePorteurMda(trimestresParRegime, anneeLiquidation) {
    const candidats = [];
    for (const [code, valides] of trimestresParRegime) {
      if (!this.catalogue.contient(code)) {
        continue;
      }
      const regime = this.catalogue.obtenir(code);
      const periode = regime.periode(Math.min(anneeLiquidation, derniereAnnee(regime)));
      if (periode === null || periode.type_calcul !== "annuites") {
        continue;
      }
      if (!periode.avantages_non_contributifs.includes("mda")) {
        continue;
      }
      candidats.push([valides, code]);
    }
    if (candidats.length === 0) {
      return null;
    }
    candidats.sort((a, b) => (a[0] - b[0]) || (a[1] < b[1] ? -1 : 1));
    return candidats[candidats.length - 1][1];
  }

  calculer(carriere, ignorerPenaliteAge = false, avantagesNonContributifs = true) {
    const anneeLiquidation = carriere.anneeLiquidation;
    const ageLiquidation = carriere.age_liquidation || 0.0;

    let trimestres = carriere.trimestresActuels;
    const trimestresMda = avantagesNonContributifs ? 8 * carriere.nombre_enfants : 0;
    trimestres += trimestresMda;

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

    // Les trimestres de la MDA ne flottent pas au-dessus des régimes : le droit
    // les attribue DANS un régime, et ils comptent donc aussi dans sa
    // proratisation, pas seulement dans la décote tous régimes confondus.
    // Faute de connaître l'année de naissance des enfants, ils vont au régime
    // de base où l'assuré a validé le plus de trimestres parmi ceux qui portent
    // la MDA — exact pour une carrière mono-affiliée, approché sinon.
    if (trimestresMda) {
      const regimeMda = this.regimePorteurMda(trimestresParRegime, anneeLiquidation);
      if (regimeMda !== null) {
        trimestresParRegime.set(
          regimeMda, trimestresParRegime.get(regimeMda) + trimestresMda,
        );
      }
    }

    for (const ligne of carriere.lignes) {
      if (!ligne.cotise && ligne.familles_cotisantes.length === 0) {
        continue;
      }
      // Pendant une période indemnisée, seuls les régimes complémentaires
      // encaissent, et sur le salaire d'avant l'interruption.
      const baseLigne = ligne.cotise ? ligne.revenu : ligne.revenu_reference;
      const famillesAdmises = ligne.cotise ? null : new Set(ligne.familles_cotisantes);
      for (const code of this.affiliations.regimes(ligne.affiliation, ligne.annee)) {
        if (!this.catalogue.contient(code)) {
          continue;
        }
        const regime = this.catalogue.obtenir(code);
        if (famillesAdmises !== null && !famillesAdmises.has(regime.famille)) {
          continue;
        }
        for (const periode of regime.periodesActives(ligne.annee)) {
          const [borneBasse, borneHaute] = periode.bornesAssietteEnPass();
          const pass = this.macro.plafond_securite_sociale.valeur(ligne.annee);
          let base = baseLigne;
          if (periode.assiette === "primes_uniquement") {
            base = baseLigne * ligne.part_primes;
          } else if (periode.assiette === "hors_primes") {
            base = baseLigne * (1.0 - ligne.part_primes);
          }
          const plafond = borneHaute === null ? base : borneHaute * pass;
          let assiette = Math.max(0.0, Math.min(base, plafond) - borneBasse * pass);
          const repere = periode.repereAssiette(
            pass, this.macro.smic_horaire.valeur(ligne.annee),
          );
          if (periode.assiette_plancher && assiette < repere) {
            // Assiette minimale : la complémentaire agricole cotise sur
            // 1 820 SMIC même quand le revenu est en dessous.
            assiette = repere;
          }
          const cotisation = assiette * periode.taux_cotisation_retraite;
          if (periode.points_maximum !== null && periode.points_maximum !== undefined
              && repere > 0) {
            // Barème écrit en POINTS et non en prix d'achat : le régime annonce
            // combien de points ouvre une assiette donnée. Le nombre de points
            // ne dépend alors pas du taux de cotisation, et c'est heureux : ce
            // sont les barèmes qui sont publiés, pas les prix d'achat.
            pointsAcquis.set(code,
              (pointsAcquis.get(code) ?? 0.0) + periode.points_maximum * assiette / repere);
            fiabilitePoints.set(code, Math.min(
              fiabilitePoints.get(code) ?? Fiabilite.CERTIFIEE, regime.fiabilite,
            ));
            continue;
          }
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
          montant *= this.abattementPoints(
            periode, carriere, trimestres, requisReference, ageLiquidation,
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
        carriere, periode, anneeLiquidation, plafonner, carriere.annee_naissance,
      );
      const [requis, fiabiliteDuree] = this.dureeRequise(periode, carriere);
      if (fiabiliteDuree !== null) {
        fiabiliteGlobale = Math.min(fiabiliteGlobale, fiabiliteDuree);
      }
      trimestresRequis = Math.max(trimestresRequis, requis);
      const trimestresRegime = Math.min(trimestresParRegime.get(code) ?? 0, requis);

      let taux = periode.taux_plein || 0.5;
      if (!ignorerPenaliteAge) {
        const [decote, fiabiliteDecote] = this.decote(periode, carriere);
        const trimestresDecote = this.trimestresDeDecote(
          periode, carriere, trimestres, requis, ageLiquidation,
        );
        if (decote && trimestresDecote > 0) {
          // Les régimes sans décote (fonction publique avant 2004, régimes
          // spéciaux avant 2008) ne subissent que la proratisation.
          if (fiabiliteDecote !== null) {
            fiabiliteGlobale = Math.min(fiabiliteGlobale, fiabiliteDecote);
          }
          taux *= Math.max(0.0, 1.0 - decote * trimestresDecote);
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
      // Le plafond de l'Agirc-Arrco s'oppose à la majoration de LA
      // complémentaire, pas à celle de chacune de ses fiches : les points d'un
      // salarié du privé sont répartis entre l'Agirc, l'Arrco et le régime
      // unifié, et plafonner chacun séparément triplerait le plafond.
      let majorationPlafonnee = 0.0;
      let plafondCommun = null;
      for (const pension of pensions) {
        const regime = this.catalogue.obtenir(pension.regime);
        const periode = regime.periode(Math.min(anneeLiquidation, derniereAnnee(regime)));
        if (periode === null
            || !periode.avantages_non_contributifs.includes("majoration_enfants")) {
          continue;
        }
        const taux = tauxMajorationEnfants(regime, carriere.nombre_enfants);
        const part = pension.montant * taux;
        const plafond = this.plafondMajoration(
          pension.regime, periode, carriere, anneeLiquidation,
        );
        if (plafond === null) {
          majoration += part;
        } else {
          majorationPlafonnee += part;
          plafondCommun = plafondCommun === null ? plafond : Math.max(plafondCommun, plafond);
        }
        tauxCite = Math.max(tauxCite, taux);
      }
      const plafonnee = plafondCommun !== null;
      if (plafondCommun !== null) {
        majoration += Math.min(majorationPlafonnee, plafondCommun);
      }
      if (majoration > 0) {
        total += majoration;
        let detail = `jusqu'à ${formatPourcentage(tauxCite, 0)} selon le régime`;
        if (plafonnee) {
          detail += ", plafonnée en euros à la complémentaire";
        }
        avantages.push({
          code: "majoration_enfants",
          libelle: "Majoration pour trois enfants et plus",
          montant: majoration,
          detail,
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

/**
 * Coefficients d'anticipation de l'Agirc-Arrco, sous leur forme de barème :
 * un point de pourcentage par trimestre jusqu'à douze, un point et quart
 * jusqu'à vingt, un point trois quarts au-delà — ce dernier palier n'existant
 * que dans la table des âges, qui descend jusqu'à 0,43 pour dix ans.
 */
const PALIERS_ANTICIPATION = [[12, 0.01], [20, 0.0125], [40, 0.0175]];

/** Dernière ligne de la table des âges : dix ans d'anticipation. */
const COEFFICIENT_ANTICIPATION_PLANCHER = 0.43;

/**
 * Coefficient d'anticipation pour un nombre de trimestres manquants.
 *
 * ``maximum`` est la dernière ligne du barème : vingt trimestres pour la table
 * des trimestres manquants, quarante pour celle des âges. Au-delà, la table ne
 * dit rien et ``null`` est renvoyé. Les trimestres sont comptés en entiers
 * ARRONDIS AU SUPÉRIEUR : le barème est un escalier.
 */
function coefficientAnticipation(trimestresManquants, maximum) {
  const manquants = Math.max(0, Math.ceil(Math.round(trimestresManquants * 1000) / 1000));
  if (manquants <= 0) {
    return 1.0;
  }
  if (manquants > maximum) {
    return null;
  }
  let coefficient = 1.0;
  let precedent = 0;
  for (const [borne, pas] of PALIERS_ANTICIPATION) {
    const tranche = Math.min(manquants, borne) - precedent;
    if (tranche > 0) {
      coefficient -= tranche * pas;
    }
    precedent = borne;
    if (manquants <= borne) {
      break;
    }
  }
  return Math.max(0.0, coefficient);
}

/**
 * Taux de majoration pour enfants, régime par régime. Le régime général et les
 * régimes spéciaux servent 10 % à partir de trois enfants ; la fonction
 * publique y ajoute 5 % par enfant au-delà du troisième. Les complémentaires
 * servent 10 % aussi, mais plafonnés en euros : le taux est le même, c'est
 * `plafondMajoration` qui borne.
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
