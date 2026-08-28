/**
 * Séries annuelles et niveaux de fiabilité.
 *
 * Portage de ``src/retraite_notionnelle/donnees/chargement.py``. Principe
 * inchangé : aucune valeur ne circule dans le modèle sans son niveau de
 * fiabilité, et une valeur interpolée n'est jamais « certifiée ».
 */

/** Niveau de certification d'une donnée, du plus faible au plus fort. */
export const Fiabilite = Object.freeze({
  ESTIMEE: 0,
  MOYENNE: 1,
  HAUTE: 2,
  CERTIFIEE: 3,
});

const NOMS_FIABILITE = ["estimee", "moyenne", "haute", "certifiee"];

export function nomFiabilite(niveau) {
  return NOMS_FIABILITE[niveau];
}

export function fiabiliteDepuisTexte(texte) {
  const cle = String(texte ?? "").trim().toLowerCase();
  const correspondance = {
    estimee: Fiabilite.ESTIMEE,
    estimée: Fiabilite.ESTIMEE,
    projetee: Fiabilite.ESTIMEE,
    projetée: Fiabilite.ESTIMEE,
    moyenne: Fiabilite.MOYENNE,
    haute: Fiabilite.HAUTE,
    certifiee: Fiabilite.CERTIFIEE,
    certifiée: Fiabilite.CERTIFIEE,
  };
  if (!(cle in correspondance)) {
    throw new Error(`niveau de fiabilité inconnu : ${texte}`);
  }
  return correspondance[cle];
}

/** Levée quand la fiabilité disponible est inférieure à celle exigée. */
export class DonneeInsuffisante extends Error {}

/**
 * Série indexée par année, avec fiabilité et interpolation contrôlée.
 *
 * ``escalier`` — la valeur d'une année absente est celle de la dernière année
 * renseignée : c'est le comportement correct pour un paramètre juridique, qui
 * reste en vigueur jusqu'à sa modification. ``lineaire`` — interpolation entre
 * les deux années encadrantes, pour les grandeurs continues.
 */
export class SerieAnnuelle {
  /**
   * @param {number[]} annees années triées par ordre croissant
   * @param {number[]} valeurs valeur de chaque année
   * @param {number[]} fiabilites niveau de fiabilité de chaque année
   */
  constructor(annees, valeurs, fiabilites, nom, interpolation = "escalier") {
    if (annees.length === 0) {
      throw new Error(`série « ${nom} » vide`);
    }
    this.nom = nom;
    this.interpolation = interpolation;
    this.annees = annees;
    this.valeurs = valeurs;
    this.fiabilites = fiabilites;
    this.premiereAnnee = annees[0];
    this.derniereAnnee = annees[annees.length - 1];
  }

  static depuisPaquet(nom, brut) {
    return new SerieAnnuelle(
      brut.annees, brut.valeurs, brut.fiabilites, nom, brut.interpolation,
    );
  }

  /** Indice de la dernière année inférieure ou égale à ``annee``, ou -1. */
  _indice(annee) {
    let bas = 0;
    let haut = this.annees.length - 1;
    let trouve = -1;
    while (bas <= haut) {
      const milieu = (bas + haut) >> 1;
      if (this.annees[milieu] <= annee) {
        trouve = milieu;
        bas = milieu + 1;
      } else {
        haut = milieu - 1;
      }
    }
    return trouve;
  }

  /** Valeur et fiabilité d'une année, règle d'interpolation appliquée. */
  brut(annee) {
    const indice = this._indice(annee);
    if (indice >= 0 && this.annees[indice] === annee) {
      return { valeur: this.valeurs[indice], fiabilite: this.fiabilites[indice] };
    }
    if (annee < this.premiereAnnee) {
      return { valeur: this.valeurs[0], fiabilite: Fiabilite.ESTIMEE };
    }
    if (annee > this.derniereAnnee) {
      return {
        valeur: this.valeurs[this.valeurs.length - 1],
        fiabilite: Fiabilite.ESTIMEE,
      };
    }

    const avantValeur = this.valeurs[indice];
    const avantFiabilite = this.fiabilites[indice];
    if (this.interpolation === "escalier") {
      return { valeur: avantValeur, fiabilite: avantFiabilite };
    }

    const precedente = this.annees[indice];
    const suivante = this.annees[indice + 1];
    const poids = (annee - precedente) / (suivante - precedente);
    const valeur = avantValeur + poids * (this.valeurs[indice + 1] - avantValeur);
    // L'interpolation ne peut pas être plus fiable que ses bornes, et une
    // valeur interpolée n'est jamais « certifiée ».
    const fiabilite = Math.min(
      avantFiabilite, this.fiabilites[indice + 1], Fiabilite.HAUTE,
    );
    return { valeur, fiabilite };
  }

  valeur(annee, fiabiliteMinimale = Fiabilite.ESTIMEE) {
    const v = this.brut(annee);
    if (v.fiabilite < fiabiliteMinimale) {
      throw new DonneeInsuffisante(
        `série « ${this.nom} », année ${annee} : fiabilité `
        + `${nomFiabilite(v.fiabilite)} < minimum exigé `
        + `${nomFiabilite(fiabiliteMinimale)}`,
      );
    }
    return v.valeur;
  }

  fiabilite(annee) {
    return this.brut(annee).fiabilite;
  }

  /**
   * Nouvelle série prolongée par une valeur constante jusqu'à ``jusquA``.
   *
   * Sert à projeter au-delà de la dernière observation. Les années ajoutées
   * portent la fiabilité indiquée — jamais celle des années observées.
   */
  prolongee(valeur, jusquA, fiabilite = Fiabilite.ESTIMEE) {
    const annees = this.annees.slice();
    const valeurs = this.valeurs.slice();
    const fiabilites = this.fiabilites.slice();
    for (let annee = this.derniereAnnee + 1; annee <= jusquA; annee += 1) {
      annees.push(annee);
      valeurs.push(valeur);
      fiabilites.push(fiabilite);
    }
    return new SerieAnnuelle(annees, valeurs, fiabilites, this.nom, this.interpolation);
  }

  /** Maillon le plus faible sur une plage — c'est lui qui qualifie un résultat. */
  fiabiliteMinimaleSur(debut, fin) {
    let minimum = null;
    for (let annee = debut; annee <= fin; annee += 1) {
      const niveau = this.brut(annee).fiabilite;
      minimum = minimum === null ? niveau : Math.min(minimum, niveau);
    }
    return minimum === null ? Fiabilite.ESTIMEE : minimum;
  }
}
