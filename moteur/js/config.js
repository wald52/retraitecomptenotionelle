/**
 * Paramètres de configuration du modèle.
 *
 * Portage de ``src/retraite_notionnelle/config.py``. Toutes les décisions de
 * modélisation contestables sont réunies ici, en un seul endroit, pour qu'on
 * puisse les faire varier sans toucher au moteur. Les valeurs par défaut
 * correspondent au cahier des charges : indexation par « triple lock inversé »,
 * âge de référence à cliquet, neutralisation intégrale des droits non
 * contributifs, fusion des régimes au cas le plus défavorable.
 */

/** Règle de revalorisation des comptes et des pensions. */
export const ModeIndexation = Object.freeze({
  //: min(inflation, croissance du salaire moyen nominal, productivité réelle).
  //: C'est la règle demandée, littéralement. Elle mêle un taux réel à deux taux
  //: nominaux : en période de forte inflation, le minimum est presque toujours
  //: la productivité réelle, ce qui écrase la valeur réelle des comptes.
  TRIPLE_LOCK_INVERSE: "triple_lock_inverse",
  //: Variante homogène : les trois termes sont ramenés en nominal.
  TRIPLE_LOCK_INVERSE_NOMINAL: "triple_lock_inverse_nominal",
  //: Indexation sur les seuls prix (règle en vigueur depuis 1993).
  PRIX: "prix",
  //: Indexation sur le salaire moyen (règle antérieure à 1987).
  SALAIRES: "salaires",
});

/**
 * Que faire de la contribution employeur des régimes publics et spéciaux.
 *
 * Les fiches ne stockent pas la même chose selon le secteur : total salarié +
 * employeur pour le privé (25,7 %), retenue de l'agent seule pour la fonction
 * publique et les régimes spéciaux (11,10 %). `alignee_sur_le_prive` substitue
 * aux seconds le taux total du statut pivot privé, seul traitement qui rende
 * les statuts comparables. `exclue` conserve le taux stocké tel quel.
 */
export const ContributionEmployeurPublic = Object.freeze({
  EXCLUE: "exclue",
  ALIGNEE_SUR_LE_PRIVE: "alignee_sur_le_prive",
});

/** Origine du flux qui alimente le compte notionnel. */
export const SourceCotisations = Object.freeze({
  TAUX_HISTORIQUES: "taux_historiques",
  TAUX_UNIFORME: "taux_uniforme",
});

/** Construction de l'âge auquel une liquidation est réputée « à l'heure ». */
export const ModeAgeReference = Object.freeze({
  //: Cliquet sur l'âge du taux plein du régime général : l'âge de référence ne
  //: redescend jamais.
  CLIQUET_LEGAL: "cliquet_legal",
  //: Cliquet légal jusqu'à la bascule, puis indexation sur l'espérance de vie.
  CLIQUET_PUIS_ESPERANCE_VIE: "cliquet_puis_esperance_vie",
  //: Âge du taux plein de l'année de liquidation, sans cliquet — contrefactuel.
  LEGAL_SANS_CLIQUET: "legal_sans_cliquet",
});

/**
 * Âge auquel les droits figés à la bascule sont convertis en capital.
 *
 * ``REFERENCE`` valorise au diviseur de l'âge de référence : un assuré qui
 * liquide avant cet âge subit, sur ses droits déjà ouverts, un abattement égal
 * au rapport des deux diviseurs. ``LIQUIDATION`` valorise au diviseur de l'âge
 * effectif de départ, ce qui rend la conversion neutre.
 */
export const AgeConversionDroitsAcquis = Object.freeze({
  REFERENCE: "reference",
  LIQUIDATION: "liquidation",
});

/** Table de mortalité servant au coefficient de conversion. */
export const TableConversion = Object.freeze({
  UNISEXE: "unisexe",
  PAR_SEXE: "par_sexe",
});

/**
 * Droits retirés du calcul, conformément au principe « seules les cotisations
 * comptent ». Chaque drapeau à ``true`` signifie : ce droit est SUPPRIMÉ dans
 * les scénarios notionnels. Le scénario « système actuel » les conserve tous.
 */
