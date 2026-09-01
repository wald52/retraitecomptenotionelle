/**
 * Durée d'assurance requise pour le taux plein, PAR GÉNÉRATION.
 *
 * Depuis la loi du 22 juillet 1993, l'exigence est indexée sur l'année de
 * NAISSANCE et non sur l'année de liquidation : deux assurés qui liquident le
 * même jour n'ont pas la même durée requise s'ils ne sont pas de la même
 * génération.
 */
export class TableParGeneration {
  constructor(table) {
    this._table = table ?? {};
    this._generations = Object.keys(this._table).map(Number).sort((a, b) => a - b);
  }

  /**
   * Lecture en escalier : la valeur d'une génération non renseignée est celle
   * de la dernière renseignée avant elle, et la dernière du fichier vaut pour
   * toutes les suivantes. En deçà de la première, `null` : le paramètre ne
   * dépendait pas encore de la génération.
   *
   * @returns {[number, number] | null} valeur et fiabilité.
   */
  valeur(generation) {
    if (this._generations.length === 0 || generation < this._generations[0]) {
      return null;
    }
    let applicable = this._generations[0];
    for (const candidate of this._generations) {
      if (candidate > generation) {
        break;
      }
      applicable = candidate;
    }
    return this._table[String(applicable)];
  }
}

/** Durée d'assurance requise pour le taux plein, par génération. */
export class DureesRequises extends TableParGeneration {
  constructor(paquet) {
    super(paquet.durees_requises);
  }

  /** @returns {[number, number] | null} trimestres et fiabilité. */
  trimestres(generation) {
    return this.valeur(generation);
  }
}

/**
 * Durée d'assurance MAXIMALE prise en compte par la proratisation.
 *
 * Ce n'est pas la durée requise pour le taux plein, et le moteur les
 * confondait. La loi du 22 juillet 1993 a fait monter la première de 150 à
 * 160 trimestres pour les générations 1934 à 1943, et n'a touché à la seconde
 * que pour les générations 1944 à 1948 (article R. 351-6). Un assuré né en
 * 1945 ayant validé 156 trimestres se voit opposer 160 trimestres pour le taux
 * — il est décoté — mais 154 pour la proratisation : son coefficient vaut 1.
 *
 * La lecture s'ARRÊTE à la dernière génération du fichier, au lieu de prolonger
 * sa dernière valeur : à compter de 1949 la durée de proratisation rejoint la
 * durée requise, et prolonger 160 trimestres à des générations qui en doivent
 * 172 rendrait l'erreur dans l'autre sens.
 */
export class DureesProratisation extends TableParGeneration {
  constructor(paquet) {
    super(paquet.durees_proratisation);
  }

  /** @returns {[number, number] | null} trimestres et fiabilité. */
  trimestres(generation) {
    if (this._generations.length === 0
        || generation > this._generations[this._generations.length - 1]) {
      return null;
    }
    return this.valeur(generation);
  }
}

/** Âge légal d'ouverture des droits, par génération. */
export class AgesOuverture extends TableParGeneration {
  constructor(paquet) {
    super(paquet.ages_ouverture);
  }

  /** @returns {[number, number] | null} âge et fiabilité. */
  age(generation) {
    return this.valeur(generation);
  }
}

/** Âge d'annulation de la décote, par génération : 65 ans, puis 67. */
export class AgesAnnulationDecote extends TableParGeneration {
  constructor(paquet) {
    super(paquet.ages_annulation_decote);
  }

  /** @returns {[number, number] | null} âge et fiabilité. */
  age(generation) {
    return this.valeur(generation);
  }
}

/** Coefficient de minoration du taux plein par trimestre manquant. */
export class CoefficientsMinoration extends TableParGeneration {
  constructor(paquet) {
    super(paquet.coefficients_minoration);
  }

  /** @returns {[number, number] | null} coefficient et fiabilité. */
  coefficient(generation) {
    return this.valeur(generation);
  }
}

/** Nombre d'années retenues au salaire annuel moyen, par génération. */
export class AnneesSalaireReference extends TableParGeneration {
  constructor(paquet) {
    super(paquet.annees_salaire_reference);
  }

  /** @returns {[number, number] | null} nombre d'années et fiabilité. */
  annees(generation) {
    return this.valeur(generation);
  }
}

