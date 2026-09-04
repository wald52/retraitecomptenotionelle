/**
 * Contenu des pages : formulaire, résultats, cas types, méthode, données.
 *
 * Portage de ``src/retraite_notionnelle/web/pages.py``. Le rendu doit être
 * identique à celui de la référence Python au caractère près : c'est ce que
 * vérifient les témoins de ``tests/temoins/pages.json``.
 */

import { enMois, formaterAge } from "./calendrier.js";
import { CAS_TYPES, GENERATIONS, calculerCasTypes } from "./castypes.js";
import {
  AgeConversionDroitsAcquis, ModeAgeReference, ModeIndexation, PARAMETRES_DEFAUT, PartCotisation,
  TableConversion, avec, cleParametres,
} from "./config.js";
import { echapper, formatFixe, formatG } from "./format.js";
import * as g from "./gabarit.js";
import { nomFiabilite } from "./serie.js";
import { Simulateur } from "./simulateur.js";

export const PROFILS = [
  ["plat", "Plat — le salaire suit le salaire moyen"],
  ["ascendant", "Ascendant — profil employé/ouvrier"],
  ["fortement_ascendant", "Fortement ascendant — profil cadre"],
];

// La règle par défaut vient EN TÊTE : c'est celle que la simulation applique, et
// donc la première ligne du tableau « D'où vient l'écart ».
export const INDEXATIONS = [
  ["masse_salariale", "Masse salariale — règle d'équilibre (défaut)"],
  ["revalorisation_portee_au_compte", "Revalorisation réellement pratiquée (arrêtés Cnav)"],
  ["triple_lock_inverse", "Triple lock inversé (règle demandée)"],
  ["triple_lock_inverse_nominal", "Triple lock inversé, tout en nominal"],
  ["mediane_trois_taux", "Médiane des trois taux"],
  ["moyenne_trois_taux", "Moyenne des trois taux"],
  ["pib_nominal", "PIB nominal (assiette la plus large)"],
  ["prix", "Prix"],
  ["salaires", "Salaire moyen"],
];

// Fenêtre de lissage maximale acceptée par le formulaire, en années. La fenêtre
// se saisit librement — 1 pour aucun lissage, 5 pour la règle italienne. La
// borne est un garde-fou de sens, pas une limite du moteur : au-delà d'une
// trentaine d'années la moyenne couvre presque toute une carrière, et ce n'est
// plus un lissage mais un taux fixe reconstitué.
export const LISSAGE_MAXIMUM = 30;

export const AGES_REFERENCE = [
  ["cliquet_legal", "Cliquet légal (défaut)"],
  ["cliquet_puis_esperance_vie", "Cliquet puis espérance de vie"],
  ["legal_sans_cliquet", "Âge légal, sans cliquet"],
];

export const TABLES = [["unisexe", "Unisexe (défaut)"], ["par_sexe", "Par sexe"]];

export const PARTS_COTISATION = [
  ["salariale", "Part salariale seule (défaut)"],
  ["totale", "Salariale et patronale"],
  ["totale_alignee", "Salariale et patronale, public aligné sur le privé"],
];

export const CONVERSIONS_ACQUIS = [
  ["reference", "À l'âge de référence (défaut)"],
  ["liquidation", "À l'âge de départ effectif"],
];

export const PROJECTIONS = [
  ["cor_central", "COR central"],
  ["cor_favorable", "COR favorable"],
  ["cor_defavorable", "COR défavorable"],
  ["stagnation", "Stagnation"],
];

/**
 * Mois de naissance. Le droit coupe deux générations en cours d'année — au
 * 1er juillet 1951, au 1er septembre 1961 — et l'âge à la liquidation ne se lit
 * qu'à partir de lui.
 */
export const MOIS_NAISSANCE = [
  ["1", "janvier"], ["2", "février"], ["3", "mars"], ["4", "avril"],
  ["5", "mai"], ["6", "juin"], ["7", "juillet"], ["8", "août"],
  ["9", "septembre"], ["10", "octobre"], ["11", "novembre"], ["12", "décembre"],
];

/** Mois qui s'ajoutent aux années entières d'un âge. */
export const MOIS_AGE = Array.from({ length: 12 }, (unused, m) => [
  String(m), m === 0 ? "0 mois" : `${m} mois`,
]);

/** Saisie inexploitable, à afficher telle quelle à l'utilisateur. */
export class ErreurSaisie extends Error {}

const DEFAUTS = Object.freeze({
  naissance: 1975,
  naissance_mois: 1,
  sexe: "H",
  statut: "salarie_prive_non_cadre",
  debut: 21,
  liquidation: 64,
  salaire: 1.0,
  profil: "ascendant",
  primes: 0.0,
  enfants: 0,
  interruptions: "",
  indexation: "masse_salariale",
  lissage: 1,
  age_reference: "cliquet_legal",
  table: "unisexe",
  conversion_acquis: "reference",
  part_cotisation: "salariale",
  projection: "cor_central",
  bascule: 2026,
  euros: 2026,
  //: Vrai si la requête portait des paramètres, donc s'il faut calculer.
  demandee: false,
});

/** Paramètres d'une simulation, tels que l'utilisateur les a saisis. */
export class Saisie {
  constructor(champs = {}) {
    Object.assign(this, DEFAUTS, champs);
  }

  static depuisRequete(parametres) {
    const saisie = new Saisie({
      naissance: entier(parametres, "naissance", DEFAUTS.naissance),
      naissance_mois: entier(parametres, "naissance_mois", DEFAUTS.naissance_mois),
      sexe: parametres.sexe === "F" ? "F" : "H",
      statut: parametres.statut || DEFAUTS.statut,
      debut: ageSaisi(parametres, "debut", DEFAUTS.debut),
      liquidation: ageSaisi(parametres, "liquidation", DEFAUTS.liquidation),
      salaire: reel(parametres, "salaire", DEFAUTS.salaire),
      profil: parmi(parametres, "profil", PROFILS, DEFAUTS.profil),
      primes: reel(parametres, "primes", DEFAUTS.primes),
      enfants: entier(parametres, "enfants", DEFAUTS.enfants),
      interruptions: (parametres.interruptions || "").trim(),
      indexation: parmi(parametres, "indexation", INDEXATIONS, DEFAUTS.indexation),
      lissage: entier(parametres, "lissage", DEFAUTS.lissage),
      age_reference: parmi(parametres, "age_reference", AGES_REFERENCE, DEFAUTS.age_reference),
      table: parmi(parametres, "table", TABLES, DEFAUTS.table),
      conversion_acquis: parmi(
        parametres, "conversion_acquis", CONVERSIONS_ACQUIS, DEFAUTS.conversion_acquis,
      ),
      part_cotisation: parmi(
        parametres, "part_cotisation", PARTS_COTISATION,
        DEFAUTS.part_cotisation,
      ),
      projection: parmi(parametres, "projection", PROJECTIONS, DEFAUTS.projection),
      bascule: entier(parametres, "bascule", DEFAUTS.bascule),
      euros: entier(parametres, "euros", DEFAUTS.euros),
      demandee: Object.keys(parametres).length > 0,
    });
    saisie.verifier();
    return saisie;
  }

  verifier() {
    if (!(this.naissance_mois >= 1 && this.naissance_mois <= 12)) {
      throw new ErreurSaisie("Mois de naissance attendu entre 1 et 12.");
    }
    if (!(this.naissance >= 1900 && this.naissance <= 2020)) {
      throw new ErreurSaisie(
        `Année de naissance hors du champ du modèle : ${this.naissance}. `
        + "Attendu entre 1900 et 2020.",
      );
    }
    if (!(this.debut >= 14 && this.debut <= 40)) {
      throw new ErreurSaisie("Âge de début d'activité attendu entre 14 et 40 ans.");
    }
    if (!(this.liquidation >= 40 && this.liquidation <= 75)) {
      throw new ErreurSaisie("Âge de liquidation attendu entre 40 et 75 ans.");
    }
    if (this.liquidation <= this.debut) {
      throw new ErreurSaisie(
        "L'âge de liquidation doit être postérieur à l'âge de début d'activité.",
      );
    }
    if (!(this.salaire >= 0.1 && this.salaire <= 10)) {
      throw new ErreurSaisie(
        "Niveau de revenu attendu entre 0,1 et 10 fois le salaire moyen.",
      );
    }
    if (!(this.primes >= 0 && this.primes <= 0.6)) {
      throw new ErreurSaisie("Part de primes attendue entre 0 et 0,6.");
    }
    if (!(this.lissage >= 1 && this.lissage <= LISSAGE_MAXIMUM)) {
      throw new ErreurSaisie(
        `Fenêtre de lissage attendue entre 1 et ${LISSAGE_MAXIMUM} ans `
        + "(1 = aucun lissage).",
      );
    }
  }