export const NEUTRALISATIONS_DEFAUT = Object.freeze({
  minimum_contributif: true,
  minimum_garanti: true,
  minimum_vieillesse_aspa: true,
  pension_majoree_reference: true,
  majoration_enfants: true,
  majoration_duree_assurance: true,
  assurance_vieillesse_parents_au_foyer: true,
  reversion: true,
  bonifications: true,
  categorie_active: true,
  periodes_assimilees: true,
  garantie_minimale_points: true,
  carriere_longue: true,
  decote_surcote: true,
  coefficient_solidarite: true,
});

/** Jeu complet de paramètres d'une simulation. */
export const PARAMETRES_DEFAUT = Object.freeze({
  // --- Bornes temporelles ---------------------------------------------------
  //: Année d'origine du système par répartition. 1941 = allocation aux vieux
  //: travailleurs salariés, premier mécanisme financé par les cotisations.
  annee_debut_repartition: 1941,
  //: Les droits acquis jusqu'à cette année incluse suivent les règles
  //: actuelles, les droits postérieurs le compte notionnel du régime fusionné.
  annee_bascule: 2026,
  annee_courante: 2026,
  //: Année dans les euros de laquelle les résultats sont exprimés.
  annee_euros_constants: 2026,
  //: Scénario de projection macroéconomique au-delà de la dernière observation.
  scenario_projection: "cor_central",

  // --- Indexation -----------------------------------------------------------
  mode_indexation: ModeIndexation.TRIPLE_LOCK_INVERSE,
  //: ``null`` = aucun plancher : le triple lock inversé peut être négatif, ce
  //: qui est sa conséquence logique et non un défaut.
  plancher_indexation: null,
  indexer_pensions_liquidees: true,

  // --- Cotisations ----------------------------------------------------------
  source_cotisations: SourceCotisations.TAUX_HISTORIQUES,
  taux_cotisation_uniforme: 0.2531,
  //: Ce qui a été prélevé pour la retraite ouvre des droits, taux d'appel
  //: compris.
  taux_appel_ouvre_droits: true,
  //: Traitement de la contribution employeur des régimes publics et spéciaux.
  traitement_contribution_employeur_etat:
    ContributionEmployeurPublic.ALIGNEE_SUR_LE_PRIVE,
  statut_pivot_cotisations: "salarie_prive_non_cadre",
  //: Plafonnement de l'assiette notionnelle, en multiples du plafond annuel de
  //: la Sécurité sociale. ``null`` = assiette déplafonnée.
  plafond_assiette_en_pass: 8.0,

  // --- Âge de référence -----------------------------------------------------
  mode_age_reference: ModeAgeReference.CLIQUET_LEGAL,
  ratio_cible_retraite_carriere: 0.5,

  // --- Conversion en rente --------------------------------------------------
  table_conversion: TableConversion.UNISEXE,
  //: Taux de préfinancement incorporé au diviseur. 0 : le diviseur est
  //: l'espérance de vie résiduelle actualisée au même taux que l'indexation,
  //: les deux se compensant exactement.
  taux_anticipe_conversion: 0.0,
  //: Âge de conversion des droits figés à la bascule, dans le scénario
  //: prospectif. ``reference`` fait payer l'anticipation une seconde fois sur
  //: des droits déjà ouverts ; ``liquidation`` rend la conversion neutre.
  age_conversion_droits_acquis: AgeConversionDroitsAcquis.REFERENCE,
  //: Table de génération plutôt que table du moment.
  table_generation: true,
  age_maximal: 120,

  // --- Fusion des régimes ---------------------------------------------------
  fusion_au_plus_defavorable: true,

  // --- Neutralisations ------------------------------------------------------
  neutralisations: NEUTRALISATIONS_DEFAUT,

  // --- Compartiments hors répartition ---------------------------------------
  isoler_capitalisation: true,

  // --- Contrôle qualité des données -----------------------------------------
  fiabilite_minimale: "estimee",
});

/** Copie modifiée : les paramètres sont traités comme immuables. */
export function avec(parametres, modifications) {
  return Object.freeze({ ...parametres, ...modifications });
}

/** Clé stable d'un jeu de paramètres, pour mémoriser un simulateur par jeu. */
export function cleParametres(parametres) {
  return JSON.stringify(parametres, Object.keys(parametres).sort());
}
