/**
 * Durée d'assurance requise pour le taux plein, PAR GÉNÉRATION.
 *
 * Depuis la loi du 22 juillet 1993, l'exigence est indexée sur l'année de
 * NAISSANCE et non sur l'année de liquidation : deux assurés qui liquident le
 * même jour n'ont pas la même durée requise s'ils ne sont pas de la même
 * génération.
 */
export class DureesRequises {
  constructor(paquet) {
    this._table = paquet.durees_requises ?? {};
    const generations = Object.keys(this._table).map(Number);
    this._derniere = generations.length ? Math.max(...generations) : null;
  }

  /** @returns {[number, number] | null} trimestres et fiabilité. */
  trimestres(generation) {
    if (this._derniere === null) {
      return null;
    }
    if (generation > this._derniere) {
      return this._table[String(this._derniere)];
    }
    return this._table[String(generation)] ?? null;
  }
}

/**
 * Montant du minimum contributif et plafond d'écrêtement, par année.
 *
 * Deux grandeurs, et pas une seule : le minimum est ÉCRÊTÉ dès que l'ensemble
 * des pensions dépasse un plafond. Sans cette seconde condition, le modèle
 * servait le minimum à des assurés que leurs complémentaires placent déjà
 * bien au-dessus.
 */
export class MinimumContributif {
  constructor(paquet, macro) {
    this.macro = macro;
    this._table = paquet.minimum_contributif ?? {};
  }

  /** @returns {[number, number, number]} montant, plafond et fiabilité. */
  valeurs(annee) {
    const annees = Object.keys(this._table).map(Number);
    if (annees.length === 0) {
      return [0.0, 0.0, 0];
    }
    let reference = annees[0];
    for (const candidate of annees) {
      if (Math.abs(candidate - annee) < Math.abs(reference - annee)) {
        reference = candidate;
      }
    }
    const [montant, plafond, fiabilite] = this._table[String(reference)];
    const coefficient = this.macro.coefficientPrix(reference, annee);
    return [montant * coefficient, plafond * coefficient, fiabilite];
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
  tranche_b: [1.0, 4.0],
  tranche_c: [4.0, 8.0],
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

  bornesAssietteEnPass() {
    return BORNES_ASSIETTE[this.assiette] || [0.0, null];
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
