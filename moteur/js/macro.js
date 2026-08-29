/**
 * Séries macroéconomiques : prix, salaires, productivité, plafond.
 *
 * Portage de ``src/retraite_notionnelle/donnees/macro.py``. Au-delà de la
 * dernière année observée, les séries sont prolongées par le scénario de
 * projection choisi et non par la dernière valeur connue ; les années projetées
 * portent la fiabilité la plus basse, ce qui se propage jusqu'au résultat.
 */

import { Fiabilite, SerieAnnuelle } from "./serie.js";

/**
 * Première année où les salaires portés au compte sont revalorisés sur les
 * PRIX et non plus sur les salaires. Avant elle, les arrêtés annuels de
 * revalorisation suivaient l'évolution des salaires ; à partir de 1987 ils
 * suivent celle des prix, ce que la loi du 22 juillet 1993 a ensuite inscrit
 * dans le code en retenant l'indice hors tabac.
 */
export const ANNEE_REVALORISATION_SUR_LES_PRIX = 1987;

export class DonneesMacro {
  constructor(paquet, scenarioProjection = null) {
    this.paquet = paquet;
    this.scenarioProjection = scenarioProjection;

    const hypotheses = paquet.hypotheses;
    const nom = scenarioProjection || hypotheses.scenario_par_defaut;
    const scenarios = hypotheses.scenarios || {};
    if (!(nom in scenarios)) {
      throw new Error(
        `scénario de projection inconnu : ${nom}. Disponibles : `
        + Object.keys(scenarios).sort().join(", "),
      );
    }
    this.projection = {
      ...scenarios[nom],
      code: nom,
      fin: Number(hypotheses.annee_fin_projection ?? 2100),
    };

    const serie = (cle) => SerieAnnuelle.depuisPaquet(cle, paquet.series[cle]);
    const prolonger = (s, cle) => s.prolongee(Number(this.projection[cle]), this.projection.fin);

    this.inflation = prolonger(serie("inflation"), "inflation");
    this.salaire_moyen = prolonger(serie("salaire_moyen"), "salaire_moyen_nominal");
    this.productivite = prolonger(serie("productivite"), "productivite_reelle");
    this.plafond_securite_sociale = this._plafond(serie("pass"), hypotheses);
    this.smic_horaire = this._prolongeParSalaire(serie("smic_horaire"), "smic_horaire");
    this.heures_par_trimestre = serie("heures_par_trimestre");

    this._coefficientsPrix = new Map();
    this._coefficientsSalaires = new Map();
  }

  /**
   * Prolonge une série de niveau par la croissance du salaire moyen.
   *
   * C'est l'indexation légale du SMIC, à laquelle s'ajoutent des coups de
   * pouce que le modèle ne prétend pas anticiper.
   */
  _prolongeParSalaire(serie, nom) {
    const annees = serie.annees.slice();
    const valeurs = serie.valeurs.slice();
    const fiabilites = serie.fiabilites.slice();
    let courant = serie.valeur(serie.derniereAnnee);
    const croissance = Number(this.projection.salaire_moyen_nominal);
    for (let annee = serie.derniereAnnee + 1; annee <= this.projection.fin; annee += 1) {
      courant *= 1 + croissance;
      annees.push(annee);
      valeurs.push(courant);
      fiabilites.push(Fiabilite.ESTIMEE);
    }
    return new SerieAnnuelle(annees, valeurs, fiabilites, nom, "escalier");
  }

  /**
   * Trimestres qu'un revenu d'activité valide dans l'année.
   *
   * Quatre au plus, et zéro si le revenu n'atteint pas le seuil du premier.
   * Avant 1972, aucun seuil de montant n'existait : une année travaillée vaut
   * quatre trimestres.
   */
  trimestresValides(revenu, annee) {
    if (revenu <= 0) {
      return 0;
    }
    if (annee < this.heures_par_trimestre.premiereAnnee) {
      return 4;
    }
    const seuil = this.heures_par_trimestre.valeur(annee) * this.smic_horaire.valeur(annee);
    if (seuil <= 0) {
      return 4;
    }
    return Math.max(0, Math.min(4, Math.floor(revenu / seuil)));
  }