/**
 * Minimum contributif, minimum majoré et plafond d'écrêtement.
 *
 * Trois grandeurs : le minimum auquel est portée la pension de base, le
 * minimum MAJORÉ servi à sa place quand la durée cotisée atteint la durée
 * requise, et le plafond de l'article L. 173-2 au-delà duquel le complément
 * est rogné.
 *
 * Les trois sont des ANCRES DATÉES, lues dans le code de la sécurité sociale
 * et non dans une série annuelle : le code n'est pas modifié chaque année, les
 * montants sont revalorisés par l'effet de la loi. C'est donc au modèle de le
 * faire, et sur le bon index — le SMIC à partir de la date d'effet, les prix
 * avant elle.
 */
/**
 * Année à partir de laquelle chaque montant suit le SMIC et non plus les prix :
 * le plafond d'écrêtement depuis le décret du 14 février 2014, les deux minima
 * depuis la réforme du 14 avril 2023. Avant, ils suivaient les prix.
 */
export const INDEXATION_SUR_LE_SMIC = Object.freeze({
  montant_base: 2023,
  montant_majore: 2023,
  plafond_ecretement: 2014,
});

export class MinimumContributif {
  constructor(paquet, macro) {
    this.macro = macro;
    this._table = paquet.minimum_contributif ?? {};
  }

  /**
   * Ancre de la mesure, portée à l'année demandée.
   *
   * Un montant CONNU passe avant tout calcul : quand l'année figure au
   * fichier, on la sert telle quelle. Sinon on projette depuis la valeur en
   * vigueur à cette date — la dernière fixée avant elle, jamais une
   * postérieure, sans quoi les marches créées par une réforme glisseraient
   * dans le passé.
   *
   * L'index dépend de l'ANNÉE TRAVERSÉE et non de l'ancre : les prix jusqu'à
   * la bascule que la loi a fixée pour cette grandeur, le SMIC ensuite.
   *
   * @returns {[number, number]} valeur, et fiabilité.
   */
  _revalorise(mesure, annee) {
    const ancres = Object.keys(this._table)
      .filter((cle) => cle.startsWith(`${mesure}|`))
      .map((cle) => Number(cle.split("|")[1]))
      .sort((a, b) => a - b);
    if (ancres.length === 0) {
      return [0.0, 0];
    }
    if (ancres.includes(annee)) {
      return this._table[`${mesure}|${annee}`];
    }
    const anterieures = ancres.filter((a) => a < annee);
    const reference = anterieures.length
      ? anterieures[anterieures.length - 1]
      : ancres[0];
    const [valeur, fiabilite] = this._table[`${mesure}|${reference}`];
    const bascule = INDEXATION_SUR_LE_SMIC[mesure];
    const pivot = Math.min(Math.max(reference, bascule), annee);
    const coefficient = this.macro.coefficientPrix(reference, pivot)
      * this.macro.coefficientSmic(pivot, annee);
    return [valeur * coefficient, fiabilite];
  }

  /**
   * Montant de base, montant majoré et plafond d'écrêtement de l'année.
   *
   * Les deux montants sont rendus ensemble parce que le droit les ADDITIONNE
   * plutôt qu'il ne choisit entre eux : la pension est portée au montant de
   * base au prorata de la durée d'assurance acquise dans le régime, puis
   * l'écart entre le majoré et le base s'y ajoute au prorata de la seule durée
   * COTISÉE (D. 351-2-2).
   *
   * @returns {[number, number, number, number]} base, majoré, plafond, fiabilité.
   */
  valeurs(annee) {
    if (Object.keys(this._table).length === 0) {
      return [0.0, 0.0, 0.0, 0];
    }
    const [base, fiabiliteBase] = this._revalorise("montant_base", annee);
    const [majore, fiabiliteMajore] = this._revalorise("montant_majore", annee);
    const [plafond, fiabilitePlafond] = this._revalorise("plafond_ecretement", annee);
    return [base, majore, plafond,
      Math.min(fiabiliteBase, fiabiliteMajore, fiabilitePlafond)];
  }
}

/**
 * Décote de la fonction publique — article L. 14 du code des pensions.
 *
 * Deux paramètres, lus à l'ANNÉE DE LIQUIDATION parce que la montée en charge
 * voulue par la loi du 21 août 2003 est calendaire et non générationnelle : le
 * coefficient de minoration par trimestre, d'un huitième de point par an de
 * 0,125 % en 2006 à 1,25 % en 2015, et le nombre de trimestres retranchés à la
 * LIMITE D'ÂGE pour obtenir l'âge d'annulation, de seize en 2006 à zéro en
 * 2020. Rien avant 2006 : la décote n'existait pas dans la fonction publique.
 */
export class DecoteFonctionPublique {
  constructor(paquet) {
    this._table = paquet.decote_fonction_publique ?? {};
    this._annees = Object.keys(this._table).map(Number).sort((a, b) => a - b);
  }

