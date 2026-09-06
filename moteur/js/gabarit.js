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

export const LIENS = [
  ["/", "Simuler"],
  ["/cas-types", "Cas types"],
  ["/cout", "Coût"],
  ["/methode", "Méthode"],
  ["/donnees", "Données"],
];

/**
 * Adresse d'une page interne.
 *
 * Le site tient dans une seule page : la navigation passe par l'ancre de
 * l'adresse (`#/cas-types`). L'ancre de section, elle, ne peut pas s'y ajouter
 * — la place est prise — et n'est acceptée que pour que les appels disent vers
 * quoi ils pointent.
 */
export function lien(chemin, ancre = "") {
  return `#${chemin}`;
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


// -- graphiques --------------------------------------------------------------
//
// Le dépôt n'a pas de bibliothèque de tracé, et n'en aura pas : le site charge
// ses propres fichiers et rien d'autre. Les graphiques sont donc du SVG écrit à
// la main, en deux exemplaires — ici et dans ``web/gabarit.py`` —, et comparés
// caractère par caractère par les témoins. D'où deux règles de construction
// qu'il ne faut pas enfreindre :
//
//   * toutes les coordonnées passent par ``nombreBrut``, qui arrondit comme
//     Python le fait, pour que les deux rendus produisent la même chaîne ;
//   * le pas des graduations est cherché par ITÉRATION sur une échelle de
//     valeurs rondes, jamais par un logarithme, dont les deux langages ne
//     garantissent pas le même dernier bit.

/** Cadre de tracé, en unités du ``viewBox``. */
export const LARGEUR_TRACE = 720;
export const HAUTEUR_TRACE = 300;
export const MARGE_GAUCHE = 66;
/**
 * La marge de droite loge la MOITIÉ de la dernière graduation d'abscisse,
 * qui est centrée sur elle : trop étroite, « 2024 » déborderait du viewBox.
 */
export const MARGE_DROITE = 24;
export const MARGE_HAUT = 26;
export const MARGE_BAS = 28;

/**
 * Nombre d'intervalles de l'axe vertical. Cinq : assez pour lire, assez peu
 * pour ne pas encombrer, et surtout assez pour qu'un maximum de 427 tienne dans
 * une échelle qui monte à 500 plutôt qu'à 800.
 */
export const DIVISIONS_Y = 5;

/** Échelle des pas de graduation admissibles, multipliée par des puissances de dix. */
const PAS_RONDS = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0];

/**
 * Écart minimal, en années, entre une décennie graduée et une borne de l'axe.
 * Les bornes sont graduées d'office — ce sont elles qui datent la série —, et
 * une décennie trop proche de l'une d'elles ne fait que chevaucher son
 * étiquette. Six ans : « 2020 » et « 2024 » ne tiennent pas côte à côte sur
 * l'écran d'un téléphone, où les textes du repère sont grossis.
 */
const ECART_MINIMAL_GRADUATIONS = 6;

/** Une courbe ou une bande d'un graphique. */
export class Serie {
  constructor(libelle, valeurs, couleur, tirets = false, glose = "") {
    this.libelle = libelle;
    this.valeurs = valeurs;
    this.couleur = couleur;
    this.tirets = tirets;
    this.glose = glose;
  }
}

/** Nombre à l'anglaise, pour un attribut SVG — jamais pour du texte lu. */
export function nombreBrut(valeur, decimales = 1) {
  return formatFixe(valeur, decimales);
}

/** Plus petit pas rond dont ``divisions`` intervalles couvrent ``maximum``. */
export function pasGraduation(maximum, divisions = DIVISIONS_Y) {
  if (maximum <= 0) {
    return 1.0;
  }
  let base = 1e-9;
  while (base < 1e12) {
    for (const facteur of PAS_RONDS) {
      const pas = base * facteur;
      if (pas * divisions >= maximum) {
        return pas;
      }
    }
    base *= 10.0;
  }
  return base;
}

function abscisse(annee, premiere, derniere) {
  const largeur = LARGEUR_TRACE - MARGE_GAUCHE - MARGE_DROITE;
  if (derniere === premiere) {
    return MARGE_GAUCHE + largeur / 2;
  }
  return MARGE_GAUCHE + largeur * ((annee - premiere) / (derniere - premiere));
}

function ordonnee(valeur, sommet) {
  const hauteur = HAUTEUR_TRACE - MARGE_HAUT - MARGE_BAS;
  if (sommet <= 0) {
    return HAUTEUR_TRACE - MARGE_BAS;
  }
  return HAUTEUR_TRACE - MARGE_BAS - hauteur * (valeur / sommet);
}

/** Décennies comprises dans la plage, plus les deux bornes. */
function graduationsX(premiere, derniere) {
  const annees = [];
  for (let a = premiere; a <= derniere; a += 1) {
    if (a % 10 === 0) annees.push(a);
  }
  if (!annees.includes(premiere)) annees.unshift(premiere);
  if (!annees.includes(derniere)) annees.push(derniere);
  // Deux graduations trop proches se chevauchent : on retire la décennie
  // voisine plutôt que la borne, qui porte l'information.
  return annees.filter(
    (a) => a === premiere || a === derniere
      || (a - premiere >= ECART_MINIMAL_GRADUATIONS
        && derniere - a >= ECART_MINIMAL_GRADUATIONS),
  );
}

/** Chemin SVG d'une courbe, interrompu là où la série n'a pas de valeur. */
function chemin(serie, annees, sommet) {
  const morceaux = [];
  let commence = false;
  annees.forEach((annee, rang) => {
    const valeur = serie.valeurs[rang];
    if (valeur === null || valeur === undefined) {
      commence = false;
      return;
    }
    const x = nombreBrut(abscisse(annee, annees[0], annees[annees.length - 1]));
    const y = nombreBrut(ordonnee(valeur, sommet));
    morceaux.push(`${commence ? "L" : "M"}${x} ${y}`);
    commence = true;
  });
  return morceaux.join(" ");
}

