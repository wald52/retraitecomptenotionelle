/**
 * Tables de mortalité : quotients observés, lois de Makeham, tables de génération.
 *
 * Portage de ``src/retraite_notionnelle/donnees/mortalite.py``. Deux sources,
 * arbitrées couple par couple (année, sexe, âge) :
 *
 * 1. les quotients réellement observés, quand le couple y figure ;
 * 2. partout ailleurs, une table paramétrique de Gompertz-Makeham calibrée pour
 *    reproduire les espérances de vie publiées à 60 et 65 ans.
 *
 * Les paramètres calibrés sont livrés avec le paquet de données, calculés une
 * fois pour toutes par ``scripts/construire_donnees.py`` : le navigateur ne
 * refait aucune bissection, et les deux implémentations partent des mêmes
 * paramètres au bit près. La calibration reste portée ci-dessous, pour qu'une
 * année absente de la table donne un résultat plutôt qu'une erreur.
 *
 * Force de mortalité retenue :  μ(x) = A + B · exp(k · (x − 60))
 */

import { Fiabilite, SerieAnnuelle } from "./serie.js";

/** Mortalité « accidentelle », indépendante de l'âge (terme de Makeham). */
export const MORTALITE_ACCIDENTELLE = 0.0005;

/** Pas d'intégration numérique, en années. */
export const PAS = 0.25;

/** Âge terminal des tables. */
export const AGE_TERMINAL = 120.0;

/** Paramètres de Makeham pour une année et un sexe donnés. */
export class LoiMortalite {
  constructor(a, b, k, annee, sexe, fiabilite) {
    this.a = a;
    this.b = b;
    this.k = k;
    this.annee = annee;
    this.sexe = sexe;
    this.fiabilite = fiabilite;
  }

  force(age) {
    return this.a + this.b * Math.exp(this.k * (age - 60.0));
  }

  /** Probabilité de survivre ``duree`` années à partir de ``ageDebut``. */
  survie(ageDebut, duree) {
    if (duree <= 0) {
      return 1.0;
    }
    const u = Math.exp(this.k * (ageDebut - 60.0));
    const integrale = this.a * duree
      + (this.b / this.k) * u * (Math.exp(this.k * duree) - 1.0);
    return Math.exp(-integrale);
  }

  /** Espérance de vie résiduelle complète à ``age``, table du moment. */
  esperance(age) {
    return esperanceMakeham(this.a, this.b, this.k, age);
  }
}

/**
 * Intégration incrémentale : la survie cumulée est propagée d'un pas à l'autre,
 * ce qui coûte une exponentielle par pas au lieu de deux.
 */
export function esperanceMakeham(a, b, k, age) {
  let total = 0.0;
  let survie = 1.0;
  let u = Math.exp(k * (age - 60.0));
  const facteurPas = Math.exp(k * PAS);
  const borne = Math.trunc((AGE_TERMINAL - age) / PAS);
  for (let pas = 0; pas < Math.max(borne, 0); pas += 1) {
    const prochaine = survie * Math.exp(-(a * PAS + (b / k) * u * (facteurPas - 1.0)));
    total += 0.5 * (survie + prochaine) * PAS;
    survie = prochaine;
    u *= facteurPas;
    if (survie < 1e-12) {
      break;
    }
  }
  return total;
}

/**
 * Ajuste (b, k) pour reproduire simultanément e60 et e65.
 *
 * Deux bissections emboîtées, toutes deux sur des fonctions monotones : à k
 * fixé, e60 décroît quand b croît ; une fois b calé sur e60, le rapport
 * e65/e60 décroît quand k croît.
 */
export function esperanceRaccordee(a, b, k, age, quotients) {
  let total = 0.0;
  let survie = 1.0;
  let courant = age;
  while (courant < AGE_TERMINAL && survie > 1e-12) {
    const quotient = quotients ? quotients[String(Math.trunc(courant))] : undefined;
    let facteur;
    if (quotient !== undefined) {
      facteur = 1.0 - quotient;
    } else {
      const u = Math.exp(k * (courant - 60.0));
      facteur = Math.exp(-(a + (b / k) * u * (Math.exp(k) - 1.0)));
    }
    const prochaine = survie * facteur;
    total += 0.5 * (survie + prochaine);
    survie = prochaine;
    courant += 1.0;
  }
  return total;
}

/** Tolérance sur les espérances reproduites par la calibration, en années. */
export const TOLERANCE_CALIBRATION = 0.05;