  /** @returns {[number, number, number]|null} trimestres, coefficient, fiabilité. */
  parametres(annee) {
    if (this._annees.length === 0 || annee < this._annees[0]) {
      return null;
    }
    let applicable = this._annees[0];
    for (const candidate of this._annees) {
      if (candidate > annee) {
        break;
      }
      applicable = candidate;
    }
    return this._table[String(applicable)];
  }
}

/**
 * Minimum garanti de la fonction publique — article L. 17 du code des pensions.
 *
 * Ce n'est pas un plancher proratisé mais un BARÈME EN ESCALIER sur la durée de
 * services, rapporté à un traitement de référence gelé : celui de l'indice
 * majoré 227 au 1er janvier 2004, revalorisé sur les prix depuis. Quinze ans de
 * services en ouvrent 57,5 %, trente ans 95 %, quarante ans la totalité.
 */
export class MinimumGaranti {
  constructor(paquet, macro) {
    this.macro = macro;
    const contenu = paquet.minimum_garanti ?? {};
    this._bareme = contenu.bareme ?? {};
    this._point = contenu.point_indice ?? {};
    this._montants = contenu.montants ?? {};
    this._anneesBareme = Object.keys(this._bareme).map(Number).sort((a, b) => a - b);
    this._anneesMontants = Object.keys(this._montants).map(Number).sort((a, b) => a - b);
  }

  /** Barème en vigueur l'année de liquidation, ou ``null`` avant 1976. */
  bareme(anneeLiquidation) {
    if (this._anneesBareme.length === 0 || anneeLiquidation < this._anneesBareme[0]) {
      return null;
    }
    let applicable = this._anneesBareme[0];
    for (const candidate of this._anneesBareme) {
      if (candidate > anneeLiquidation) {
        break;
      }
      applicable = candidate;
    }
    return this._bareme[String(applicable)];
  }

  _pointIndice(annee) {
    const annees = Object.keys(this._point).map(Number).filter((a) => a <= annee);
    if (annees.length === 0) {
      return null;
    }
    return this._point[String(Math.max(...annees))];
  }

  /**
   * Montant plein du minimum garanti, quarante ans de services.
   *
   * Un montant SERVI connu prime sur tout calcul ; après 2004 la référence est
   * le traitement gelé de l'indice majoré 227, projeté sur les prix depuis
   * l'ancre en vigueur ; avant 2004, le gel n'existe pas et c'est le traitement
   * de l'indice majoré de l'année, au point d'indice de cette année-là.
   */
  reference(anneeLiquidation) {
    const bareme = this.bareme(anneeLiquidation);
    if (bareme === null || bareme === undefined) {
      return null;
    }
    const indice = bareme[0];
    const fiabiliteBareme = bareme[5];

    if (anneeLiquidation <= MinimumGaranti.ANNEE_GEL
        && this._montants[String(anneeLiquidation)] === undefined) {
      const point = this._pointIndice(anneeLiquidation);
      if (point === null) {
        return null;
      }
      return [indice * point[0], Math.min(fiabiliteBareme, point[1])];
    }

    if (this._anneesMontants.length === 0) {
      return null;
    }
    let valeur;
    let fiabilite;
    if (this._montants[String(anneeLiquidation)] !== undefined) {
      [valeur, fiabilite] = this._montants[String(anneeLiquidation)];
    } else {
      const anterieures = this._anneesMontants.filter((a) => a < anneeLiquidation);
      const ancre = anterieures.length
        ? anterieures[anterieures.length - 1]
        : this._anneesMontants[0];
      [valeur, fiabilite] = this._montants[String(ancre)];
      valeur *= this.macro.coefficientPrix(ancre, anneeLiquidation);
    }
    return [valeur * indice / MinimumGaranti.INDICE_REFERENCE,
      Math.min(fiabiliteBareme, fiabilite)];
  }

  /** Plancher opposable pour une durée de services donnée. */
  montant(anneeLiquidation, trimestresServices) {
    const bareme = this.bareme(anneeLiquidation);
    const reference = this.reference(anneeLiquidation);
    if (bareme === null || bareme === undefined || reference === null) {
      return null;
    }
    const [, part, pointsBas, pointsHaut, seuil] = bareme;
    const duree = Math.max(0, Math.min(trimestresServices, MinimumGaranti.SEUIL_HAUT));
    if (duree <= 0) {
      return null;
    }
    let taux;
    if (duree < MinimumGaranti.SEUIL_BAS) {
      taux = part * duree / MinimumGaranti.SEUIL_BAS;
    } else if (duree >= MinimumGaranti.SEUIL_HAUT) {
      taux = 1.0;
    } else if (duree < seuil) {
      taux = part + (duree - MinimumGaranti.SEUIL_BAS) * pointsBas;
    } else {
      taux = part + (seuil - MinimumGaranti.SEUIL_BAS) * pointsBas
        + (duree - seuil) * pointsHaut;
    }
    return [reference[0] * taux, reference[1]];
  }
}