  /**
   * Plafond annuel de la Sécurité sociale, en euros courants.
   *
   * Au-delà de la dernière valeur publiée, le plafond suit la croissance du
   * salaire moyen, conformément à l'article L. 241-3 du code de la sécurité
   * sociale.
   */
  _plafond(serie, hypotheses) {
    if (hypotheses.plafond_suit_salaire_moyen === false) {
      return serie;
    }
    const annees = serie.annees.slice();
    const valeurs = serie.valeurs.slice();
    const fiabilites = serie.fiabilites.slice();
    let courant = serie.valeur(serie.derniereAnnee);
    const croissance = Number(this.projection.salaire_moyen_nominal);
    for (let annee = serie.derniereAnnee + 1; annee <= this.projection.fin; annee += 1) {
      courant *= 1 + croissance;
      annees.push(annee);
      valeurs.push(courant);
      fiabilites.push(Fiabilite.ESTIMEE);
    }
    return new SerieAnnuelle(annees, valeurs, fiabilites, "pass", "escalier");
  }

  // -- grandeurs dérivées ----------------------------------------------------

  /** Croissance réelle du salaire moyen : (1+w)/(1+π) - 1. */
  salaireMoyenReel(annee) {
    return (1 + this.salaire_moyen.valeur(annee)) / (1 + this.inflation.valeur(annee)) - 1;
  }

  /** Productivité réelle ramenée en nominal : (1+ρ)(1+π) - 1. */
  productiviteNominale(annee) {
    return (1 + this.productivite.valeur(annee)) * (1 + this.inflation.valeur(annee)) - 1;
  }

  /**
   * Coefficient de passage d'euros de ``depart`` en euros de ``arrivee``.
   *
   * Sert à exprimer tous les résultats dans une unité comparable — sans quoi
   * confronter une pension liquidée en 1975 à une pension de 2026 n'a aucun
   * sens.
   */
  coefficientPrix(depart, arrivee) {
    if (arrivee === depart) {
      return 1.0;
    }
    if (arrivee > depart) {
      const cle = `${depart}|${arrivee}`;
      const memorise = this._coefficientsPrix.get(cle);
      if (memorise !== undefined) {
        return memorise;
      }
      let coefficient = 1.0;
      for (let annee = depart + 1; annee <= arrivee; annee += 1) {
        coefficient *= 1 + this.inflation.valeur(annee);
      }
      this._coefficientsPrix.set(cle, coefficient);
      return coefficient;
    }
    return 1.0 / this.coefficientPrix(arrivee, depart);
  }

  /**
   * Coefficient de passage par le SMIC, d'une année à l'autre.
   *
   * Plusieurs montants du droit positif ne suivent ni les prix ni les salaires
   * mais le SALAIRE MINIMUM DE CROISSANCE : le plafond d'écrêtement du minimum
   * contributif depuis février 2014, les deux montants du minimum lui-même
   * depuis la réforme du 14 avril 2023.
   */
  coefficientSmic(depart, arrivee) {
    const valeurDepart = this.smic_horaire.valeur(depart);
    return valeurDepart > 0 ? this.smic_horaire.valeur(arrivee) / valeurDepart : 1.0;
  }

  /**
   * Revalorisation d'un salaire porté au compte, de ``depart`` à ``arrivee``.
   *
   * Ce n'est pas l'indice des prix. Les salaires inscrits au compte sont
   * revalorisés par un coefficient fixé chaque année par arrêté, et cet arrêté
   * a suivi les SALAIRES jusqu'en 1986 avant de suivre les prix. Sur les
   * Trente Glorieuses l'écart est massif : appliquer la règle des prix à ces
   * années-là ramenait au compte des salaires très en dessous de ce que le
   * droit y a réellement inscrit.
   */
  coefficientRevalorisationSalaires(depart, arrivee) {
    if (arrivee === depart) {
      return 1.0;
    }
    if (arrivee < depart) {
      return 1.0 / this.coefficientRevalorisationSalaires(arrivee, depart);
    }
    const cle = `${depart}|${arrivee}`;
    const memorise = this._coefficientsSalaires.get(cle);
    if (memorise !== undefined) {
      return memorise;
    }
    let coefficient = 1.0;
    for (let annee = depart + 1; annee <= arrivee; annee += 1) {
      coefficient *= 1 + (annee >= ANNEE_REVALORISATION_SUR_LES_PRIX
        ? this.inflation.valeur(annee)
        : this.salaire_moyen.valeur(annee));
    }
    this._coefficientsSalaires.set(cle, coefficient);
    return coefficient;
  }

  /** Fiabilité du maillon le plus faible des séries macro sur la plage. */
  fiabiliteSur(debut, fin) {
    return Math.min(
      this.inflation.fiabiliteMinimaleSur(debut, fin),
      this.salaire_moyen.fiabiliteMinimaleSur(debut, fin),
      this.productivite.fiabiliteMinimaleSur(debut, fin),
    );
  }
}