  parametres(base) {
    return avec(base, {
      mode_indexation: ModeIndexation[cleEnum(ModeIndexation, this.indexation)],
      lissage_indexation: this.lissage,
      mode_age_reference: ModeAgeReference[cleEnum(ModeAgeReference, this.age_reference)],
      table_conversion: TableConversion[cleEnum(TableConversion, this.table)],
      age_conversion_droits_acquis:
        AgeConversionDroitsAcquis[cleEnum(AgeConversionDroitsAcquis, this.conversion_acquis)],
      part_cotisation: PartCotisation[
        cleEnum(PartCotisation, this.part_cotisation)],
      scenario_projection: this.projection,
      annee_bascule: this.bascule,
      annee_euros_constants: this.euros,
    });
  }

  /** « 1995:1999:education_enfant, 2003:2004:chomage » -> Map année → motif. */
  interruptionsAnalysees() {
    const plages = new Map();
    for (const brut of this.interruptions.replace(/\n/g, ",").split(",")) {
      const morceau = brut.trim();
      if (!morceau) {
        continue;
      }
      const parties = morceau.split(":");
      const [debut, fin, motif] = parties;
      if (parties.length !== 3 || !estEntier(debut) || !estEntier(fin)) {
        throw new ErreurSaisie(
          `Interruption mal formée : « ${morceau} ». Attendu `
          + "« année_début:année_fin:motif », par exemple "
          + "1995:1999:education_enfant.",
        );
      }
      for (let annee = Number(debut); annee <= Number(fin); annee += 1) {
        plages.set(annee, motif.trim());
      }
    }
    return plages;
  }

  /** Mois qui s'ajoutent aux années entières de l'âge de départ. */
  get liquidation_mois() {
    return enMois(this.liquidation) % 12;
  }

  get debut_mois() {
    return enMois(this.debut) % 12;
  }

  requete(remplacements = {}) {
    const champs = {
      naissance: this.naissance, naissance_mois: this.naissance_mois,
      sexe: this.sexe, statut: this.statut,
      // L'âge s'écrit en années ENTIÈRES et en mois : « 64 ans et sept mois »
      // plutôt que « 64,583333 ». L'adresse reste lisible, et une ancienne
      // adresse portant un âge décimal reste comprise.
      debut: Math.floor(enMois(this.debut) / 12), debut_mois: this.debut_mois,
      liquidation: Math.floor(enMois(this.liquidation) / 12),
      liquidation_mois: this.liquidation_mois,
      salaire: nombreBrut(this.salaire), profil: this.profil,
      primes: nombreBrut(this.primes), enfants: this.enfants,
      interruptions: this.interruptions, indexation: this.indexation,
      lissage: this.lissage,
      age_reference: this.age_reference, table: this.table,
      conversion_acquis: this.conversion_acquis,
      part_cotisation: this.part_cotisation,
      projection: this.projection, bascule: this.bascule, euros: this.euros,
      ...remplacements,
    };
    return Object.entries(champs)
      .map(([cle, valeur]) => `${encodeURIComponent(cle).replace(/%20/g, "+")}`
        + `=${encodeURIComponent(String(valeur)).replace(/%20/g, "+")}`)
      .join("&");
  }
}

function cleEnum(enumeration, valeur) {
  const cle = Object.keys(enumeration).find((nom) => enumeration[nom] === valeur);
  if (cle === undefined) {
    throw new ErreurSaisie(`valeur inconnue : ${valeur}`);
  }
  return cle;
}

const NOMBRE = /^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/;

function versFlottant(texte) {
  const propre = String(texte).trim();
  if (!NOMBRE.test(propre)) {
    return null;
  }
  return Number(propre);
}

function estEntier(texte) {
  return /^\s*[+-]?\d+\s*$/.test(String(texte ?? ""));
}

function entier(parametres, nom, defaut) {
  const valeur = parametres[nom];
  if (valeur === undefined || valeur === null || valeur === "") {
    return defaut;
  }
  const flottant = versFlottant(valeur);
  if (flottant === null) {
    throw new ErreurSaisie(`« ${nom} » doit être un nombre entier (reçu : ${valeur}).`);
  }
  return Math.trunc(flottant);
}

function reel(parametres, nom, defaut) {
  const valeur = parametres[nom];
  if (valeur === undefined || valeur === null || valeur === "") {
    return defaut;
  }
  const flottant = versFlottant(String(valeur).replace(/,/g, "."));
  if (flottant === null) {
    throw new ErreurSaisie(`« ${nom} » doit être un nombre (reçu : ${valeur}).`);
  }
  return flottant;
}

function parmi(parametres, nom, options, defaut) {
  const valeur = parametres[nom];
  return options.some(([code]) => code === valeur) ? valeur : defaut;
}

/** Valeur telle qu'elle est réinjectée dans un champ de formulaire. */
function nombreBrut(valeur) {
  return formatG(valeur);
}

/**
 * Âge lu en années entières plus un nombre de mois.
 *
 * Le formulaire envoie deux champs — `liquidation` et `liquidation_mois` —, et
 * l'adresse les porte tous deux. Une adresse ancienne ne portant qu'un âge
 * décimal reste valide et vaut ce qu'elle a toujours valu.
 */
function ageSaisi(parametres, nom, defaut) {
  const annees = reel(parametres, nom, defaut);
  const cle = `${nom}_mois`;
  const brut = parametres[cle];
  if (brut === undefined || brut === null || brut === "") {
    return annees;
  }
  const mois = entier(parametres, cle, 0);
  if (!(mois >= 0 && mois <= 11)) {
    throw new ErreurSaisie(`« ${cle} » doit être compris entre 0 et 11 mois.`);
  }
  return Math.floor(annees) + mois / 12;
}

/**
 * Âge à la française, en ans et en mois : « 64 ans », « 64 ans et 9 mois ».
 *
 * Le modèle date la liquidation au mois : l'écrire « 64,75 » demanderait au
 * lecteur de multiplier par douze pour retrouver ce qu'il a saisi.
 */
function age(valeur) {
  return formaterAge(valeur);
}

// -- fabrique ----------------------------------------------------------------

/**
 * Simulateurs mémorisés par jeu de paramètres. Le chargement des données coûte
 * quelques dixièmes de seconde ; une simulation en coûte dix millisecondes.
 */
export class Contexte {
  constructor(paquet, base = PARAMETRES_DEFAUT) {
    this.paquet = paquet;
    this.base = base;
    this._instances = new Map();
  }

  simulateur(parametres = null) {
    const retenus = parametres || this.base;
    const cle = cleParametres(retenus);
    if (!this._instances.has(cle)) {
      this._instances.set(cle, new Simulateur(this.paquet, retenus));
    }
    return this._instances.get(cle);
  }

  simuler(saisie) {
    const simulateur = this.simulateur(saisie.parametres(this.base));
    if (!simulateur.affiliations.contient(saisie.statut)) {
      throw new ErreurSaisie(`Statut d'affiliation inconnu : « ${saisie.statut} ».`);
    }
    const carriere = simulateur.carriereSimple({
      annee_naissance: saisie.naissance,
      mois_naissance: saisie.naissance_mois,
      sexe: saisie.sexe,
      affiliation: saisie.statut,
      age_debut: saisie.debut,
      age_liquidation: saisie.liquidation,
      niveau_salaire: saisie.salaire,
      profil_carriere: saisie.profil,
      interruptions: saisie.interruptionsAnalysees(),
      nombre_enfants: saisie.enfants,
      part_primes: saisie.primes,
      identifiant: "assuré",
    });
    return simulateur.simuler(carriere);
  }
}

/** Titre de chaque page, dans l'ordre de la navigation. */
export const TITRES = {
  "/": "Simuler",
  "/cas-types": "Cas types",
  "/methode": "Méthode",
  "/donnees": "Données",
};

/**
 * Contenu d'une page : ``[titre, corps HTML]``. Les erreurs de saisie sont
 * rendues dans la page, jamais levées : une adresse mal formée doit afficher un
 * message, pas une trace d'exécution.
 */