/** Quinze ans de services, en trimestres : première marche du barème. */
MinimumGaranti.SEUIL_BAS = 60;
/** Quarante ans : au-delà, la référence est servie en entier. */
MinimumGaranti.SEUIL_HAUT = 160;
/** Année à partir de laquelle la référence est gelée puis indexée sur les prix. */
MinimumGaranti.ANNEE_GEL = 2004;
/** Indice majoré auquel se rapportent les montants transcrits. */
MinimumGaranti.INDICE_REFERENCE = 227;

/**
 * Minimum vieillesse — allocation de solidarité aux personnes âgées (ASPA).
 *
 * Allocation DIFFÉRENTIELLE qui porte les ressources au montant du barème.
 * Ce n'est pas une pension : condition d'âge, de ressources du foyer et de
 * demande, et récupérable sur les successions.
 */
export class MinimumVieillesse {
  constructor(paquet, macro) {
    this.macro = macro;
    this._table = paquet.minimum_vieillesse ?? {};
    this._annees = Object.keys(this._table).map(Number).sort((a, b) => a - b);
  }

  /** Montant maximal d'une personne seule, l'année demandée. */
  plafond(annee) {
    if (this._annees.length === 0) {
      return null;
    }
    if (this._table[String(annee)] !== undefined) {
      return this._table[String(annee)];
    }
    const anterieures = this._annees.filter((a) => a < annee);
    const ancre = anterieures.length
      ? anterieures[anterieures.length - 1]
      : this._annees[0];
    const [valeur, fiabilite] = this._table[String(ancre)];
    return [valeur * this.macro.coefficientPrix(ancre, annee), fiabilite];
  }
}

/** Âge d'ouverture de droit commun de l'ASPA. */
MinimumVieillesse.AGE_OUVERTURE = 65;

/**
 * Trimestres accordés au titre des enfants, dispositif par dispositif.
 *
 * Le module en servait huit par enfant, à tout assuré, à toute date et dans
 * tout régime. Le droit n'en a jamais servi autant : la majoration de durée
 * d'assurance n'existe pas avant 1972, elle vaut un an par enfant jusqu'en
 * 1974, elle est attribuée à la mère, et la fonction publique ne l'applique
 * pas — elle a sa propre bonification, qui vaut un an par enfant né avant 2004
 * et deux trimestres pour les enfants nés depuis.
 *
 * Deux horloges, et la distinction est dans les textes : la MDA se lit à
 * l'ANNÉE DE LIQUIDATION, la bonification à l'ANNÉE DE NAISSANCE DE L'ENFANT.
 */
export class MajorationsPourEnfants {
  constructor(paquet) {
    this._table = paquet.majorations_enfants ?? [];
  }

  /**
   * Trimestres accordés PAR ENFANT, ou `null` si rien n'est dû.
   *
   * @returns {[number, number]|null} trimestres et fiabilité.
   */
  parEnfant(dispositif, sexe, anneeNaissance, anneeLiquidation, nombreEnfants) {
    for (const [code, reference, debut, fin, trimestres, enfantsMinimum,
      beneficiaire, fiabilite] of this._table) {
      if (code !== dispositif) {
        continue;
      }
      const annee = reference === "liquidation"
        ? anneeLiquidation
        : anneeNaissance + MajorationsPourEnfants.AGE_PRESUME_A_LA_NAISSANCE;
      if (annee < debut || annee > fin) {
        continue;
      }
      if (beneficiaire === "mere" && sexe !== "F") {
        return null;
      }
      if (nombreEnfants < enfantsMinimum) {
        return null;
      }
      return [trimestres, fiabilite];
    }
    return null;
  }
}

/**
 * Âge présumé de la mère à la naissance de ses enfants. Le modèle ne collecte
 * pas leur date de naissance ; il la déduit de cette convention, qui est l'âge
 * moyen des mères à l'accouchement.
 */
MajorationsPourEnfants.AGE_PRESUME_A_LA_NAISSANCE = 30;

/**
 * Surcote parentale — article L. 351-1-2-1 du code de la sécurité sociale.
 *
 * Contrepartie du recul de l'âge légal : un assuré qui avait sa durée requise à
 * 63 ans s'est vu imposer par la loi du 14 avril 2023 une année de travail de
 * plus qui ne lui rapportait rien, la surcote ordinaire ne comptant qu'au-delà
 * de l'âge légal. La loi comble ce trou pour les parents : 1,25 % par trimestre
 * acquis entre 63 ans et l'âge légal, quatre au plus.
 */
