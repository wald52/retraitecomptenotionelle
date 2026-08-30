/**
 * Compte notionnel : accumulation des cotisations et liquidation.
 *
 * Portage de ``src/retraite_notionnelle/moteur/compte.py``. Le compte notionnel
 * est un compte virtuel : on y inscrit chaque année les cotisations retraite
 * réellement versées, on le revalorise au taux d'indexation retenu, et on
 * divise le solde final par un coefficient de conversion actuariel. Aucun
 * capital n'est placé — le système reste intégralement en répartition.
 *
 * Trois principes tiennent tout le reste : seules les cotisations comptent ;
 * l'année du versement fixe la valeur du droit ; l'âge de liquidation fixe le
 * partage.
 */

import { SourceCotisations, ContributionEmployeurPublic,
} from "./config.js";
import { ContributionsEmployeurPubliques } from "./regimes.js";
import { Fiabilite } from "./serie.js";

/** Construit un compte notionnel à partir d'une carrière. */
export class ConstructeurCompte {
  constructor(macro, catalogue, affiliations, indexation, parametres) {
    this.macro = macro;
    this.catalogue = catalogue;
    this.affiliations = affiliations;
    this.indexation = indexation;
    this.parametres = parametres;
    this._tauxPivot = new Map();
    this.contributionsPubliques = new ContributionsEmployeurPubliques(macro.paquet);
  }

  // -- taux ------------------------------------------------------------------

  /**
   * Taux total salarié + employeur du statut pivot privé, cette année-là.
   * Sert de référence aux régimes dont la fiche ne stocke que la retenue de
   * l'agent. On somme les régimes dont l'assiette commence au premier euro,
   * pour ne pas compter deux fois les tranches hautes.
   */
  tauxPivotPrive(annee) {
    if (this._tauxPivot.has(annee)) {
      return this._tauxPivot.get(annee);
    }
    let total = 0.0;
    for (const code of this.affiliations.regimes(
      this.parametres.statut_pivot_cotisations, annee,
    )) {
      if (!this.catalogue.contient(code)) {
        continue;
      }
      const regime = this.catalogue.obtenir(code);
      if (regime.hors_repartition) {
        continue;
      }
      for (const periode of regime.periodesActives(annee)) {
        const [borneBasse] = periode.bornesAssietteEnPass();
        if (borneBasse > 0) {
          continue;
        }
        total += periode.taux_cotisation_retraite;
      }
    }
    this._tauxPivot.set(annee, total);
    return total;
  }

  /**
   * Taux à porter au compte, sa part employeur, d'où elle vient et ce qu'elle
   * vaut. Les trois derniers termes ne valent que pour les régimes dont la
   * fiche s'arrête à la retenue de l'agent, et seulement dans les scénarios 4
   * et 5.
   *
   * @returns {[number, number, string, number]} taux, part employeur, origine,
   *   fiabilité.
   */
  tauxEffectif(regime, periode, annee) {
    const taux = periode.taux_cotisation_retraite;
    const traitement = this.parametres.traitement_contribution_employeur_etat;
    if (periode.perimetre_taux !== "agent_seul") {
      return [taux, 0.0, "", Fiabilite.CERTIFIEE];
    }

    if (traitement === ContributionEmployeurPublic.FINANCEMENT_HISTORIQUE) {
      // La retenue de l'agent, plus ce que l'employeur public a versé.
      const contribution = this.contributionsPubliques.taux(regime, annee);
      if (contribution !== null) {
        return [taux + contribution[0], contribution[0], contribution[1], contribution[2]];
      }
      // Aucune série pour ce régime cette année-là : on retombe sur
      // l'alignement du scénario 2, et le résultat le dit. La part employeur
      // reste à zéro : l'écart entre la retenue et le taux du privé est une
      // convention de comparaison, pas une cotisation qu'on aurait versée.
      const pivot = this.tauxPivotPrive(annee);
      return [pivot > 0 ? pivot : taux, 0.0, "repli", Fiabilite.ESTIMEE];
    }

    if (traitement === ContributionEmployeurPublic.ALIGNEE_SUR_LE_PRIVE) {
      // La fiche ne porte que la retenue de l'agent : on lui substitue l'effort
      // contributif complet d'un salarié de la même année.
      const pivot = this.tauxPivotPrive(annee);
      if (pivot > 0) {
        return [pivot, 0.0, "", Fiabilite.CERTIFIEE];
      }
    }
    return [taux, 0.0, "", Fiabilite.CERTIFIEE];
  }