export function rendre(contexte, chemin, parametres = null) {
  if (chemin === "/cas-types") {
    return [TITRES[chemin], casTypes(contexte)];
  }
  if (chemin === "/methode") {
    return [TITRES[chemin], methode(contexte)];
  }
  if (chemin === "/donnees") {
    return [TITRES[chemin], donnees(contexte)];
  }

  let saisie;
  try {
    saisie = Saisie.depuisRequete(parametres || {});
  } catch (erreur) {
    if (!(erreur instanceof ErreurSaisie)) {
      throw erreur;
    }
    return [TITRES["/"], presentation() + messageErreur(erreur.message)
      + formulaire(new Saisie({ demandee: false }), contexte)];
  }

  let corps = presentation() + formulaire(saisie, contexte);
  if (saisie.demandee) {
    try {
      corps += resultats(contexte, saisie);
    } catch (erreur) {
      // Saisie refusée, données insuffisantes, régime inconnu : le message est
      // rendu dans la page. Une adresse mal formée doit afficher une phrase,
      // pas une trace d'exécution.
      corps += messageErreur(erreur.message);
    }
  }
  return [TITRES["/"], corps];
}

export function statuts(contexte) {
  const affiliations = contexte.simulateur().affiliations;
  return affiliations.codes.map((code) => ({
    code, libelle: affiliations.libelle(code),
  }));
}

// -- fragments ---------------------------------------------------------------

function messageErreur(message) {
  return `<div class="erreur"><strong>Saisie refusée.</strong> ${echapper(message)}</div>`;
}

function presentation() {
  return `
<p class="chapeau">Ce simulateur calcule, pour une même carrière, ce que verse le
système de retraite français tel qu'il est, et ce que verserait un système
en <strong>comptes notionnels</strong> — pension strictement proportionnelle aux
cotisations versées, divisée par l'espérance de vie restante à la liquidation —
appliqué de deux façons : <strong>rétroactivement</strong> depuis 1941, ou
seulement <strong>à compter de 2026</strong>.</p>

<div class="note"><strong>À lire avant les chiffres.</strong> Le scénario
rétroactif n'est pas une proposition de réforme : c'est un contrefactuel, qui
mesure ce qu'aurait produit une règle purement contributive appliquée depuis
l'origine de la répartition. L'essentiel de l'écart qu'il affiche vient de la
<a href="${g.lien("/methode", "indexation")}">règle d'indexation</a>, pas du passage aux comptes
notionnels — le simulateur permet de séparer les deux effets.</div>
`;
}

function formulaire(saisie, contexte) {
  const affiliations = contexte.simulateur().affiliations;
  const listeStatuts = affiliations.codes.map((code) => [code, affiliations.libelle(code)]);

  const principal = [
    g.champ("naissance", "Année de naissance", saisie.naissance, "", "number",
      { min: "1900", max: "2020", step: "1" }),
    g.liste("naissance_mois", "Mois de naissance", MOIS_NAISSANCE,
      String(saisie.naissance_mois),
      "deux générations sont coupées en cours d'année par les textes"),
    g.liste("sexe", "Sexe", [["H", "Homme"], ["F", "Femme"]], saisie.sexe,
      "table de mortalité unisexe par défaut"),
    g.liste("statut", "Statut d'affiliation", listeStatuts, saisie.statut),
    g.champ("debut", "Âge de début d'activité",
      Math.floor(enMois(saisie.debut) / 12), "", "number",
      { min: "14", max: "40", step: "1" }),
    g.liste("debut_mois", "…et mois", MOIS_AGE, String(saisie.debut_mois),
      "l'année d'entrée n'est complète que si l'on entre en janvier"),
    g.champ("liquidation", "Âge de départ à la retraite",
      Math.floor(enMois(saisie.liquidation) / 12),
      "effectif si retraité, souhaité si actif", "number",
      { min: "40", max: "75", step: "1" }),
    g.liste("liquidation_mois", "…et mois", MOIS_AGE,
      String(saisie.liquidation_mois),
      "la pension prend effet le premier du mois"),
    g.champ("salaire", "Niveau de revenu", nombreBrut(saisie.salaire),
      "en multiples du salaire moyen : 0,55 ≈ SMIC, 1 = salaire moyen", "number",
      { min: "0.1", max: "10", step: "0.05" }),
  ].join("");

  const avance = [
    g.liste("profil", "Profil de carrière", PROFILS, saisie.profil,
      "déformation du salaire relatif au fil de la carrière"),
    g.champ("primes", "Part de primes", nombreBrut(saisie.primes),
      "fonction publique : assiette du RAFP", "number",
      { min: "0", max: "0.6", step: "0.01" }),
    g.champ("enfants", "Nombre d'enfants", saisie.enfants,
      "sans effet notionnel : les majorations sont supprimées", "number",
      { min: "0", max: "12", step: "1" }),
    g.champ("interruptions", "Interruptions", saisie.interruptions,
      "« 1995:1999:education_enfant », séparées par des virgules"),
    g.liste("indexation", "Règle d'indexation", INDEXATIONS, saisie.indexation,
      "revalorisation des comptes et des pensions"),
    g.champ("lissage", "Lissage de l'indexation", saisie.lissage,
      "moyenne glissante sur la règle choisie, en années : 1 = aucun, "
      + "5 = comme l'Italie",
      "number", { min: "1", max: String(LISSAGE_MAXIMUM), step: "1" }),
    g.liste("age_reference", "Âge de référence", AGES_REFERENCE, saisie.age_reference),
    g.liste("table", "Table de conversion", TABLES, saisie.table),
    g.liste("part_cotisation", "Part de la cotisation portée au compte",
      PARTS_COTISATION, saisie.part_cotisation,
      "salariale seule, ou salariale et patronale"),
    g.liste("conversion_acquis", "Conversion des droits acquis",
      CONVERSIONS_ACQUIS, saisie.conversion_acquis,
      "âge auquel les droits figés à la bascule sont convertis"),
    g.liste("projection", "Scénario macroéconomique", PROJECTIONS, saisie.projection,
      "au-delà de la dernière observation"),
    g.champ("bascule", "Année de bascule", saisie.bascule,
      "passage au régime unique", "number", { min: "1941", max: "2070" }),
    g.champ("euros", "Euros constants de", saisie.euros, "", "number",
      { min: "1941", max: "2070" }),
  ].join("");

  return `
<form class="carte" method="get" action="${g.lien("/")}">
  <h2 style="margin-top:0">Simuler une carrière</h2>
  <div class="grille">${principal}</div>
  <details>
    <summary>Options de modélisation (profil, indexation, âge de référence, projection)</summary>
    <div class="grille">${avance}</div>
  </details>
  <p style="margin-top:1.4rem"><button type="submit">Calculer les cinq scénarios</button></p>
</form>
`;
}