export class SurcoteParentale {
  constructor(paquet) {
    this._table = paquet.surcote_parentale ?? [];
  }

  /**
   * @returns {[number, number, number, number]|null} âge d'ouverture, taux par
   * trimestre, plafond de trimestres, fiabilité.
   */
  parametres(anneeLiquidation) {
    for (const [debut, fin, age, taux, maximum, fiabilite] of this._table) {
      if (anneeLiquidation >= debut && anneeLiquidation <= fin) {
        return [age, taux, maximum, fiabilite];
      }
    }
    return null;
  }
}

/**
 * Départ anticipé pour carrière longue — article L. 351-1-1.
 *
 * La principale porte d'entrée avant l'âge légal, et la seule qui se déduise de
 * la carrière elle-même : la pénibilité, l'invalidité et l'inaptitude demandent
 * des informations que le modèle n'a pas.
 */
export class CarriereLongue {
  constructor(paquet) {
    this._table = paquet.carriere_longue ?? {};
    this._annees = Object.keys(this._table).map(Number).sort((a, b) => a - b);
  }

  /**
   * Âge le plus précoce ouvert par le dispositif, ou ``null``.
   *
   * @returns {[number, number]|null} âge de départ et fiabilité.
   */
  ageDeDepart(carriere, anneeLiquidation, trimestresCotises, requis) {
    if (this._annees.length === 0 || anneeLiquidation < this._annees[0]) {
      return null;
    }
    let applicable = this._annees[0];
    for (const candidate of this._annees) {
      if (candidate > anneeLiquidation) {
        break;
      }
      applicable = candidate;
    }

    let meilleur = null;
    for (const [ageMax, trimestresDebut, ageDepart, supplement, fiabilite]
      of this._table[String(applicable)]) {
      let acquis = 0;
      for (const ligne of carriere.lignes) {
        if (ligne.cotise && ligne.annee <= carriere.annee_naissance + ageMax
            && ligne.annee < anneeLiquidation) {
          acquis += ligne.trimestres_valides;
        }
      }
      if (acquis < trimestresDebut || trimestresCotises < requis + supplement) {
        continue;
      }
      // Départage identique à celui de Python, qui compare des couples
      // (âge, fiabilité) : à âge égal, la fiabilité la plus basse l'emporte.
      if (meilleur === null || ageDepart < meilleur[0]
          || (ageDepart === meilleur[0] && fiabilite < meilleur[1])) {
        meilleur = [ageDepart, fiabilite];
      }
    }
    return meilleur;
  }
}

/**
 * Catalogue des régimes, profils d'affiliation et barèmes du point.
 *
 * Portage de ``src/retraite_notionnelle/donnees/regimes.py``, de la classe
 * ``Affiliations`` de ``carriere.py`` et des deux lecteurs de barèmes de
 * ``scenarios/actuel.py``. Les fiches arrivent déjà normalisées par
 * ``scripts/construire_donnees.py`` : la validation des champs et des familles
 * reste du côté Python, où elle est testée, et n'est pas dupliquée ici.
 */

/**
 * Assiettes reconnues et leur borne exprimée en plafonds de la Sécurité
 * sociale. ``null`` signifie « pas de borne supérieure ».
 */
export const BORNES_ASSIETTE = Object.freeze({
  plafonnee: [0.0, 1.0],
  deplafonnee: [0.0, null],
  tranche_1: [0.0, 1.0],
  tranche_a: [0.0, 1.0],
  tranche_2: [1.0, 8.0],
  // Tranche 2 de l'Arrco d'AVANT la fusion : elle s'arrêtait à trois plafonds,
  // là où celle de l'Agirc-Arrco va jusqu'à huit.
  tranche_2_arrco: [1.0, 3.0],
  tranche_b: [1.0, 4.0],
  tranche_c: [4.0, 8.0],
  // Tranches propres au régime de base des professions libérales : la première
  // s'arrêtait à 0,85 plafond avant 2015, la seconde part de zéro depuis — les
  // deux se recouvrent donc, et c'est bien la règle du régime.
  plafonnee_085_pass: [0.0, 0.85],
  tranche_085_5_pass: [0.85, 5.0],
  plafonnee_5_pass: [0.0, 5.0],
  hors_primes: [0.0, null],
  primes_uniquement: [0.0, null],
  forfaitaire: [0.0, null],
  sans_objet: [0.0, null],
});

/** Jeu de paramètres d'un régime sur une plage d'années. */
export class PeriodeRegime {
  constructor(fiche) {
    Object.assign(this, fiche);
  }