export function calibrer(e60Cible, e65Cible, annee, sexe, fiabilite, quotients = null) {
  const bPour = (k, cible, observes) => {
    let bas = 1e-9;
    let haut = 5.0;
    for (let i = 0; i < 50; i += 1) {
      const milieu = Math.sqrt(bas * haut);
      if (esperanceRaccordee(MORTALITE_ACCIDENTELLE, milieu, k, 60.0, observes) > cible) {
        bas = milieu;
      } else {
        haut = milieu;
      }
    }
    return Math.sqrt(bas * haut);
  };
  const bPourE60 = (k) => bPour(k, e60Cible, null);

  const ratioCible = e65Cible / e60Cible;
  let basK = 0.02;
  let hautK = 0.3;
  for (let i = 0; i < 30; i += 1) {
    const k = 0.5 * (basK + hautK);
    const b = bPourE60(k);
    const e60 = esperanceMakeham(MORTALITE_ACCIDENTELLE, b, k, 60.0);
    const e65 = esperanceMakeham(MORTALITE_ACCIDENTELLE, b, k, 65.0);
    if (e65 / e60 > ratioCible) {
      basK = k;
    } else {
      hautK = k;
    }
  }
  const k = 0.5 * (basK + hautK);
  let b = bPourE60(k);

  // Le NIVEAU de la queue est recalé, à forme constante, pour que la table
  // telle que le modèle la lit — quotients observés compris — reproduise
  // l'espérance publiée. Sans ce second temps, la loi rendait 11,3 ans
  // d'espérance résiduelle à 85 ans pour une femme en 2010, là où la cible en
  // implique 7,5.
  if (quotients) {
    const recale = bPour(k, e60Cible, quotients);
    const atteint = esperanceRaccordee(MORTALITE_ACCIDENTELLE, recale, k, 60.0, quotients);
    if (Math.abs(atteint - e60Cible) <= TOLERANCE_CALIBRATION) {
      b = recale;
    }
  }
  return new LoiMortalite(MORTALITE_ACCIDENTELLE, b, k, annee, sexe, fiabilite);
}

/** Tables du moment et tables de génération pour les deux sexes. */
export class DonneesMortalite {
  static SEXES = ["H", "F"];

  constructor(paquet, poidsUnisexe = [0.5, 0.5]) {
    this.poidsUnisexe = poidsUnisexe;
    this._calibrations = paquet.calibrations || {};
    this._quotients = paquet.quotients || {};
    this._e60 = {};
    this._e65 = {};
    for (const sexe of DonneesMortalite.SEXES) {
      this._e60[sexe] = SerieAnnuelle.depuisPaquet(`e60_${sexe}`, paquet.series[`e60_${sexe}`]);
      this._e65[sexe] = SerieAnnuelle.depuisPaquet(`e65_${sexe}`, paquet.series[`e65_${sexe}`]);
    }
    this._lois = new Map();
    this._courbes = new Map();
  }

  get utiliseTablesReelles() {
    return Object.keys(this._quotients).length > 0;
  }

  // -- tables du moment ------------------------------------------------------

  /** Loi de mortalité du moment pour une année civile et un sexe. */
  loi(annee, sexe) {
    const cleMemoire = `${annee}|${sexe}`;
    const memorisee = this._lois.get(cleMemoire);
    if (memorisee !== undefined) {
      return memorisee;
    }

    const serie = this._e60[sexe];
    const anneeBornee = Math.max(serie.premiereAnnee, Math.min(annee, serie.derniereAnnee));
    const e60 = serie.brut(anneeBornee);
    const e65 = this._e65[sexe].brut(anneeBornee);
    let fiabilite = Math.min(e60.fiabilite, e65.fiabilite);
    if (annee !== anneeBornee) {
      fiabilite = Fiabilite.ESTIMEE;
    }

    const parametres = this._calibrations[`${anneeBornee}|${sexe}`];
    const loi = parametres !== undefined
      ? new LoiMortalite(MORTALITE_ACCIDENTELLE, parametres[0], parametres[1],
        annee, sexe, fiabilite)
      : calibrer(e60.valeur, e65.valeur, annee, sexe, fiabilite,
        this._quotients[`${anneeBornee}|${sexe}`] ?? null);
    this._lois.set(cleMemoire, loi);
    return loi;
  }

  /** Survie d'un âge ENTIER au suivant, quotient observé s'il existe. */
  _survieCellule(age, annee, sexe) {
    const table = this._quotients[`${annee}|${sexe}`];
    if (table !== undefined) {
      const qx = table[String(age)];
      if (qx !== undefined) {
        return 1.0 - qx;
      }
    }
    return this.loi(annee, sexe).survie(age, 1.0);
  }