function resultats(contexte, saisie) {
  const comparaison = contexte.simuler(saisie);
  const carriere = comparaison.carriere;
  const retro = comparaison.notionnel_retroactif;
  const ecart = retro.ecart_age;
  const conversion = retro.conversion;

  const constants = {
    actuel: comparaison.enEurosConstants(comparaison.actuel.pension_annuelle),
    retroactif: comparaison.enEurosConstants(retro.pension_annuelle),
    prospectif: comparaison.enEurosConstants(
      comparaison.notionnel_prospectif.pension_annuelle,
    ),
    "retroactif-employeur": comparaison.enEurosConstants(
      comparaison.notionnel_retroactif_employeur.pension_annuelle,
    ),
    "prospectif-employeur": comparaison.enEurosConstants(
      comparaison.notionnel_prospectif_employeur.pension_annuelle,
    ),
  };
  const reference = Math.max(...Object.values(constants)) || 1.0;

  const bloc = (cle, titre, glose, variation, tauxRemplacement) => {
    const montant = constants[cle];
    const variationHtml = variation === null
      ? '<span class="discret">référence</span>'
      : `<strong>${g.pourcentage(variation, true)}</strong>`;
    return `
<div class="scenario">
  <div class="entete">
    <span class="titre">${echapper(titre)}</span>
    <span class="montant">
      <span class="mensuel">${g.euros(montant / 12)}</span>
      <span class="discret">/ mois</span>
      <span class="annuel"> — ${g.euros(montant)} par an</span>
    </span>
  </div>
  <div class="barre ${cle}"><span style="width:${formatFixe(montant / reference * 100, 1)}%"></span></div>
  <div class="glose">${glose} · taux de remplacement
    ${g.pourcentage(tauxRemplacement)} · écart au système actuel : ${variationHtml}</div>
</div>`;
  };

  const scenarios = bloc("actuel", "1. Système actuel",
    "droit en vigueur, minima et majorations compris",
    null, comparaison.tauxRemplacementActuel)
    + bloc("retroactif", "2. Comptes notionnels, rétroactifs depuis 1941",
      "toute la carrière recalculée sur la seule part salariale",
      comparaison.variation("notionnel_retroactif"),
      comparaison.tauxRemplacementRetroactif)
    + bloc("prospectif", `3. Comptes notionnels à compter de ${saisie.bascule}`,
      "droits acquis conservés, règles notionnelles ensuite",
      comparaison.variation("notionnel_prospectif"),
      comparaison.tauxRemplacementProspectif)
    + bloc("retroactif-employeur",
      "4. Comptes notionnels rétroactifs, salariale + patronale",
      "le scénario 2, la part patronale en plus",
      comparaison.variation("notionnel_retroactif_employeur"),
      comparaison.tauxRemplacement("notionnel_retroactif_employeur"))
    + bloc("prospectif-employeur",
      `5. Comptes notionnels à compter de ${saisie.bascule}, salariale + patronale`,
      "le scénario 3, la part patronale en plus",
      comparaison.variation("notionnel_prospectif_employeur"),
      comparaison.tauxRemplacement("notionnel_prospectif_employeur"));

  const anticipation = `départ ${g.nombre(Math.abs(ecart.ecart), 2).replace(/0+$/, "").replace(/,$/, "")} ans `
    + (ecart.anticipe ? "plus tôt" : "plus tard");
  const fiches = [
    g.fiche("années cotisées", String(carriere.anneesCotisees.length)),
    // La date, et pas seulement l'année : la pension prend effet le premier du
    // mois, et c'est ce mois que l'utilisateur vient de choisir.
    g.fiche("liquidation", `${age(carriere.age_liquidation)} `
      + `<span class="discret">en ${carriere.dateLiquidation}</span>`),
    g.fiche(`âge de référence — ${anticipation}`, `${age(ecart.age_reference)}`),
    g.fiche("coefficient de conversion", g.nombre(conversion.diviseur, 1)),
    g.fiche("capital notionnel rétroactif", g.euros(retro.capital_notionnel)),
  ].join("");

  let capitalisation = "";
  if (comparaison.actuel.pension_hors_repartition > 0) {
    const montant = comparaison.enEurosConstants(
      comparaison.actuel.pension_hors_repartition,
    );
    capitalisation = '<p class="discret">Hors répartition, servi à part : '
      + `${g.euros(montant / 12)} par mois de RAFP. Ce régime est PROVISIONNÉ `
      + "— sa rente sort d'un placement, non de la cotisation des actifs —, si "
      + "bien qu'une réforme de la répartition ne l'atteint pas. Il est donc "
      + "retiré des cinq totaux et servi à l'identique dans les cinq "
      + "scénarios : c'est la seule façon de comparer ce qui est comparable.</p>";
  }

  let minimum = "";
  if (comparaison.actuel.minimum_applique) {
    minimum = '<p class="discret">Le minimum contributif s\'applique dans le '
      + "scénario 1 ; il est supprimé dans les scénarios 2 à 5.</p>";
  }

  let ouverture = "";
  if (!comparaison.actuel.liquidation_ouverte) {
    const age = comparaison.actuel.age_ouverture_opposable;
    const attente = age === null ? "" : ` — il faut attendre ${g.nombre(age, 2)} ans`;
    ouverture = '<p class="note avertissement">Le droit en vigueur <strong>n\'ouvre pas'
      + "</strong> cette liquidation à "
      + `${g.nombre(comparaison.carriere.age_liquidation, 2)} ans${attente}. `
      + "Ni l'âge légal du régime, ni le départ anticipé pour carrière longue "
      + "ne le permettent. Le montant du scénario 1 reste calculé, parce qu'il "
      + "faut bien comparer les cinq scénarios sur la même carrière, mais il "
      + "ne décrit aucune pension que le système actuel servirait.</p>";
  }

  return `
<h2>Résultats</h2>
<div class="carte">
  <div class="fiches">${fiches}</div>
</div>
<div class="carte">
  ${scenarios}
  <p class="discret" style="margin-top:1.5rem">Montants bruts mensuels, en euros
  constants de ${saisie.euros} — seule unité qui permette de comparer des
  liquidations d'années différentes. Fiabilité du résultat :
  <span class="etiquette-fiabilite">${echapper(nomFiabilite(comparaison.fiabilite))}</span></p>
  ${capitalisation}
  ${minimum}
  ${ouverture}
</div>
${decomposition(contexte, saisie, comparaison)}
${contributionEmployeur(comparaison)}
${cascade(comparaison, saisie)}
${detail(contexte, comparaison)}
`;
}

const NATURES_PART_EMPLOYEUR = {
  appelee: "contribution appelée par décret ou par arrêté",
  implicite: "taux implicite reconstitué par les documents budgétaires",
  repli: "aucune série publiée : effort du privé de la même année",
};

/**
 * Qui verse la cotisation : l'assuré, son employeur, dans quelle proportion.
 *
 * C'est la mesure directe de ce qui sépare les scénarios 2 et 3 des scénarios 4
 * et 5. Le bloc ne s'affiche pas pour un non-salarié, qui n'a pas d'employeur.
 */
function contributionEmployeur(comparaison) {
  const employeur = comparaison.contributionEmployeur;
  if (!(employeur.a_un_employeur || employeur.concerne_un_regime_public)) {
    return "";
  }

  const partage = employeur.a_un_employeur
    ? g.tableau(
      ["Sur toute la carrière, en euros courants cumulés", "", "Montant"],
      [
        ["Part salariale", "ce que l'assuré supporte — scénarios 2 et 3",
          g.euros(employeur.agent)],
        ["Part patronale", "ce que verse l'employeur", g.euros(employeur.employeur)],
        ["Total", "scénarios 4 et 5", g.euros(employeur.total)],
      ],
      ["", "", "nombre"],
    ) + `<p>L'employeur verse ici <strong>${g.pourcentage(employeur.part)}`
      + "</strong> du total.</p>"
    : "";

  // La part patronale d'un agent public n'est dans aucune fiche : elle vient
  // d'une série à part, qui ne couvre pas tous les régimes ni toutes les
  // années. Le dire est le prix de s'en servir.
  let public_ = "";
  if (employeur.concerne_un_regime_public) {
    const origines = Object.entries(employeur.annees_par_origine)
      .sort((a, b) => (a[0] < b[0] ? -1 : 1))
      .map(([origine, nombre]) => `<li>${
        echapper(NATURES_PART_EMPLOYEUR[origine] ?? origine)
      } — ${nombre} année${nombre > 1 ? "s" : ""}</li>`)
      .join("");
    public_ = `
<p>Les fiches de la fonction publique et des régimes spéciaux ne portent que la
<strong>retenue de l'agent</strong>. La part de l'employeur vient d'une série à
part — reconstituée par les documents budgétaires de 1995 à 2005, appelée par
décret depuis 2006 pour l'État, versée à une caisse depuis 1948 pour la fonction
publique territoriale et hospitalière. Origine, année par année :</p>
<ul class="serree">${origines}</ul>
<p class="discret">Et c'est la limite de ces deux scénarios pour un agent
public. Un taux de 82,28 % ne signifie pas qu'un fonctionnaire acquiert 82 % de
son traitement en droits nouveaux : il est fixé pour que le compte
d'affectation spéciale « Pensions » soit à l'équilibre, donc pour payer les
pensions d'aujourd'hui. Le porter au compte répond à une question précise —
« et si tout ce qui a été consacré aux pensions avait été porté au compte des
actifs ? » — et à elle seule.</p>`;
  }

  return `
<h2>Qui verse la cotisation</h2>
<p>Une cotisation retraite a deux parts : ce que l'assuré supporte, et ce que
son employeur verse. Les scénarios 2 et 3 ne portent au compte que la première ;
les scénarios 4 et 5 y ajoutent la seconde, et ne changent rien d'autre.</p>
${partage}${public_}`;
}

