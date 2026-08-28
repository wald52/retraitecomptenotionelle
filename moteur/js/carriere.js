/**
 * Description d'une carrière individuelle.
 *
 * Portage de ``src/retraite_notionnelle/carriere.py``. Deux niveaux d'entrée :
 * une ligne par année, telle qu'on la lit sur un relevé de carrière, ou un
 * profil — statut, âges de début et de fin, niveau de rémunération.
 */

import { arrondi } from "./format.js";

/**
 * Périodes non cotisées reconnues par le système actuel. Elles ouvrent des
 * droits gratuits aujourd'hui ; elles n'en ouvrent aucun dans les scénarios
 * notionnels, sauf si des cotisations ont réellement été versées.
 */
export const PERIODES_NON_COTISEES = new Set([
  "chomage_indemnise",
  "chomage_non_indemnise",
  "maladie",
  "invalidite",
  "maternite",
  "education_enfant",
  "service_militaire",
  "inactivite",
  "etudes",
]);

/** Une année de carrière. */
export class AnneeCarriere {
  constructor({
    annee,
    //: Revenu d'activité brut, EN EUROS COURANTS DE CETTE ANNÉE-LÀ.
    revenu,
    affiliation,
    type_periode = "emploi",
    quotite = 1.0,
    //: Trimestres validés au sens du système ACTUEL.
    trimestres_valides = 4,
    //: Des cotisations retraite ont-elles réellement été versées ? C'est le
    //: seul critère qui compte pour les comptes notionnels.
    cotisations_versees = true,
    //: Part de primes dans le revenu (fonction publique) : assiette du RAFP.
    part_primes = 0.0,
  }) {
    Object.assign(this, {
      annee, revenu, affiliation, type_periode, quotite,
      trimestres_valides, cotisations_versees, part_primes,
    });
  }

  get cotise() {
    return this.cotisations_versees && this.revenu > 0;
  }
}

/** Carrière complète d'un assuré. */
export class Carriere {
  constructor({
    annee_naissance,
    sexe,
    lignes = [],
    //: Âge de liquidation effectif (réel pour un retraité, souhaité sinon).
    age_liquidation = null,
    //: Sans effet notionnel : utilisé par le seul scénario « système actuel ».
    nombre_enfants = 0,
    identifiant = "assuré",
  }) {
    if (sexe !== "H" && sexe !== "F") {
      throw new Error(`sexe attendu 'H' ou 'F', reçu ${sexe}`);
    }
    this.annee_naissance = annee_naissance;
    this.sexe = sexe;
    this.lignes = [...lignes].sort((a, b) => a.annee - b.annee);
    this.age_liquidation = age_liquidation;
    this.nombre_enfants = nombre_enfants;
    this.identifiant = identifiant;
    this._parAnnee = new Map(this.lignes.map((ligne) => [ligne.annee, ligne]));
  }

  // -- dates -----------------------------------------------------------------

  get premiereAnnee() {
    return Math.min(...this.lignes.map((ligne) => ligne.annee));
  }

  get derniereAnnee() {
    return Math.max(...this.lignes.map((ligne) => ligne.annee));
  }

  get anneeLiquidation() {
    if (this.age_liquidation === null) {
      throw new Error(`${this.identifiant} : âge de liquidation non renseigné`);
    }
    return arrondi(this.annee_naissance + this.age_liquidation);
  }

  ageEn(annee) {
    return annee - this.annee_naissance;
  }

  // -- agrégats --------------------------------------------------------------

  get anneesCotisees() {
    return this.lignes.filter((ligne) => ligne.cotise).map((ligne) => ligne.annee);
  }

  /** Trimestres validés au sens du droit en vigueur, tous régimes. */
  get trimestresActuels() {
    return this.lignes.reduce((total, ligne) => total + ligne.trimestres_valides, 0);
  }

  ligne(annee) {
    return this._parAnnee.get(annee) ?? null;
  }

  affiliationsUtilisees() {
    return [...new Set(this.lignes.map((ligne) => ligne.affiliation))];
  }

  // -- constructeurs ---------------------------------------------------------