  /**
   * Taux du régime unique, après la bascule — et ce que l'employeur y met.
   *
   * Le taux du régime unique est une convention — la somme des taux du statut
   * pivot privé — qui efface toute trace de ce que verse un employeur public.
   * Sous `financement_historique`, le régime unique conserve donc, pour un agent
   * public, l'effort contributif réel de son régime, ramené à l'assiette élargie
   * du régime unique en le multipliant par la part hors primes.
   *
   * @returns {[number, number, string, number]} taux, part employeur, origine,
   *   fiabilité.
   */
  tauxUnifie(ligne, annee, regimeFusionne) {
    if (this.parametres.source_cotisations !== SourceCotisations.TAUX_HISTORIQUES) {
      return [this.parametres.taux_cotisation_uniforme, 0.0, "", Fiabilite.CERTIFIEE];
    }
    const unifie = regimeFusionne.taux_cotisation_retraite;
    if (this.parametres.traitement_contribution_employeur_etat
        !== ContributionEmployeurPublic.FINANCEMENT_HISTORIQUE) {
      return [unifie, 0.0, "", Fiabilite.CERTIFIEE];
    }

    for (const code of this.affiliations.regimes(ligne.affiliation, annee)) {
      if (!this.catalogue.contient(code)) {
        continue;
      }
      const regime = this.catalogue.obtenir(code);
      if (regime.hors_repartition) {
        continue;
      }
      for (const periode of regime.periodesActives(annee)) {
        if (periode.perimetre_taux !== "agent_seul") {
          continue;
        }
        const part = periode.assiette === "hors_primes"
          ? 1.0 - ligne.part_primes : 1.0;
        const contribution = this.contributionsPubliques.taux(code, annee);
        if (contribution === null) {
          return [unifie, 0.0, "repli", Fiabilite.ESTIMEE];
        }
        return [
          (periode.taux_cotisation_retraite + contribution[0]) * part,
          contribution[0] * part,
          contribution[1],
          contribution[2],
        ];
      }
    }
    // Statut privé : la fiche porte déjà le total, le régime unique aussi.
    return [unifie, 0.0, "", Fiabilite.CERTIFIEE];
  }

  /**
   * Réunion d'intervalles d'assiette, sans recouvrement.
   *
   * Un taux d'acquisition commun s'applique une fois à la rémunération, et non
   * une fois par régime : les régimes qui découpent la même tranche doivent se
   * réunir, pas s'ajouter. ``null`` en borne haute vaut « sans plafond de
   * régime » — le plafond global du modèle s'applique ensuite.
   */
  static fusionner(bornes) {
    const ordonnees = [...bornes].sort((a, b) => (
      a[0] - b[0]
      || (a[1] === null ? 1 : 0) - (b[1] === null ? 1 : 0)
      || (a[1] ?? 0) - (b[1] ?? 0)
    ));
    const fusionnees = [];
    for (const [basse, haute] of ordonnees) {
      if (fusionnees.length === 0) {
        fusionnees.push([basse, haute]);
        continue;
      }
      const [precedenteBasse, precedenteHaute] = fusionnees[fusionnees.length - 1];
      if (precedenteHaute !== null && basse > precedenteHaute) {
        fusionnees.push([basse, haute]);
      } else if (precedenteHaute === null || haute === null) {
        fusionnees[fusionnees.length - 1] = [precedenteBasse, null];
      } else {
        fusionnees[fusionnees.length - 1] = [
          precedenteBasse, Math.max(precedenteHaute, haute),
        ];
      }
    }
    return fusionnees;
  }

  _baseSelonAssiette(assiette, baseLigne, partPrimes) {
    if (assiette === "primes_uniquement") {
      return baseLigne * partPrimes;
    }
    if (assiette === "hors_primes") {
      return baseLigne * (1.0 - partPrimes);
    }
    return baseLigne;
  }

  // -- assiette --------------------------------------------------------------

  /** Part du revenu comprise entre deux bornes exprimées en plafonds. */
  /**
   * Part du revenu comprise entre deux bornes, exprimées EN EUROS.
   *
   * Le plafond global du modèle, lui, reste en plafonds de la Sécurité sociale :
   * c'est un paramètre de simulation, pas une règle de régime.
   */
  _assiette(revenu, annee, plancher, plafondPeriode) {
    const pass = this.macro.plafond_securite_sociale.valeur(annee);
    const plafondGlobal = this.parametres.plafond_assiette_en_pass;
    let plafond;
    if (plafondPeriode === null) {
      plafond = plafondGlobal === null ? revenu : plafondGlobal * pass;
    } else {
      plafond = plafondPeriode;
      if (plafondGlobal !== null) {
        plafond = Math.min(plafond, plafondGlobal * pass);
      }
    }
    return Math.max(0.0, Math.min(revenu, plafond) - plancher);
  }

  // -- cotisation d'une année ------------------------------------------------