/** Sépare l'effet de la règle d'indexation de celui des comptes notionnels. */
function decomposition(contexte, saisie, comparaison) {
  // Le défaut est lu sur DEFAUTS, non écrit en dur : ailleurs, l'utilisateur a
  // choisi lui-même sa ligne de comparaison.
  if (saisie.indexation !== DEFAUTS.indexation) {
    return "";
  }

  const lignes = [];
  for (const [code, libelle] of INDEXATIONS) {
    let variante;
    try {
      variante = code === saisie.indexation
        ? comparaison
        : contexte.simuler(new Saisie({ ...saisie, indexation: code }));
    } catch (erreur) {
      continue;
    }
    const mensuel = variante.enEurosConstants(
      variante.notionnel_retroactif.pension_annuelle,
    ) / 12;
    lignes.push([
      echapper(libelle),
      `×${g.nombre(variante.notionnel_retroactif.compte.rendement_cumule, 2)}`,
      g.euros(mensuel),
      g.pourcentage(variante.variation("notionnel_retroactif"), true),
    ]);
  }

  return `
<h2>D'où vient l'écart</h2>
<p>La même carrière, le même calcul notionnel rétroactif, avec neuf règles de
revalorisation des comptes. La <strong>première ligne est celle que la
simulation applique</strong> : la croissance de la masse salariale, c'est-à-dire
le rendement qu'un système en répartition peut servir sans changer son taux de
cotisation. La deuxième n'est pas une hypothèse mais un relevé : le coefficient
que les arrêtés ont réellement appliqué aux salaires portés au compte, celui-là
même dont le scénario 1 se sert. Les quatre suivantes sont le triple lock
inversé et ses variantes — mêmes trois séries, inflation, salaire moyen,
productivité, seul change ce qu'on en retient. La colonne « rendement » est le
facteur par lequel les cotisations ont été multipliées entre leur versement et
la liquidation.</p>
${g.tableau(
    ["Règle d'indexation", "Rendement cumulé", "Pension mensuelle", "Écart au système actuel"],
    lignes,
    ["", "nombre", "nombre", "nombre"],
  )}
<p class="discret">La ligne de repère est la <strong>revalorisation réellement
pratiquée</strong> : c'est celle du droit positif. L'écart entre elle et le
système actuel mesure l'effet propre des comptes notionnels ; tout ce qui sépare
les autres lignes de celle-là mesure l'effet de la règle d'indexation. La ligne
« Prix » ne joue pas ce rôle, contrairement à ce que cette page a longtemps dit :
le régime général ne revalorise sur les prix que depuis 1987, et suivait les
salaires avant. Le triple lock inversé, lui, compare deux taux nominaux
(inflation, salaire moyen) à un taux réel (productivité) : dès que l'inflation
dépasse la productivité — soit presque toute la période 1945-1985 — c'est la
productivité qui l'emporte, et la valeur réelle des comptes s'effondre. Les
lignes « médiane » et « moyenne » gardent ses trois séries et n'en changent que
la statistique.</p>
<p class="discret">La première ligne, la <strong>masse salariale</strong>, est
la seule qui repose sur un argument théorique et non sur un choix : c'est
l'assiette des cotisations, donc le taux de rendement qu'un système en
répartition peut servir sans toucher à son taux de cotisation. C'est pourquoi
elle est le défaut du simulateur. Elle vaut salaire moyen + emploi salarié, et
l'emploi salarié a doublé depuis 1950 : c'est la règle la plus généreuse du
tableau, et de loin. Elle a sa propre incohérence, à
garder en tête : elle crédite le compte du rendement que le système ENTIER
dégage, alors que les scénarios 2 et 3 n'y versent que la part salariale de la
cotisation. C'est aux scénarios 4 et 5, qui portent la cotisation entière,
qu'elle se compare sans biais. La ligne « PIB nominal » est la même idée poussée
à l'assiette la plus large : elle capte le déplacement de la valeur ajoutée vers
les revenus non salariaux, que la masse salariale subit.</p>
<p class="discret">Le <strong>lissage</strong>, dans les options, est
indépendant de la règle : il applique une moyenne glissante au taux que la règle
produit, quelle qu'elle soit, et s'applique donc à toutes les lignes de ce
tableau à la fois. Ce qu'il vise n'est pas le niveau mais la loterie de cohorte :
sur le PIB nominal brut, une cotisation de 1980 vaut ×5,44 à une liquidation de
2019 et ×5,18 en 2020 — attendre un an fait perdre, parce que l'année traversée
s'est mal passée. Lissée sur cinq ans, la même cotisation vaut ×6,64 puis ×6,71,
et le recul disparaît. « PIB nominal » lissé sur cinq ans, c'est la règle
italienne ; le modèle en reprend le taux, pas le reste du système italien.</p>
`;
}

/**
 * Détaille le passage du scénario 1 au scénario 3, étape par étape.
 *
 * C'est la partie du modèle la moins intuitive : le scénario 3 n'est pas le
 * scénario 1 diminué d'un pourcentage, c'est une autre formule appliquée à la
 * même carrière. Tant qu'on ne voit pas la chaîne de calcul, l'écart affiché
 * reste un chiffre à croire.
 */
function cascade(comparaison, saisie) {
  const prospectif = comparaison.notionnel_prospectif;
  const acquis = prospectif.droits_acquis;
  if (acquis === null || prospectif.capital_notionnel <= 0) {
    // Rien n'a été cotisé : une cascade de zéros n'explique rien, et le reste
    // de la page dit déjà que le compte est vide.
    return "";
  }

  const liquidation = comparaison.carriere.anneeLiquidation;
  const ageLiquidation = comparaison.carriere.age_liquidation || 0.0;
  const diviseur = prospectif.conversion.diviseur;
  const capitalApres = prospectif.capital_notionnel - acquis.capital;
  const actuel = comparaison.actuel.pension_annuelle;

  const lignes = [
    [`a) Droits acquis à ${saisie.bascule}`,
      "carrière arrêtée à la bascule, règles actuelles, avantages non "
      + "contributifs retirés, sans décote",
      `${g.euros(acquis.pension_figee)} par an`],
    [`b) × diviseur à ${age(acquis.age_conversion)}`,
      `coefficient de conversion en ${saisie.bascule} : `
      + `${g.nombre(acquis.diviseur, 2)}`,
      g.euros(acquis.capital_a_la_bascule)],
    [`c) × revalorisation ${saisie.bascule}-${liquidation}`,
      "règle d'indexation retenue : ×"
      + `${g.nombre(acquis.coefficient_revalorisation, 3)}`,
      g.euros(acquis.capital)],
    [`d) + cotisations ${saisie.bascule}-${liquidation - 1}`,
      "versées au régime unique, revalorisées de même",
      g.euros(capitalApres)],
    ["e) = capital notionnel", "ce que la carrière a effectivement financé",
      g.euros(prospectif.capital_notionnel)],
    [`f) ÷ diviseur à ${age(ageLiquidation)}`,
      `coefficient de conversion en ${liquidation} : ${g.nombre(diviseur, 2)}`,
      `${g.euros(prospectif.pension_annuelle)} par an`],
  ];

  const partAcquis = acquis.capital / prospectif.capital_notionnel;
  let neutralite = "";
  if (saisie.conversion_acquis === "reference"
      && acquis.age_conversion > ageLiquidation) {
    neutralite = `<p>Ligne b) : les droits déjà ouverts sont convertis au diviseur de `
      + `l'âge de référence (${age(acquis.age_conversion)}), alors que la `
      + `rente sera servie depuis ${age(ageLiquidation)}. L'anticipation `
      + `est donc payée une seconde fois, sur le passé. L'option « conversion `
      + `des droits acquis à l'âge de départ effectif » supprime cet `
      + `abattement, et c'est la convention qu'une réforme réelle `
      + `retiendrait.</p>`;
  }

  return `
<h2>Du scénario 1 au scénario 3, ligne à ligne</h2>
<p>Le scénario 3 n'est pas le scénario 1 diminué d'un pourcentage : c'est une
autre formule appliquée à la même carrière. Montants en euros courants de
l'année de liquidation — la chaîne de calcul est arithmétique, la convertir en
euros constants ligne à ligne la rendrait fausse.</p>
${g.tableau(
    ["Étape", "Ce qu'elle fait", "Résultat"],
    lignes,
    ["", "", "nombre"],
  )}
<p>À comparer aux ${g.euros(actuel)} par an du système actuel. L'écart ne vient
d'aucun abattement appliqué au scénario 1 : il vient de ce que le capital
réellement constitué, ${g.euros(prospectif.capital_notionnel)}, ne finance pas
les ${g.euros(actuel * diviseur)} que le droit en vigueur promet sur
${g.nombre(diviseur, 1)} années de retraite.</p>
${neutralite}
<p class="discret">Les droits acquis avant ${saisie.bascule} pèsent
${g.pourcentage(partAcquis)} du capital final. Cette part décroît de génération
en génération : c'est elle qui étale la réforme dans le temps, et non un
dispositif transitoire.</p>
`;
}