/** Chemin fermé d'une bande empilée : le dessus à l'aller, le dessous au retour. */
function bande(basses, hautes, annees, sommet) {
  const derniere = annees[annees.length - 1];
  const aller = annees.map((annee, rang) => `${rang === 0 ? "M" : "L"}`
    + `${nombreBrut(abscisse(annee, annees[0], derniere))} `
    + `${nombreBrut(ordonnee(hautes[rang], sommet))}`);
  const retour = [];
  for (let rang = annees.length - 1; rang >= 0; rang -= 1) {
    retour.push(`L${nombreBrut(abscisse(annees[rang], annees[0], derniere))} `
      + `${nombreBrut(ordonnee(basses[rang], sommet))}`);
  }
  return `${aller.concat(retour).join(" ")} Z`;
}

/** Sommet de l'axe vertical et pas de graduation. */
function sommetEchelle(series, empile) {
  let maximum = 0.0;
  if (empile) {
    for (let rang = 0; rang < series[0].valeurs.length; rang += 1) {
      let somme = 0.0;
      for (const serie of series) {
        const valeur = serie.valeurs[rang];
        if (valeur !== null && valeur !== undefined) somme += valeur;
      }
      if (somme > maximum) maximum = somme;
    }
  } else {
    for (const serie of series) {
      for (const valeur of serie.valeurs) {
        if (valeur !== null && valeur !== undefined && valeur > maximum) {
          maximum = valeur;
        }
      }
    }
  }
  const pas = pasGraduation(maximum);
  return { sommet: pas * DIVISIONS_Y, pas };
}

/**
 * Graphique en courbes, ou en bandes empilées si ``empile``.
 *
 * ``titre`` n'est pas affiché : il est le texte alternatif du SVG, c'est-à-dire
 * ce que lit une synthèse vocale. Ce que voit l'œil est dans la légende et dans
 * la phrase qui précède le graphique.
 */
export function graphique(titre, annees, series, unite = "", empile = false,
                          decimales = 0, legendeVisible = true) {
  if (!annees.length || !series.length) {
    return "";
  }
  const { sommet, pas } = sommetEchelle(series, empile);
  const derniereAnnee = annees[annees.length - 1];
  const gauche = nombreBrut(abscisse(annees[0], annees[0], derniereAnnee));
  const droite = nombreBrut(abscisse(derniereAnnee, annees[0], derniereAnnee));

  const lignes = [];
  for (let division = 0; division <= DIVISIONS_Y; division += 1) {
    const valeur = pas * division;
    const y = nombreBrut(ordonnee(valeur, sommet));
    lignes.push(`<line class="grille" x1="${gauche}" y1="${y}" x2="${droite}" y2="${y}"/>`
      + `<text class="graduation" x="${nombreBrut(MARGE_GAUCHE - 6)}" y="${y}" `
      + `dy="0.32em" text-anchor="end">${nombre(valeur, decimales)}</text>`);
  }
  const base = nombreBrut(ordonnee(0.0, sommet));
  for (const annee of graduationsX(annees[0], derniereAnnee)) {
    const x = nombreBrut(abscisse(annee, annees[0], derniereAnnee));
    lignes.push(`<text class="graduation" x="${x}" `
      + `y="${nombreBrut(HAUTEUR_TRACE - MARGE_BAS + 16)}" `
      + `text-anchor="middle">${annee}</text>`);
  }

  const traces = [];
  if (empile) {
    // La PREMIÈRE série est la bande du BAS : la légende se lit alors dans
    // l'ordre du graphique, de bas en haut, et non à l'envers.
    let cumul = annees.map(() => 0.0);
    for (const serie of series) {
      const hautes = cumul.map((bas, position) => {
        const valeur = serie.valeurs[position];
        return bas + (valeur === null || valeur === undefined ? 0.0 : valeur);
      });
      traces.push(`<path class="bande" fill="${serie.couleur}" `
        + `d="${bande(cumul, hautes, annees, sommet)}"/>`);
      cumul = hautes;
    }
  } else {
    for (const serie of series) {
      const tirets = serie.tirets ? ' stroke-dasharray="5 4"' : "";
      traces.push(`<path class="courbe" stroke="${serie.couleur}"${tirets} `
        + `d="${chemin(serie, annees, sommet)}"/>`);
    }
  }

  const uniteHtml = unite
    ? `<text class="graduation" x="${nombreBrut(MARGE_GAUCHE - 6)}" `
      + `y="${nombreBrut(MARGE_HAUT - 10)}" text-anchor="end">${echapper(unite)}</text>`
    : "";
  return '<figure class="graphique">'
    + `<svg viewBox="0 0 ${LARGEUR_TRACE} ${HAUTEUR_TRACE}" role="img" `
    + `aria-label="${echapper(titre)}">`
    + lignes.join("") + traces.join("")
    + `<line class="axe" x1="${gauche}" y1="${base}" x2="${droite}" y2="${base}"/>`
    + uniteHtml
    + `</svg>${legendeVisible ? legende(series) : ""}</figure>`;
}

function legende(series) {
  const entrees = series.map((serie) => '<li><span class="pastille" '
    + `style="background:${serie.couleur}"></span>`
    + `<span>${echapper(serie.libelle)}`
    + (serie.glose ? ` <span class="discret">${echapper(serie.glose)}</span>` : "")
    + "</span></li>").join("");
  return `<ul class="legende">${entrees}</ul>`;
}
