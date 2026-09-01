# Méthodologie

Ce document décrit ce que le modèle calcule, et pourquoi il le calcule ainsi.
Chaque décision contestable y est nommée, justifiée, et rattachée au paramètre
qui permet d'en changer.

---

## 1. Ce qu'est un compte notionnel

Un compte notionnel est un compte **virtuel**. Aucun capital n'est placé : les
cotisations de l'année financent les pensions de l'année, comme dans toute
répartition. Ce qui change, c'est la façon de calculer le droit.

Pour chaque assuré :

1. **Accumulation** — chaque année, la cotisation retraite effectivement versée
   est inscrite au compte ;
2. **Revalorisation** — le solde est revalorisé chaque année à un taux
   d'indexation défini par la règle collective ;
3. **Liquidation** — la pension annuelle vaut

   ```
   pension = capital notionnel / coefficient de conversion
   ```

Le coefficient de conversion est l'espérance de vie résiduelle à l'âge de
liquidation, lue sur une table de génération.

Trois propriétés en découlent, et ce sont elles qui répondent au cahier des
charges :

- **la pension est strictement proportionnelle aux cotisations** — aucun effet
  de seuil, aucun palier, aucun minimum ;
- **partir plus tôt coûte deux fois** — moins de cotisations accumulées, et une
  rente à servir plus longtemps ;
- **rien n'est gratuit** — un droit non financé par une cotisation n'existe pas.

---

## 2. Périmètre temporel

L'origine par défaut est **1941**, date de l'allocation aux vieux travailleurs
salariés : premier dispositif français où les cotisations des actifs financent
directement les prestations des retraités. Le paramètre
`annee_debut_repartition` accepte 1945 (ordonnances créant la Sécurité sociale)
pour qui préfère cette borne.

Les régimes antérieurs figurent au catalogue mais sont traités à part :

- les **assurances sociales de 1930** étaient en capitalisation individuelle —
  leur ruine par l'inflation des années 1940 est précisément ce qui a motivé le
  passage à la répartition. Elles sont marquées `hors_repartition` ;
- les **pensions civiles de 1853** étaient versées sur crédits budgétaires
  courants, donc fonctionnellement en répartition : elles sont incluses.

---

## 3. L'indexation : le triple lock inversé

### La règle

À chaque année *t* :

```
taux d'indexation = min( inflation , croissance du salaire moyen , productivité réelle )
```

Elle s'applique à la revalorisation des **comptes en cours de constitution**,
depuis 1941. Elle ne s'applique pas aux pensions déjà liquidées — non par
choix, mais parce que le modèle n'a pas de phase postérieure à la liquidation :
il calcule une pension à la date de départ, dans les euros de cette année-là,
et s'arrête. Les cinq scénarios sont donc lus au même instant, ce qui les rend
comparables ; ce que la règle ferait aux pensions servies reste hors du modèle,
et `docs/limites.md` le dit. Un paramètre `indexer_pensions_liquidees` figurait
en tête de la configuration et laissait croire le contraire : il n'était lu
nulle part, et il a été retiré.

Une convention à connaître, parce qu'elle vaut un pour cent : une cotisation
versée l'année *t* est revalorisée de *t*+1 **jusqu'à l'année de liquidation
incluse**. Le compte est arrêté à la fin de l'année de départ, pas à son début.
La docstring de `Indexation.coefficient` annonçait l'inverse alors que le code
a toujours fait ainsi ; c'est le texte qui a été corrigé.

### Ce qu'elle produit, et pourquoi il faut le savoir

Deux des trois termes sont nominaux, le troisième est réel. Dès que l'inflation
dépasse la croissance de la productivité — c'est-à-dire pendant la quasi-totalité
de la période 1945-1985 — c'est la productivité réelle qui l'emporte, et le
compte est revalorisé de 1 à 5 % quand les prix montent de 10 à 50 %.

Mesure sur la période complète (`retraite-notionnelle indexation --de 1941 --a 2025`) :

| Règle | Revalorisation cumulée 1941-2025 | Prix | Pouvoir d'achat conservé |
|---|---|---|---|
| Triple lock inversé, littéral | ×4,9 | ×322,2 | **1,5 %** |
| Triple lock inversé, tout en nominal | ×223,3 | ×322,2 | 69,3 % |
| Indexation sur les prix | ×322,2 | ×322,2 | 100 % |

Ces trois chiffres sont ceux que produit la commande citée ci-dessus, et le
tableau les a longtemps donnés périmés — ×243,7 et ×318,6, valeurs d'une
révision antérieure des séries INSEE, quand le README, lui, portait les bonnes.
Deux documents ne peuvent pas dire deux chiffres pour la même mesure : c'est le
genre d'écart qu'un lecteur ne peut pas arbitrer.

Autrement dit, sous la règle littérale, **une cotisation versée en 1950 ne vaut
presque plus rien à la liquidation**. Le scénario rétroactif mesure alors
davantage l'effet de la règle d'indexation que celui du passage aux comptes
notionnels.

C'est un résultat, pas un défaut : la règle a été appliquée telle qu'énoncée.
Mais l'interprétation doit en tenir compte. Deux moyens de faire la part des
choses :

- `--indexation triple_lock_inverse_nominal` ramène la productivité en termes
  nominaux avant de prendre le minimum : la règle reste austère, mais homogène ;
- `--indexation prix` isole l'effet propre des comptes notionnels, indexation
  neutralisée.

Aucun plancher n'est appliqué par défaut : le taux peut être négatif, ce qui est
la conséquence logique de la règle (`plancher_indexation`).

### Au-delà de 2025

Les séries observées s'arrêtent en 2025. Geler la dernière valeur serait une
hypothèse implicite et fausse. Le modèle projette donc explicitement, selon des
scénarios inspirés de ceux du Conseil d'orientation des retraites
(`data/reference/macro/hypotheses_projection.yaml`) : inflation 1,75 %,
productivité réelle 0,7 % / 1,0 % / 1,3 % selon la variante. Toute année
projetée porte la fiabilité la plus basse, qui se propage jusqu'au résultat.