function detail(contexte, comparaison) {
  const retro = comparaison.notionnel_retroactif;
  const catalogue = contexte.simulateur().catalogue;
  const pensions = comparaison.actuel.pensions_par_regime;

  const nomRegime = (code) => (catalogue.contient(code) ? catalogue.obtenir(code).nom : code);

  const actuel = comparaison.actuel;
  const lignesActuel = pensions.map((pension) => [
    echapper(nomRegime(pension.regime)),
    g.euros(pension.montant),
    g.franciser(echapper(pension.detail)),
  ]);
  if (lignesActuel.length > 0 && actuel.avantages_appliques.length > 0) {
    lignesActuel.push([
      "<strong>Sous-total contributif</strong>",
      `<strong>${g.euros(actuel.total_contributif)}</strong>`,
      '<span class="discret">ce que la carrière a ouvert par ses seules '
      + "cotisations</span>",
    ]);
  }
  for (const avantage of actuel.avantages_appliques) {
    lignesActuel.push([
      `+ ${echapper(avantage.libelle)}`,
      g.euros(avantage.montant),
      `<span class="discret">${echapper(avantage.detail)}</span>`,
    ]);
  }
  if (lignesActuel.length > 0) {
    lignesActuel.push([
      "<strong>Pension du système actuel</strong>",
      `<strong>${g.euros(actuel.pension_annuelle)}</strong>`,
      '<span class="discret">c\'est le montant de la ligne 1 ci-dessus</span>',
    ]);
  }

  const regimes = lignesActuel.length > 0
    ? g.tableau(
      ["Régime, puis avantage", "Pension annuelle", "Calcul"],
      lignesActuel,
      ["", "nombre", ""],
    )
    : "<p>Aucun droit liquidé dans le système actuel.</p>";

  let part = "";
  if (actuel.avantages_appliques.length > 0 && actuel.pension_annuelle > 0) {
    const gratuit = actuel.avantages_appliques
      .reduce((somme, a) => somme + a.montant, 0.0);
    part = `<p>Les avantages non contributifs pèsent ${g.euros(gratuit)} par an, `
      + `soit ${g.pourcentage(gratuit / actuel.pension_annuelle)} de la `
      + "pension. C'est exactement ce que les deux scénarios notionnels "
      + "retirent : ils ne conservent que le sous-total contributif, et le "
      + "recalculent sur les cotisations réellement versées.</p>";
  }

  const compte = g.tableau(
    ["Poste", "Montant"],
    [
      ["Cotisations effectivement versées, en euros courants",
        g.euros(retro.compte.cotisations_versees)],
      ["Rendement cumulé appliqué à ces cotisations",
        `×${g.nombre(retro.compte.rendement_cumule, 2)}`],
      ["Capital notionnel à la liquidation", g.euros(retro.capital_notionnel)],
      ["Divisé par le coefficient de conversion",
        `${g.nombre(retro.conversion.diviseur, 2)} (${echapper(retro.conversion.table)})`],
      ["Pension annuelle en euros courants", g.euros(retro.pension_annuelle)],
    ],
    ["", "nombre"],
  );

  return `
<h2>Le détail du calcul</h2>
<h3>Scénario 1 — de quoi votre pension actuelle est faite</h3>
<p>Chaque régime d'abord, puis les avantages que le droit en vigueur ajoute
par-dessus. Les lignes s'additionnent exactement : le total est la pension du
scénario 1.</p>
${regimes}
${part}
<h3>Scénario 2 — construction du compte notionnel rétroactif</h3>
${compte}
<details>
  <summary>Les résultats complets en JSON</summary>
  <pre class="json">${echapper(JSON.stringify(comparaison.dictionnaire(), null, 2))}</pre>
</details>
<p class="discret">L'adresse de cette page contient tous les paramètres :
elle peut être citée ou partagée telle quelle.</p>
`;
}

function casTypes(contexte) {
  const resultat = calculerCasTypes(contexte.simulateur());

  const grille = (scenario) => {
    const lignes = CAS_TYPES.map((cas) => {
      const cellules = [
        `<span title="${echapper(cas.commentaire)}">${echapper(cas.libelle)}</span>`,
      ];
      for (const generation of GENERATIONS) {
        const comparaison = resultat.resultats.get(`${cas.code}|${generation}`);
        if (comparaison === undefined) {
          cellules.push("—");
          continue;
        }
        const variation = comparaison.variation(scenario);
        cellules.push(new g.Cellule(g.pourcentage(variation, true, 0), variation));
      }
      return cellules;
    });
    return g.tableau(
      ["Cas type", ...GENERATIONS.map(String)],
      lignes,
      ["", ...GENERATIONS.map(() => "nombre")],
    );
  };

  let echecs = "";
  if (resultat.echecs.size > 0) {
    const elements = [...resultat.echecs.entries()]
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
      .map(([cle, motif]) => {
        const [code, generation] = cle.split("|");
        return `<li>${echapper(code)} / ${generation} : ${echapper(motif)}</li>`;
      })
      .join("");
    echecs = `<h3>Combinaisons non calculées</h3><ul class='serree'>${elements}</ul>`;
  }

  return `
<h2 style="margin-top:0">Le cas général</h2>
<p class="chapeau">Douze carrières représentatives × sept générations. Chaque
cellule est l'écart de pension par rapport au système actuel, à carrière
identique : négatif = pension plus faible qu'aujourd'hui.</p>

<h3>Scénario 2 — comptes notionnels rétroactifs depuis 1941</h3>
${grille("notionnel_retroactif")}
<p class="discret">Les générations anciennes sont les plus touchées : leurs
cotisations, versées quand l'inflation dépassait la productivité, ont été
revalorisées à un taux très inférieur à la hausse des prix.</p>

<h3>Scénario 3 — comptes notionnels à compter de la bascule</h3>
${grille("notionnel_prospectif")}
<p class="discret">Les générations déjà retraitées sont inchangées : leurs droits
sont intégralement acquis avant la bascule. Les indépendants et professions
libérales progressent parce que le régime unique relève leur taux de cotisation
et déplafonne leur assiette — un effort contributif accru, pas un avantage
accordé.</p>

<h3>Scénario 4 — le scénario 2, part patronale comprise</h3>
${grille("notionnel_retroactif_employeur")}
<p class="discret">Toutes les lignes bougent, sauf celles des non-salariés —
artisan, exploitant agricole, profession libérale — qui n'ont pas d'employeur et
pour qui ce scénario est le scénario 2. Les lignes publiques bougent le plus :
la contribution de leur employeur est un taux d'équilibre, sans commune mesure
avec la part patronale d'un salarié.</p>

<h3>Scénario 5 — le scénario 3, part patronale comprise</h3>
${grille("notionnel_prospectif_employeur")}
<p class="discret">Même lecture, à compter de la bascule : les droits acquis
restent ceux du scénario 3, et seul le flux postérieur change. À compter de la
bascule il n'y a plus qu'un régime, dont la répartition salarié/employeur est
celle du statut pivot privé : les écarts entre statuts s'y referment.</p>
${echecs}
`;
}