  /**
   * Construit une carrière à partir de quelques paramètres.
   *
   * ``niveauSalaire`` s'exprime en multiples du salaire moyen par tête de
   * l'année considérée : 1,0 = salaire moyen, 0,6 ≈ niveau du SMIC. Ce choix
   * d'unité évite d'avoir à convertir des francs de 1975 en euros.
   *
   * ``profilCarriere`` décrit la déformation du salaire relatif au cours de la
   * vie active ; ``interruptions`` associe une année à une période non cotisée.
   */
  static depuisProfil({
    annee_naissance,
    sexe,
    affiliation,
    age_debut,
    age_liquidation,
    macro,
    niveau_salaire = 1.0,
    profil_carriere = "plat",
    interruptions = null,
    nombre_enfants = 0,
    part_primes = 0.0,
    identifiant = "assuré",
  }) {
    const anneeDebut = arrondi(annee_naissance + age_debut);
    const anneeFin = arrondi(annee_naissance + age_liquidation) - 1;
    if (anneeFin < anneeDebut) {
      throw new Error("âge de liquidation antérieur à l'âge de début d'activité");
    }

    const plages = interruptions || new Map();
    const duree = Math.max(anneeFin - anneeDebut, 1);
    const salaireMoyen = indiceSalaireMoyen(macro, anneeDebut, anneeFin);

    const lignes = [];
    for (let annee = anneeDebut; annee <= anneeFin; annee += 1) {
      const avancement = (annee - anneeDebut) / duree;
      const revenu = niveau_salaire * deformation(profil_carriere, avancement)
        * salaireMoyen.get(annee);

      const typePeriode = plages.get(annee) ?? "emploi";
      const cotise = typePeriode === "emploi";
      lignes.push(new AnneeCarriere({
        annee,
        revenu: cotise ? revenu : 0.0,
        affiliation,
        type_periode: typePeriode,
        trimestres_valides: 4,
        cotisations_versees: cotise,
        part_primes,
      }));
    }

    return new Carriere({
      annee_naissance, sexe, lignes, age_liquidation, nombre_enfants, identifiant,
    });
  }
}

function deformation(profil, avancement) {
  if (profil === "plat") {
    return 1.0;
  }
  if (profil === "ascendant") {
    // Profil ouvrier/employé : de 60 % à 130 % du niveau cible.
    return 0.6 + 0.7 * avancement;
  }
  if (profil === "fortement_ascendant") {
    // Profil cadre : de 50 % à 190 %.
    return 0.5 + 1.4 * avancement;
  }
  throw new Error(`profil de carrière inconnu : ${profil}`);
}

/**
 * Salaire moyen par tête reconstitué en euros courants de chaque année.
 *
 * La série de comptes nationaux ne donne que des TAUX DE CROISSANCE. On les
 * cumule à partir d'un point d'ancrage : le salaire moyen par tête du secteur
 * privé en 2024, arrondi à 40 000 € bruts annuels. Ce point d'ancrage est un
 * paramètre documenté, pas une donnée certifiée — il déplace proportionnellement
 * tous les revenus reconstitués, donc toutes les pensions, mais il est sans
 * effet sur les RAPPORTS entre scénarios, qui sont l'objet du modèle.
 */
export function indiceSalaireMoyen(macro, debut, fin) {
  const ancrageAnnee = 2024;
  const ancrageValeur = 40000.0;
  const valeurs = new Map([[ancrageAnnee, ancrageValeur]]);

  const borneHaute = Math.max(fin, ancrageAnnee);
  for (let annee = ancrageAnnee + 1; annee <= borneHaute; annee += 1) {
    valeurs.set(annee, valeurs.get(annee - 1) * (1 + macro.salaire_moyen.valeur(annee)));
  }

  const borneBasse = Math.min(debut, ancrageAnnee);
  for (let annee = ancrageAnnee - 1; annee >= borneBasse; annee -= 1) {
    valeurs.set(annee, valeurs.get(annee + 1) / (1 + macro.salaire_moyen.valeur(annee + 1)));
  }

  return valeurs;
}