---

## 4. L'âge de référence à cliquet

### La construction

L'âge de référence est l'âge auquel une liquidation est réputée « à l'heure ».
Il est bâti **à cliquet** : c'est le maximum de tous les âges de taux plein
observés jusqu'à l'année considérée. Il ne redescend jamais.

| Période | Âge du taux plein en droit | Âge de référence retenu |
|---|---|---|
| 1945-1981 | 65 ans | 65 ans |
| 1982-2010 | **60 ans** (ordonnance du 26 mars 1982) | **65 ans** — le cliquet tient |
| 2011-2016 | montée en charge 65 → 67 | 65 → 67 ans |
| 2017- | 67 ans | 67 ans |

Conséquences directes, conformes à la demande :

- une liquidation à 60 ans en 1990 est une **anticipation de 5 ans** ;
- un agent de conduite parti à 50 ans en 1990 anticipe de **15 ans** ;
- un danseur de l'Opéra parti à 40 ans anticipe de **25 ans**.

### Comment l'écart pèse sur la pension

Il ne faut **pas** ajouter une décote par-dessus, et le modèle ne le fait pas
par défaut. L'anticipation est déjà sanctionnée deux fois, mécaniquement :

1. les années non travaillées n'ont produit aucune cotisation ;
2. la rente est servie plus longtemps, donc le diviseur est plus élevé.

Ordre de grandeur du second effet seul : cinq ans d'anticipation à 64 ans en
2026 augmentent le diviseur d'environ 4 années d'espérance de vie, soit une
pension annuelle inférieure d'environ 15 %. En ajoutant les cinq années de
cotisations manquantes sur une carrière de 42 ans, la perte totale approche 25 %.

Une décote explicite supplémentaire reste disponible
(`ModeCoefficientEcart.EXPLICITE`), mais c'est alors une double peine assumée.

### Variantes

- `cliquet_legal` (défaut) — la règle décrite ci-dessus ;
- `cliquet_puis_esperance_vie` — après la bascule, l'âge de référence suit
  l'espérance de vie de façon à stabiliser le rapport durée de retraite / durée
  de carrière ;
- `legal_sans_cliquet` — contrefactuel reproduisant le droit positif.

---

## 5. Le coefficient de conversion

```
G(a, L) = Σ_t  (probabilité de survie t années après la liquidation) × (1+ν)^(-t)
```

- **Table de génération**, pas table du moment. À chaque année vécue est
  appliquée la mortalité de l'année civile correspondante. Une table du moment
  sous-estimerait la longévité des générations récentes de 1,5 à 3 ans, et
  surestimerait donc leur pension d'autant.
- **Table unisexe** par défaut. C'est la pratique des systèmes notionnels suédois
  et italien. Une table sexuée est actuariellement exacte mais réduirait la
  pension des femmes de 5 à 10 % à capital identique, et serait contraire au
  principe de non-discrimination. `--table par_sexe` permet de mesurer l'écart.
- **ν = 0** par défaut. La rente est actualisée au taux auquel elle sera ensuite
  revalorisée ; les deux étant identiques, ils se compensent et le diviseur se
  réduit à l'espérance de vie résiduelle. Le résultat est directement lisible.
- **Pas de réversion**, donc pas de rente sur deux têtes : la demande est
  explicite sur ce point.

Les tables elles-mêmes sont décrites au §9.

---

## 6. Les neutralisations

Sont **supprimés** dans les scénarios notionnels — tous activés par défaut dans
`Neutralisations` :

| Supprimé | Raison invoquée dans la demande |
|---|---|
| minimum contributif, minimum garanti, ASPA, PMR | supprimer les effets de seuil |
| majoration pour trois enfants et plus | avantage sans cotisation |
| majoration de durée d'assurance, AVPF | l'aide doit être versée au moment de la difficulté |
| pension de réversion | seules les cotisations comptent |
| bonifications, catégorie active | avantage sans cotisation |
| périodes assimilées (chômage, maladie, service militaire) | pas de cotisation, pas de droit |
| trimestres assimilés au régime de base | pas de cotisation, pas de droit |
| garantie minimale de points (Agirc) | droit gratuit |
| carrières longues | dispositif d'âge, remplacé par l'actuariel |
| décote et surcote | remplacées par le coefficient de conversion |

La page de simulation affiche désormais leur effet en euros, ligne à ligne :
sous-total contributif, puis chaque avantage, puis le total. Les lignes
s'additionnent exactement, et l'écart avec les scénarios notionnels devient
lisible — ce qu'ils retirent, c'est précisément la somme de ces lignes.

Les drapeaux ci-dessus ne sont pas lus par le scénario 1 : ils décrivent ce que
les scénarios notionnels retirent, pas ce que le droit en vigueur accorde. Les
lire des deux côtés amputait l'étalon du minimum contributif, de la majoration
pour trois enfants et de la MDA, c'est-à-dire précisément de ce qui protège les
carrières que le notionnel pénalise le plus : l'écart mesuré s'en trouvait
minoré.

**Mais ce tableau a longtemps annoncé retirer ce que le scénario 1 ne servait
pas.** On ne retire pas ce qui n'a jamais été mis, et cinq lignes étaient dans
ce cas : le minimum garanti, l'ASPA, l'AVPF, la garantie minimale de points et
la carrière longue. Elles sont désormais calculées. L'état exact, ligne à
ligne :

