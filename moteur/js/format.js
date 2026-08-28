/**
 * Primitives de formatage compatibles avec Python.
 *
 * Le site affiche les mêmes chiffres que la référence Python et que la CLI :
 * il faut donc arrondir comme elle. Or Python et JavaScript ne tranchent pas
 * les demis de la même façon — ``format(-12.5, '.0f')`` donne ``-12`` (arrondi
 * au pair) là où ``(-12.5).toFixed(0)`` donne ``-13`` (arrondi à l'écart). Sur
 * une grille de cas types en pourcentages entiers, l'écart se voit.
 *
 * On ne s'en remet donc pas à ``toFixed`` : le développement décimal EXACT du
 * flottant est reconstruit en arithmétique entière — tout double est un
 * rationnel dyadique, donc son écriture décimale est finie — puis arrondi au
 * pair. Le résultat est celui de Python, chiffre pour chiffre, sans heuristique
 * sur les cas limites.
 */

const TAMPON = new DataView(new ArrayBuffer(8));

/**
 * Développement décimal exact d'un flottant positif.
 * @returns {{entier: string, decimales: string}}
 */
function developpementExact(valeur) {
  TAMPON.setFloat64(0, valeur);
  const bits = TAMPON.getBigUint64(0);
  const exposantBrut = Number((bits >> 52n) & 0x7ffn);
  const fraction = bits & 0xfffffffffffffn;

  let mantisse;
  let exposant;
  if (exposantBrut === 0) {
    mantisse = fraction;
    exposant = -1074;
  } else {
    mantisse = fraction | (1n << 52n);
    exposant = exposantBrut - 1075;
  }

  if (mantisse === 0n) {
    return { entier: "0", decimales: "" };
  }
  if (exposant >= 0) {
    return { entier: (mantisse << BigInt(exposant)).toString(), decimales: "" };
  }
  // valeur = mantisse / 2^k = mantisse · 5^k / 10^k : exact, et fini.
  const k = -exposant;
  const chiffres = (mantisse * 5n ** BigInt(k)).toString().padStart(k + 1, "0");
  return {
    entier: chiffres.slice(0, chiffres.length - k),
    decimales: chiffres.slice(chiffres.length - k),
  };
}

/** Déplace la virgule de ``rang`` chiffres vers la droite. */
function decaler(developpement, rang) {
  if (rang === 0) {
    return developpement;
  }
  const decimales = developpement.decimales.padEnd(rang, "0");
  return {
    entier: developpement.entier + decimales.slice(0, rang),
    decimales: decimales.slice(rang),
  };
}

/** Arrondit un développement décimal à ``decimales`` chiffres, au pair. */
function arrondirAuPair(developpement, decimales) {
  const gardees = developpement.decimales.slice(0, decimales).padEnd(decimales, "0");
  const reste = developpement.decimales.slice(decimales);

  let monter = false;
  if (reste.length > 0) {
    const premier = reste[0];
    const suite = reste.slice(1).replace(/0+$/, "");
    if (premier > "5" || (premier === "5" && suite.length > 0)) {
      monter = true;
    } else if (premier === "5") {
      // Demi exact : on monte seulement si le dernier chiffre gardé est impair.
      const dernier = decimales > 0
        ? gardees[decimales - 1]
        : developpement.entier[developpement.entier.length - 1];
      monter = Number(dernier) % 2 === 1;
    }
  }

  let chiffres = developpement.entier + gardees;
  if (monter) {
    chiffres = (BigInt(chiffres) + 1n).toString().padStart(chiffres.length, "0");
  }
  const coupure = chiffres.length - decimales;
  const entier = (chiffres.slice(0, coupure) || "0").replace(/^0+(?=\d)/, "");
  return { entier, decimales: chiffres.slice(coupure) };
}

/** Groupe les milliers, comme le ``,`` du format Python. */
function grouper(entier) {
  return entier.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/**
 * Équivalent de ``f"{valeur:,.Nf}"`` (ou ``f"{valeur:.Nf}"`` sans groupes).
 */
export function formatFixe(valeur, decimales, groupes = false) {
  return _format(valeur, decimales, groupes, 0, "");
}

/**
 * Équivalent de ``f"{valeur:.N%}"``.
 *
 * CPython multiplie par 100 en virgule flottante avant de formater, et non par
 * décalage décimal : c'est cette multiplication qui fait de ``2.675`` un
 * ``268 %`` et non un ``267 %``. On la reproduit telle quelle.
 */
export function formatPourcentage(valeur, decimales) {
  return `${formatFixe(valeur * 100, decimales)}%`;
}

function _format(valeur, decimales, groupes, rang, suffixe) {
  if (!Number.isFinite(valeur)) {
    return (Number.isNaN(valeur) ? "nan" : (valeur > 0 ? "inf" : "-inf")) + suffixe;
  }
  const negatif = valeur < 0 || Object.is(valeur, -0);
  const arrondi = arrondirAuPair(
    decaler(developpementExact(Math.abs(valeur)), rang), decimales,
  );
  const entier = groupes ? grouper(arrondi.entier) : arrondi.entier;
  const partie = decimales > 0 ? `.${arrondi.decimales}` : "";
  return `${negatif ? "-" : ""}${entier}${partie}${suffixe}`;
}

/**
 * Équivalent de ``f"{valeur:g}"`` : six chiffres significatifs, zéros de fin
 * retirés, notation exponentielle hors de la plage utile.
 */
export function formatG(valeur, precision = 6) {
  if (!Number.isFinite(valeur)) {
    return Number.isNaN(valeur) ? "nan" : (valeur > 0 ? "inf" : "-inf");
  }
  if (valeur === 0) {
    return Object.is(valeur, -0) ? "-0" : "0";
  }
  const exponentielle = Math.abs(valeur).toExponential(precision - 1);
  const exposant = Number(exponentielle.slice(exponentielle.indexOf("e") + 1));

  if (exposant < -4 || exposant >= precision) {
    const [mantisse, puissance] = exponentielle.split("e");
    const signe = Number(puissance) < 0 ? "-" : "+";
    const chiffres = String(Math.abs(Number(puissance))).padStart(2, "0");
    return `${valeur < 0 ? "-" : ""}${_sansZerosInutiles(mantisse)}e${signe}${chiffres}`;
  }
  return _sansZerosInutiles(formatFixe(valeur, Math.max(precision - 1 - exposant, 0)));
}

function _sansZerosInutiles(texte) {
  if (!texte.includes(".")) {
    return texte;
  }
  return texte.replace(/\.?0+$/, "");
}

/** Équivalent de ``round(valeur)`` en Python : arrondi au pair. */
export function arrondi(valeur) {
  const bas = Math.floor(valeur);
  const reste = valeur - bas;
  if (reste > 0.5) {
    return bas + 1;
  }
  if (reste < 0.5) {
    return bas;
  }
  return bas % 2 === 0 ? bas : bas + 1;
}

/** Équivalent de ``html.escape`` (avec ``quote=True``). */
export function echapper(texte) {
  return String(texte)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#x27;");
}