function methode(contexte) {
  const fusionne = contexte.simulateur().regimeFusionne;
  const nombreRegimes = contexte.simulateur().catalogue.taille;
  return `
<h2 style="margin-top:0">Ce que le modèle calcule</h2>

<h3>Le compte notionnel</h3>
<p>Un compte notionnel est un compte <em>virtuel</em> : aucun capital n'est
placé, les cotisations de l'année financent les pensions de l'année, comme dans
toute répartition. Ce qui change, c'est le calcul du droit.</p>
<ol>
  <li><strong>Accumulation</strong> — la cotisation retraite effectivement
  versée chaque année est inscrite au compte ;</li>
  <li><strong>Revalorisation</strong> — le solde est revalorisé chaque année au
  taux fixé par la règle collective ;</li>
  <li><strong>Liquidation</strong> — pension annuelle = capital notionnel ÷
  espérance de vie résiduelle à l'âge de départ, lue sur une table de
  génération.</li>
</ol>
<p>Trois conséquences : la pension est strictement proportionnelle aux
cotisations ; partir tôt coûte deux fois (moins de cotisations, rente servie
plus longtemps) ; aucun droit non financé par une cotisation n'existe.</p>

<h3 id="indexation">La règle d'indexation, et pourquoi elle domine tout</h3>
<p>La règle retenue par défaut est la croissance de la <strong>masse
salariale</strong> : l'assiette des cotisations, c'est-à-dire le rendement qu'un
système en répartition peut servir sans toucher à son taux de cotisation. C'est
la règle que la théorie désigne, et non celle qui a donné son cahier des charges
au modèle.</p>
<p>Celle-là, le <strong>triple lock inversé</strong> —
<code>min(inflation, croissance du salaire moyen, productivité réelle)</code> —
reste à un clic dans les options, et c'est elle qui a motivé ce simulateur.
Prise à la lettre, elle compare deux taux nominaux à un taux réel, et voici ce
qu'elle produit.</p>
${g.tableau(
    ["Règle appliquée 1941-2025", "Comptes", "Prix", "Pouvoir d'achat conservé"],
    [
      ["Triple lock inversé, littéral", "×4,9", "×322,2", "<strong>1,5 %</strong>"],
      ["Moyenne des trois taux", "×175,7", "×322,2", "54,5 %"],
      ["Triple lock inversé, tout en nominal", "×223,3", "×322,2", "69,3 %"],
      ["Indexation sur les prix", "×322,2", "×322,2", "100 %"],
      ["Médiane des trois taux", "×397,6", "×322,2", "123,4 %"],
      ["Revalorisation réellement pratiquée", "×1 538,2", "×322,2", "477,4 %"],
      ["Masse salariale (règle d'équilibre)", "×3 685,1", "×322,2", "1 143,7 %"],
      ["PIB nominal", "×3 442,3", "×322,2", "1 068,6 %"],
      ["PIB nominal lissé sur 5 ans (Italie)", "×4 152,7", "×322,2", "1 288,8 %"],
    ],
    ["", "nombre", "nombre", "nombre"],
  )}
<p>Une cotisation de 1950 ne conserve donc que 1,5 % de sa valeur réelle. C'est
la règle telle qu'énoncée, appliquée sans correctif — et c'est de là que vient
l'essentiel de la baisse affichée par le scénario rétroactif, non du passage aux
comptes notionnels. Le tableau « D'où vient l'écart » de chaque simulation
sépare les deux effets.</p>
<p>La ligne « Revalorisation réellement pratiquée » est la seule qui ne soit pas
une hypothèse : c'est le coefficient que les arrêtés annuels ont réellement
appliqué aux salaires portés au compte, celui dont le scénario 1 se sert pour
calculer le salaire de référence. Il vaut <strong>×1 538</strong> sur la période, soit près de cinq
fois les prix, parce que le régime général a revalorisé sur les SALAIRES
jusqu'en 1986 et sur les prix seulement depuis 1987. C'est donc cette ligne, et
non « Indexation sur les prix », qui neutralise la question de l'indexation
quand on veut isoler l'effet propre des comptes notionnels — cette page a
longtemps désigné la mauvaise. Sur une carrière, la correction reste modeste :
+6,2 points pour la génération 1920, +0,1 pour 1945, et -0,5 pour 1958, dont la
carrière est presque entièrement postérieure à 1987. Les cotisations se
concentrent sur les dernières années, là où les deux règles coïncident.</p>
<p>La dernière ligne est d'une autre nature : elle ne décrit ni une règle
demandée, ni une règle appliquée, mais la règle que la <strong>théorie</strong>
désigne. En répartition, le rendement qu'un système peut servir sans changer son
taux de cotisation est la croissance de son assiette — la masse salariale, soit
le salaire moyen multiplié par l'emploi salarié (Samuelson 1958, Aaron 1966).
C'est le taux d'indexation des comptes notionnels suédois, italiens, polonais et
lettons, à des variantes près. Sur 1941-2025 il vaut ×3 685, onze fois les
prix : l'emploi salarié a doublé depuis 1950, et cette croissance-là s'ajoute
chaque année à celle des salaires. Une réserve : ce rendement est celui du
système ENTIER, alors que les scénarios 2 et 3 ne portent au compte que la part
salariale de la cotisation. C'est aux scénarios 4 et 5 qu'il faut le comparer.</p>
<p>Les deux dernières lignes sont la même idée poussée à l'assiette la plus
large : le <strong>PIB nominal</strong>, qui gagne ce que la masse salariale
perd quand la valeur ajoutée se déplace vers les revenus non salariaux. La
seconde y ajoute un <strong>lissage sur cinq ans</strong>, comme le fait
l'Italie pour ses propres comptes notionnels.</p>
<p>Le lissage n'est pas une règle : c'est un réglage à part, qui applique une
moyenne glissante au taux que la règle produit — n'importe laquelle. Ce qu'il
vise n'est pas le niveau mais la <strong>loterie de cohorte</strong> : sur le PIB
nominal brut, une cotisation de 1980 vaut ×5,44 à une liquidation de 2019 et
×5,18 en 2020 — attendre un an fait <em>perdre</em>, parce que l'année traversée
s'est mal passée. Lissée sur cinq ans, elle vaut ×6,64 puis ×6,71 : le trou de
2020 est absorbé par les quatre années qui l'entourent au lieu d'être porté en
entier par qui a eu le tort de liquider cette année-là. Sur 1950-2025, le PIB
nominal brut compte deux années où liquider plus tard rapporte moins ; lissé sur
trois ou cinq ans, aucune.</p>
<p>Une réserve pour lire le tableau : sur quatre-vingts ans, une moyenne
glissante n'est pas neutre. Elle revient à mesurer la croissance depuis une base
reculée d'environ la moitié de la fenêtre, ce qui gonfle le cumul d'une
vingtaine de pour cent à cinq ans — sans qu'aucune série ait changé. Sur une
carrière, l'écart entre lissé et non lissé reste d'un à deux points. Et la règle
italienne n'est reprise ici que par son taux, pas par le reste du système
italien (décalage de publication de deux ans, coefficients de transformation,
planchers).</p>
<p>Le minimum n'est pas la seule statistique possible sur ces trois séries. Deux
variantes gardent les <em>mêmes</em> termes et ne changent que ce qu'on en
retient : la <strong>médiane</strong> — le taux du milieu — et la
<strong>moyenne</strong>. Le résultat n'est pas celui qu'on attend. La médiane
est l'inflation ou le salaire moyen trois années sur quatre, donc un taux
nominal : elle suit les prix et les dépasse même un peu, et cesse d'être une
règle d'austérité. La moyenne, elle, est plus sévère que les prix, non par
sévérité assumée mais parce qu'elle incorpore un tiers de productivité réelle
<em>chaque</em> année, y compris à vingt points d'inflation — là où le minimum
et la médiane ne retiennent le terme réel que les années où il gagne. Les deux
sont sélectionnables dans les options de modélisation.</p>

<h3>Ce que le scénario 1 applique du droit positif</h3>
<p>L'étalon ne vaut que par ce qu'il reproduit. Il applique la décote et la
surcote, la proratisation par la durée, le salaire de référence de chaque
régime — sur ses seules années, jamais sur toute la carrière —, et cinq
paramètres lus à la GÉNÉRATION et non à l'année de liquidation : durée requise,
âge légal, âge d'annulation de la décote, coefficient de minoration, nombre
d'années retenues au salaire de référence.</p>
<p>Il applique aussi, dans l'ordre où le droit les applique, les avantages non
contributifs que la carrière suffit à déterminer :</p>
<ul>
  <li><strong>l'assurance vieillesse des parents au foyer</strong>, qui porte au
  compte un salaire forfaitaire égal au SMIC — c'est ce qui la distingue d'une
  période assimilée, laquelle valide des trimestres sans jamais ajouter de
  salaire ;</li>
  <li><strong>les trimestres accordés au titre des enfants</strong>, datés : la
  majoration de durée d'assurance du régime général et des régimes alignés naît
  en 1972 à un an par enfant, passe à deux ans en 1975 et va à la mère ; la
  fonction publique et les régimes spéciaux servent leur bonification, un an par
  enfant né avant 2004 et deux trimestres pour les enfants nés depuis. Ils sont
  attribués DANS un régime et non au-dessus d'eux : ils comptent donc aussi dans
  sa proratisation ;</li>
  <li><strong>le minimum contributif</strong>, réservé aux pensions liquidées au
  taux plein, proratisé par la durée d'assurance acquise dans le régime, et sa
  majoration au titre des périodes cotisées proratisée par la seule durée
  cotisée, puis écrêté quand le total des pensions personnelles dépasse le
  plafond de l'article L. 173-2 ;</li>
  <li><strong>le minimum garanti</strong> de la fonction publique, barème en
  escalier sur la durée de services — 57,5 % de la référence à quinze ans, 95 %
  à trente, la totalité à quarante ;</li>
  <li><strong>la surcote parentale</strong>, créée par la loi du 14 avril 2023 :
  1,25 % par trimestre acquis entre 63 ans et l'âge légal, quatre au plus, à qui
  justifie de la durée requise à 63 ans et détient un trimestre de majoration
  pour enfants. C'est la contrepartie du recul de l'âge légal, et elle se cumule
  avec la surcote ordinaire, qui ne compte qu'au-delà de cet âge ;</li>
  <li><strong>la majoration pour trois enfants</strong>, calculée sur le montant
  déjà relevé par les minima, et plafonnée en euros à la complémentaire ;</li>
  <li><strong>le minimum vieillesse</strong>, allocation différentielle servie à
  partir de 65 ans sous le barème d'une personne seule. Ce n'est pas une
  pension : elle apparaît toujours comme une ligne séparée de la cascade.</li>
</ul>
<p>Deux barèmes propres complètent l'ensemble : la décote de la fonction
publique, dont le coefficient et l'âge d'annulation montent en charge de 2006 à
2020 et dont l'âge d'annulation est la limite d'âge du grade et non 67 ans ; et
la garantie minimale de points de l'Agirc, 120 points par an de 1989 à 2018
même quand la tranche B est nulle.</p>
<p>Enfin, le scénario dit si le droit <strong>ouvre</strong> la liquidation
demandée — âge légal du régime, ou départ anticipé pour carrière longue. Quand
il ne l'ouvre pas, le montant reste calculé, parce qu'il faut comparer les cinq
scénarios sur la même carrière, mais la page le signale : il ne décrit alors
aucune pension que le système actuel servirait.</p>

<h3>Ce qui est supprimé dans les scénarios notionnels</h3>
<p>Le principe « seules les cotisations comptent » est appliqué sans exception :
ni minimum contributif, ni minimum garanti, ni ASPA, ni majoration pour enfants,
ni majoration de durée d'assurance, ni AVPF, ni bonifications, ni catégorie
active, ni périodes assimilées, ni réversion, ni décote ni surcote. Le scénario
1 les conserve tous, puisqu'il décrit le droit en vigueur.</p>

<h3>La fusion des régimes</h3>
<p>À compter de l'année de bascule, les ${nombreRegimes} régimes du catalogue sont remplacés
par un régime unique dont chaque paramètre est le plus défavorable de
l'ensemble : ouverture à ${age(fusionne.age_ouverture)}, taux plein à
${age(fusionne.age_taux_plein)}, ${fusionne.duree_requise_trimestres} trimestres
requis, cotisation de ${g.pourcentage(fusionne.taux_cotisation_retraite, false, 2)}
sur assiette déplafonnée.</p>

<h3>Périmètre</h3>
<p>Origine 1941 (allocation aux vieux travailleurs salariés), premier dispositif
où les cotisations des actifs financent les prestations des retraités. Les
assurances sociales de 1930, en capitalisation individuelle, et le RAFP sont
isolés dans un compartiment séparé, jamais converti.</p>

<p><a href="${g.DEPOT}/blob/main/docs/methodologie.md">Méthodologie complète</a> ·
<a href="${g.DEPOT}/blob/main/docs/limites.md">Limites connues</a></p>
`;
}

