# Limites — à lire avant d'utiliser un chiffre

Ce modèle est une charpente complète et fonctionnelle. Ses séries
macroéconomiques sont **certifiées de 1950 à 2025**, ses tables de mortalité sont
celles réellement observées depuis 1986, et son plafond de la Sécurité sociale
remonte à 1931 daté décret par décret — le tout recontrôlé automatiquement contre
les sources. Ce qui précède 1950, et les paramètres propres à chaque régime,
restent saisis à la main. Ce document dit exactement où passe la frontière, pour
qu'aucun résultat ne soit cité sans savoir sur quoi il repose.

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
| Espérance de vie à 65 ans | 1960-2024 | **certifiée** | OCDE `DSD_HEALTH_STAT@DF_LE` |
| Espérance de vie à 65 ans | 1946-1959 | haute / moyenne | tables TD/TV, saisies |
| Quotients de mortalité par âge | 1986-2024 | **certifiée** | Eurostat `demo_mlifetable`, âges 0-94 |
| Quotients de mortalité par âge | avant 1986, grands âges | absents | calibration paramétrique |
| Plafond Sécurité sociale | 2002-2025 | **certifiée** | INSEE BDM, idbank 000822494 |
| Plafond Sécurité sociale | 1931-2001 | haute | OpenFisca-France, daté décret par décret |
| Taux de cotisation, régime général | 1967-2026 | moyenne | OpenFisca-France, recoupé à chaque exécution |
| Taux de cotisation, autres régimes | tous | moyenne / estimée | Comptes de la Sécurité sociale |
| Valeurs d'achat et de service du point | Agirc 1947-2018, Arrco 1949-2018, Agirc-Arrco 2019-2025, Ircantec 1949-2022, RAFP 2005-2021, RCI 2013-2023 | haute | OpenFisca-France-Pension |
| Valeurs du point, Arrco avant 1999 | 1949-1998 | moyenne | UNIRS, la plus grosse caisse Arrco |
| Rendement des autres régimes en points | CNAVPL, MSA, CNBF | haute / estimée | calculé là où le point est connu, reconstitué sinon |

**Comment la certification fonctionne.** Une valeur n'est `certifiee` que si
elle a été confrontée à un fichier téléchargé depuis le producteur. Le circuit
est le même pour toutes les séries : récupérer, puis confronter.

```bash
python scripts/fetch/insee_bdm.py              # séries longues INSEE
python scripts/fetch/oecd_esperance_vie.py     # espérance de vie à 65 ans
python scripts/fetch/eurostat_mortalite.py     # tables de mortalité par âge
python scripts/fetch/openfisca_plafond.py      # plafond ancien
python scripts/fetch/openfisca_cotisations.py  # taux de cotisation du RG
python scripts/fetch/openfisca_points.py       # valeurs du point, depuis 1947
python scripts/fetch/eurostat_hicp.py          # contrôle croisé de l'inflation

python scripts/verifier_donnees.py             # confronte, sans rien écrire
python scripts/verifier_donnees.py --appliquer # aligne sur la source et certifie
```

`data/brut/` n'est pas versionné : c'est `data/derive/certification.json` qui
garde la trace du dernier recontrôle — quelle source, quel jour, combien de
valeurs, à quel niveau, et une empreinte de la série reconstruite.

**Deux niveaux, deux exigences.** `certifiee` suppose que la source soit le
**producteur** de la donnée : INSEE, Eurostat, OCDE. Une transcription tierce,
même sourcée et reprise automatiquement, plafonne à `haute` — c'est le cas du
plafond ancien, qui vient d'OpenFisca-France. La distinction n'est pas
cosmétique : elle dit ce qu'on saurait vérifier soi-même en remontant d'un cran.

**Ce que l'automatisation a corrigé.** L'API SDMX de la Banque de données
macroéconomiques de l'INSEE (`api.insee.fr/series/BDM/V1`) est ouverte sans clé
d'accès et diffuse, elle, les séries longues — contrairement à l'API Melodi, qui
ne remonte pas avant les années 1990. Le recontrôle a confirmé la plupart des
valeurs saisies mais en a corrigé beaucoup : 28 années d'inflation, 72 de
salaire moyen et 70 de productivité s'écartaient de plus de 0,05 point. Comme
l'indexation retient le **minimum** de ces trois taux, une erreur sur l'un
d'entre eux ne se compense pas : elle se transmet telle quelle au résultat.

**Deux corrections que le recoupement a révélées.**