| Ligne du tableau | Le scénario 1 la sert-il ? |
|---|---|
| minimum contributif | oui, réservé au taux plein, deux prorata, écrêté |
| minimum garanti | oui, barème de l'article L. 17 |
| ASPA | oui, à partir de 65 ans, barème d'une personne seule, ligne séparée |
| PMR (retraite agricole) | **non** — voir `docs/limites.md` |
| majoration pour trois enfants | oui, plafonnée en euros à la complémentaire |
| majoration de durée d'assurance | oui, attribuée dans un régime |
| AVPF | oui, salaire forfaitaire au SMIC porté au compte |
| pension de réversion | **non** — elle ne concerne pas l'assuré lui-même |
| bonifications, catégorie active | **non** — elles supposent des informations que le modèle n'a pas |
| périodes assimilées | oui, motif par motif |
| garantie minimale de points | oui, 120 points par an de 1989 à 2018 |
| carrières longues | oui, pour dire si le droit ouvre la liquidation |
| décote et surcote | oui, barème propre à la fonction publique compris |
| coefficient de solidarité Agirc-Arrco | **non** — dispositif éteint, voir `docs/limites.md` |

Une seule exception, et elle est explicite : la valorisation des droits acquis
du scénario 3 appelle le scénario 1 avec `avantages_non_contributifs=False`,
parce qu'elle mesure du contributif pur.

Le critère retenu pour une période non cotisée est **le versement effectif de
cotisations**, pas la nature de la période — et c'est bien ainsi que le modèle
la traite, motif par motif
(`data/reference/legislation/periodes_non_travaillees.csv`). Deux droits sont à
distinguer, et ils ne suivent pas la même règle :

- les **trimestres assimilés** comptent dans la durée d'assurance du régime de
  base sans aucune cotisation. Ils protègent de la décote et entrent dans la
  proratisation, mais n'ajoutent aucun salaire au compte, donc rien au salaire
  de référence. Le scénario 1 les conserve, les scénarios notionnels les
  suppriment ;
- les **points complémentaires** sont, eux, de vrais droits contributifs :
  pendant un chômage indemnisé, l'UNEDIC verse des cotisations à l'Agirc-Arrco,
  calculées sur le salaire d'avant l'interruption. Ils sont donc acquis dans
  les trois scénarios, y compris en notionnel — puisque des cotisations ont
  bien été versées.

Une année de chômage indemnisé n'est donc pas vide à l'Agirc-Arrco alors
qu'elle l'est à la CNAV ; une année de chômage non indemnisé est vide partout.

### La validation des trimestres

Un trimestre ne s'acquiert pas par le temps qui passe mais par un **montant
cotisé** : 150 fois le SMIC horaire depuis 2014, 200 fois entre 1972 et 2013,
dans la limite de quatre par année civile. Une année à temps très partiel en
valide donc moins de quatre. La série du SMIC horaire vient d'OpenFisca-France
(`scripts/fetch/openfisca_smic.py`), transcription du *Journal officiel* : elle
plafonne à la fiabilité `haute`.

---

## 7. La fusion des régimes

À compter de l'année de bascule (2026 par défaut), les régimes disparaissent au
profit d'un régime unique construit **au cas le plus défavorable** :

| Paramètre | Règle | Valeur 2026 |
|---|---|---|
| âge d'ouverture | le plus élevé | 64 ans |
| âge du taux plein | le plus élevé | 67 ans |
| durée requise | la plus longue | 172 trimestres |
| salaire de référence | le moins avantageux | carrière entière |
| assiette | la plus large | déplafonnée |
| avantages non contributifs | aucun | — |

**Le taux de cotisation fait exception, et c'est le seul.** Le retenir « au plus
défavorable » n'aurait pas de sens : un taux plus faible réduit les droits, mais
réduit tout autant les prélèvements. Retenir le maximum n'est pas meilleur : ce
maximum est le taux de tranche 2 de l'Agirc-Arrco (21,59 %), qui ne s'applique
aujourd'hui qu'au-dessus du plafond. Le régime fusionné retient donc la **somme
des taux d'un statut pivot** — régime général 17,86 % + Agirc-Arrco 7,87 % =
**25,73 %** — c'est-à-dire l'effort contributif réel d'un salarié pour une
retraite complète. Modifiable par `RegleFusion.critere_taux`.

Le régime unique **hérite aussi de la répartition salarié/employeur** de ses
régimes pivots : 10,45 % de part salariale sur 25,73 % en 2026. Ce n'est pas une
décision de la fusion mais la conséquence de ce qui la compose, et c'est elle
qui, après la bascule, sépare le scénario 5 du scénario 3. Une exception : un
assuré qui n'avait pas d'employeur — artisan, libéral — n'en gagne pas un en
changeant de régime ; le taux unique lui est alors intégralement personnel.

**Conséquence à connaître.** Ce taux appliqué à une assiette déplafonnée
augmente fortement les cotisations des indépendants et des professions
libérales, qui cotisent aujourd'hui à taux plus faible et sur assiette plafonnée.
Leur pension notionnelle monte en proportion : c'est pour eux la seule ligne du
tableau des cas types qui progresse. Le résultat est correct, il faut seulement
savoir qu'il traduit une hausse de prélèvement, pas un cadeau.

---

## 8. Les cinq scénarios

### Scénario 1 — le système actuel

Étalon en droit constant. Approximation documentée, pas un simulateur officiel
(voir `docs/limites.md` §3).

Les régimes en annuités suivent la formule `taux × salaire de référence ×
durée / durée requise`. Les **régimes en points** sont calculés en points, et
non par un rendement moyen :

```
points acquis en année t = cotisation(t) / (taux d'appel(t) × salaire de référence(t))
pension                  = Σ points × valeur de service (année de liquidation)
```

Le taux d'appel est le décalage, invisible ailleurs, entre ce qui est prélevé et
ce qui ouvre des droits : depuis 1995, cotiser 125 € n'acquiert que 100 € de
points. L'ignorer surestimerait la retraite complémentaire d'un quart.

Un régime fermé ne sert plus ses points : ils passent à son successeur, au
coefficient que l'accord de fusion a fixé. Le modèle refait ce chemin (UNIRS →
Arrco → Agirc-Arrco, Agirc → Agirc-Arrco, IPACTE et IGRANTE → Ircantec) à
partir de `regimes/conversions_points.csv`, où **ces coefficients sont lus et
non plus devinés**.