function donnees(contexte) {
  const simulateur = contexte.simulateur();
  const macro = simulateur.macro;

  const periodes = [];
  for (let debut = 1940; debut < 2030; debut += 10) {
    const fin = debut + 9;
    periodes.push([
      `${debut}-${fin}`,
      echapper(nomFiabilite(macro.inflation.fiabiliteMinimaleSur(debut, fin))),
      echapper(nomFiabilite(macro.salaire_moyen.fiabiliteMinimaleSur(debut, fin))),
      echapper(nomFiabilite(macro.productivite.fiabiliteMinimaleSur(debut, fin))),
      `<strong>${echapper(nomFiabilite(macro.fiabiliteSur(debut, fin)))}</strong>`,
    ]);
  }

  const parNiveau = new Map();
  for (const regime of simulateur.catalogue) {
    const niveau = nomFiabilite(regime.fiabilite);
    if (!parNiveau.has(niveau)) {
      parNiveau.set(niveau, []);
    }
    parNiveau.get(niveau).push(regime.code);
  }
  const regimes = ["certifiee", "haute", "moyenne", "estimee"]
    .filter((niveau) => parNiveau.has(niveau))
    .map((niveau) => [
      niveau,
      String(parNiveau.get(niveau).length),
      echapper([...parNiveau.get(niveau)].sort().join(", ")),
    ]);

  const journal = contexte.paquet.certification || {};
  const certifications = Object.entries(journal.series || {})
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([nom, trace]) => [
      echapper(nom), String(trace.valeurs),
      echapper(trace.niveau ?? "certifiee"), echapper(trace.source),
    ]);

  const bandeau = certifications.length > 0
    ? `<div class="note"><strong>Les séries macroéconomiques sont
certifiées de 1950 à 2025</strong>, les tables de mortalité sont celles
réellement observées depuis 1986, et le plafond de la Sécurité sociale remonte à
1931 daté décret par décret — le tout recontrôlé automatiquement contre les
sources, le ${echapper(journal.certifie_le)}. Ce qui précède 1950 et les
paramètres propres à chaque régime restent saisis à la main : les
<em>niveaux</em> de pension des carrières les plus anciennes gardent une marge,
les <em>écarts entre scénarios</em>, qui sont l'objet du modèle, sont plus
robustes encore.</div>`
    : `<div class="note avertissement"><strong>Aucune série n'a
encore été recontrôlée contre sa source.</strong> Lancer <code>scripts/fetch/</code>
puis <code>scripts/verifier_donnees.py --appliquer</code>.</div>`;

  return `
<h2 style="margin-top:0">Ce que valent les chiffres</h2>
${bandeau}

<h3>Ce qui a été recontrôlé contre la source</h3>
${g.tableau(["Série", "Valeurs", "Niveau", "Source"], certifications,
    ["", "nombre", "", ""])}
<p class="discret">Une valeur n'est « certifiée » que si elle a été confrontée au
fichier téléchargé depuis le <em>producteur</em> de la donnée. Une transcription
tierce, même sourcée et reprise automatiquement, plafonne à « haute ». Hors de
cette liste : les séries d'avant 1950, l'espérance de vie à 65 ans d'avant 1960,
les quotients de mortalité d'avant 1986, les taux de cotisation d'avant 1967, les
montants servis du minimum contributif, du minimum garanti et du minimum
vieillesse — transcrits de leur publication, et préférés à toute projection
parce qu'ils disent ce qui a été payé —, et les âges, durées et coefficients
propres à chaque régime, repris des textes.</p>

<h3>Fiabilité des séries macroéconomiques, par décennie</h3>
${g.tableau(
    ["Période", "Inflation", "Salaire moyen", "Productivité", "Ensemble"],
    periodes,
    ["", "", "", "", ""],
  )}
<p class="discret">Une projection ne se fait jamais passer pour une observation :
au-delà de la dernière année observée, la fiabilité retombe à « estimée ».</p>

<h3>Fiabilité des ${simulateur.catalogue.taille} régimes</h3>
${g.tableau(["Niveau", "Nombre", "Régimes"], regimes, ["", "nombre", ""])}

<h3>Sources</h3>
<p>Dix-neuf institutions sont recensées dans
<a href="${g.DEPOT}/blob/main/data/sources.yaml">data/sources.yaml</a> : INSEE,
COR, Comité de suivi des retraites, DREES, CNAV, Service des retraites de l'État,
Caisse des dépôts, Direction de la Sécurité sociale, Cour des comptes,
Agirc-Arrco, Union Retraite, CCMSA, CNAVPL, CNBF, DGAFP, Direction du Budget,
ERAFP, Ircantec, caisses des régimes spéciaux, Urssaf.</p>
<p>Chaque valeur porte son niveau de fiabilité — <code>certifiee</code>,
<code>haute</code>, <code>moyenne</code>, <code>estimee</code> — et la fiabilité
d'un résultat est celle de son maillon le plus faible.</p>
<p><a href="${g.DEPOT}/blob/main/docs/limites.md">Limites détaillées</a></p>
`;
}
