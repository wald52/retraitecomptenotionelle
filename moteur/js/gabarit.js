/**
 * Rendu HTML, sans moteur de gabarits.
 *
 * Portage de ``src/retraite_notionnelle/web/gabarit.py``. Les fonctions
 * ci-dessous assemblent du HTML et échappent systématiquement ce qui vient de
 * l'utilisateur.
 *
 * La feuille de style, elle, n'est pas dupliquée ici : elle reste écrite dans
 * le module Python, d'où ``scripts/construire_donnees.py`` l'extrait vers
 * ``moteur/style.css``, que la page charge directement. Une seule source, deux
 * consommateurs.
 */

import { echapper, formatFixe } from "./format.js";

export const DEPOT = "https://github.com/wald52/retraitecomptenotionelle";

/** Espace insécable fin, séparateur de milliers à la française. */
const FINE = "\u202f";

/**
 * « serveur » : une adresse par page, servie par FastAPI. « navigateur » : tout
 * tourne dans le navigateur et la navigation se fait par l'ancre de l'adresse.
 * Le rendu est identique ; seuls les liens changent.
 */
export const etat = { mode: "navigateur" };

export const LIENS = [
  ["/", "Simuler"],
  ["/cas-types", "Cas types"],
  ["/methode", "Méthode"],
  ["/donnees", "Données"],
];

export function dansLeNavigateur() {
  return etat.mode === "navigateur";
}

/** Adresse d'une page interne, selon le mode de service. */
export function lien(chemin, ancre = "") {
  if (dansLeNavigateur()) {
    return `#${chemin}`;
  }
  return chemin + (ancre ? `#${ancre}` : "");
}

export function navigation(cheminActif = "/") {
  return LIENS.map(([chemin, libelle]) => `<a href="${lien(chemin)}"`
    + (chemin === cheminActif ? ' aria-current="page"' : "")
    + `>${echapper(libelle)}</a>`).join("");
}

export function entete(cheminActif = "/") {
  return `<header class="bandeau"><div class="interieur">
  <h1><a href="${lien("/")}">Retraite à comptes notionnels</a></h1>
  <nav>${navigation(cheminActif)}</nav>
</div></header>`;
}

export function pied() {
  return `<footer>
  <p>Modèle ouvert, code et données sur <a href="${DEPOT}">GitHub</a> (licence MIT).
  Les montants sont bruts, exprimés en euros constants de l'année de référence.
  Les séries d'avant 1950 et les paramètres de régime restent saisis à la main :
  <a href="${DEPOT}/blob/main/docs/limites.md">lire les limites</a> avant de citer un chiffre.</p>
</footer>`;
}

// -- fragments ---------------------------------------------------------------

/** Nombre à la française : virgule décimale, espace insécable des milliers. */
export function nombre(valeur, decimales = 2) {
  return formatFixe(valeur, decimales, true).replace(/,/g, FINE).replace(".", ",");
}

/** Montant en euros. */
export function euros(montant) {
  return `${nombre(montant, 0)}${FINE}€`;
}

export function pourcentage(valeur, signe = false, decimales = 1) {
  let texte = nombre(valeur * 100, decimales);
  if (signe && valeur >= 0) {
    texte = `+${texte}`;
  }
  return `${texte}${FINE}%`;
}

const GROUPES = /\d{1,3}(?:,\d{3})+(?:\.\d+)?/g;
const DECIMAL = /\d+\.\d+/g;
const AVANT_POURCENT = /(\d)%/g;

/**
 * Convertit les nombres à l'anglaise produits par le moteur.
 *
 * « 17,542 € × rendement 6.00% » devient « 17 542 € × rendement 6,00 % ». Le
 * moteur formate ses libellés de calcul pour un terminal ; la page web les
 * présente à un lecteur francophone, pour qui « 17,542 » se lit 17,5.
 */
export function franciser(texte) {
  return texte
    .replace(GROUPES, (trouve) => trouve.replace(/,/g, FINE))
    .replace(DECIMAL, (trouve) => trouve.replace(".", ","))
    .replace(AVANT_POURCENT, `$1${FINE}%`);
}

export function champ(nom, libelle, valeur, aide = "", type = "text", attributs = {}) {
  const supplement = Object.entries(attributs)
    .map(([cle, val]) => ` ${cle.replace(/_+$/, "").replace(/_/g, "-")}="${echapper(val)}"`)
    .join("");
  const aideHtml = aide ? `<span class="aide">${echapper(aide)}</span>` : "";
  return `<div><label for="${nom}">${echapper(libelle)}${aideHtml}</label>`
    + `<input type="${type}" id="${nom}" name="${nom}" `
    + `value="${echapper(valeur)}"${supplement}></div>`;
}

export function liste(nom, libelle, options, selection, aide = "") {
  const choix = options.map(([code, texte]) => `<option value="${echapper(code)}"`
    + (code === selection ? " selected" : "")
    + `>${echapper(texte)}</option>`).join("");
  const aideHtml = aide ? `<span class="aide">${echapper(aide)}</span>` : "";
  return `<div><label for="${nom}">${echapper(libelle)}${aideHtml}</label>`
    + `<select id="${nom}" name="${nom}">${choix}</select></div>`;
}

/** Cellule de tableau portant une teinte de fond proportionnelle à sa valeur. */
export class Cellule {
  constructor(html, intensite = 0.0) {
    this.html = html;
    this.intensite = intensite;
  }

  style() {
    if (!this.intensite) {
      return "";
    }
    // Teintes calibrées pour rester lisibles sur fond clair comme sur fond
    // sombre : rouge = pension plus faible, vert-de-gris = pension plus forte.
    const couleur = this.intensite < 0 ? "162, 71, 46" : "90, 116, 80";
    const alpha = Math.min(Math.abs(this.intensite), 1.0) * 0.3;
    return ` style="background: rgba(${couleur}, ${formatFixe(alpha, 2)})"`;
  }
}

export function tableau(entetes, lignes, classesColonnes = null) {
  const classes = classesColonnes || entetes.map(() => "");
  const tete = entetes.map((titre, i) => `<th class="${classes[i]}" scope="col">`
    + `${echapper(titre)}</th>`).join("");
  const corps = lignes.map((ligne) => `<tr>${
    ligne.slice(0, classes.length).map((cellule, i) => `<td class="${classes[i]}"`
      + (cellule instanceof Cellule ? cellule.style() : "")
      + ">"
      + (cellule instanceof Cellule ? cellule.html : cellule)
      + "</td>").join("")
  }</tr>`).join("");
  return `<div class="defilant"><table><thead><tr>${tete}</tr></thead>`
    + `<tbody>${corps}</tbody></table></div>`;
}

export function fiche(etiquette, valeur) {
  return `<div class="fiche"><div class="valeur">${valeur}</div>`
    + `<div class="etiquette">${echapper(etiquette)}</div></div>`;
}