Les deviner coûtait cher, et de deux façons. Le modèle prenait le rapport entre
la dernière valeur de service du régime d'origine et la **première** du
successeur ; or les séries `arrco` et `ircantec` sont rétro-remplies bien avant
leur fusion — la première depuis 1957 avec les valeurs de l'UNIRS, la seconde
depuis 1949 avec celles de l'IPACTE. On comparait donc deux valeurs distantes
de quarante ou soixante-dix ans : le point UNIRS ressortait **quinze fois** trop
cher pour toute liquidation postérieure à 1998, le point IPACTE **cinquante-quatre
fois** trop cher au-delà de 2022. Jusqu'à 35 % de la pension du scénario 1 n'avait
alors aucune existence, et la case « SMIC carrière complète, génération 1940 » de
la grille de cas types en était atteinte. Et là même où les deux bornes tombaient
juste, la valeur du successeur était celle du 31 décembre quand la conversion
s'opère au 1<sup>er</sup> janvier : un pour cent de trop peu sur tous les points
d'avant 2019.

**L'unification Arrco du 1<sup>er</sup> janvier 1999 n'est pas une fusion mais un
changement d'unité**, et c'est le défaut le plus lourd que ce fichier corrige.
Les valeurs d'achat et de service portées ici pour les années antérieures sont
celles de l'UNIRS, la plus grosse des quarante-cinq caisses Arrco ; celles
d'après 1999 sont celles du régime unifié, dont la valeur de service a été fixée
à 6,55957 F, soit exactement 1 €. Le moteur accumulait des points dans la
première unité et les liquidait dans la seconde : cent euros cotisés en 1998
produisaient 30,31 € de pension annuelle quand les mêmes cent euros de 1999 n'en
produisaient que 11,15 — un facteur 2,7 en une année, pour une opération que la
formule officielle rendait neutre par construction. Le coefficient, 0,387464,
est la valeur du point UNIRS au 31 décembre 1998. La correction abaisse la
pension du scénario 1 de 1,3 % pour un cadre né en 1975 à 17 % pour les
générations nées entre 1940 et 1955.

