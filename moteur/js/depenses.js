/**
 * Ce que la retraite a coûté : les dépenses réellement versées, depuis 1959.
 *
 * Portage de ``src/retraite_notionnelle/donnees/depenses.py``. Le reste du
 * modèle calcule des DROITS — ce qu'une carrière ouvre ; ce module porte la
 * grandeur inverse, ce que la collectivité a effectivement payé.
 *
 * La source est unique : les Comptes de la protection sociale de la DREES,
 * risque vieillesse-survie. Le total tous régimes court de 1959 à 2024 sans
 * trou ; la ventilation par système ne commence qu'en 1990, parce que la
 * nomenclature d'avant ne se raccorde pas à celle d'après.
 */

import { SerieAnnuelle } from "./serie.js";

/**
 * Les treize postes de la ventilation, dans l'ordre d'affichage : la
 * répartition obligatoire d'abord, par masse décroissante en 2024, puis ce qui
 * n'en relève pas. `repartition` dit si le système relève de la répartition
 * OBLIGATOIRE — le risque vieillesse-survie porte aussi la capitalisation,
 * l'aide sociale aux personnes âgées et le minimum vieillesse, et l'on ne
 * compare pas des comptes notionnels à une allocation d'autonomie.
 */
export const SYSTEMES = [
  {
    code: "regime_general",
    libelle: "Régime général (Cnav)",
    glose: "Le socle des salariés du privé. Il absorbe depuis 2020 les artisans "
      + "et les commerçants, dont le régime a été adossé à la Cnav : la marche "
      + "de cette année-là est une réorganisation, pas une dépense nouvelle.",
    repartition: true,
  },
  {
    code: "agirc_arrco",
    libelle: "Agirc-Arrco",
    glose: "Les complémentaires des salariés du privé, deux caisses jusqu'en "
      + "2018 et une seule depuis. À elles seules, un quart de la dépense.",
    repartition: true,
  },
  {
    code: "fonction_publique_etat",
    libelle: "Fonction publique d'État",
    glose: "Les pensions civiles et militaires de l'État, versées par le compte "
      + "d'affectation spéciale « Pensions ». La territoriale et l'hospitalière "
      + "n'y sont pas : la DREES les range avec les régimes spéciaux.",
    repartition: true,
  },
  {
    code: "regimes_speciaux",
    libelle: "Régimes spéciaux",
    glose: "La CNRACL — fonction publique territoriale et hospitalière —, la "
      + "SNCF, la RATP, les industries électriques et gazières et les autres, "
      + "réunies par la comptabilité nationale sous un seul poste.",
    repartition: true,
  },
  {
    code: "exploitants_agricoles",
    libelle: "Exploitants agricoles",
    glose: "Le régime des chefs d'exploitation, dont la dépense recule en euros "
      + "constants depuis trente ans : ses cotisants ont disparu avant ses "
      + "pensionnés.",
    repartition: true,
  },
  {
    code: "professions_liberales",
    libelle: "Professions libérales (CNAVPL)",
    glose: "Base et complémentaires des sections professionnelles.",
    repartition: true,
  },
  {
    code: "salaries_agricoles",
    libelle: "Salariés agricoles",
    glose: "Le régime aligné de la MSA.",
    repartition: true,
  },
  {
    code: "ircantec",
    libelle: "Ircantec",
    glose: "La complémentaire des agents non titulaires de l'État et des "
      + "collectivités.",
    repartition: true,
  },
  {
    code: "non_salaries_autres",
    libelle: "Autres régimes de non-salariés",
    glose: "Ce qui reste des régimes de non-salariés une fois les exploitants "
      + "agricoles et les professions libérales mis à part — la part la plus "
      + "réduite depuis l'adossement du RSI à la Cnav.",
    repartition: true,
  },
  {
    code: "repartition_autres",
    libelle: "Autres régimes par répartition",
    glose: "Fonds spéciaux, régimes résiduels, prestations vieillesse versées "
      + "par les branches maladie et famille.",
    repartition: true,
  },
  {
    code: "solidarite_etat",
    libelle: "Solidarité de l'État",
    glose: "Minimum vieillesse et crédits d'impôt liés à l'âge. Non "
      + "contributif : aucun compte notionnel ne le porterait, et c'est "
      + "précisément ce que les scénarios notionnels retirent.",
    repartition: false,
  },
  {
    code: "aide_sociale_locale",
    libelle: "Aide sociale des collectivités",
    glose: "Allocation personnalisée d'autonomie, hébergement des personnes "
      + "âgées dépendantes. Ce n'est pas de la retraite : c'est de la "
      + "dépendance, que le risque vieillesse-survie loge au même endroit.",
    repartition: false,
  },
  {
    code: "supplementaire",
    libelle: "Retraite supplémentaire",
    glose: "Capitalisation : RAFP, contrats collectifs d'assurance, de "
      + "prévoyance et de mutuelle, régimes d'entreprise. Un capital est placé "
      + "— c'est ce qui la sépare de tout le reste de ce tableau.",
    repartition: false,
  },
];

export const CODES_SYSTEMES = SYSTEMES.map((systeme) => systeme.code);

/** Les dépenses observées, avec leur ventilation et le PIB qui les rapporte. */
export class DepensesRetraite {
  constructor(paquet) {
    const brut = paquet.depenses;
    const serie = (cle) => SerieAnnuelle.depuisPaquet(cle, brut[cle]);
    this.total = serie("total");
    this.pib = serie("pib_courant");
    this.systemes = new Map(
      SYSTEMES.map((systeme) => [systeme.code, serie(systeme.code)]),
    );
    this.premiereAnnee = this.total.premiereAnnee;
    this.derniereAnnee = this.total.derniereAnnee;
    this.premiereAnneeVentilee = Math.max(
      ...SYSTEMES.map((systeme) => this.systemes.get(systeme.code).premiereAnnee),
    );
  }

  annees() {
    const liste = [];
    for (let a = this.premiereAnnee; a <= this.derniereAnnee; a += 1) liste.push(a);
    return liste;
  }

  anneesVentilees() {
    const liste = [];
    for (let a = this.premiereAnneeVentilee; a <= this.derniereAnnee; a += 1) {
      liste.push(a);
    }
    return liste;
  }

  /** Dépense totale du risque vieillesse-survie, en millions d'euros courants. */
  depense(annee) {
    return this.total.valeur(annee);
  }

  depenseSysteme(code, annee) {
    return this.systemes.get(code).valeur(annee);
  }

  /** Part de la dépense dans le produit intérieur brut de la même année. */
  partPib(annee) {
    return this.total.valeur(annee) / this.pib.valeur(annee);
  }

  /**
   * Ce que coûte la seule répartition obligatoire, ventilation à l'appui.
   * Le total publié est plus large : il porte aussi la capitalisation, l'aide
   * sociale aux personnes âgées et le minimum vieillesse.
   */
  repartition(annee) {
    let somme = 0;
    for (const systeme of SYSTEMES) {
      if (systeme.repartition) somme += this.depenseSysteme(systeme.code, annee);
    }
    return somme;
  }

  fiabilite(annee) {
    return Math.min(this.total.fiabilite(annee), this.pib.fiabilite(annee));
  }
}