  /**
   * Probabilité de passer de ``age`` à ``age+1`` pendant l'année ``annee``.
   *
   * **L'âge est fractionnaire, et il compte.** La méthode lisait
   * ``quotients[trunc(age)]`` : la part OBSERVÉE de la table était aveugle aux
   * mois, et le diviseur d'un départ à 60 ans et onze mois était celui d'un
   * départ à 60 ans tout rond — 1,7 % de pension d'un coup à chaque
   * anniversaire, et rien entre deux.
   *
   * Entre deux âges entiers, la force de mortalité est supposée CONSTANTE —
   * l'hypothèse actuarielle usuelle, et la seule qui rende la survie continue
   * en l'âge : p(x+f) = p(x)^(1-f) · p(x+1)^f. L'année civile, elle, n'est pas
   * interpolée : une table est publiée par millésime, et lisser entre deux
   * millésimes inventerait une tendance infra-annuelle que la source ne porte
   * pas.
   */
  survieAnnuelle(age, annee, sexe) {
    const plancher = Math.floor(age);
    const fraction = age - plancher;
    const basse = this._survieCellule(plancher, annee, sexe);
    if (fraction <= 1e-9) {
      return basse;
    }
    const haute = this._survieCellule(plancher + 1, annee, sexe);
    return basse ** (1.0 - fraction) * haute ** fraction;
  }

  // -- tables de génération --------------------------------------------------

  /**
   * Survie cumulée année par année à partir de ``ageDebut``.
   *
   * L'élément d'indice ``t`` est la probabilité d'être encore en vie ``t``
   * années après la liquidation. En table de génération, chaque année vécue se
   * voit appliquer la mortalité de l'année civile correspondante : l'ignorer
   * surestime la pension des générations récentes.
   */
  courbeSurvie(ageDebut, anneeDebut, sexe, generation = true) {
    const cle = `${ageDebut}|${anneeDebut}|${sexe}|${generation}`;
    const memorisee = this._courbes.get(cle);
    if (memorisee !== undefined) {
      return memorisee;
    }

    const probabilites = [1.0];
    let courante = 1.0;
    let duree = 0;
    while (ageDebut + duree < AGE_TERMINAL && courante > 1e-10) {
      // Table du moment : la mortalité de l'année de liquidation est appliquée
      // à tous les âges. Table de génération : chaque année vécue reçoit celle
      // de l'année civile correspondante. Dans les deux cas les quotients
      // OBSERVÉS priment là où ils existent — la table du moment les ignorait,
      // si bien qu'elle ne décrivait pas la même mortalité que celle du calcul
      // par défaut.
      const anneeLue = generation ? anneeDebut + duree : anneeDebut;
      courante *= this.survieAnnuelle(ageDebut + duree, anneeLue, sexe);
      probabilites.push(courante);
      duree += 1;
    }
    this._courbes.set(cle, probabilites);
    return probabilites;
  }

  /**
   * Courbe de survie moyenne pondérée des deux sexes.
   *
   * On moyenne les FONCTIONS DE SURVIE, pas les espérances : c'est la
   * pondération correcte pour une rente servie indifféremment aux hommes et aux
   * femmes à partir d'un même capital notionnel.
   */
  courbeSurvieUnisexe(ageDebut, anneeDebut, generation = true) {
    const cle = `unisexe|${ageDebut}|${anneeDebut}|${generation}`;
    const memorisee = this._courbes.get(cle);
    if (memorisee !== undefined) {
      return memorisee;
    }
    const [poidsH, poidsF] = this.poidsUnisexe;
    const ch = this.courbeSurvie(ageDebut, anneeDebut, "H", generation);
    const cf = this.courbeSurvie(ageDebut, anneeDebut, "F", generation);
    const longueur = Math.max(ch.length, cf.length);
    const courbe = [];
    for (let t = 0; t < longueur; t += 1) {
      courbe.push(poidsH * (t < ch.length ? ch[t] : 0.0)
        + poidsF * (t < cf.length ? cf[t] : 0.0));
    }
    this._courbes.set(cle, courbe);
    return courbe;
  }

  /** Courbe de survie, unisexe si ``sexe`` vaut ``null``. */
  courbe(ageDebut, anneeDebut, sexe, generation = true) {
    if (sexe === null || sexe === undefined) {
      return this.courbeSurvieUnisexe(ageDebut, anneeDebut, generation);
    }
    return this.courbeSurvie(ageDebut, anneeDebut, sexe, generation);
  }

  survie(ageDebut, anneeDebut, duree, sexe, generation = true) {
    const courbe = this.courbeSurvie(ageDebut, anneeDebut, sexe, generation);
    return duree < courbe.length ? courbe[duree] : 0.0;
  }

  /** Espérance de vie résiduelle en années, table de génération par défaut. */
  esperanceResiduelle(age, annee, sexe = null, generation = true) {
    const courbe = this.courbe(age, annee, sexe, generation);
    let total = 0.0;
    for (let t = 0; t < courbe.length - 1; t += 1) {
      total += 0.5 * (courbe[t] + courbe[t + 1]);
    }
    return total;
  }

  fiabilite(annee) {
    return Math.min(this.loi(annee, "H").fiabilite, this.loi(annee, "F").fiabilite);
  }
}