Les régimes dont le dépôt n'a pas les barèmes — CNAVPL, MSA, CNBF, RCI, RAFP —
gardent l'ancienne approximation : `pension = cotisations revalorisées ×
rendement instantané`, où le rendement est `valeur de service / (taux d'appel ×
salaire de référence)`.

#### Ce que chaque régime liquide, et sur quoi

Le salaire de référence porte sur **les seules années passées dans ce
régime-là**. Un régime ne liquide que ce qui lui a été déclaré : la pension
civile se calcule sur le traitement des six derniers mois de service, pas sur le
dernier salaire d'une carrière poursuivie ailleurs. Le modèle a longtemps pris
toute la carrière, si bien qu'un agent SNCF passé au régime général liquidait sa
pension spéciale sur son dernier salaire de salarié — vingt pour cent de trop
sur un cas type — pendant que le prorata de durée, lui, restait celui du régime.

**Les salaires portés au compte sont revalorisés par les coefficients que la
Cnav publie**, lus dans `legislation/revalorisation_salaires.csv`. Cette grandeur
commande le salaire annuel moyen deux fois plutôt qu'une : la moyenne porte sur
les N MEILLEURES années, et « meilleures » se juge sur des salaires revalorisés
— changer les coefficients ne déplace donc pas seulement le niveau de chaque
année, cela change lesquelles sont retenues.

Le modèle les approchait par « les salaires jusqu'en 1986, les prix depuis », ce
qu'ont fait les arrêtés dans les grandes lignes. Mais seulement dans les grandes
lignes : ils ont connu des revalorisations semestrielles, des gels, des
revalorisations exceptionnelles, et des changements du délai d'application.
L'approximation **sur-revalorise les salaires anciens de 12,1 % sur 1970-2018**,
et gonflait d'autant le salaire de référence de toute carrière en comportant.

La source est la circulaire annuelle de revalorisation de la Cnav, qui publie la
table entière : c'est la caisse qui les applique qui les publie. Le dépôt a
d'abord repris la table d'OpenFisca-France-Pension, à qui il manque la
revalorisation exceptionnelle de 4 % du 1<sup>er</sup> juillet 2022 — de 3 à
5,5 % d'écart avec la circulaire sur toutes les perceptions postérieures à 1990,
et jusqu'à 17 % sur les années 1950. Une seconde implémentation est une
contre-expertise, pas une source.

**Un seul indice par année de perception suffit** : le coefficient entre deux
années quelconques est le rapport de leurs indices, parce que l'arrêté annuel
applique un coefficient unique à tous les salaires déjà portés au compte.
Reconstruire ainsi les colonnes publiées pour 2023 et 2025 à partir de celle de
2026 les retrouve à 0,13 %, l'arrondi de la table publiée ; le récupérateur
revérifie ce recoupement à chaque exécution.

Au-delà de l'année de référence — 2026, et c'est l'année où le site liquide par
défaut — le coefficient est ancré sur elle et l'approximation ne couvre que les
dernières années. Avant 1930, il n'y a rien sur quoi ancrer. Les régimes qui
liquident sur le dernier traitement ou sur les six derniers mois ne portent
aucun salaire à un compte : elle y reste la règle.

#### Le taux plein, et ce qui l'ouvre

Trois choses distinctes, que le modèle confondait :

* **l'âge d'OUVERTURE des droits**, en deçà duquel aucune liquidation n'est
  possible — sauf carrière longue ;
* **la durée requise**, qui ouvre le taux plein à l'âge d'ouverture ;
* **l'âge d'ANNULATION de la décote**, qui l'ouvre sans condition de durée.

**La durée requise et la durée de proratisation sont deux paramètres, et le
modèle les confondait.** La première (L. 161-17-3) commande le TAUX : en deçà,
la décote s'applique. La seconde (R. 351-6) est le DÉNOMINATEUR qui réduit la
pension d'une carrière incomplète. La loi du 22 juillet 1993 a fait monter la
première de 150 à 160 trimestres pour les générations 1934 à 1943 ; elle n'a
touché à la seconde que pour les générations 1944 à 1948, et de deux trimestres
par génération — 150 avant 1944, puis 152, 154, 156, 158, 160. Un assuré né en
1945 ayant validé 156 trimestres se voit donc opposer 160 trimestres pour le
taux, et il est décoté de quatre, mais 154 pour la proratisation : son
coefficient vaut 1, et non 156/160. Le modèle lui retirait 2,5 % de pension de
base que le droit ne retire pas. La table est dans
`legislation/duree_proratisation.csv`, et elle est réservée aux régimes alignés
sur le code de la sécurité sociale : la fonction publique et les régimes
spéciaux ont la leur, calendaire (L. 13 du code des pensions), qui n'est pas
modélisée.

Le taux plein par la durée est une création de l'ordonnance du 26 mars 1982.
Avant elle, le taux ne dépendait QUE de l'âge : 20 % à 60 ans majorés de quatre
points par année différée jusqu'en 1971, puis — loi Boulin — 25 % à 60 ans et
50 % à 65. Une carrière de quarante ans liquidée à 60 ans en 1975 était servie
au même taux réduit qu'une carrière de vingt.

La **fonction publique** n'a pas la décote du régime général. L'article L. 14 du
code des pensions lui donne la sienne, et rien n'y coïncide : elle n'existe qu'à
compter de 2006, son coefficient monte d'un huitième de point par an jusqu'à
1,25 % en 2015, et son âge d'annulation n'est pas un âge en propre mais la
**limite d'âge du grade**, diminuée d'un nombre de trimestres décroissant
jusqu'à s'annuler en 2020. Un sédentaire liquidant en 2012 voyait sa décote
s'annuler à 63 ans, pas à 67.

#### La cascade des avantages non contributifs, dans l'ordre du droit

L'ordre n'est pas indifférent : chaque étage se calcule sur le résultat du
précédent, et le modèle en prenait deux à l'envers.

1. **AVPF** — la Caisse nationale des allocations familiales cotise au régime
   général pour le parent qui interrompt son activité, sur une assiette
   forfaitaire égale au SMIC. Ce salaire est PORTÉ AU COMPTE : c'est ce qui
   distingue l'AVPF d'une période assimilée, laquelle valide des trimestres sans
   jamais ajouter de salaire. Son effet n'est pas toujours favorable — sur une
   carrière de moins de vingt-cinq années portées au compte, les années au SMIC
   s'ajoutent aux années retenues au lieu de les remplacer, et abaissent la
   moyenne. C'est la règle, et le modèle la montre telle qu'elle est.
2. **Trimestres accordés au titre des enfants** — datés, sexués, et propres à
   chaque famille de régimes (`legislation/majoration_duree_assurance.csv`). La
   majoration de durée d'assurance de l'article L. 351-4 naît avec la loi du
   31 décembre 1971 à un an par enfant, passe à deux ans en 1975, et va à la
   mère : le partage ouvert en 2010 entre maternité et éducation laisse à la
   mère, à défaut d'accord des parents, les mêmes huit trimestres. La fonction
   publique et les régimes spéciaux ne l'appliquent pas : ils servent la
   bonification de l'article L. 12 b, un an par enfant né avant 2004, puis les
   deux trimestres de l'article L. 12 bis pour les enfants nés depuis. Les
   régimes alignés — artisans, commerçants, salariés agricoles — suivent le
   régime général (L. 634-2). Dans tous les cas ces trimestres sont attribués
   DANS un régime et non au-dessus d'eux : ils comptent donc aussi dans sa
   proratisation, pas seulement dans la décote tous régimes confondus.
3. **Minimum contributif** — réservé aux pensions liquidées AU TAUX PLEIN
   (L. 351-10). Deux durées le proratisent, et ce ne sont pas les mêmes : le
   montant de base suit la durée d'assurance acquise dans le régime, sa
   majoration au titre des périodes cotisées suit la seule durée cotisée
   (D. 351-2-2), et cette majoration demande en outre 120 trimestres cotisés
   tous régimes. Il se compare à la pension AVANT surcote, puis est écrêté de ce
   qui ferait dépasser le plafond de l'article L. 173-2 — plafond auquel se
   comparent les pensions personnelles, majorations pour enfants exclues.
4. **Minimum garanti** de la fonction publique (L. 17) — non pas un plancher
   proratisé mais un barème en escalier sur la durée de services : 57,5 % de la
   référence à quinze ans, 95 % à trente, la totalité à quarante. La référence
   est le traitement de l'indice majoré 227 au 1er janvier 2004, revalorisé
   comme les pensions depuis. Il n'est dû qu'au taux plein depuis la loi du
   9 novembre 2010.
5. **Surcote parentale** (L. 351-1-2-1) — 1,25 % par trimestre acquis entre
   63 ans et l'âge légal, quatre au plus, à l'assuré qui justifie de la durée
   requise à 63 ans et détient au moins un trimestre de majoration pour enfants.
   C'est la contrepartie du recul de l'âge légal voulu par la loi du 14 avril
   2023 : l'année de travail qu'elle impose à qui avait déjà sa durée ne
   rapportait rien, la surcote ordinaire ne comptant qu'au-delà de l'âge légal.
   Les deux se cumulent donc sans se recouvrir. Sa montée en charge est celle de
   l'âge légal : rien jusqu'à la génération 1964, un trimestre pour 1965, quatre
   à partir de 1968. C'est le trimestre pour enfants qui ouvre le droit, et non
   le sexe.
6. **Majoration pour trois enfants et plus** — 10 %, davantage dans la fonction
   publique, calculée sur le montant DÉJÀ RELEVÉ par les minima, et plafonnée en
   euros à la complémentaire.
7. **Minimum vieillesse** — allocation différentielle qui complète tout le
   reste, majorations comprises, jusqu'au barème d'une personne seule. Servie à
   partir de 65 ans, et toujours affichée comme une ligne séparée : ce n'est pas
   une pension mais une aide sociale, soumise à condition de ressources du
   foyer, à demande, et récupérable sur les successions. Le paramètre
   `minimum_vieillesse_dans_le_scenario_actuel` la retire d'un seul geste.

#### Le droit ouvre-t-il cette liquidation ?

Le modèle calculait une pension à n'importe quel âge sans jamais dire si la loi
ouvrait ce départ-là. Un salarié né en 1965 y liquidait à 58 ans une pension
décotée que le droit ne lui aurait pas servie du tout. La question est
maintenant posée, et sa réponse accompagne le montant : l'âge d'ouverture du
régime le plus précoce de la carrière, ou le **départ anticipé pour carrière
longue** de l'article L. 351-1-1 — cinq trimestres validés avant la fin de
l'année civile des seize, dix-huit, vingt ou vingt et un ans, et une durée
cotisée au moins égale à la durée requise.

Quand la liquidation n'est pas ouverte, le montant reste calculé : il faut bien
comparer les trois scénarios sur la même carrière. Mais il ne décrit alors
aucune pension que le système actuel servirait, et la restitution le dit.

### Scénario 2 — comptes notionnels rétroactifs

Compte ouvert à l'entrée dans la vie active, ou en 1941 si la carrière a commencé
avant. Toute la carrière est recalculée. C'est le scénario qui répond à
« qu'aurait été ma retraite si le système avait toujours été notionnel ».

Ce qu'on y porte est la **part salariale** de la cotisation — ce que l'assuré a
supporté lui-même, la même grandeur pour tous les statuts. La part de
l'employeur fait l'objet des scénarios 4 et 5.

### Scénario 3 — comptes notionnels à compter d'aujourd'hui

Les droits acquis à la bascule sont figés selon les règles actuelles, convertis
en capital notionnel d'ouverture, puis le compte fonctionne en notionnel au-delà.

La conversion des droits acquis inverse la formule de liquidation :

```
capital d'ouverture = pension de droits figés × G(âge de conversion, année de bascule)
```

Trois précisions importantes :

- les droits figés sont calculés **sans décote ni surcote d'âge** : on mesure des
  droits déjà ouverts, pas une liquidation anticipée ;
- **l'âge de conversion est un choix, pas une donnée**, et c'est le seul endroit
  du modèle où le passage aux comptes notionnels peut, à lui seul, retirer
  quelque chose à des droits déjà ouverts. Voir ci-dessous ;
- pour un assuré **déjà retraité** à la bascule, ce scénario renvoie sa pension
  actuelle inchangée. Ses droits sont intégralement acquis ; tout autre résultat
  serait dépourvu de sens.

#### L'âge de conversion des droits acquis

Le capital d'ouverture est obtenu en multipliant une pension par un diviseur,
puis il sera redivisé par le diviseur de l'âge réel de liquidation. Si les deux
diviseurs diffèrent, la conversion n'est pas neutre.

| `--conversion-acquis` | Diviseur pris à | Effet sur des droits déjà ouverts |
|---|---|---|
| `reference` (défaut) | l'âge de référence | abattement du rapport des diviseurs si l'assuré part avant cet âge |
| `liquidation` | l'âge de départ effectif | aucun : la conversion est neutre |

Pour un salarié né en 1975 partant à 64 ans, l'âge de référence est de 67 ans :
les droits acquis sont convertis à `G(67, 2026) = 22,03` puis servis à
`G(64, 2039) = 25,81`. L'écart entre les deux, environ 10 %, est retiré de
droits que le système actuel aurait servis sans décote — l'anticipation est
payée une seconde fois, sur le passé. La pension du scénario 3 passe de
25 771 € à 27 808 € par an lorsqu'on retient l'autre convention.

Le défaut est la lecture stricte du cahier des charges : dans un système
notionnel, l'âge de départ se paie, y compris sur le passé. `liquidation` est la
convention qu'une réforme réelle retiendrait, puisqu'elle seule respecte
véritablement les droits acquis. Les deux sont fournies, et le modèle affiche la
cascade de calcul pour que l'écart soit visible plutôt que subi.

Dans les deux cas, l'écart de longévité entre l'année de bascule et l'année de
liquidation subsiste : `G(64, 2039)` dépasse `G(64, 2026)` parce que l'espérance
de vie progresse. C'est un effet de table, pas une pénalité d'âge, et il est
inhérent au principe même des comptes notionnels.

### Le périmètre du taux de cotisation

Les fiches de régime ne stockent pas la même grandeur selon le secteur, et rien
ne le disait :

| Secteur | Ce que porte `taux_cotisation_retraite` | Valeur 2023 |
|---|---|---|
| Privé (régime général + Agirc-Arrco) | total salarié **+ employeur** | 25,7 % |
| Fonction publique, régimes spéciaux | retenue de l'agent **seule** | 11,10 %, parfois 7 % |

Alimenter un compte notionnel avec ces deux grandeurs revient à comparer un
effort contributif complet à un demi-effort. À rémunération et carrière
identiques, un fonctionnaire affichait une pension notionnelle inférieure de
37 % à celle d'un salarié — écart qui ne traduisait aucune règle de retraite.

Le modèle a d'abord refermé cet écart par une **convention** : prêter au public
la part employeur du privé. Elle rendait les statuts comparables, mais au prix
d'un chiffre inventé, et elle interdisait de poser la question la plus simple —
combien l'assuré verse-t-il, et combien son employeur ? Deux séries permettent
aujourd'hui d'y répondre sans rien inventer.

#### `part_salariale` : qui paie quoi, dans les fiches

Chaque période de fiche porte désormais la fraction du taux que l'assuré
supporte lui-même. Le défaut, `1.0`, couvre deux cas où il n'y a rien à
partager : les **non-salariés**, dont la cotisation est intégralement
personnelle, et les périodes **`agent_seul`**, dont le taux est déjà la seule
retenue de l'agent. Toute autre période doit porter une valeur explicite, et
`scripts/verifier_donnees.py` échoue si l'une manque.

| Régime | Période | Part salariale | Origine |
|---|---|---:|---|
| Régime général | 1945-1971 | 34,79 % | mesurée sur 1968-1971, OpenFisca ne remontant pas plus haut |
| Régime général | 1972-1982 | 33,24 % | OpenFisca, moyenne de période |
| Régime général | 1983-1993 | 42,53 % | idem |
| Régime général | 1994-2022 | 40,1 à 41,0 % | idem |
| Régime général | 2023- | 40,87 % | idem |
| Arrco, Agirc-Arrco, Ircantec | toutes | 40 % | règle de répartition 40-60 (ANI du 17 novembre 2017, art. 38) |
| Agirc | 1947-1980 | 25 % | OpenFisca : un quart, trois quarts |
| Agirc | 1981-2018 | 31 à 37 % | OpenFisca, moyenne de période |
| RAFP | 2005- | 50 % | décret 2004-569 : 5 % agent, 5 % employeur |
| Assurances sociales, AVTS | 1930-1945 | 50 % | loi du 30 avril 1930 : 8 %, moitié ouvrier moitié patron |

La part est une **moyenne sur la période**, comme le taux lui-même : les fiches
sont découpées par période législative, et les parts salariale et patronale
bougent chacune à son rythme. Le contrôle de vraisemblance les confronte année
par année à OpenFisca, et le fait pour la répartition comme pour le taux.

**Le drapeau porte sur le STATUT, pas seulement sur le régime.** Un artisan
cotise au régime général, dont la fiche porte la répartition 41/59 d'un salarié.
Le taux y est le bon — un artisan verse à peu près ce que verse le couple
salarié-employeur — mais la répartition ne le concerne pas : lui paie tout.
`affiliations.yaml` marque donc `sans_employeur: true` les cinq statuts
concernés (artisan, commerçant, profession libérale, avocat, exploitant
agricole), et le modèle force alors la part à un.

#### La contribution employeur du public

Elle n'est dans aucune fiche, et le dépôt a longtemps soutenu qu'elle n'existait
pas avant 2006. C'était vrai de l'État, et faux du reste.

- La **CNRACL** est une caisse depuis 1947 : le taux versé par les employeurs
  territoriaux et hospitaliers est fixé par décret et publié depuis 1948 — 12 %
  à l'origine, 10,2 % au creux de 1984, 34,65 % en 2025.
- L'**État** a bien un taux avant 2006, non pas appelé mais **reconstitué** :
  l'annexe « pensions » au PLF 2011 publie, page 26, une série de « taux de
  cotisation employeur implicite » remontant à 1995.
- Depuis 2006 le taux est appelé par décret, et le Service des retraites de
  l'État en publie l'historique : 49,90 %, puis 74,28 % de 2013 à 2024, 78,28 %
  en 2025, 82,28 % en 2026.
- La **SNCF** publie par arrêté les composantes T1 et T2 de la contribution de
  l'entreprise, de 2007 à 2018.

La série est dans `legislation/contribution_employeur_public.csv`. Trois
conventions à connaître. L'**assiette ne change pas** : le taux du CAS porte sur
le traitement indiciaire brut et la NBI, à l'exclusion des primes — exactement
l'assiette `hors_primes` des fiches. Le **taux retenu est celui du 1er
janvier**, comme partout ailleurs dans le dépôt ; deux abattements d'un mois y
échappent volontairement, décembre 2009 et décembre 2013, qui soldent l'exercice
budgétaire. Enfin, **là où la série n'existe pas, le modèle le dit** : avant 1995
pour l'État, avant 1948 pour la CNRACL, hors 2007-2018 pour la SNCF, et pour les
douze régimes spéciaux qui n'en publient aucune, la part patronale est estimée
par l'effort d'un salarié du privé de la même année, la fiabilité retombe à
`estimee`, et le nombre d'années concernées est affiché sous la simulation.

La marche 2005 → 2006, où le taux de l'État passe de 59,4 % à 49,9 %, n'est pas
une baisse du coût des droits : c'est un changement de mesure, le périmètre du
taux implicite étant plus étroit que celui du CAS.

### Scénarios 4 et 5 — les mêmes, part patronale comprise

Ce sont **exactement les scénarios 2 et 3**, à une différence près et une
seule : ce qui alimente le compte.

| | Point de départ du compte | Ce qui y est porté |
|---|---|---|
| **2** | origine de la répartition | la part **salariale** seule |
| **3** | année de bascule, droits acquis figés | la part **salariale** seule |
| **4** | origine de la répartition | salariale **et patronale** |
| **5** | année de bascule, droits acquis figés | salariale **et patronale** |

Le 4 se lit donc contre le 2, le 5 contre le 3, et l'écart mesure une chose à la
fois : ce que verse l'employeur. Pour un **non-salarié**, qui n'en a pas, les
quatre scénarios se réduisent à deux — et c'est le test qui le vérifie.

Le paramètre est `part_cotisation`, en ligne de commande `--part-cotisation`.
Une troisième valeur, `totale_alignee`, conserve l'ancienne convention — part
patronale du public empruntée au privé — comme contrefactuel : elle répond à
« à effort contributif égal, que donnerait la règle notionnelle ? », question
légitime mais différente, et sous elle un fonctionnaire et un salarié de même
rémunération retrouvent exactement la même pension.

#### Après la bascule, le régime unique tranche

À compter de la bascule il n'y a plus ni fonction publique ni régimes spéciaux :
un seul régime, dont le taux est la somme des taux du statut pivot privé (§7).
Il en **hérite la répartition** salarié/employeur — 10,45 % de part salariale
sur 25,73 % en 2026 — et c'est elle qui sépare le scénario 5 du scénario 3 après
la bascule. Il n'y a donc, après la bascule, aucune contribution publique à
retrouver décret par décret : la réforme l'a remplacée.

Une exception, et une seule : un assuré qui n'avait pas d'employeur n'en gagne
pas un en changeant de régime. Un artisan cotise seul avant la bascule ; il
cotise seul après, à un taux plus élevé — c'est déjà ce que dit le modèle (§7),
et la répartition doit le suivre.

#### Ce que ces scénarios ne disent pas

Les taux employeur publics sont des taux d'**équilibre**, fixés pour que le
compte tombe juste. Un taux de 82,28 % ne signifie pas qu'un fonctionnaire
acquiert 82 % de son traitement en droits nouveaux : il signifie qu'il faut
aujourd'hui cette contribution pour payer les pensions d'aujourd'hui,
démographie et engagements hérités compris. Les porter à un compte notionnel
répond à une question précise :

> qu'aurait donné un compte notionnel si **tout ce qui a été consacré aux
> pensions** avait été porté au compte des actifs ?

Et à elle seule. Ce n'est pas une proposition de réforme, pas plus que le
scénario 2 ne l'est.

Une troisième lecture existe — fixer un **taux d'acquisition commun** à tous, le
surplus restant une contribution de transition qui n'ouvre aucun droit — et le
moteur sait la calculer : `source_cotisations = taux_uniforme`, soit
`--cotisations taux_uniforme` en ligne de commande. Elle ne figure pas parmi les
cinq scénarios parce qu'elle ne répond pas à la même question : elle ne mesure
plus ce qui a été versé, mais ce qu'une réforme choisirait de reconnaître.

---

## 9. Les données

### Sources

`data/sources.yaml` recense les soixante et un jeux de données des vingt-six
institutions, avec pour chacun l'URL, le mode d'accès et l'état d'intégration.

### Fiabilité

Aucune valeur ne circule dans le modèle sans son niveau de fiabilité :

| Niveau | Sens |
|---|---|
| `certifiee` | recontrôlée automatiquement contre la source |
| `haute` | valeur publiée, recopiée, non recontrôlée |
| `moyenne` | valeur publiée mais champ ou base incertains |
| `estimee` | reconstitution, ou projection |

La fiabilité d'un résultat est celle de **son maillon le plus faible**.
`Parametres.fiabilite_minimale` fait échouer la simulation plutôt que de
produire un chiffre trompeur. `retraite-notionnelle donnees` en dresse l'état.

Le niveau `certifiee` suppose que la source soit le **producteur** de la donnée
et que la valeur ait été recontrôlée contre elle par
`scripts/verifier_donnees.py`. Une transcription tierce, même sourcée et reprise
automatiquement, plafonne à `haute`. L'état exact figure dans `docs/limites.md`.

### Tables de mortalité

Deux sources, par ordre de priorité, et le partage se fait couple par couple
(année, sexe, âge) — pas en bloc :

1. `data/reference/mortalite/quotients_periode.csv` — les **quotients observés**
   (`annee,sexe,age,qx`). Ils couvrent 1986-2024, des âges 0 à 84 puis 0 à 94
   selon les millésimes, et viennent de la table de mortalité française
   diffusée par Eurostat ;
2. partout ailleurs — avant 1986, au-delà du dernier âge publié, et pour les
   années projetées — une table paramétrique de **Gompertz-Makeham**
   `μ(x) = A + B·exp(k(x−60))`, dont *B* et *k* sont ajustés par bissection.

**La cible de cet ajustement est la table RACCORDÉE, pas la loi seule**, et
c'est ce qui a longtemps manqué. Calibrée sur elle-même, la loi n'avait aucune
raison de rendre la queue que la cible implique : elle donnait 11,3 ans
d'espérance résiduelle à 85 ans pour une femme en 2010, quand l'espérance
publiée à 60 ans en implique 7,5. Comme les millésimes 1998-2013 s'arrêtent à
84 ans, la table effectivement lue par le modèle débordait alors l'espérance de
l'INSEE de jusqu'à 2,5 ans.

L'ajustement se fait donc en deux temps. La **forme** de la queue — le
paramètre *k* — vient de la calibration classique sur la loi seule, où e60 et
e65 portent sur toute la plage d'âges et la déterminent sans ambiguïté. Son
**niveau** — le paramètre *B* — est ensuite recalé, à forme constante, pour que
la table raccordée reproduise l'espérance publiée à 60 ans. Là où la queue n'a
pas prise sur la cible — millésimes dont les quotients vont jusqu'à 104 ans, où
les données décident seules —, le recalage est abandonné plutôt que forcé.

Le raccord est contrôlé, et le contrôle est cette fois réel : un test recalcule
l'espérance de vie à 60 ans par le seul chemin que le moteur emprunte
(`survie_annuelle`, quotients observés puis loi) et la confronte à l'espérance
publiée par l'INSEE, qui vient d'une tout autre chaîne de production. Les deux
concordent à 0,1 an près sur 1990-2024. Le test précédent passait par une
branche qui ne consultait aucun quotient : il comparait la calibration à sa
propre cible et ne pouvait pas échouer.

Ce partage donne la bonne mortalité aux âges qui pilotent le diviseur sans
prétendre décrire la mortalité aux âges jeunes, qui n'entrent pas dans le
calcul.

### Unité de compte

Tous les montants sont produits en euros courants de l'année de liquidation
**et** en euros constants de 2026 (`annee_euros_constants`). Sans cette
conversion, comparer une pension liquidée en 1975 à une pension de 2064 n'a
aucun sens : l'écart de niveau des prix dépasse largement l'effet de la réforme
simulée.

### Ancrage des rémunérations

Les comptes nationaux ne publient que des taux de croissance du salaire moyen.
Le modèle les cumule à partir d'un point d'ancrage — 40 000 € bruts annuels en
2024 — documenté dans `carriere.py`. Ce point déplace proportionnellement tous
les revenus reconstitués, donc toutes les pensions, mais il est **sans effet sur
les rapports entre scénarios**, qui sont l'objet du modèle.