  couvre(annee) {
    return this.debut <= annee && (this.fin === null || annee <= this.fin);
  }

  /** Part du taux que l'assuré supporte lui-même. */
  get tauxCotisationSalarie() {
    return this.taux_cotisation_retraite * this.part_salariale;
  }

  bornesAssietteEnPass() {
    return BORNES_ASSIETTE[this.assiette] || [0.0, null];
  }

  /**
   * Bornes de l'assiette EN EUROS de l'année, quelle que soit leur forme.
   *
   * Les bornes en euros priment quand la fiche en porte : un régime qui fixe
   * ses tranches en euros et ne les indexe pas — la complémentaire des avocats,
   * 42 507 € de 2023 à 2026 quand le plafond passait de 43 992 à 48 060 € — ne
   * peut pas être décrit en multiples d'un plafond qui, lui, suit les salaires.
   */
  bornesAssietteEnEuros(pass) {
    const basse = this.borne_basse_euros;
    const haute = this.borne_haute_euros;
    if ((basse !== null && basse !== undefined)
        || (haute !== null && haute !== undefined)) {
      return [basse ?? 0.0, haute ?? null];
    }
    const [borneBasse, borneHaute] = this.bornesAssietteEnPass();
    return [borneBasse * pass, borneHaute === null ? null : borneHaute * pass];
  }

  /** Assiette qui ouvre droit à ``points_maximum`` points. */
  repereAssiette(pass, smicHoraire) {
    if (this.assiette_repere_smic !== null && this.assiette_repere_smic !== undefined) {
      return this.assiette_repere_smic * smicHoraire;
    }
    const [borneBasse, borneHaute] = this.bornesAssietteEnPass();
    return borneHaute === null ? 0.0 : (borneHaute - borneBasse) * pass;
  }
}

export class Regime {
  constructor(fiche) {
    Object.assign(this, fiche);
    this.periodes = fiche.periodes.map((p) => new PeriodeRegime(p));
  }

  /**
   * Paramètres applicables une année donnée. Quand plusieurs périodes couvrent
   * la même année — cas des régimes à tranches — la première est retournée.
   */
  periode(annee) {
    return this.periodes.find((p) => p.couvre(annee)) || null;
  }

  periodesActives(annee) {
    return this.periodes.filter((p) => p.couvre(annee));
  }

  /** Le régime accepte-t-il de nouveaux affiliés cette année-là ? */
  ouvert(annee) {
    if (annee < this.creation) {
      return false;
    }
    return !(this.fermeture !== null && annee >= this.fermeture);
  }

  /** Le régime sert-il encore des droits cette année-là ? */
  vivant(annee) {
    if (annee < this.creation) {
      return false;
    }
    return this.extinction === null || annee < this.extinction;
  }
}

export class CatalogueRegimes {
  constructor(paquet) {
    this._regimes = new Map();
    for (const fiche of paquet.regimes) {
      this._regimes.set(fiche.code, new Regime(fiche));
    }
    if (this._regimes.size === 0) {
      throw new Error("aucun régime chargé");
    }
    this.codes = [...this._regimes.keys()].sort();
  }

  obtenir(code) {
    const regime = this._regimes.get(code);
    if (regime === undefined) {
      throw new Error(
        `régime inconnu : ${code}. Régimes disponibles : ${this.codes.join(", ")}`,
      );
    }
    return regime;
  }

  contient(code) {
    return this._regimes.has(code);
  }

  get taille() {
    return this._regimes.size;
  }

  * [Symbol.iterator]() {
    yield* this._regimes.values();
  }

  parFamille(famille) {
    return [...this].filter((r) => r.famille === famille);
  }

  enRepartition() {
    return [...this].filter((r) => !r.hors_repartition);
  }

  ouverts(annee) {
    return [...this].filter((r) => r.ouvert(annee));
  }

  /**
   * Suit la chaîne d'absorption jusqu'au régime réellement compétent.
   * Exemple : ``organic`` en 2010 renvoie ``rsi`` ; en 2020, ``regime_general``.
   */
  resoudreSuccession(code, annee) {
    const vu = new Set([code]);
    let courant = this.obtenir(code);
    while (courant.extinction !== null && annee >= courant.extinction) {
      const suivant = courant.integre_dans;
      if (suivant === null || suivant === undefined || vu.has(suivant)) {
        break;
      }
      vu.add(suivant);
      courant = this.obtenir(suivant);
    }
    return courant.code;
  }
}

