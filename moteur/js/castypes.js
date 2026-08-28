/**
 * Cas types — le « cas général », par opposition au cas particulier.
 *
 * Portage de ``src/retraite_notionnelle/castypes.py``. Une simulation
 * individuelle répond à « et moi ? » ; les cas types répondent à « et
 * globalement ? ». On croise un jeu de carrières représentatives avec un jeu de
 * générations, et l'on regarde comment la réforme déplace chacune d'elles.
 *
 * Les carrières retenues suivent l'esprit des cas types du Conseil
 * d'orientation des retraites : elles ne prétendent pas décrire un individu
 * réel, mais isoler l'effet des règles à comportement donné. Elles couvrent
 * volontairement les cas extrêmes du système — régime spécial à départ précoce,
 * carrière interrompue — parce que ce sont eux que la réforme déplace le plus.
 */

/** Jeu de cas types couvrant les principales configurations du système. */
export const CAS_TYPES = [
  {
    code: "smic_carriere_complete",
    libelle: "Salarié au niveau du SMIC, carrière complète",
    affiliation: "salarie_prive_non_cadre",
    age_debut: 18, age_liquidation: 64, niveau_salaire: 0.55,
    profil_carriere: "plat",
    commentaire: "Carrière longue à bas salaire : le cas où les minima pèsent le plus.",
  },
  {
    code: "salaire_moyen",
    libelle: "Salarié au salaire moyen",
    affiliation: "salarie_prive_non_cadre",
    age_debut: 21, age_liquidation: 64, niveau_salaire: 1.0,
    commentaire: "Référence centrale.",
  },
  {
    code: "cadre",
    libelle: "Cadre du privé",
    affiliation: "salarie_prive_cadre",
    age_debut: 23, age_liquidation: 64, niveau_salaire: 2.2,
    profil_carriere: "fortement_ascendant",
    commentaire: "Forte part de rémunération au-dessus du plafond.",
  },
  {
    code: "carriere_interrompue",
    libelle: "Carrière interrompue (5 ans hors emploi)",
    affiliation: "salarie_prive_non_cadre",
    age_debut: 21, age_liquidation: 64, niveau_salaire: 0.9,
    sexe: "F", nombre_enfants: 2,
    interruptions_relatives: [8, 9, 10, 11, 12].map((d) => [d, "education_enfant"]),
    commentaire: "Cinq années sans cotisation. Le système actuel les compense par "
      + "l'AVPF et la majoration de durée d'assurance ; le compte notionnel ne "
      + "compense rien. Écart maximal entre les scénarios.",
  },
  {
    code: "fonctionnaire_sedentaire",
    libelle: "Fonctionnaire sédentaire (catégorie B)",
    affiliation: "fonctionnaire_etat",
    age_debut: 22, age_liquidation: 64, niveau_salaire: 1.2,
    part_primes: 0.18,
    commentaire: "Traitement indiciaire hors primes ; les primes relèvent du RAFP.",
  },
  {
    code: "fonctionnaire_actif",
    libelle: "Fonctionnaire de catégorie active (départ à 57 ans)",
    affiliation: "fonctionnaire_territorial_hospitalier",
    age_debut: 22, age_liquidation: 57, niveau_salaire: 1.1,
    part_primes: 0.22,
    commentaire: "Départ anticipé de dix ans par rapport à l'âge de référence.",
  },
  {
    code: "agent_sncf_conduite",
    libelle: "Agent de conduite SNCF (départ à 52 ans)",
    affiliation: "agent_sncf",
    age_debut: 20, age_liquidation: 52, niveau_salaire: 1.1,
    commentaire: "Écart à l'âge de référence parmi les plus élevés du système.",
  },
  {
    code: "agent_ieg",
    libelle: "Agent des industries électriques et gazières",
    affiliation: "agent_ieg",
    age_debut: 21, age_liquidation: 57, niveau_salaire: 1.4,
    commentaire: "Régime spécial fermé aux embauches depuis 2023.",
  },
  {
    code: "artisan",
    libelle: "Artisan",
    affiliation: "artisan",
    age_debut: 24, age_liquidation: 64, niveau_salaire: 0.9,
    commentaire: "Assiette de cotisation plus faible que celle d'un salarié.",
  },
  {
    code: "exploitant_agricole",
    libelle: "Chef d'exploitation agricole",
    affiliation: "exploitant_agricole",
    age_debut: 20, age_liquidation: 64, niveau_salaire: 0.5,
    commentaire: "Retraite majoritairement forfaitaire aujourd'hui : la part non "
      + "contributive disparaît intégralement dans les scénarios notionnels.",
  },
  {
    code: "profession_liberale",
    libelle: "Profession libérale",
    affiliation: "profession_liberale",
    age_debut: 27, age_liquidation: 66, niveau_salaire: 2.5,
    profil_carriere: "fortement_ascendant",
    commentaire: "Régime complémentaire de section non paramétré : résultat incomplet.",
  },
  {
    code: "contractuel_public",
    libelle: "Agent contractuel de la fonction publique",
    affiliation: "contractuel_public",
    age_debut: 24, age_liquidation: 64, niveau_salaire: 0.85,
    commentaire: "Régime général + Ircantec.",
  },
].map((cas) => ({
  profil_carriere: "ascendant",
  sexe: "H",
  nombre_enfants: 0,
  part_primes: 0.0,
  interruptions_relatives: [],
  ...cas,
}));

