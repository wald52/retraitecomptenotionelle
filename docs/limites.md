# Limites — à lire avant d'utiliser un chiffre

Ce modèle est une charpente complète et fonctionnelle. Ses **données ne sont pas
encore certifiées**. Ce document dit exactement ce qui manque, pour qu'aucun
résultat ne soit cité sans savoir sur quoi il repose.

---

## 1. Aucune série n'est certifiée

`retraite-notionnelle donnees` affiche l'état exact. En résumé :

| Donnée | Période | Niveau | Ce qu'il faudrait |
|---|---|---|---|
| Inflation (IPC) | 1970-2024 | haute | export certifié INSEE série longue |
| Inflation | 1930-1969 | estimée / moyenne | tableau INSEE « IPC depuis 1901 » |
| Salaire moyen par tête | 1990-2024 | haute | export comptes nationaux |
| Salaire moyen par tête | 1930-1989 | estimée / moyenne | série rétropolée INSEE |
| Productivité réelle | 1990-2024 | haute | export comptes nationaux |
| Productivité réelle | 1930-1989 | estimée / moyenne | série rétropolée INSEE |
| Plafond Sécurité sociale | 2002-2025 | haute | — |
| Plafond Sécurité sociale | 1945-1967 | **reconstituée** | valeurs du *Journal officiel* |
| Espérances de vie | 1946-2024 | haute / moyenne | tables TD/TV INSEE complètes |
| Taux de cotisation par régime | tous | moyenne / estimée | Comptes de la Sécurité sociale |
| Rendement des régimes en points | avant 2019 | **estimée** | historique des valeurs du point |

**Pourquoi l'automatisation ne suffit pas.** Les scripts de `scripts/fetch/`
fonctionnent pour l'API Melodi de l'INSEE et pour Eurostat, mais ces portails ne
diffusent pas les séries longues : l'IPC ne remonte pas avant les années 1990,
et les séries de comptes nationaux rétropolées ne sont publiées qu'en fichiers
téléchargeables. Les valeurs antérieures ont donc été **saisies**, et le seul
moyen de les faire passer au niveau `certifiee` est de déposer les fichiers
sources dans `data/brut/` puis de lancer `scripts/verifier_donnees.py`.

**Ce que cela veut dire concrètement.** Les niveaux absolus de pension sont
indicatifs. Les **écarts entre les trois scénarios** sont beaucoup plus robustes :
ils sont calculés sur les mêmes carrières, avec les mêmes séries, et une erreur
sur une série se propage dans le même sens aux trois scénarios.

---

## 2. La règle d'indexation domine le scénario rétroactif

Le triple lock inversé, pris à la lettre, retient le minimum entre deux taux
**nominaux** (inflation, salaire moyen) et un taux **réel** (productivité). Dès
que l'inflation dépasse la croissance de la productivité, c'est cette dernière
qui l'emporte.

Sur 1941-2025, les comptes sont revalorisés ×4,9 quand les prix sont multipliés
par 318,6 : **une cotisation de 1950 conserve 1,5 % de sa valeur réelle.**

Conséquence : dans le scénario rétroactif, l'essentiel de la baisse affichée
vient de la règle d'indexation, pas du passage aux comptes notionnels. Les deux
effets ne sont pas séparables par lecture directe du tableau.

Pour les distinguer :

```bash
retraite-notionnelle simuler ... --indexation triple_lock_inverse_nominal
retraite-notionnelle simuler ... --indexation prix
```

La variante nominale conserve 76 % du pouvoir d'achat sur la même période, tout
en restant plus sévère que l'indexation sur les prix. C'est probablement ce que
vise l'intention d'une règle d'indexation prudente ; le choix reste ouvert.

---

## 3. Le scénario « système actuel » est une approximation

Reproduire exactement le droit positif de tous les régimes depuis 1930 suppose
un moteur législatif complet, du type de ceux de la DREES (TRAJECTOiRE) ou de
l'Institut des politiques publiques (PENSIPP). Écarts connus :

- **régimes en points** — la pension est reconstituée à partir d'un rendement
  instantané, pas de l'historique des valeurs d'achat et de service du point ;
- **montée en charge des réformes** — les paramètres sont ceux de l'année de
  liquidation, sans le détail génération par génération des lois Balladur (1993)
  et Touraine (2014) ;
- **revalorisation des salaires portés au compte** — la règle des prix est
  appliquée sur toute la période, alors qu'elle ne s'impose qu'à partir de 1993.
  Cela minore le salaire de référence des carrières anciennes ;
- **carrières longues, pénibilité, invalidité, inaptitude** — non modélisés ;
- **polypensionnés** — le modèle gère plusieurs régimes simultanés, mais pas les
  règles de coordination interrégimes (proratisation croisée, LURA).

Un écart de quelques pour cent avec la pension réelle est attendu.

---

## 4. Régimes incomplets

| Régime | Ce qui manque |
|---|---|
| Professions libérales (CNAVPL) | régimes complémentaires des dix sections (CARMF, CARPIMKO, CIPAV…) ; grille des classes de cotisation avant 2004 |
| Marins (ENIM) | grille des salaires forfaitaires par catégorie et par année |
| Avocats (CNBF) | barème forfaitaire par tranche d'ancienneté |
| Régimes spéciaux résiduels | paramètres saisis au niveau `estimee`, à certifier auprès de chaque caisse |
| Non-salariés agricoles | part forfaitaire et points RCO traités de façon agrégée |

Le catalogue compte **35 régimes**, actuels et disparus. Il est structurellement
extensible : ajouter un régime consiste à écrire une fiche YAML conforme à
`data/reference/regimes/_schema.yaml`, sans toucher au moteur.

---

## 5. Ce que le modèle ne calcule pas

- **L'équilibre financier du système.** Le modèle calcule des droits
  individuels. Il ne vérifie pas que la somme des pensions servies égale la
  somme des cotisations encaissées. Un système notionnel réel exige un
  coefficient d'équilibre et un fonds de réserve ; ni l'un ni l'autre ne sont
  modélisés.
- **Les comportements.** Les âges de liquidation sont ceux que l'utilisateur
  déclare. Or une réforme qui pénalise fortement les départs précoces conduit à
  les décaler : les écarts affichés sont donc des effets à comportement
  inchangé, qui surestiment la perte réelle.
- **Le net.** Tous les montants sont **bruts**. CSG, CRDS et CASA ne sont pas
  appliquées.
- **La capitalisation.** Le compartiment RAFP est isolé et converti au même
  coefficient actuariel, mais son rendement financier propre n'est pas modélisé.
  Conformément à la demande, seule la répartition est traitée à ce stade.
- **Les carrières réelles.** Les carrières sont reconstituées à partir d'un
  profil paramétrique. Une simulation à partir d'un relevé de carrière réel est
  possible via `Carriere.depuis_lignes`, mais l'import automatique du relevé
  Info-Retraite n'est pas implémenté : le RGCU n'est pas ouvert au public.

---

## 6. Reproductibilité

- Aucune dépendance hors PyYAML ; tous les calculs sont déterministes.
- La calibration des tables de mortalité est mémorisée dans
  `data/derive/calibrations_mortalite.json`, régénérable en supprimant le fichier.
- 64 tests couvrent le chargement, la fiabilité, les propriétés du moteur et le
  comportement des scénarios : `python -m pytest tests`.