/** Correspondance statut -> régimes, année par année. */
export class Affiliations {
  constructor(paquet) {
    this._profils = paquet.affiliations;
    if (!this._profils || Object.keys(this._profils).length === 0) {
      throw new Error("aucun profil d'affiliation chargé");
    }
    this.codes = Object.keys(this._profils).sort();
  }

  contient(code) {
    return Object.prototype.hasOwnProperty.call(this._profils, code);
  }

  libelle(code) {
    return this._profils[code].libelle ?? code;
  }

  /**
   * Ce statut cotise-t-il sans employeur ?
   *
   * Vrai pour les non-salariés. Le drapeau est porté par le STATUT et non par
   * le régime : un artisan cotise au régime général, dont la fiche porte la
   * répartition d'un salarié. Le taux y est le bon ; la répartition, non.
   */
  sansEmployeur(affiliation) {
    return Boolean((this._profils[affiliation] ?? {}).sans_employeur);
  }

  /** Régimes applicables à ce statut cette année-là. */
  regimes(affiliation, annee) {
    const profil = this._profils[affiliation];
    if (profil === undefined) {
      throw new Error(
        `affiliation inconnue : ${affiliation}. Disponibles : ${this.codes.join(", ")}`,
      );
    }
    for (const periode of profil.periodes || []) {
      const fin = periode.fin ?? null;
      if (periode.debut <= annee && (fin === null || annee <= fin)) {
        return periode.regimes || [];
      }
    }
    return [];
  }
}

/** Rendements instantanés des régimes en points. */
export class Rendements {
  constructor(paquet) {
    this._table = paquet.rendements_points;
  }

  /** @returns {[number, number]} rendement et fiabilité. */
  rendement(regime, annee) {
    for (const [code, debut, fin, valeur, fiabilite] of this._table) {
      if (code === regime && debut <= annee && annee <= fin) {
        return [valeur, fiabilite];
      }
    }
    return [0.0, 0];
  }
}

/**
 * Prix d'achat et valeur de service du point, régime par régime et année.
 *
 * Trois grandeurs suffisent à reconstituer exactement une pension en points :
 * le salaire de référence (prix d'achat du point l'année de la cotisation), le
 * taux d'appel (quelle part de la cotisation ouvre des droits) et la valeur de
 * service (conversion des points en rente à la liquidation).
 */
/**
 * Coefficients de conversion des points, lus et non devinés.
 *
 * Portage de ``ConversionsPoints`` de ``scenarios/actuel.py``. Deux sortes de
 * lignes : celles qui portent un `successeur` décrivent la reprise des points à
 * une fusion ; celles qui n'en portent pas décrivent un changement d'UNITÉ
 * interne au régime — l'unification de l'Arrco au 1er janvier 1999, dont les
 * valeurs d'avant sont celles de l'UNIRS.
 */
//: Niveau de fiabilité maximal, tel que le paquet le code. Ce module n'importe
//: rien : toutes ses valeurs viennent du paquet de données, où les fiabilités
//: sont déjà des entiers.
const FIABILITE_CERTIFIEE = 3;


export class ConversionsPoints {
  constructor(paquet) {
    this._fusions = new Map();
    this._echelles = new Map();
    for (const ligne of paquet.conversions_points ?? []) {
      const [regime, anneeEffet, successeur, coefficient, fiabilite] = ligne;
      const conversion = { anneeEffet, successeur, coefficient, fiabilite };
      if (successeur) {
        this._fusions.set(`${regime}|${successeur}`, conversion);
      } else {
        if (!this._echelles.has(regime)) {
          this._echelles.set(regime, []);
        }
        this._echelles.get(regime).push(conversion);
      }
    }
    for (const conversions of this._echelles.values()) {
      conversions.sort((a, b) => a.anneeEffet - b.anneeEffet);
    }
  }

  /** Coefficient de reprise des points de ``regime`` par ``successeur``. */
  fusion(regime, successeur) {
    return this._fusions.get(`${regime}|${successeur}`) ?? null;
  }

  /** Facteur d'unité entre l'année d'acquisition et celle de liquidation. */
  echelle(regime, anneeAcquisition, anneeLiquidation) {
    let facteur = 1.0;
    let fiabilite = FIABILITE_CERTIFIEE;
    for (const conversion of this._echelles.get(regime) ?? []) {
      if (anneeAcquisition < conversion.anneeEffet
          && conversion.anneeEffet <= anneeLiquidation) {
        facteur *= conversion.coefficient;
        fiabilite = Math.min(fiabilite, conversion.fiabilite);
      }
    }
    return [facteur, fiabilite];
  }
}


