/**
 * Le moteur JavaScript contre les cas-témoins du modèle Python.
 *
 * Le Python de ``src/`` reste la référence : il a été écrit contre les sources,
 * testé et documenté. Ce fichier vérifie que le JavaScript qui fait tourner le
 * site en retrouve les chiffres — et le HTML — sur un jeu de cas figé par
 * ``scripts/construire_temoins.py``. Toute divergence, sur n'importe quelle
 * valeur de l'un des cas, fait échouer le test.
 *
 *     node --test tests/js/
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { Contexte, Saisie, rendre } from "../../moteur/js/pages.js";

const RACINE = join(dirname(fileURLToPath(import.meta.url)), "..", "..");

const lire = (chemin) => JSON.parse(readFileSync(join(RACINE, chemin), "utf8"));

const paquet = lire("moteur/donnees.json");
const temoinsSimulations = lire("tests/temoins/simulations.json");
const temoinsPages = lire("tests/temoins/pages.json");

/**
 * Tolérance relative. Python et JavaScript s'appuient sur la libm de leur
 * plateforme pour ``exp`` : deux implémentations correctes peuvent différer
 * d'un ulp, soit 1e-16 en relatif. On accepte 1e-9, six ordres de grandeur
 * au-dessus du bruit et six en dessous de ce qui se verrait à l'affichage.
 */
const TOLERANCE = 1e-9;

function comparer(obtenu, attendu, chemin, ecarts) {
  if (attendu === null) {
    // Le témoin écrit ``null`` là où Python produit NaN — écart non défini.
    if (!(obtenu === null || Number.isNaN(obtenu))) {
      ecarts.push(`${chemin} : attendu null, obtenu ${obtenu}`);
    }
    return;
  }
  if (typeof attendu === "number") {
    if (typeof obtenu !== "number") {
      ecarts.push(`${chemin} : attendu un nombre, obtenu ${typeof obtenu}`);
      return;
    }
    const ecart = Math.abs(obtenu - attendu);
    const relatif = attendu === 0 ? ecart : ecart / Math.abs(attendu);
    if (relatif > TOLERANCE) {
      ecarts.push(`${chemin} : python=${attendu} js=${obtenu} (écart ${relatif.toExponential(2)})`);
    }
    return;
  }
  if (Array.isArray(attendu)) {
    if (!Array.isArray(obtenu) || obtenu.length !== attendu.length) {
      ecarts.push(`${chemin} : tableau de ${attendu.length} attendu, obtenu ${
        Array.isArray(obtenu) ? obtenu.length : typeof obtenu}`);
      return;
    }
    attendu.forEach((valeur, i) => comparer(obtenu[i], valeur, `${chemin}[${i}]`, ecarts));
    return;
  }
  if (attendu !== null && typeof attendu === "object") {
    const clesAttendues = Object.keys(attendu).sort();
    const clesObtenues = Object.keys(obtenu ?? {}).sort();
    assert.deepEqual(clesObtenues, clesAttendues, `clés différentes en ${chemin}`);
    for (const cle of clesAttendues) {
      comparer(obtenu[cle], attendu[cle], `${chemin}.${cle}`, ecarts);
    }
    return;
  }
  if (obtenu !== attendu) {
    ecarts.push(`${chemin} : python=${JSON.stringify(attendu)} js=${JSON.stringify(obtenu)}`);
  }
}

test("les simulations retrouvent les chiffres du modèle Python", () => {
  const contexte = new Contexte(paquet);
  const ecarts = [];
  let cas = 0;
  for (const [nom, temoin] of Object.entries(temoinsSimulations)) {
    const saisie = Saisie.depuisRequete(temoin.requete);
    const obtenu = contexte.simuler(saisie).dictionnaire();
    comparer(obtenu, temoin.resultat, nom, ecarts);
    cas += 1;
  }
  assert.ok(cas > 50, `${cas} cas seulement : les témoins sont-ils à jour ?`);
  assert.deepEqual(ecarts, [], `${ecarts.length} écart(s) sur ${cas} cas`);
});

test("les pages rendent le même HTML que le modèle Python", () => {
  const contexte = new Contexte(paquet);
  for (const [nom, temoin] of Object.entries(temoinsPages)) {
    const [titre, corps] = rendre(contexte, temoin.chemin, temoin.parametres);
    assert.equal(titre, temoin.titre, `titre de la page « ${nom} »`);
    assert.equal(sansBlocJson(corps), temoin.corps, `corps de la page « ${nom} »`);
  }
});

/**
 * Le bloc JSON de la page reprend les chiffres déjà comparés un à un ; ne
 * subsisterait que l'écriture des flottants, que Python et JavaScript ne
 * formatent pas de la même façon. On le retire des deux côtés, comme le fait le
 * générateur de témoins.
 */
function sansBlocJson(html) {
  return html.replace(/(<pre class="json">)[\s\S]*?(<\/pre>)/g, "$1$2");
}
