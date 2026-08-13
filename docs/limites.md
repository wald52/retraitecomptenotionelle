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
| Valeurs d'achat et de service du point, Ircantec | 1971-2021 | **certifiée** | Caisse des dépôts, qui gère le régime |
| Valeurs d'achat et de service du point, autres | Agirc 1947-2018, Arrco 1949-2018, Agirc-Arrco 2019-2025, RAFP 2005-2021, RCI 2013-2023 | haute | OpenFisca-France-Pension, recoupé à l'INSEE depuis 2001 |
| Valeurs du point, Arrco avant 1999 | 1949-1998 | moyenne | UNIRS, la plus grosse caisse Arrco |
| Valeurs du point, complémentaire des avocats | 2017-2026 | **certifiée** | CNBF, ses barèmes annuels |
| Valeur du point et taux, base des professions libérales | 2021-2025 | **certifiée** | CNAVPL, ses recueils statistiques |
| Rendement des autres régimes en points | MSA | estimée | reconstitué faute de barème exploitable |

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
python scripts/fetch/cdc_ircantec.py           # barèmes Ircantec, par son gestionnaire
python scripts/fetch/cnbf_baremes.py           # valeurs du point des avocats
python scripts/fetch/cnavpl_recueils.py        # valeur du point des professions libérales
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