  cotisationAnnuelle(carriere, annee, regimeFusionne = null) {
    const ligne = carriere.ligne(annee);
    if (ligne === null
        || (!ligne.cotise && ligne.familles_cotisantes.length === 0)) {
      return {
        annee, revenu: 0.0, assiette_retenue: 0.0, cotisation: 0.0,
        regimes: [], taux_effectif: 0.0, hors_repartition: 0.0,
        fiabilite: Fiabilite.CERTIFIEE, nulle: true, origine_part_employeur: "",
        part_employeur: 0.0,
      };
    }

    // Après la bascule, un seul régime : le régime fusionné.
    if (regimeFusionne !== null && annee >= regimeFusionne.annee_bascule) {
      const assiette = this._assiette(ligne.revenu, annee, 0.0, null);
      const [taux, tauxEmployeur, origine, fiabiliteTaux] = this.tauxUnifie(
        ligne, annee, regimeFusionne,
      );
      const cotisation = assiette * taux;
      return {
        annee, revenu: ligne.revenu, assiette_retenue: assiette, cotisation,
        regimes: ["regime_unifie"], taux_effectif: taux, hors_repartition: 0.0,
        fiabilite: origine
          ? Math.min(regimeFusionne.fiabilite, fiabiliteTaux)
          : regimeFusionne.fiabilite,
        nulle: cotisation <= 0,
        origine_part_employeur: origine,
        part_employeur: assiette * tauxEmployeur,
      };
    }

    // Pendant une période indemnisée, seuls les régimes complémentaires
    // encaissent, et sur le salaire d'avant l'interruption.
    const baseLigne = ligne.cotise ? ligne.revenu : ligne.revenu_reference;
    const famillesAdmises = ligne.cotise ? null : new Set(ligne.familles_cotisantes);

    const codes = this.affiliations.regimes(ligne.affiliation, annee);
    let cotisation = 0.0;
    let assietteTotale = 0.0;
    let horsRepartition = 0.0;
    let fiabilite = Fiabilite.CERTIFIEE;
    const retenus = [];
    const origines = [];
    let partEmployeur = 0.0;

    // Taux d'acquisition commun (``source_cotisations = taux_uniforme``) : un
    // seul taux, prélevé une fois sur la rémunération. Les régimes en
    // répartition n'y servent plus qu'à délimiter l'assiette, qu'on réunit
    // avant de prélever. Le compartiment de capitalisation garde ses taux
    // propres.
    const acquisitionCommune = this.parametres.source_cotisations
      === SourceCotisations.TAUX_UNIFORME;
    const intervalles = new Map();

    for (const code of codes) {
      if (!this.catalogue.contient(code)) {
        continue;
      }
      const regime = this.catalogue.obtenir(code);
      if (famillesAdmises !== null && !famillesAdmises.has(regime.famille)) {
        continue;
      }
      fiabilite = Math.min(fiabilite, regime.fiabilite);
      const enRepartition = !(
        regime.hors_repartition && this.parametres.isoler_capitalisation
      );
      for (const periode of regime.periodesActives(annee)) {
        const [borneBasse, borneHaute] = periode.bornesAssietteEnEuros(
          this.macro.plafond_securite_sociale.valeur(annee),
        );

        const base = this._baseSelonAssiette(
          periode.assiette, baseLigne, ligne.part_primes,
        );

        if (acquisitionCommune && enRepartition) {
          // Regroupées par ASSIETTE DE DÉPART, et non par régime : c'est la
          // même rémunération qu'on découpe. Les planchers d'assiette propres à
          // un régime ne survivent pas non plus : un taux unique porte sur la
          // rémunération réelle.
          if (this._assiette(base, annee, borneBasse, borneHaute) > 0) {
            const groupe = (periode.assiette === "primes_uniquement"
              || periode.assiette === "hors_primes") ? periode.assiette : "total";
            if (!intervalles.has(groupe)) {
              intervalles.set(groupe, []);
            }
            intervalles.get(groupe).push([borneBasse, borneHaute]);
            retenus.push(code);
          }
          continue;
        }

        let assiette = this._assiette(base, annee, borneBasse, borneHaute);
        const repere = periode.repereAssiette(
          this.macro.plafond_securite_sociale.valeur(annee),
          this.macro.smic_horaire.valeur(annee),
        );
        if (periode.assiette_plancher && assiette < repere) {
          // Assiette minimale : la complémentaire agricole prélève sur
          // 1 820 SMIC même quand le revenu est en dessous. Ce qui a été
          // prélevé ouvre des droits, ici comme dans le scénario 1.
          assiette = repere;
        }
        if (assiette <= 0) {
          continue;
        }

        const [taux, tauxEmployeur, origine, fiabiliteTaux] = this.tauxEffectif(
          code, periode, annee,
        );
        if (origine) {
          origines.push(origine);
          fiabilite = Math.min(fiabilite, fiabiliteTaux);
        }
        const montant = assiette * taux;

        if (regime.hors_repartition && this.parametres.isoler_capitalisation) {
          // RAFP, assurances sociales d'avant-guerre : ces droits sont
          // provisionnés, ils ne rejoignent pas le compte notionnel.
          horsRepartition += montant;
        } else {
          cotisation += montant;
          assietteTotale += assiette;
          partEmployeur += assiette * tauxEmployeur;
        }
        retenus.push(code);
      }
    }

    if (acquisitionCommune) {
      const tauxCommun = this.parametres.taux_cotisation_uniforme;
      for (const [groupe, bornes] of intervalles) {
        const base = this._baseSelonAssiette(groupe, baseLigne, ligne.part_primes);
        for (const [borneBasse, borneHaute] of ConstructeurCompte.fusionner(bornes)) {
          const assiette = this._assiette(base, annee, borneBasse, borneHaute);
          if (assiette <= 0) {
            continue;
          }
          assietteTotale += assiette;
          cotisation += assiette * tauxCommun;
        }
      }
    }

    return {
      annee,
      revenu: baseLigne,
      assiette_retenue: assietteTotale,
      cotisation,
      regimes: [...new Set(retenus)],
      taux_effectif: baseLigne ? cotisation / baseLigne : 0.0,
      hors_repartition: horsRepartition,
      fiabilite,
      nulle: cotisation <= 0,
      // Un même agent ne relève que d'un régime en répartition à la fois ; si
      // deux périodes se recouvraient, le repli l'emporte.
      origine_part_employeur: origines.includes("repli")
        ? "repli" : (origines[0] ?? ""),
      part_employeur: partEmployeur,
    };
  }

