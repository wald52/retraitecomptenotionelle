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
    revenu_reference = 0.0,
    familles_cotisantes = [],
    //: Des cotisations retraite ont-elles réellement été versées ? C'est le
    //: seul critère qui compte pour les comptes notionnels.
    cotisations_versees = true,
    //: Part de primes dans le revenu (fonction publique) : assiette du RAFP.
    part_primes = 0.0,
    //: Salaire forfaitaire porté au compte du régime de base au titre de
    //: l'assurance vieillesse des parents au foyer. Ce n'est pas un revenu
    //: d'activité — l'année n'est pas cotisée par l'assuré — mais la CNAF
    //: cotise pour lui sur cette assiette, et le salaire entre dans le salaire
    //: annuel moyen. Une période assimilée, elle, n'y entre jamais.
    revenu_avpf = 0.0,
  }) {
    Object.assign(this, {
      annee, revenu, affiliation, type_periode, quotite,
      trimestres_valides, cotisations_versees, part_primes,
      revenu_reference, familles_cotisantes, revenu_avpf,
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

  /**
   * Trimestres validés au sens du droit en vigueur, tous régimes.
   *
   * Bornés à l'année de liquidation : une ligne postérieure décrit une activité
   * exercée APRÈS le départ, et le droit ne la fait pas entrer dans la durée
   * d'assurance qui commande la décote.
   */
  get trimestresActuels() {
    const borne = this.age_liquidation === null || this.age_liquidation === undefined
      ? null
      : this.anneeLiquidation;
    return this.lignes.reduce(
      (total, ligne) => (borne === null || ligne.annee < borne
        ? total + ligne.trimestres_valides
        : total),
      0,
    );
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
      const motifs = macro.paquet.periodes_non_travaillees ?? {};
      const regle = cotise ? null : (motifs[typePeriode] ?? motifs.sans_activite ?? null);
      const ouvreComplementaires = regle !== null && regle[1] === true;
      const ouvreAvpf = regle !== null && regle[3] === true;
      lignes.push(new AnneeCarriere({
        annee,
        revenu: cotise ? revenu : 0.0,
        affiliation,
        type_periode: typePeriode,
        // Un trimestre s'acquiert par un montant cotisé — 150 fois le SMIC
        // horaire depuis 2014, 200 avant. Les périodes assimilées en valident
        // quatre sans condition de montant : c'est tout leur objet.
        trimestres_valides: cotise
          ? macro.trimestresValides(revenu, annee)
          : (regle !== null ? regle[0] : 4),
        // Pendant une période indemnisée, l'UNEDIC ou la Sécurité sociale
        // versent de vraies cotisations aux régimes complémentaires, assises
        // sur le salaire d'avant.
        revenu_reference: ouvreComplementaires ? revenu : 0.0,
        familles_cotisantes: ouvreComplementaires ? ["complementaire_prive"] : [],
        cotisations_versees: cotise,
        part_primes,
        // Assurance vieillesse des parents au foyer : la CNAF cotise au régime
        // général sur une assiette forfaitaire égale au SMIC — 1 820 heures,
        // soit le SMIC mensuel multiplié par douze.
        revenu_avpf: (!cotise && ouvreAvpf)
          ? 1820.0 * macro.smic_horaire.valeur(annee)
          : 0.0,
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