**Et une confirmation, qui compte autant.** Les barèmes de l'Agirc et de
l'Arrco pèsent, dans la pension d'un salarié du privé, plus lourd que tous les
autres réunis, et leur seule source était OpenFisca — c'est-à-dire une
transcription qu'on ne savait pas vérifier, la caisse ne publiant pas de série.
L'INSEE, lui, diffuse la valeur de service du point depuis 2001, mensuelle,
sous trois idbanks (`000849395` pour l'Arrco, `000822495` pour l'Agirc,
`010593202` pour l'Agirc-Arrco). **Sur les 42 années où les deux se recouvrent,
elles ne divergent pas une fois.** Ces valeurs restent au niveau `haute` — deux
transcriptions ne font pas un producteur — mais leur accord est désormais
recontrôlé à chaque exécution. Le recoupement a en outre comblé un trou : la
valeur de service 2025 de l'Agirc-Arrco manquait, la transcription s'arrêtant à
2024, si bien qu'une liquidation de 2025 convertissait ses points au barème de
l'année précédente.

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
* *Valeur du point de la MSA* — la dernière caisse en points dont aucune série
  exploitable ne sort. Ont été essayés sans succès : OpenFisca-France-Pension
  (ne modélise pas ce régime), les barèmes IPP (même périmètre — c'est la source
  amont d'OpenFisca, ses quarante-cinq feuilles couvrent l'Arrco, l'Agirc,
  l'UNIRS, PRO-BTP, l'Ircantec, la CANCAVA et l'ORGANIC), l'open data de la
  DREES (cinquante et un jeux « retraite », tous des résultats statistiques), le
  portail open data de la Caisse des dépôts (effectifs seulement), data.gouv.fr
  (les jeux de la MSA sont des effectifs de retraités et d'exploitants), le
  portail statistiques.msa.fr, la BDM de l'INSEE — qui porte le point de l'Agirc
  et de l'Arrco mais aucun point agricole — et le site de la caisse, dont les
  pages de barèmes sont construites en JavaScript.

  **Ce qui manque n'est pas ce qu'on croyait.** Les paramètres, eux, ont fini
  par se laisser établir, et ils disent où est le vrai obstacle :

  * le régime **complémentaire** (RCO) n'a pas de prix d'achat du point, et ne
    peut pas en avoir : l'article D. 732-165 du code rural attribue les points
    par une formule, `points = revenus × 100 ÷ (1 820 × SMIC horaire)`, avec un
    plancher de 100 points à l'assiette minimale. Sa valeur de service est à
    l'article D. 732-166, à 0,3919 € pour 2025 ;
  * le régime de **base** comporte une part forfaitaire et une **retraite
    proportionnelle en points**, dont le COR donne la valeur — 4,264 € en 2023.
    Mais ces points ne s'achètent pas davantage : ils sont attribués par un
    barème annuel par tranche de revenu, de 23 à 113 points selon la tranche.

  L'obstacle est donc ce barème annuel par tranche, que ni la caisse ni le
  ministère ne publient en série — et non un prix d'acquisition manquant, comme
  cette page l'a d'abord écrit. S'y ajoute que le modèle traite la MSA comme un
  régime unique quand il y a deux étages, et que la RCO attribue des points
  gratuits autant que cotisés (66 par an aux conjoints et aides familiaux avant
  2011, dans la limite de 17 années). Ce régime reste au rendement instantané
  reconstitué, et la confrontation des autres à leurs vraies valeurs a montré
  que ces reconstitutions peuvent se tromper du simple au double : à prendre
  avec la même méfiance.

  *Légifrance porte bien ces articles, mais refuse les requêtes automatisées*
  (403 sur toute requête non navigateur), et son API demande une clé. Les
  valeurs ci-dessus ont donc été relevées à la lecture, et ne peuvent pas être
  certifiées par un script : c'est pourquoi elles restent dans ce document et
  dans les fiches de régime, pas dans une série.

  **La voie légale a été suivie jusqu'au bout, et elle ne mène pas où il
  faudrait.** Les bases ouvertes de la DILA ont été dépouillées en flux, sans
  écriture disque : 12,4 Go de JORF puis 9,1 Go de LEGI, deux fois — une passe
  ciblée, puis une passe large gardant tout article codifié portant une valeur
  de point, pour ne pas manquer un renvoi du type « la valeur mentionnée à
  l'article L. 643-1 ». Ce qu'on y trouve, et qui vaut d'être noté pour ne pas
  refaire le trajet :

  * la valeur de service du point de la **retraite complémentaire obligatoire
    agricole** est portée par un article codifié, `D. 732-166` du code rural,
    dont LEGI garde les versions successives datées — 0,3023 € en 2006,
    0,3188 € en 2010, 0,3642 € en 2023, 0,3835 € en 2025. C'est une vraie série,
    mais incomplète et surtout inexploitable telle quelle : le modèle traite la
    MSA comme un régime unique, alors que la RCO n'en est que la part
    complémentaire, créée en 2003, et qu'elle attribue des points
    **forfaitaires** autant que cotisés. Il manque le prix d'acquisition, qui
    n'existe pas sous cette forme. L'intégrer à moitié serait pire que
    l'approximation assumée d'aujourd'hui ;
  * la **CNAVPL** n'apparaît dans aucun article codifié portant une valeur de
    point, et la passe large n'en trouve pas davantage : la législation
    consolidée ne contient, sous ce libellé, que le point d'indice des pensions
    militaires d'invalidité et celui de la fonction publique. Côté *Journal
    officiel*, la passe large remonte 104 textes portant une valeur de point,
    dont aucun ne mentionne le mot « libérale ». L'explication n'est pas que la
    recherche ait été trop étroite, mais que la donnée cherchée n'y est pas :
    **le décret annuel fixe un coefficient de revalorisation, non un montant.**
    La valeur qui en résulte n'est publiée que par la caisse.

  *La CNBF et la CNAVPL ont fini par livrer les leurs* — non par la loi, mais
  l'une par ses barèmes annuels, l'autre par ses recueils statistiques. Voir les
  deux limites suivantes.

* *Régime de base des avocats, et emploi des valeurs trouvées* — la CNBF publie
  chaque janvier un barème en PDF qui donne le **coût d'acquisition** et la
  **valeur de service** du point de son régime complémentaire. Ces valeurs sont
  désormais dans le dépôt, certifiées, de 2017 à 2026 : le rendement du régime
  y décroît régulièrement de 10,1 % à 8,2 %.

  Le moteur ne s'en sert pas encore, et c'est délibéré. La fiche `cnbf` agrège
  en un seul taux le régime de base — forfaitaire, sans point — et le régime
  complémentaire. Verser toutes les cotisations dans le second gonflerait la
  pension complémentaire et ferait disparaître la base. Les valeurs sont donc
  rangées sous le code `cnbf_complementaire`, que le catalogue ne connaît pas,
  en attendant que la fiche soit scindée en ses deux étages — ce qui suppose de
  décider quelle classe de cotisation retenir par défaut, la CNBF en proposant
  cinq. Un test garde les deux moitiés de cette décision.

  Au passage, ces valeurs éclairent l'estimation en place : un rendement agrégé
  de 6,5 % pour l'ensemble base + complémentaire est cohérent avec un
  complémentaire à 8,2 % et une base forfaitaire moins rentable. L'estimation
  n'était donc pas absurde, ce que rien ne permettait de dire jusqu'ici.

* *Régime de base des professions libérales* — la CNAVPL ne publie sa valeur de
  point nulle part ailleurs que dans son **recueil statistique**, un annuaire
  d'une soixantaine de pages paru chaque année, sous une phrase invariable :
  « La valeur du point est fixée à 0,6540 au 1er janvier 2025. » Le même recueil
  donne les deux taux de cotisation — 8,23 % sur la tranche 1, 1,87 % sur la
  tranche 2. Ces valeurs sont dans le dépôt, certifiées, de 2021 à 2025 ; les
  millésimes antérieurs mettent la valeur dans un graphique et non dans une
  phrase, d'où le début de série.

  Le moteur ne s'en sert pas encore, pour une raison différente de celle de la
  CNBF : le régime n'attribue pas un nombre de points proportionnel à la
  cotisation, mais **525 points au maximum sur la tranche 1 et 25 sur la tranche
  2**, soit 550 depuis 2015. Le prix d'un point s'en déduit — taux × plafond
  ÷ 525 — mais ce plafonnement en points est une règle de calcul, pas un barème :
  l'écrire suppose de la coder dans le moteur, non d'ajouter une colonne. Faute
  de `salaire_reference`, `ValeursPoint.achat()` renvoie `None` et la CNAVPL
  reste sur le rendement instantané, inchangée. Ce qu'apporte cette limite
  aujourd'hui, c'est que les trois grandeurs nécessaires sont désormais sourcées.

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
  Restent au rendement instantané la CNAVPL, la MSA, la CNBF, le RCI et le
  RAFP — pour la MSA faute de barème exploitable, pour les autres faute d'une
  fiche assez fine pour recevoir celui qu'on a ;
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
- 144 tests couvrent le chargement, la fiabilité, la règle de certification, la
  concordance des tables de mortalité observées avec les espérances publiées, les
  propriétés du moteur et le comportement des scénarios : `python -m pytest tests`.
  Aucun test n'accède au réseau : les sources sont simulées.