  // -- accumulation ----------------------------------------------------------

  /**
   * Accumule les cotisations de ``anneeDebut`` à la liquidation.
   *
   * ``anneeDebut`` permet de n'ouvrir le compte qu'à partir d'une date — c'est
   * ce qui distingue le scénario notionnel prospectif (compte ouvert à l'année
   * de bascule) du scénario rétroactif (compte ouvert à l'entrée dans la vie
   * active).
   */
  construire(carriere, anneeLiquidation, anneeDebut = null, regimeFusionne = null) {
    const debut = Math.max(
      anneeDebut !== null ? anneeDebut : carriere.premiereAnnee,
      this.parametres.annee_debut_repartition,
    );
    const fin = Math.min(anneeLiquidation - 1, carriere.derniereAnnee);

    let capital = 0.0;
    let capitalHors = 0.0;
    const cotisations = [];
    let fiabilite = Fiabilite.CERTIFIEE;

    for (let annee = debut; annee <= fin; annee += 1) {
      const detail = this.cotisationAnnuelle(carriere, annee, regimeFusionne);
      cotisations.push(detail);
      if (detail.nulle && detail.hors_repartition === 0) {
        continue;
      }
      fiabilite = Math.min(fiabilite, detail.fiabilite);
      const coefficient = this.indexation.coefficient(annee, anneeLiquidation);
      capital += detail.cotisation * coefficient;
      capitalHors += detail.hors_repartition * coefficient;
    }

    if (cotisations.length > 0) {
      fiabilite = Math.min(fiabilite, this.indexation.fiabiliteSur(debut, anneeLiquidation));
    }

    const cotisationsVersees = cotisations.reduce((total, c) => total + c.cotisation, 0.0);
    // Ce que le scénario 4 doit dire de lui-même : sur combien d'années la
    // contribution employeur réelle a été trouvée, et sur combien il a fallu
    // retomber sur l'alignement du scénario 2 faute de série.
    const anneesPartEmployeur = {};
    for (const detail of cotisations) {
      if (detail.origine_part_employeur && !detail.nulle) {
        const origine = detail.origine_part_employeur;
        anneesPartEmployeur[origine] = (anneesPartEmployeur[origine] ?? 0) + 1;
      }
    }
    return {
      capital,
      capital_hors_repartition: capitalHors,
      annee_liquidation: anneeLiquidation,
      cotisations,
      fiabilite,
      /** Somme des cotisations en euros courants, sans revalorisation. */
      cotisations_versees: cotisationsVersees,
      annees_cotisees: cotisations.filter((c) => !c.nulle).length,
      /** Rapport entre capital revalorisé et cotisations versées. */
      rendement_cumule: cotisationsVersees ? capital / cotisationsVersees : 0.0,
      /** Part des cotisations versée par l'employeur public, euros courants. */
      cotisations_employeur: cotisations.reduce(
        (total, c) => total + (c.part_employeur ?? 0.0), 0.0,
      ),
      annees_part_employeur: anneesPartEmployeur,
    };
  }
}
