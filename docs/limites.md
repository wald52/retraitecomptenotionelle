# Limites — à lire avant d'utiliser un chiffre

Ce modèle est une charpente complète et fonctionnelle. Ses séries
macroéconomiques sont **certifiées de 1950 à 2025** : recalculées depuis les
séries publiées par l'INSEE et recontrôlées automatiquement contre elles. Ce qui
précède 1950, le plafond ancien et les paramètres de régime restent saisis à la
main. Ce document dit exactement où passe la frontière, pour qu'aucun résultat ne
soit cité sans savoir sur quoi il repose.

---

## 1. État de certification des données

`retraite-notionnelle donnees` affiche l'état exact. En résumé :

| Donnée | Période | Niveau | Source |
|---|---|---|---|
| Inflation (IPC) | 1950-2025 | **certifiée** | INSEE BDM, idbanks 000008965 et 001764363 |
| Inflation | 1930-1949 | estimée | tableau « IPC depuis 1901 », saisi |
| Salaire moyen par tête | 1950-2025 | **certifiée** | INSEE BDM, idbanks 011785411 et 011793486 |
| Salaire moyen par tête | 1930-1949 | estimée | reconstitution |
| Productivité réelle | 1950-2025 | **certifiée** | INSEE BDM, idbanks 011785223 et 011793334 |
| Productivité réelle | 1930-1949 | estimée | reconstitution |
| Espérance de vie à 0 et 60 ans | 1946-2025 | **certifiée** | INSEE BDM, quatre idbanks, annuel par sexe |
| Espérance de vie à 65 ans | 1986-2024 | **certifiée** | Eurostat `demo_mlexpec` |
| Espérance de vie à 65 ans | 1946-1985 | haute / moyenne | tables TD/TV, saisies |
| Plafond Sécurité sociale | 2002-2025 | **certifiée** | INSEE BDM, idbank 000822494 |
| Plafond Sécurité sociale | 1968-2001 | moyenne | plafonds en francs convertis |
| Plafond Sécurité sociale | 1945-1967 | **reconstituée** | valeurs à relever au *Journal officiel* |
| Taux de cotisation par régime | tous | moyenne / estimée | Comptes de la Sécurité sociale |
| Rendement des régimes en points | avant 2019 | **estimée** | historique des valeurs du point |
| Quotients de mortalité par âge | — | absents | tables TD/TV INSEE, en tableur |

**Comment la certification fonctionne.** Une valeur n'est `certifiee` que si
elle a été confrontée à un fichier téléchargé depuis le producteur. Le circuit
tient en deux commandes :

```bash
python scripts/fetch/insee_bdm.py              # dépose les séries source
python scripts/fetch/eurostat_esperance_vie.py
python scripts/verifier_donnees.py             # confronte, sans rien écrire
python scripts/verifier_donnees.py --appliquer # aligne sur la source et certifie
```

`data/brut/` n'est pas versionné : c'est `data/derive/certification.json` qui
garde la trace du dernier recontrôle — quelle source, quel jour, combien de
valeurs, et une empreinte de la série reconstruite.

**Ce que l'automatisation a corrigé.** L'API SDMX de la Banque de données
macroéconomiques de l'INSEE (`api.insee.fr/series/BDM/V1`) est ouverte sans clé
d'accès et diffuse, elle, les séries longues — contrairement à l'API Melodi, qui
ne remonte pas avant les années 1990. Le recontrôle a confirmé la plupart des
valeurs saisies mais en a corrigé beaucoup : 28 années d'inflation, 72 de
salaire moyen et 70 de productivité s'écartaient de plus de 0,05 point. Comme
l'indexation retient le **minimum** de ces trois taux, une erreur sur l'un
d'entre eux ne se compense pas : elle se transmet telle quelle au résultat.

**Ce qui reste hors de portée, et pourquoi.**

* *Avant 1950* — ni l'indice des prix ni les comptes nationaux ne sont diffusés
  en série continue. Le tableau « IPC depuis 1901 » n'existe qu'en fichier
  tableur ; les comptes nationaux commencent en 1949.
* *Plafond d'avant 2002* — la série INSEE ne remonte pas plus haut et le portail
  open data de l'Urssaf ne publie aucun jeu « plafond ». Les valeurs anciennes
  sont au *Journal officiel*, à relever décret par décret.
* *Espérance de vie à 65 ans d'avant 1986* — l'INSEE publie e0, e1, e20, e40 et
  e60, jamais e65 ; Eurostat, qui le publie, ne remonte pas avant 1986.
* *Quotients de mortalité par âge* — diffusés en tableur seulement. Tant qu'ils
  ne sont pas déposés, le modèle calibre une table paramétrique sur e60 et e65.
* *Paramètres de régime* — taux de cotisation, âges, valeurs de point : ils
  viennent de règlements et de circulaires, pas de séries statistiques. Aucune
  API ne les expose.

**Ce que cela veut dire concrètement.** Les carrières entamées après 1950 —
c'est-à-dire les générations nées à partir de 1930 environ, soit la quasi-totalité
des cas simulés — reposent désormais sur des séries recontrôlées. Les **écarts
entre les trois scénarios** restent plus robustes encore que les niveaux : ils
sont calculés sur les mêmes carrières, avec les mêmes séries, et une erreur
résiduelle se propage dans le même sens aux trois scénarios.

---

## 2. La règle d'indexation domine le scénario rétroactif

Le triple lock inversé, pris à la lettre, retient le minimum entre deux taux
**nominaux** (inflation, salaire moyen) et un taux **réel** (productivité). Dès
que l'inflation dépasse la croissance de la productivité, c'est cette dernière
qui l'emporte.

Sur 1941-2025, les comptes sont revalorisés ×4,9 quand les prix sont multipliés
par 322,2 : **une cotisation de 1950 conserve 1,5 % de sa valeur réelle.**

Conséquence : dans le scénario rétroactif, l'essentiel de la baisse affichée
vient de la règle d'indexation, pas du passage aux comptes notionnels. Les deux
effets ne sont pas séparables par lecture directe du tableau.

Pour les distinguer :

```bash
retraite-notionnelle simuler ... --indexation triple_lock_inverse_nominal
retraite-notionnelle simuler ... --indexation prix
```

La variante nominale conserve 69 % du pouvoir d'achat sur la même période, tout
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
- La certification des séries est tracée dans `data/derive/certification.json`,
  régénérable par `scripts/verifier_donnees.py --appliquer`.
- 124 tests couvrent le chargement, la fiabilité, la règle de certification, les
  propriétés du moteur et le comportement des scénarios : `python -m pytest tests`.
  Aucun test n'accède au réseau : les sources sont simulées.