/**
 * Générations couvertes par défaut : de la première génération entièrement
 * couverte par la Sécurité sociale aux actifs entrés récemment.
 */
export const GENERATIONS = [1940, 1950, 1960, 1970, 1980, 1990, 2000];

/** Construit la carrière d'un cas type pour une génération donnée. */
export function construireCasType(cas, simulateur, generation) {
  const interruptions = new Map(
    cas.interruptions_relatives.map(([decalage, motif]) => [
      Math.trunc(generation + cas.age_debut + decalage), motif,
    ]),
  );
  return simulateur.carriereSimple({
    annee_naissance: generation,
    sexe: cas.sexe,
    affiliation: cas.affiliation,
    age_debut: cas.age_debut,
    age_liquidation: cas.age_liquidation,
    niveau_salaire: cas.niveau_salaire,
    profil_carriere: cas.profil_carriere,
    interruptions,
    nombre_enfants: cas.nombre_enfants,
    part_primes: cas.part_primes,
    identifiant: `${cas.libelle} (génération ${generation})`,
  });
}

/**
 * Calcule la grille complète cas type × génération.
 *
 * Les combinaisons impossibles — un régime qui n'existait pas encore, une
 * liquidation avant l'origine de la répartition — sont écartées avec leur motif
 * plutôt que de faire échouer l'ensemble.
 */
export function calculerCasTypes(simulateur, casTypes = CAS_TYPES, generations = GENERATIONS) {
  const resultats = new Map();
  const echecs = new Map();
  for (const cas of casTypes) {
    for (const generation of generations) {
      const cle = `${cas.code}|${generation}`;
      try {
        const carriere = construireCasType(cas, simulateur, generation);
        if (carriere.anneeLiquidation <= simulateur.parametres.annee_debut_repartition) {
          echecs.set(cle, "liquidation antérieure à la répartition");
          continue;
        }
        const regimesConnus = carriere.lignes.some(
          (ligne) => simulateur.affiliations.regimes(cas.affiliation, ligne.annee).length > 0,
        );
        if (!regimesConnus) {
          echecs.set(cle, "aucun régime actif sur la période");
          continue;
        }
        resultats.set(cle, simulateur.simuler(carriere));
      } catch (erreur) {
        echecs.set(cle, erreur.message);
      }
    }
  }
  return { resultats, echecs };
}
