/**
 * Fusion de tous les régimes sur le cas le plus défavorable.
 *
 * Portage de ``src/retraite_notionnelle/moteur/fusion.py``. À compter de
 * l'année de bascule, les régimes disparaissent au profit d'un régime unique
 * dont chaque paramètre est, paramètre par paramètre, le plus défavorable à
 * l'assuré : âge d'ouverture et âge du taux plein les plus élevés, durée
 * requise la plus longue, salaire de référence le moins avantageux, assiette la
 * plus large, aucun avantage non contributif.
 *
 * Le taux de cotisation fait exception, et c'est le seul paramètre qui ne suive
 * pas la règle littérale : le retenir « au plus défavorable » n'aurait pas de
 * sens, un taux plus faible réduisant tout autant les droits que les
 * prélèvements. Le régime fusionné retient la somme des taux d'un statut pivot
 * — régime général plus Agirc-Arrco — c'est-à-dire l'effort contributif
 * réellement consenti aujourd'hui pour une retraite complète.
 */

import { formatPourcentage } from "./format.js";

/**
 * Ordre des salaires de référence, du plus avantageux au moins avantageux. La
 * carrière entière est la moins avantageuse : elle intègre les années de début
 * de carrière, les plus faibles.
 */
export const ORDRE_SALAIRE_REFERENCE = [
  "derniers_6_mois",
  "dernier_salaire",
  "10_meilleures_annees",
  "25_meilleures_annees",
  "carriere_entiere",
  "sans_objet",
];

export const CritereTaux = Object.freeze({
  //: Somme des taux du statut pivot (base + complémentaire).
  SOMME_PIVOT: "somme_pivot",
  LE_PLUS_ELEVE: "le_plus_eleve",
  LE_PLUS_FAIBLE: "le_plus_faible",
  MOYENNE_PONDEREE: "moyenne_ponderee",
});

export const REGLE_FUSION_DEFAUT = Object.freeze({
  critere_taux: CritereTaux.SOMME_PIVOT,
  //: Régimes dont les taux sont additionnés en mode ``SOMME_PIVOT``.
  regimes_pivot: ["regime_general", "agirc_arrco"],
  //: Familles exclues de la fusion. La capitalisation reste à part.
  familles_exclues: ["additionnel_capitalise"],
});

/** Premier maximum, comme ``max`` en Python : à égalité, le premier gagne. */
function premierExtremum(candidats, cle, comparateur) {
  let retenu = candidats[0];
  for (const candidat of candidats.slice(1)) {
    if (comparateur(cle(candidat), cle(retenu))) {
      retenu = candidat;
    }
  }
  return retenu;
}

const plusGrand = (a, b) => a > b;
const plusPetit = (a, b) => a < b;

/** Construit le régime unique applicable à compter de ``annee``. */
export function fusionner(catalogue, annee, regle = REGLE_FUSION_DEFAUT) {
  const candidats = [];
  for (const regime of catalogue) {
    if (regle.familles_exclues.includes(regime.famille) || regime.hors_repartition) {
      continue;
    }
    if (!regime.vivant(annee)) {
      continue;
    }
    for (const periode of regime.periodesActives(annee)) {
      candidats.push([regime, periode]);
    }
  }

  if (candidats.length === 0) {
    throw new Error(`aucun régime vivant en ${annee} : fusion impossible`);
  }

  const extremum = (cle, comparateur) => {
    const retenu = premierExtremum(candidats, (couple) => cle(couple[1]), comparateur);
    return [cle(retenu[1]), retenu[0].code];
  };

  const [ageOuverture, origineOuverture] = extremum((p) => p.age_ouverture, plusGrand);
  const [ageTauxPlein, origineTauxPlein] = extremum((p) => p.age_taux_plein, plusGrand);

  const avecDuree = candidats.filter((c) => c[1].duree_requise_trimestres !== null);
  let duree;
  let origineDuree;
  if (avecDuree.length > 0) {
    const retenu = premierExtremum(
      avecDuree, (c) => c[1].duree_requise_trimestres, plusGrand,
    );
    duree = retenu[1].duree_requise_trimestres;
    origineDuree = retenu[0].code;
  } else {
    duree = 172;
    origineDuree = "défaut";
  }

  // Salaire de référence le moins avantageux : le plus loin dans l'ordre.
  // `sans_objet` n'est pas un désavantage mais une absence d'information : on
  // ne le retient que si aucun autre régime n'a de salaire de référence.
  const rang = (periode) => {
    const indice = ORDRE_SALAIRE_REFERENCE.indexOf(periode.salaire_reference);
    return indice === -1 ? ORDRE_SALAIRE_REFERENCE.length : indice;
  };
  const exploitables = candidats.filter((c) => c[1].salaire_reference !== "sans_objet");
  const baseSalaire = exploitables.length > 0 ? exploitables : candidats;
  const retenuSalaire = premierExtremum(baseSalaire, (c) => rang(c[1]), plusGrand);
  const salaireReference = retenuSalaire[1].salaire_reference;
  const origineSalaire = retenuSalaire[0].code;

  let taux;
  let origineTaux;
  if (regle.critere_taux === CritereTaux.SOMME_PIVOT) {
    taux = 0.0;
    const composantes = [];
    for (const code of regle.regimes_pivot) {
      if (!catalogue.contient(code)) {
        continue;
      }
      const actives = catalogue.obtenir(code).periodesActives(annee);
      if (actives.length === 0) {
        continue;
      }
      // Pour un régime à tranches, on retient la tranche 1 : c'est celle qui
      // s'applique à l'ensemble des rémunérations.
      const pivot = premierExtremum(actives, (p) => p.bornesAssietteEnPass()[0], plusPetit);
      taux += pivot.taux_cotisation_retraite;
      composantes.push(`${code} ${formatPourcentage(pivot.taux_cotisation_retraite, 2)}`);
    }
    if (taux <= 0) {
      throw new Error(
        `aucun régime pivot exploitable en ${annee} parmi ${regle.regimes_pivot}`,
      );
    }
    origineTaux = `somme ${composantes.join(" + ")}`;
  } else if (regle.critere_taux === CritereTaux.LE_PLUS_ELEVE) {
    [taux, origineTaux] = extremum((p) => p.taux_cotisation_retraite, plusGrand);
  } else if (regle.critere_taux === CritereTaux.LE_PLUS_FAIBLE) {
    [taux, origineTaux] = extremum((p) => p.taux_cotisation_retraite, plusPetit);
  } else {
    let somme = 0.0;
    for (const [, periode] of candidats) {
      somme += periode.taux_cotisation_retraite;
    }
    taux = somme / candidats.length;
    origineTaux = "moyenne des régimes";
  }

  let fiabilite = candidats[0][0].fiabilite;
  for (const [regime] of candidats) {
    fiabilite = Math.min(fiabilite, regime.fiabilite);
  }

  return {
    annee_bascule: annee,
    age_ouverture: ageOuverture,
    age_taux_plein: ageTauxPlein,
    duree_requise_trimestres: duree,
    salaire_reference: salaireReference,
    assiette: "deplafonnee",
    taux_cotisation_retraite: taux,
    avantages_non_contributifs: [],
    origines: {
      age_ouverture: origineOuverture,
      age_taux_plein: origineTauxPlein,
      duree_requise_trimestres: origineDuree,
      salaire_reference: origineSalaire,
      taux_cotisation_retraite: origineTaux,
    },
    regimes_fusionnes: [...new Set(candidats.map(([regime]) => regime.code))].sort(),
    fiabilite,
  };
}
