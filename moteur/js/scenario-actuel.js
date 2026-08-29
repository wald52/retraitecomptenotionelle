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
  AgesAnnulationDecote, AgesOuverture, AnneesSalaireReference, CarriereLongue,
  CoefficientsMinoration, DecoteFonctionPublique, DureesRequises,
  MinimumContributif, MinimumGaranti, MinimumVieillesse, Rendements,
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
    this.decoteFonctionPublique = new DecoteFonctionPublique(paquet);
    this.minimumGaranti = new MinimumGaranti(paquet, macro);
    this.minimumVieillesse = new MinimumVieillesse(paquet, macro);
    this.carriereLongue = new CarriereLongue(paquet);
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
  salaireDeReference(code, carriere, periode, anneeLiquidation, plafonner,
    generation = null, avpf = true) {
    const avpfOuvert = avpf
      && periode.avantages_non_contributifs.includes("avpf");
    const revenus = [];
    for (const ligne of carriere.lignes) {
      if (ligne.annee >= anneeLiquidation) {
        continue;
      }
      if (!this.affiliations.regimes(ligne.affiliation, ligne.annee).includes(code)) {
        continue;
      }
      let revenu;
      if (!ligne.cotise) {
        // Assurance vieillesse des parents au foyer : la CNAF cotise sur une
        // assiette forfaitaire égale au SMIC, et ce salaire est PORTÉ AU
        // COMPTE. C'est ce qui la distingue d'une période assimilée, laquelle
        // valide des trimestres sans jamais ajouter de salaire.
        if (!(avpfOuvert && ligne.revenu_avpf > 0)) {
          continue;
        }
        revenu = ligne.revenu_avpf;
      } else {
        revenu = assietteDeReference(periode, ligne);
      }
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
   * Décote opposable : coefficient, âge d'annulation, fiabilité.
   *
   * La FONCTION PUBLIQUE n'a pas la décote du régime général. L'article L. 14
   * du code des pensions lui donne la sienne, montée en charge de 2006 à 2020,
   * et surtout un âge d'annulation qui n'est pas un âge en propre : c'est la
   * LIMITE D'ÂGE du grade, diminuée d'un nombre de trimestres décroissant. Un
   * sédentaire liquidant en 2012 voyait sa décote s'annuler à 63 ans, pas à
   * 67 — et chaque trimestre manquant lui coûtait 0,875 %, pas 1,25 %.
   *
   * @returns {[number|null, number, number|null]} coefficient, âge, fiabilité.
   */
  decote(periode, carriere, anneeLiquidation) {
    const ageAnnulation = this.ageTauxPlein(periode, carriere);
    if (periode.bareme_decote === "fonction_publique") {
      const parametres = this.decoteFonctionPublique.parametres(anneeLiquidation);
      if (parametres === null || parametres === undefined) {
        return [null, ageAnnulation, null];
      }
      const [trimestresAvant, coefficient, fiabilite] = parametres;
      return [coefficient, ageAnnulation - trimestresAvant / 4.0, fiabilite];
    }
    if (periode.decote_par_trimestre === null) {
      return [null, ageAnnulation, null];
    }
    if (periode.decote_par_generation) {
      const parGeneration = this.coefficientsMinoration.coefficient(
        carriere.annee_naissance,
      );
      if (parGeneration !== null) {
        return [parGeneration[0], ageAnnulation, parGeneration[1]];
      }
    }
    return [periode.decote_par_trimestre, ageAnnulation, null];
  }

  /**
   * Trimestres de décote opposables, plafond compris.
   *
   * Le décompte retient le plus favorable des deux : trimestres manquants pour
   * la durée requise, ou trimestres manquants jusqu'à l'âge d'annulation de la
   * décote. Et il est PLAFONNÉ — vingt trimestres partout où une décote
   * s'applique.
   *
   * Avant l'ordonnance du 26 mars 1982, le taux ne dépendait QUE de l'âge :
   * aucune durée, si longue fût-elle, n'ouvrait le taux plein avant l'heure.
   */
  trimestresDeDecote(periode, trimestres, requis, ageLiquidation, ageAnnulation) {
    const manquantsAge = Math.max(0.0, (ageAnnulation - ageLiquidation) * 4);
    let trimestresDecote = periode.decote_annulee_par_la_duree
      ? Math.min(Math.max(0, requis - trimestres), manquantsAge)
      : manquantsAge;
    if (trimestresDecote <= 0) {
      return 0.0;
    }
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
  abattementPoints(periode, carriere, trimestres, requis, ageLiquidation,
    anneeLiquidation) {
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

    const [decote, ageAnnulation] = this.decote(periode, carriere, anneeLiquidation);
    if (decote === null) {
      return 1.0;
    }
    const trimestresDecote = this.trimestresDeDecote(
      periode, trimestres, requis, ageLiquidation, ageAnnulation,
    );
    return Math.max(0.0, 1.0 - decote * trimestresDecote);
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

  calculer(carriere, ignorerPenaliteAge = false, avantagesNonContributifs = true,
    avpf = true) {
    const anneeLiquidation = carriere.anneeLiquidation;
    const ageLiquidation = carriere.age_liquidation || 0.0;

    let trimestres = carriere.trimestresActuels;
    const trimestresMda = avantagesNonContributifs ? 8 * carriere.nombre_enfants : 0;
    trimestres += trimestresMda;

    const pensions = [];
    let fiabiliteGlobale = Fiabilite.CERTIFIEE;
    let trimestresRequis = 0;
    let tauxRetenu = 0.0;

    // Régimes de base qui portent le minimum contributif : indice dans
    // `pensions`, prorata de durée d'assurance, prorata de durée COTISÉE,
    // condition de taux plein, et coefficient de surcote déjà incorporé.
    const eligiblesMinimum = [];
    // Régimes de la fonction publique qui portent le minimum garanti.
    const eligiblesGaranti = [];

    // Cotisations cumulées par régime, pour les régimes en points dont on n'a
    // pas le prix d'achat du point ; points acquis pour les autres.
    const cumulCotisations = new Map();
    const pointsAcquis = new Map();
    const fiabilitePoints = new Map();
    // Durée d'assurance validée dans chaque régime, PÉRIODES ASSIMILÉES
    // COMPRISES : le coefficient de proratisation porte sur la durée
    // d'assurance, pas sur les seules années cotisées.
    const trimestresParRegime = new Map();
    // Durée COTISÉE dans chaque régime : c'est elle, et non la durée
    // d'assurance, qui proratise la majoration du minimum contributif au titre
    // des périodes cotisées (D. 351-2-2).
    const trimestresCotisesParRegime = new Map();
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
        if (ligne.cotise) {
          trimestresCotisesParRegime.set(
            code,
            (trimestresCotisesParRegime.get(code) ?? 0) + ligne.trimestres_valides,
          );
        }
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
      if (ligne.annee >= anneeLiquidation) {
        // Une ligne postérieure à la liquidation décrit une activité exercée
        // APRÈS le départ : elle n'ouvre pas de droits dans la pension qu'on
        // liquide.
        continue;
      }
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
            let pointsAnnee = cotisation / (tauxAppel * reference);
            if (periode.points_minimum_annuels !== null
                && periode.points_minimum_annuels !== undefined) {
              // Garantie minimale de points de l'Agirc : tout cadre cotisant en
              // acquiert au moins 120 par an de 1989 à 2018, même quand sa
              // tranche B est nulle.
              pointsAnnee = Math.max(pointsAnnee, periode.points_minimum_annuels);
            }
            pointsAcquis.set(code, (pointsAcquis.get(code) ?? 0.0) + pointsAnnee);
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
    // Âge d'ouverture des droits le plus précoce parmi les régimes de base de
    // la carrière. Un polypensionné liquide en réalité chaque pension à l'âge
    // de son régime ; le modèle liquide tout à la fois, et retient donc l'âge
    // du régime le plus précoce.
    let ageOuvertureReference = null;
    for (const code of codes) {
      const regime = this.catalogue.obtenir(code);
      const periode = regime.periode(Math.min(anneeLiquidation, derniereAnnee(regime)));
      if (periode === null || periode.type_calcul !== "annuites") {
        continue;
      }
      requisReference = Math.max(requisReference, this.dureeRequise(periode, carriere)[0]);
      const ageRegime = this.ageOuverture(periode, carriere);
      ageOuvertureReference = ageOuvertureReference === null
        ? ageRegime
        : Math.min(ageOuvertureReference, ageRegime);
    }
    requisReference = requisReference || 160;

    // Trimestres réellement COTISÉS, tous régimes : ils commandent la carrière
    // longue et la majoration du minimum contributif.
    let trimestresCotises = 0;
    for (const ligne of carriere.lignes) {
      if (ligne.cotise && ligne.annee < anneeLiquidation) {
        trimestresCotises += ligne.trimestres_valides;
      }
    }

    // Le droit ouvre-t-il cette liquidation à cet âge ? La question n'était pas
    // posée : le modèle servait une pension décotée à qui ne pouvait pas encore
    // liquider, ce qui n'est ni le droit ni un contrefactuel utile.
    let motifOuverture = "age_legal";
    let liquidationOuverte = true;
    if (ageOuvertureReference !== null && ageLiquidation < ageOuvertureReference) {
      const anticipe = this.carriereLongue.ageDeDepart(
        carriere, anneeLiquidation, trimestresCotises, requisReference,
      );
      if (anticipe !== null && ageLiquidation >= anticipe[0]) {
        motifOuverture = "carriere_longue";
        ageOuvertureReference = anticipe[0];
        fiabiliteGlobale = Math.min(fiabiliteGlobale, anticipe[1]);
      } else {
        motifOuverture = "non_ouverte";
        liquidationOuverte = false;
      }
    }

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
            anneeLiquidation,
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
        code, carriere, periode, anneeLiquidation, plafonner,
        carriere.annee_naissance, avpf,
      );
      const [requis, fiabiliteDuree] = this.dureeRequise(periode, carriere);
      if (fiabiliteDuree !== null) {
        fiabiliteGlobale = Math.min(fiabiliteGlobale, fiabiliteDuree);
      }
      trimestresRequis = Math.max(trimestresRequis, requis);
      const trimestresRegime = Math.min(trimestresParRegime.get(code) ?? 0, requis);

      let taux = periode.taux_plein || 0.5;
      // Part du taux qui vient de la surcote : le minimum contributif se
      // compare à la pension AVANT surcote, il faut donc pouvoir la retirer.
      let coefficientSurcote = 1.0;
      // Trimestres de décote effectivement retenus : la condition d'ouverture
      // du minimum garanti en dépend.
      let trimestresDecote = 0.0;
      if (!ignorerPenaliteAge) {
        const [decote, ageAnnulation, fiabiliteDecote] = this.decote(
          periode, carriere, anneeLiquidation,
        );
        trimestresDecote = this.trimestresDeDecote(
          periode, trimestres, requis, ageLiquidation, ageAnnulation,
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
            coefficientSurcote = 1.0 + periode.surcote_par_trimestre * supplementaires;
            taux *= coefficientSurcote;
          }
        }
      }

      tauxRetenu = Math.max(tauxRetenu, taux);
      if (periode.avantages_non_contributifs.includes("minimum_contributif")) {
        // Le minimum ne relève que les régimes de base qui le portent, au
        // prorata de la durée acquise DANS CE régime — durée d'assurance pour
        // le montant de base, durée COTISÉE pour la majoration —, et seulement
        // si la pension est liquidée AU TAUX PLEIN (L. 351-10).
        const cotisesRegime = Math.min(
          trimestresCotisesParRegime.get(code) ?? 0, requis,
        );
        eligiblesMinimum.push({
          indice: indicePension,
          prorataAssurance: trimestresRegime / requis,
          prorataCotise: cotisesRegime / requis,
          tauxPlein: trimestres >= requis
            || ageLiquidation >= this.ageTauxPlein(periode, carriere),
          surcote: coefficientSurcote,
        });
      }
      if (periode.avantages_non_contributifs.includes("minimum_garanti")) {
        // Depuis la loi du 9 novembre 2010, le minimum garanti n'est dû qu'au
        // taux plein. Les assurés qui atteignaient l'âge d'ouverture de leurs
        // droits avant 2011 gardent le droit inconditionnel.
        const ageOuverturePeriode = this.ageOuverture(periode, carriere);
        eligiblesGaranti.push({
          indice: indicePension,
          trimestresServices: trimestresParRegime.get(code) ?? 0,
          ouvert: carriere.annee_naissance + ageOuverturePeriode < 2011
            || trimestresDecote <= 0
            || trimestres >= requis,
        });
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

    let totalContributif = total;
    const avantages = [];

    // Avantages non contributifs du droit positif, DANS L'ORDRE OÙ LE DROIT
    // LES APPLIQUE, et l'ordre commande le résultat : l'AVPF d'abord, qui
    // déplace le salaire annuel moyen ; la majoration de durée d'assurance
    // ensuite, qui change la décote et la proratisation ; puis le minimum
    // contributif, qui porte la pension de base à son plancher ; puis seulement
    // la majoration pour enfants, qui se calcule SUR CE plancher ; l'ASPA
    // enfin, qui est différentielle et complète tout le reste.
    let minimumApplique = false;

    if (avantagesNonContributifs && carriere.nombre_enfants > 0) {
      // Effet de la MDA : la même carrière sans les huit trimestres par enfant.
      const sansMda = this.calculer(carriere, ignorerPenaliteAge, false, avpf);
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

    if (avantagesNonContributifs && avpf
        && carriere.lignes.some((ligne) => ligne.revenu_avpf > 0)) {
      // Effet de l'AVPF, mesuré comme celui de la MDA : la même carrière sans
      // le salaire forfaitaire porté au compte. Il joue en amont de tout le
      // reste, et peut jouer dans les deux sens — il relève une carrière longue
      // à bas salaire, il abaisse la moyenne d'une carrière courte et bien
      // payée, où les années au SMIC s'ajoutent aux années retenues.
      const sansAvpf = this.calculer(carriere, ignorerPenaliteAge, false, false);
      const effetAvpf = totalContributif - sansAvpf.total_contributif;
      totalContributif = sansAvpf.total_contributif;
      if (Math.abs(effetAvpf) > 1e-9) {
        avantages.unshift({
          code: "avpf",
          libelle: "Assurance vieillesse des parents au foyer",
          montant: effetAvpf,
          detail: "salaire forfaitaire au SMIC porté au compte",
        });
      }
    }

    if (avantagesNonContributifs && eligiblesMinimum.length > 0) {
      // Le minimum contributif ne relève que les pensions liquidées AU TAUX
      // PLEIN (L. 351-10). Sa majoration au titre des périodes cotisées demande
      // en outre 120 trimestres cotisés tous régimes ; elle se proratise
      // ensuite sur la durée cotisée DANS le régime, quand le montant de base
      // se proratise sur sa durée d'assurance (D. 351-2-2).
      const [montantBase, montantMajore, plafond, fiabiliteMinimum] = this
        .minimumContributif.valeurs(anneeLiquidation);
      const majorationOuverte = trimestresCotises >= TRIMESTRES_COTISES_MINIMUM_MAJORE;
      const complements = new Map();
      for (const eligible of eligiblesMinimum) {
        if (!eligible.tauxPlein) {
          continue;
        }
        const pension = pensions[eligible.indice];
        // Le minimum se compare à la pension AVANT surcote : le droit porte la
        // pension au plancher, puis applique la surcote au montant relevé.
        const nue = pension.montant / eligible.surcote;
        let plancher = montantBase * Math.min(1.0, eligible.prorataAssurance);
        if (majorationOuverte) {
          plancher += (montantMajore - montantBase)
            * Math.min(1.0, eligible.prorataCotise);
        }
        if (nue > 0 && nue < plancher) {
          complements.set(eligible.indice, (plancher - nue) * eligible.surcote);
        }
      }
      let releve = [...complements.values()].reduce((a, b) => a + b, 0.0);
      if (releve > 0) {
        // Écrêtement de l'article L. 173-2 : le complément est rogné de ce qui
        // dépasse le plafond, tous régimes confondus, et jamais au-delà. La
        // comparaison porte sur les pensions PERSONNELLES, majorations pour
        // enfants exclues — raison de plus pour les calculer après.
        const admissible = Math.max(0.0, Math.min(releve, plafond - total));
        if (admissible < releve) {
          const facteur = admissible / releve;
          for (const [indice, complement] of complements) {
            complements.set(indice, complement * facteur);
          }
        }
        releve = admissible;
      }
      if (releve > 0) {
        for (const [indice, complement] of complements) {
          pensions[indice] = {
            ...pensions[indice],
            montant: pensions[indice].montant + complement,
            detail: `${pensions[indice].detail}, porté au minimum contributif`,
          };
        }
        total += releve;
        minimumApplique = true;
        fiabiliteGlobale = Math.min(fiabiliteGlobale, fiabiliteMinimum);
        avantages.push({
          code: "minimum_contributif",
          libelle: "Minimum contributif",
          montant: releve,
          detail: "porté au plancher, au prorata de la durée acquise"
            + (majorationOuverte ? ", majoration des périodes cotisées comprise" : ""),
        });
      }
    }

    if (avantagesNonContributifs && eligiblesGaranti.length > 0) {
      // Le minimum garanti n'est pas un minimum proratisé mais un BARÈME sur la
      // durée de services : quinze ans en ouvrent 57,5 % de la référence,
      // trente ans 95 %, quarante ans la totalité. Il ne s'ajoute pas à la
      // pension, il s'y substitue quand il lui est supérieur.
      let releveGaranti = 0.0;
      for (const eligible of eligiblesGaranti) {
        if (!eligible.ouvert) {
          continue;
        }
        const plancher = this.minimumGaranti.montant(
          anneeLiquidation, eligible.trimestresServices,
        );
        if (plancher === null) {
          continue;
        }
        const pension = pensions[eligible.indice];
        if (pension.montant > 0 && pension.montant < plancher[0]) {
          releveGaranti += plancher[0] - pension.montant;
          fiabiliteGlobale = Math.min(fiabiliteGlobale, plancher[1]);
          pensions[eligible.indice] = {
            ...pension,
            montant: plancher[0],
            detail: `${pension.detail}, porté au minimum garanti`,
          };
        }
      }
      if (releveGaranti > 0) {
        total += releveGaranti;
        avantages.push({
          code: "minimum_garanti",
          libelle: "Minimum garanti de la fonction publique",
          montant: releveGaranti,
          detail: "barème de l'article L. 17, sur la durée de services",
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

    if (avantagesNonContributifs
        && this.parametres.minimum_vieillesse_dans_le_scenario_actuel
        && ageLiquidation >= MinimumVieillesse.AGE_OUVERTURE) {
      // L'ASPA vient en DERNIER, et pour cause : elle est différentielle. Elle
      // complète tout le reste, majorations comprises, jusqu'au montant du
      // barème — c'est la seule prestation du système actuel qui ne suppose
      // aucune cotisation.
      const bareme = this.minimumVieillesse.plafond(anneeLiquidation);
      if (bareme !== null && total < bareme[0]) {
        const complement = bareme[0] - total;
        total = bareme[0];
        fiabiliteGlobale = Math.min(fiabiliteGlobale, bareme[1]);
        avantages.push({
          code: "minimum_vieillesse",
          libelle: "Minimum vieillesse (ASPA)",
          montant: complement,
          detail: "allocation différentielle, barème d'une personne seule",
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
      age_ouverture_opposable: ageOuvertureReference,
      liquidation_ouverte: liquidationOuverte,
      motif_ouverture: motifOuverture,
      avantages_appliques: avantages,
      total_contributif: totalContributif,
      fiabilite: fiabiliteGlobale,
      pension_mensuelle: total / 12.0,
    };
  }
}

/**
 * Durée cotisée, tous régimes, qui ouvre la majoration du minimum contributif
 * au titre des périodes cotisées (article L. 351-10). En deçà, seul le montant
 * de base est dû.
 */
const TRIMESTRES_COTISES_MINIMUM_MAJORE = 120;

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