* *Le plafond de la Sécurité sociale était décalé d'un an sur 1968-2001* : la
  valeur inscrite à l'année N était celle de N−1. L'erreur a été trouvée en
  confrontant la série saisie à celle d'OpenFisca, puis confirmée par la série
  mensuelle de l'INSEE. Elle déplaçait d'un cran, pendant trente-quatre ans, la
  frontière entre droits de base et droits complémentaires. Les plafonds de
  1931 à 1967, jusque-là rétropolés en indexant 1968 sur le salaire moyen,
  étaient quant à eux sous-estimés d'un facteur 2,5 en 1945.
* *Les taux de cotisation du régime général sous-estimaient la cotisation
  réelle* de 0,2 à 0,8 point selon les périodes, la période 1972-1982 étant la
  plus fausse (10,40 % au lieu de 11,19 %). Le taux de cotisation est ce qui
  alimente le compte notionnel : un écart de cette taille sur onze ans se lit
  directement dans le capital accumulé.
* *Les rendements des régimes en points étaient estimés très en dessous du
  réel*, l'Ircantec des années 1970 à 11 % quand ses barèmes en donnent 22,8 %,
  l'Agirc des années 1980 à 9,8 % contre 11,8 %. Le scénario « système actuel »
  servant de référence aux deux autres, il les sous-estimait tous les trois :
  la retraite complémentaire d'un salarié du privé à carrière complète monte
  d'environ un tiers.

**Ce qui reste hors de portée, et pourquoi.** La liste vaut recensement de ce
qui a été cherché, pour éviter de le rechercher deux fois.

* *Inflation, salaires et productivité d'avant 1950* — ni l'indice des prix ni
  les comptes nationaux ne sont diffusés en série continue plus haut. Ont été
  essayés sans succès : la BDM de l'INSEE (débute en 1949), le convertisseur
  franc-euro de l'INSEE (calcul côté navigateur, coefficients non exposés), les
  longues séries de prix de la BRI (débutent en 1951), Eurostat (1996), les
  données de la Banque mondiale (1960). Le tableau « IPC depuis 1901 » n'existe
  qu'en fichier tableur, à déposer dans `data/brut/`.
* *Espérance de vie à 65 ans d'avant 1960* — l'INSEE publie e0, e1, e20, e40 et
  e60, jamais e65. Ni l'OCDE (1960) ni Eurostat (1986) ne remontent plus haut.
  La Human Mortality Database, seule à couvrir la France depuis 1816, exige une
  inscription : elle n'est donc pas récupérable par script.
* *Quotients de mortalité par âge d'avant 1986, et au-delà de 94 ans* — Eurostat
  n'y publie rien, et ses classes ouvertes (85 et plus, 95 et plus) ne sont pas
  des quotients à un âge donné. Au-delà du dernier âge publié, le modèle
  reprend sa loi de Gompertz-Makeham : c'est un raccord assumé.
* *Taux de cotisation d'avant octobre 1967 et des régimes autres que le régime
  général* — aucune transcription machine n'existe. Ils viennent des
  ordonnances de 1945 et de leurs modificatifs, saisis à la main.
* *Valeurs du point de la CNAVPL, de la MSA et de la CNBF* — les trois seules
  caisses en points dont aucune série ne sort. Ont été essayés sans succès :
  OpenFisca-France-Pension (ne modélise pas ces régimes), les barèmes IPP (même
  périmètre, c'est la source amont d'OpenFisca), l'open data de la DREES
  (résultats statistiques, pas paramètres), data.gouv.fr (les jeux de la MSA
  sont des effectifs de retraités), et les sites des caisses — la CNAVPL décrit
  le mécanisme sans publier de table, la CNBF ne met en ligne que des barèmes
  annuels en PDF depuis 2016. Ces trois régimes restent au rendement instantané
  reconstitué, et la confrontation des autres à leurs vraies valeurs a montré
  que ces reconstitutions peuvent se tromper du simple au double : à prendre
  avec la même méfiance.
* *Âges, durées requises, décotes* — ils viennent de lois, pas de séries
  statistiques. Légifrance expose une API, mais elle demande une clé et renvoie
  du texte juridique, non des paramètres.

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

- **régimes en points** — la pension est désormais calculée en points, sur
  l'historique réel des valeurs d'achat et de service (Agirc depuis 1947, Arrco
  depuis 1949, Ircantec depuis 1949), avec conversion des points aux fusions.
  Restent au rendement instantané, faute de barèmes intégrés, la CNAVPL, la MSA,
  la CNBF, le RCI et le RAFP ;
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
- 140 tests couvrent le chargement, la fiabilité, la règle de certification, la
  concordance des tables de mortalité observées avec les espérances publiées, les
  propriétés du moteur et le comportement des scénarios : `python -m pytest tests`.
  Aucun test n'accède au réseau : les sources sont simulées.
