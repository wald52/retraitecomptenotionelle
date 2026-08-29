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

Elle s'applique **à la fois** à la revalorisation des comptes en cours de
constitution et à la revalorisation des pensions déjà liquidées, depuis 1941.

### Ce qu'elle produit, et pourquoi il faut le savoir

Deux des trois termes sont nominaux, le troisième est réel. Dès que l'inflation
dépasse la croissance de la productivité — c'est-à-dire pendant la quasi-totalité
de la période 1945-1985 — c'est la productivité réelle qui l'emporte, et le
compte est revalorisé de 1 à 5 % quand les prix montent de 10 à 50 %.

Mesure sur la période complète (`retraite-notionnelle indexation --de 1941 --a 2025`) :

| Règle | Revalorisation cumulée 1941-2025 | Prix | Pouvoir d'achat conservé |
|---|---|---|---|
| Triple lock inversé, littéral | ×4,9 | ×318,6 | **1,5 %** |
| Triple lock inversé, tout en nominal | ×243,7 | ×318,6 | 76,5 % |
| Indexation sur les prix | ×318,6 | ×318,6 | 100 % |

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
des taux d'un statut pivot** — régime général 17,87 % + Agirc-Arrco 7,87 % =
**25,74 %** — c'est-à-dire l'effort contributif réel d'un salarié pour une
retraite complète. Modifiable par `RegleFusion.critere_taux`.

**Conséquence à connaître.** Ce taux appliqué à une assiette déplafonnée
augmente fortement les cotisations des indépendants et des professions
libérales, qui cotisent aujourd'hui à taux plus faible et sur assiette plafonnée.
Leur pension notionnelle monte en proportion : c'est pour eux la seule ligne du
tableau des cas types qui progresse. Le résultat est correct, il faut seulement
savoir qu'il traduit une hausse de prélèvement, pas un cadeau.

---

## 8. Les trois scénarios

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
rapport des deux valeurs de service à la date de la reprise — le rapport qui
laisse, par construction, les pensions inchangées le jour de la fusion. Le
modèle refait ce chemin (UNIRS → Arrco → Agirc-Arrco, Agirc → Agirc-Arrco,
IPACTE et IGRANTE → Ircantec) à partir de `regimes/valeurs_point.csv`.

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

#### Le taux plein, et ce qui l'ouvre

Trois choses distinctes, que le modèle confondait :

* **l'âge d'OUVERTURE des droits**, en deçà duquel aucune liquidation n'est
  possible — sauf carrière longue ;
* **la durée requise**, qui ouvre le taux plein à l'âge d'ouverture ;
* **l'âge d'ANNULATION de la décote**, qui l'ouvre sans condition de durée.

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
2. **Majoration de durée d'assurance** — huit trimestres par enfant, attribués
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
5. **Majoration pour trois enfants et plus** — 10 %, davantage dans la fonction
   publique, calculée sur le montant DÉJÀ RELEVÉ par les minima, et plafonnée en
   euros à la complémentaire.
6. **Minimum vieillesse** — allocation différentielle qui complète tout le
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

Les fiches de régime ne stockaient pas la même grandeur selon le secteur, et
rien ne le disait :

| Secteur | Ce que porte `taux_cotisation_retraite` | Valeur 2023 |
|---|---|---|
| Privé (régime général + Agirc-Arrco) | total salarié **+ employeur** | 25,7 % |
| Fonction publique, régimes spéciaux | retenue de l'agent **seule** | 11,10 %, parfois 7 % |

Alimenter un compte notionnel avec ces deux grandeurs revient à comparer un
effort contributif complet à un demi-effort. À rémunération et carrière
identiques, un fonctionnaire affichait une pension notionnelle inférieure de
37 % à celle d'un salarié — écart qui ne traduisait aucune règle de retraite.

Les périodes concernées portent désormais `perimetre_taux: agent_seul`, et le
paramètre `traitement_contribution_employeur_etat` dit quoi en faire :

- `alignee_sur_le_prive` (défaut) leur substitue le taux total du statut pivot
  privé de l'année. C'est déjà ce que fait la fusion des régimes après la
  bascule, et c'est le seul traitement qui rende les 22 statuts comparables ;
- `exclue` conserve le taux stocké, et reproduit les chiffres antérieurs.

**Pourquoi il n'existe pas de troisième option.** On aimerait utiliser la
contribution employeur réelle de l'État — 74,28 % du traitement pour les
civils. Elle n'est pas utilisable, pour deux raisons distinctes :

1. **Elle n'existe pas avant 2006.** Le compte d'affectation spéciale Pensions
   a été créé par la LOLF ; auparavant les pensions étaient payées sur crédits
   budgétaires, sans aucun taux. Il n'y a donc pas de série historique à
   retrouver — elle n'a jamais été produite.
2. **Depuis 2006, c'est un taux d'équilibre.** Il est recalculé chaque année
   pour que le compte tombe juste. L'injecter dans un compte notionnel rendrait
   le calcul circulaire : les cotisations y seraient égales aux pensions par
   construction, et le scénario 2 afficherait mécaniquement un écart nul pour
   les fonctionnaires. Ce ne serait pas un résultat, ce serait une tautologie.

L'alignement sur le privé est donc une convention, et elle est affichée comme
telle. Elle répond à la question « à effort contributif égal, que donnerait la
règle notionnelle ? », qui est la seule que ce modèle puisse honnêtement poser
sur le secteur public.

---

## 9. Les données

### Sources

`data/sources.yaml` recense les jeux de données des dix-neuf institutions
demandées, avec pour chacun l'URL, le mode d'accès et l'état d'intégration.

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
   `μ(x) = A + B·exp(k(x−60))`, dont *B* et *k* sont ajustés par bissection pour
   reproduire **exactement** les espérances de vie publiées à 60 et 65 ans.

Le raccord entre les deux est assumé, et il est contrôlé : un test recalcule
l'espérance de vie à 60 ans à partir des seuls quotients observés et la
confronte à l'espérance publiée par l'INSEE, qui vient d'une tout autre chaîne
de production. Les deux concordent à 0,4 an près. La calibration paramétrique,
elle, est vérifiée à 0,05 an près sur ses propres cibles.

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