export class ValeursPoint {
  constructor(paquet) {
    this._table = new Map();
    for (const [cle, valeurs] of Object.entries(paquet.valeurs_point)) {
      const annees = Object.keys(valeurs).map(Number).sort((a, b) => a - b);
      this._table.set(cle, {
        annees,
        valeurs: annees.map((a) => valeurs[String(a)]),
      });
    }
  }

  /**
   * Dernière valeur publiée à l'année demandée, ou avant elle. Une valeur reste
   * en vigueur jusqu'à sa modification : c'est la règle de lecture d'un barème.
   * Rien n'est renvoyé pour les années antérieures à la première publication.
   */
  _enVigueur(regime, mesure, annee) {
    const table = this._table.get(`${regime}|${mesure}`);
    if (table === undefined) {
      return null;
    }
    let retenu = null;
    for (let i = 0; i < table.annees.length; i += 1) {
      if (table.annees[i] <= annee) {
        retenu = table.valeurs[i];
      } else {
        break;
      }
    }
    return retenu;
  }

  /**
   * Prix d'achat effectif d'un point : [salaire de référence, taux d'appel,
   * fiabilité]. Rien n'est renvoyé au-delà de la dernière année publiée :
   * prolonger le dernier prix connu reviendrait à supposer un barème gelé, les
   * points seraient achetés trop bon marché et la pension surestimée.
   */
  achat(regime, annee) {
    const table = this._table.get(`${regime}|salaire_reference`);
    if (table === undefined || annee > table.annees[table.annees.length - 1]) {
      return null;
    }
    const reference = this._enVigueur(regime, "salaire_reference", annee);
    if (reference === null || reference[0] <= 0) {
      return null;
    }
    const appel = this._enVigueur(regime, "taux_appel", annee);
    const [taux, fiabiliteAppel] = appel !== null ? appel : [1.0, 1];
    return [reference[0], taux, Math.min(reference[1], fiabiliteAppel)];
  }

  derniereAnneeServie(regime) {
    const table = this._table.get(`${regime}|valeur_service`);
    return table === undefined ? null : table.annees[table.annees.length - 1];
  }

  premiereAnneeServie(regime) {
    const table = this._table.get(`${regime}|valeur_service`);
    return table === undefined ? null : table.annees[0];
  }

  service(regime, annee) {
    return this._enVigueur(regime, "valeur_service", annee);
  }
}

/**
 * Contribution employeur des régimes publics, année par année.
 *
 * Portage de ``ContributionsEmployeurPubliques`` du module Python. Les fiches
 * de régime ne portent, pour la fonction publique et les régimes spéciaux, que
 * la retenue de l'agent ; cette table porte l'autre moitié, pour les trois
 * régimes dont elle est publiée — l'État (reconstituée de 1995 à 2005, appelée
 * depuis 2006), la CNRACL (appelée depuis 1948) et la SNCF (2007-2018).
 *
 * Avant la première année d'un régime, la table ne rend rien : il n'y a rien à
 * extrapoler, et l'appelant estime alors la part patronale. Après la
 * dernière, le dernier taux est prolongé, avec la fiabilité d'une projection.
 */
export class ContributionsEmployeurPubliques {
  constructor(paquet) {
    this._table = new Map();
    for (const [cle, valeur] of Object.entries(
      paquet.contribution_employeur_public ?? {},
    )) {
      const [regime, annee] = cle.split("|");
      if (!this._table.has(regime)) {
        this._table.set(regime, new Map());
      }
      this._table.get(regime).set(Number(annee), valeur);
    }
    this._bornes = new Map();
    for (const [regime, annees] of this._table) {
      const liste = [...annees.keys()].sort((a, b) => a - b);
      this._bornes.set(regime, [liste[0], liste[liste.length - 1], liste]);
    }
  }

  /** Première et dernière année publiées, ou ``null`` si le régime est absent. */
  couverture(regime) {
    const bornes = this._bornes.get(regime);
    return bornes === undefined ? null : [bornes[0], bornes[1]];
  }

  /**
   * Contribution employeur du régime cette année-là.
   *
   * @returns {[number, string, number]|null} taux, nature, fiabilité.
   */
  taux(regime, annee) {
    const annees = this._table.get(regime);
    if (annees === undefined) {
      return null;
    }
    if (annees.has(annee)) {
      return annees.get(annee);
    }
    const [premiere, derniere, liste] = this._bornes.get(regime);
    if (annee < premiere) {
      return null;
    }
    if (annee > derniere) {
      const [taux, nature] = annees.get(derniere);
      return [taux, nature, 0];
    }
    let applicable = premiere;
    for (const candidate of liste) {
      if (candidate > annee) {
        break;
      }
      applicable = candidate;
    }
    return annees.get(applicable);
  }
}
