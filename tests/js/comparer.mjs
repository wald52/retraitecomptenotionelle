/**
 * Compare le moteur JavaScript à des cas calculés par le modèle Python.
 *
 *     node tests/js/comparer.mjs cas.json
 *
 * Le fichier attendu est une liste d'objets ``{requete, resultat}`` — ou
 * ``{requete, erreur}`` quand le modèle Python refuse de calculer. C'est le
 * format que produit ``tests/test_web.py``, qui tire des carrières au hasard :
 * les témoins figés de ``tests/temoins/`` couvrent des cas choisis, celui-ci
 * couvre ceux auxquels personne n'a pensé.
 *
 * Sortie : un compte rendu sur la sortie standard, et un code de retour non nul
 * dès la première divergence.
 */

import { readFileSync } from "node:fs";

import { Contexte, Saisie } from "../../moteur/js/pages.js";

/** Voir tests/js/moteur.test.js : un ulp de bruit sur ``exp``, pas davantage. */
const TOLERANCE = 1e-9;

const [, , fichierCas, fichierPaquet = "moteur/donnees.json"] = process.argv;
if (!fichierCas) {
  console.error("usage : node tests/js/comparer.mjs <cas.json> [donnees.json]");
  process.exit(2);
}

const cas = JSON.parse(readFileSync(fichierCas, "utf8"));
const contexte = new Contexte(JSON.parse(readFileSync(fichierPaquet, "utf8")));

const divergences = [];
let valeurs = 0;
let exactes = 0;
let pire = 0;
let refus = 0;

function comparer(obtenu, attendu, chemin) {
  if (attendu === null) {
    // Le générateur écrit ``null`` là où Python produit NaN — écart non défini.
    if (!(obtenu === null || Number.isNaN(obtenu))) {
      divergences.push(`${chemin} : attendu null, obtenu ${obtenu}`);
    }
    return;
  }
  if (typeof attendu === "number") {
    valeurs += 1;
    if (typeof obtenu !== "number") {
      divergences.push(`${chemin} : attendu un nombre, obtenu ${typeof obtenu}`);
      return;
    }
    const ecart = attendu === 0
      ? Math.abs(obtenu)
      : Math.abs(obtenu - attendu) / Math.abs(attendu);
    if (ecart === 0) {
      exactes += 1;
    }
    if (ecart > pire) {
      pire = ecart;
    }
    if (ecart > TOLERANCE) {
      divergences.push(`${chemin} : python=${attendu} js=${obtenu}`);
    }
    return;
  }
  if (Array.isArray(attendu)) {
    attendu.forEach((valeur, i) => comparer(obtenu?.[i], valeur, `${chemin}[${i}]`));
    return;
  }
  if (typeof attendu === "object") {
    for (const cle of Object.keys(attendu)) {
      comparer(obtenu?.[cle], attendu[cle], `${chemin}.${cle}`);
    }
    return;
  }
  if (obtenu !== attendu) {
    divergences.push(`${chemin} : python=${JSON.stringify(attendu)} js=${JSON.stringify(obtenu)}`);
  }
}

cas.forEach((temoin, i) => {
  const nom = temoin.nom ?? `cas ${i}`;
  let obtenu = null;
  let leve = null;
  try {
    obtenu = contexte.simuler(Saisie.depuisRequete(temoin.requete)).dictionnaire();
  } catch (erreur) {
    leve = erreur;
  }

  if (temoin.erreur !== undefined) {
    // Python a refusé : le JavaScript doit refuser aussi. Le libellé exact du
    // message n'est comparé que sur les cas figés de moteur.test.js.
    refus += 1;
    if (leve === null) {
      divergences.push(`${nom} : Python refuse (« ${temoin.erreur} »), pas le JavaScript`);
    }
    return;
  }
  if (leve !== null) {
    divergences.push(`${nom} : le JavaScript refuse un cas que Python calcule — ${leve.message}`);
    return;
  }
  comparer(obtenu, temoin.resultat, nom);
});

console.log(`${cas.length} cas comparés, dont ${refus} refusés des deux côtés`);
console.log(`${valeurs} valeurs numériques, ${exactes} identiques au bit près`
  + ` (${((100 * exactes) / Math.max(valeurs, 1)).toFixed(1)} %)`);
console.log(`écart relatif maximal : ${pire.toExponential(2)}`);

if (divergences.length > 0) {
  console.error(`\n${divergences.length} divergence(s) :`);
  for (const divergence of divergences.slice(0, 20)) {
    console.error(`  ${divergence}`);
  }
  process.exit(1);
}
