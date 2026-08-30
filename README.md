# Retraite à comptes notionnels — modèle français rétroactif

**Ce dépôt répond à une question : que verserait la retraite française si elle
avait toujours été calculée en comptes notionnels, c'est-à-dire au franc le
franc des cotisations réellement versées ?**

Un compte notionnel est un compte virtuel — aucun capital n'est placé, la
répartition reste la répartition. Ce qui change, c'est le calcul du droit :

1. **accumulation** — chaque année, la cotisation retraite effectivement versée
   est inscrite au compte ;
2. **revalorisation** — le solde est revalorisé chaque année selon une règle
   collective ;
3. **liquidation** — `pension = capital notionnel ÷ espérance de vie restante`
   à l'âge de départ.

Il n'y a donc ni minimum, ni majoration, ni trimestre gratuit : ce qui n'a pas
été cotisé n'existe pas, et partir tôt coûte deux fois — moins de cotisations
accumulées, et une rente à servir plus longtemps.

Le modèle calcule **cinq scénarios pour une même carrière**, afin qu'ils soient
comparables :

| | Scénario | Ce qu'il mesure |
|---|---|---|
| **1** | Système actuel | Le droit en vigueur, minima et majorations compris. C'est la référence. |
| **2** | Notionnel **rétroactif** depuis 1941 | Contrefactuel : toute la carrière recalculée sur les seules cotisations, comme si la règle avait toujours existé. |
| **3** | Notionnel **à compter de 2026** | Réforme prospective : les droits déjà acquis sont conservés, les règles notionnelles s'appliquent ensuite. |
| **4** | Le scénario **2**, cotisations employeur incluses | Le même compte rétroactif, mais ce que l'employeur public a réellement versé — jusqu'à 82,28 % du traitement en 2026 — y est porté au lieu d'être remplacé par l'effort du privé. |
| **5** | Le scénario **3**, cotisations employeur incluses | Le même compte prospectif, droits acquis conservés, avec la même correction sur la part employeur du public. |

```
Agent de conduite SNCF né en 1955, parti à 50 ans (quinze ans avant l'âge de référence)

Scénario                                                  Courants   Constants   Mensuel    Écart
------------------------------------------------------------------------------------------------
1. Système actuel                                          15,719€     22,008€    1,834€     réf.
2. Notionnel rétroactif (depuis l'origine)                  3,298€      4,617€      385€   -79.0%
3. Notionnel à compter de 2026                             15,719€     22,008€    1,834€    +0.0%
4. Notionnel rétroactif, cotisations employeur              3,298€      4,617€      385€   -79.0%
5. Notionnel à compter de 2026, cotisations employeur      15,719€     22,008€    1,834€    +0.0%
```

> Les scénarios 4 et 5 sont les scénarios 2 et 3, à une différence près : **ce
> qui alimente le compte d'un agent public**. Même carrière, même indexation,
> même liquidation, mêmes droits acquis figés à la bascule. Ici, ils ne s'en
> écartent pas d'un euro — aucune série de contribution employeur n'est publiée
> pour la SNCF avant 2007, et le modèle le dit plutôt que d'inventer. Pour un
> fonctionnaire d'État, l'écart est tout autre : voir
> [« Qui verse les cotisations d'un agent public »](#3-qui-verse-les-cotisations-dun-agent-public).

> **Le scénario 2 n'est pas une proposition de réforme**, et l'écart qu'il
> affiche ne mesure pas l'effet des comptes notionnels. Il vient pour
> l'essentiel de la règle d'indexation retenue — voir
> [« La règle d'indexation domine tout le reste »](#1-la-règle-dindexation-domine-tout-le-reste)
> plus bas. Le modèle permet de séparer les deux effets ; c'est même son
> principal résultat.

---

## Ouvrir le simulateur

### 👉 [wald52.github.io/retraitecomptenotionelle](https://wald52.github.io/retraitecomptenotionelle/)

Rien à installer, rien à lancer : une adresse à ouvrir. Le modèle et ses données
de référence s'exécutent **dans votre navigateur**. Aucune donnée saisie ne
quitte votre machine, puisqu'il n'y a pas de serveur de calcul. Le premier
chargement transfère 212 Ko compressés (781 Ko bruts) et prend quelques dixièmes
de seconde ; les suivants sont immédiats.

Quatre pages : **Simuler** (une carrière, avec le détail du calcul, la
décomposition de l'écart règle par règle et la cascade qui mène du scénario 1 au
scénario 3), **Cas types** (la grille 12 carrières × 7 générations),
**Méthode**, **Données** (l'état de fiabilité des séries).

L'adresse d'une simulation contient tous ses paramètres — elle peut être citée
ou partagée telle quelle — et chaque résultat est consultable en JSON au bas de
la page.

<details>
<summary>Comment la page fonctionne, et comment on sait qu'elle dit vrai</summary>

`index.html` charge deux choses : `moteur/donnees.json` (521 Ko — les séries, les
tables de mortalité observées de 1899 à 2024, les 37 fiches de régime) et
`moteur/js/`, un portage du modèle en JavaScript sans aucune bibliothèque. Le site est servi depuis la racine
du dépôt, telle quelle : c'est ce que GitHub Pages publie sans aucun réglage, et
`.nojekyll` demande que les fichiers soient servis sans transformation. Rien
n'est chargé depuis un CDN ou un service tiers, ce qu'un test vérifie : le site
fonctionne derrière un réseau fermé, et survivra à la disparition de n'importe
quel hébergeur.

Le site a d'abord exécuté le Python lui-même, par [Pyodide](https://pyodide.org).
C'était le choix le plus sûr — un seul code — mais il faisait télécharger
13,5 Mo d'interpréteur pour faire tourner 229 Ko de modèle, soit soixante fois le
poids de ce qu'on voulait exécuter.

Le risque d'un portage, c'est qu'il déplace un chiffre sans que rien n'échoue.
Il est traité de front : **le Python de `src/` reste la référence**, et
`scripts/construire_temoins.py` fige depuis lui 86 simulations complètes et le
HTML des quatre pages, dans `tests/temoins/`. `node --test` rejoue le tout côté
JavaScript et compare valeur par valeur — 7 176 nombres, dont 98,2 % identiques
au bit près, l'écart maximal étant d'un *ulp* (3 · 10⁻¹⁶, la précision d'un
flottant). Les pages, elles, sont comparées caractère par caractère : le
formatage à la française reproduit jusqu'à l'arrondi au pair de Python, faute de
quoi un « −12,5 % » deviendrait « −13 % » d'un côté et « −12 % » de l'autre.

Des cas figés ne prouvent que ce qu'on a pensé à figer. Un second contrôle tire
donc des carrières au hasard — graine fixe, donc reproductible —, les calcule en
Python et les fait recalculer par le site : mêmes chiffres exigés, à 10⁻⁹ près.

`pytest` lance cette comparaison, il n'y a donc qu'une commande à retenir. Les
deux fichiers que charge le site sont produits par
`python scripts/construire_donnees.py` — le paquet de données depuis `data/`, et
`moteur/style.css` depuis la feuille de style du module Python, qui reste écrite
en un seul endroit. Le test `test_le_paquet_est_a_jour` échoue si l'un des deux a
été oublié.

</details>

## En local, avec un serveur

Utile pour développer, ou pour disposer de l'API JSON (`/api/simuler`,
`/api/cas-types`, `/api/statuts`, documentation OpenAPI sur `/api/docs`).

```bash
pip install -e ".[web]"
retraite-notionnelle web            # puis http://127.0.0.1:8000
```

## En ligne de commande

Sans l'interface web, la seule dépendance est PyYAML.

```bash
pip install -e .

# Simuler une carrière : cinq informations suffisent
retraite-notionnelle simuler --naissance 1960 --statut salarie_prive_non_cadre \
                             --debut 20 --liquidation 62

# Le cas général : grille cas type × génération
retraite-notionnelle cas-types

# Les 22 statuts et les 37 régimes du catalogue
retraite-notionnelle regimes

# La série d'indexation, année par année
retraite-notionnelle indexation --de 1941 --a 2025

# Le régime unique issu de la fusion
retraite-notionnelle fusion

# L'état de fiabilité des données — à lire en premier
retraite-notionnelle donnees
```

## En bibliothèque

```python
from retraite_notionnelle import Parametres
from retraite_notionnelle.simulateur import Simulateur

simulateur = Simulateur(Parametres())
carriere = simulateur.carriere_simple(
    annee_naissance=1975, sexe="F", affiliation="fonctionnaire_etat",
    age_debut=23, age_liquidation=64, part_primes=0.20,
)
print(simulateur.simuler(carriere).tableau())
```

---

## Ce que le modèle fait

| Exigence | Réalisation |
|---|---|
| Comptes notionnels rétroactifs depuis l'origine de la répartition | Origine 1941 (AVTS), paramétrable à 1945 |
| Tous les régimes, actuels **et** disparus | 37 régimes : AGIRC, ARRCO, CANCAVA, ORGANIC, RSI, mines, SEITA, chemins de fer secondaires… |
| Départ trop tôt = pension réduite | Âge de référence **à cliquet** : l'abaissement de 1982 ne le fait pas redescendre |
| Régimes à départ précoce traités au même étalon | SNCF à 50 ans = 15 ans d'anticipation ; Opéra à 40 ans = 25 ans |
| Indexation par triple lock inversé, depuis l'origine | `min(inflation, salaire moyen, productivité réelle)`, appliqué aux comptes **et** aux pensions liquidées |
| Cinq résultats comparables | Système actuel / notionnel rétroactif / notionnel prospectif, puis les deux mêmes comptes notionnels avec les cotisations employeur du public |
| Cas particulier **et** cas général | Simulation individuelle + grille 12 cas types × 7 générations |
| Fusion des régimes au cas le plus défavorable | Âge 64/67, 172 trimestres, carrière entière, assiette déplafonnée, zéro avantage |
| Droits acquis respectés à la bascule | Conversion à l'âge de référence ou à l'âge de départ effectif, au choix ; la cascade de calcul est affichée |
| Statuts comparables au même étalon | Les fiches publiques ne portent que la retenue de l'agent ; elle est alignée sur l'effort contributif total du privé, sans quoi on compare un demi-effort à un effort entier |
| Part employeur du public, quand elle est publiée | Taux implicite de l'État 1995-2005, taux appelé par le CAS « Pensions » 2006-2026, CNRACL depuis 1948, SNCF 2007-2018 — portés au compte par les scénarios 4 et 5, et le modèle dit sur combien d'années il a dû s'en passer |
| Capitalisation isolée | RAFP et assurances sociales de 1930 dans un compartiment séparé, jamais convertis |
| Trimestres acquis par le revenu, pas par le temps | 150 SMIC horaires depuis 2014, 200 avant : un temps très partiel valide moins de quatre trimestres |
| Motif d'interruption lu, pas seulement enregistré | Un chômage indemnisé ouvre des points complémentaires financés par l'UNEDIC ; un chômage non indemnisé n'ouvre rien |
| Étalon fidèle au droit, minima compris | Le scénario 1 sert le minimum contributif (au taux plein, deux prorata, écrêté), le minimum garanti de la fonction publique, l'ASPA, la majoration pour enfants, les trimestres accordés au titre des enfants — MDA du régime général et des régimes alignés, bonification de la fonction publique —, la surcote parentale de 2023, l'AVPF et la garantie minimale de points de l'Agirc |
| Décote propre à la fonction publique | Article L. 14 : coefficient et âge d'annulation montent en charge de 2006 à 2020, et cet âge est la limite d'âge du grade, non 67 ans |
| Chaque régime liquide sur ses années | Le salaire de référence ne balaie plus toute la carrière : un polypensionné ne liquide pas sa pension civile sur son dernier salaire privé |
| Le droit ouvre-t-il ce départ ? | Âge légal du régime ou carrière longue ; sinon le montant est marqué comme un contrefactuel, pas une pension servie |
| Suppression des minima | Ni minimum contributif, ni minimum garanti, ni ASPA : peu cotisé, peu de retraite |
| Suppression des avantages | Ni majorations enfants, ni MDA, ni AVPF, ni bonifications, ni réversion, ni trimestres gratuits |
| Tout le monde peut simuler | 22 statuts d'affiliation, cinq informations suffisent |
| Utilisable sans rien installer | Le modèle s'exécute dans le navigateur, sur une simple adresse |
| Portage vérifié, pas cru sur parole | Le site rejoue 86 simulations témoins figées depuis le modèle Python |

---

## Trois résultats à connaître avant de lire les chiffres

### 1. La règle d'indexation domine tout le reste

Le triple lock inversé, pris à la lettre, compare deux taux **nominaux**
(inflation, salaire moyen) à un taux **réel** (productivité). Dès que l'inflation
dépasse la productivité — soit presque toute la période 1945-1985 — c'est la
productivité qui l'emporte.

| Règle | Comptes 1941-2025 | Prix | Pouvoir d'achat conservé |
|---|---|---|---|
| Triple lock inversé, littéral | ×4,9 | ×322,2 | **1,5 %** |
| Triple lock inversé, tout en nominal | ×223,3 | ×322,2 | 69,3 % |
| Indexation sur les prix | ×322,2 | ×322,2 | 100 % |

Une cotisation de 1950 ne conserve donc que 1,5 % de sa valeur réelle. Dans le
scénario rétroactif, **l'essentiel de la baisse affichée vient de la règle
d'indexation, pas du passage aux comptes notionnels**.

C'est la règle telle qu'énoncée, appliquée sans correctif. Pour séparer les deux
effets : `--indexation triple_lock_inverse_nominal` (règle homogène, toujours
austère) ou `--indexation prix` (effet propre des comptes notionnels). Chaque
simulation web affiche cette décomposition d'office.

### 2. La fusion augmente les cotisations des indépendants

Le régime unique applique 25,74 % sur assiette déplafonnée. Pour les professions
libérales et les indépendants, qui cotisent aujourd'hui moins et sous plafond,
c'est une forte hausse de prélèvement — et donc de pension. C'est la seule ligne
du tableau des cas types qui progresse ; le résultat est correct, mais il traduit
un effort contributif accru, pas un avantage accordé.

### 3. Qui verse les cotisations d'un agent public

Les fiches de la fonction publique et des régimes spéciaux ne portent que la
**retenue de l'agent** : 11,10 % aujourd'hui, 7,85 % hier. La part de
l'employeur y manquait, et le dépôt a longtemps soutenu qu'elle ne pouvait pas
s'y trouver — le compte d'affectation spéciale « Pensions » datant de 2006, il
n'y aurait rien avant. C'était vrai de l'État, et faux du reste.

- La **CNRACL** est une caisse depuis 1947 : le taux versé par les employeurs
  territoriaux et hospitaliers est fixé par décret et publié depuis 1948.
- L'**État** a bien un taux avant 2006, non pas appelé mais **reconstitué** :
  l'annexe « pensions » au PLF 2011 publie une série de « taux implicite »
  remontant à 1995 — 48,6 % en 1995, 59,4 % en 2005.
- Depuis 2006 le taux est appelé par décret : 49,90 %, puis 74,28 % de 2013 à
  2024, 78,28 % en 2025 et **82,28 % en 2026**.
- La **SNCF** publie par arrêté les deux composantes T1 et T2 de la contribution
  de l'entreprise, de 2007 à 2018.

Les scénarios 4 et 5 les portent au compte, et ne changent rien d'autre.

```
Fonctionnaire d'État née en 1975, 20 % de primes, partie à 64 ans

Scénario                                                  Courants   Constants   Mensuel    Écart
------------------------------------------------------------------------------------------------
1. Système actuel                                          31,714€     25,310€    2,109€     réf.
2. Notionnel rétroactif (depuis l'origine)                 14,622€     11,670€      972€   -53.9%
3. Notionnel à compter de 2026                             23,194€     18,511€    1,543€   -26.9%
4. Notionnel rétroactif, cotisations employeur             43,413€     34,647€    2,887€   +36.9%
5. Notionnel à compter de 2026, cotisations employeur      36,237€     28,920€    2,410€   +14.3%

Cotisations des scénarios 4 et 5 :
  retenue de l'agent           120,675 €
  employeur public             873,300 €   soit 88% du total
  total porté au compte        993,975 €
  contribution employeur trouvée sur 41 année(s)
```

L'employeur verse 88 % du total : c'est l'ordre de grandeur d'un taux
d'**équilibre**. Et c'est la limite de ces deux scénarios. 82,28 % ne signifie
pas qu'un fonctionnaire acquiert 82 % de son traitement en droits nouveaux, mais
qu'il faut aujourd'hui cette contribution pour payer les pensions
d'aujourd'hui — démographie et engagements hérités compris. Les porter au compte
répond à une question précise, « et si tout ce qui a été consacré aux pensions
avait été porté au compte des actifs ? », et à elle seule.

Trois limites à connaître. La série n'existe que pour trois régimes : douze
autres retombent sur l'alignement du scénario 2, et le modèle affiche sur
combien d'années. L'État n'est couvert qu'à partir de 1995 : plus une carrière
publique est ancienne, moins le scénario 4 s'écarte du 2 — non parce que le
financement d'alors ressemblait à celui du privé, mais parce qu'on ne le connaît
pas. Enfin le scénario 5, qui n'ouvre son compte qu'en 2026, prolonge le taux de
2026 jusqu'à la liquidation : presque tout ce qu'il calcule est une projection.

---

## Les données

Vingt-six institutions sont recensées dans [`data/sources.yaml`](data/sources.yaml) :
INSEE, COR, Comité de suivi des retraites, DREES, CNAV, Service des retraites de
l'État, Caisse des dépôts, Direction de la Sécurité sociale, Cour des comptes,
Agirc-Arrco, Assemblée nationale, Union Retraite, CCMSA, CNAVPL, CNBF, DGAFP,
Direction du Budget, ERAFP, Ircantec, caisses des régimes spéciaux, Urssaf,
Légifrance, INED, Eurostat, OCDE, OpenFisca-France.

**Chaque valeur porte son niveau de fiabilité** — `certifiee`, `haute`,
`moyenne`, `estimee` — et la fiabilité d'un résultat est celle de son maillon le
plus faible. `Parametres.fiabilite_minimale` fait échouer la simulation plutôt
que de produire un chiffre trompeur.

Une valeur n'est `certifiee` que si elle a été **confrontée à la source
elle-même**, téléchargée depuis le producteur. Une transcription tierce, même
sourcée et reprise automatiquement, plafonne à `haute`.

| Donnée | Période certifiée | Producteur |
|---|---|---|
| Inflation, salaire moyen, productivité | 1950-2025 | INSEE, Banque de données macroéconomiques |
| Espérance de vie à 0 et 60 ans | 1946-2025 | INSEE |
| Espérance de vie à 65 ans | 1960-2024 | OCDE (l'INSEE ne la publie pas) |
| Quotients de mortalité par âge | 1986-2024 | Eurostat |
| Quotients de mortalité par âge | 1899-1985, et 95-104 ans jusqu'en 1997 | INED, tables de Vallin et Meslé |
| Plafond de la Sécurité sociale | 2002-2025 | INSEE |
| Valeurs du point de l'Ircantec | 1971-2021 | Caisse des dépôts, qui gère le régime |
| Valeurs du point des avocats | 2017-2026 | CNBF, ses barèmes annuels |
| Valeur du point des professions libérales | 2021-2025 | CNAVPL, ses recueils statistiques |
| Valeur du point de la complémentaire agricole | 2005-2024 | code rural D. 732-166, base LEGI de la DILA |
| Minimum contributif et plafond d'écrêtement | ancres 2007-2014 | code de la sécurité sociale, base LEGI de la DILA |
| Âge d'ouverture et coefficient de minoration, par génération | 1900-1975 | code de la sécurité sociale `D. 161-2-1-9` et `R. 351-27`, base LEGI |
| Durée d'assurance requise, par génération | 1958-1975 | code de la sécurité sociale `L. 161-17-3`, base LEGI |
| Bornes du départ pour carrière longue | depuis 2023 | code de la sécurité sociale `L. 351-1-1` et `D. 351-1-1`, base LEGI |

Trois séries de plus sont reprises automatiquement d'**OpenFisca-France**, le
modèle socio-fiscal de l'administration — le plafond de la Sécurité sociale
depuis 1931, les valeurs d'achat et de service du point depuis 1947, et le point
d'indice de la fonction publique depuis 1960 avec le barème du minimum garanti.
Ce sont des transcriptions du *Journal officiel* et des circulaires, pas des
sources primaires : elles plafonnent au niveau `haute`. Le point de l'Agirc et de
l'Arrco, qui pèse le plus lourd des deux, est en outre recoupé à la série que
l'INSEE publie depuis 2001 : sur les 42 années communes, les deux ne divergent
pas une fois.

```bash
python scripts/fetch/insee_bdm.py               # séries longues INSEE (BDM)
python scripts/fetch/oecd_esperance_vie.py      # espérance de vie à 65 ans
python scripts/fetch/eurostat_mortalite.py      # tables de mortalité par âge
python scripts/fetch/openfisca_plafond.py       # plafond ancien
python scripts/fetch/openfisca_cotisations.py   # taux de cotisation du RG
python scripts/fetch/openfisca_points.py        # valeurs du point, depuis 1947
python scripts/fetch/openfisca_point_indice.py  # point d'indice, minimum garanti
python scripts/fetch/cdc_ircantec.py            # barèmes Ircantec, par son gestionnaire
python scripts/fetch/cnbf_baremes.py            # valeurs du point des avocats
python scripts/fetch/cnavpl_recueils.py         # valeur du point des libéraux
python scripts/fetch/dila_legi_msa.py           # point agricole (lent : 1,1 Go)
python scripts/fetch/dila_legi_minimum_contributif.py   # minimum contributif (lent)
python scripts/fetch/dila_legi_parametres_retraite.py   # âges, durées, décotes (lent)
python scripts/fetch/ined_vallin_mesle.py       # quotients de mortalité d'avant 1986
python scripts/fetch/eurostat_hicp.py           # contrôle croisé de l'inflation

python scripts/verifier_donnees.py              # confronte, sans rien écrire
python scripts/verifier_donnees.py --appliquer  # aligne sur la source et certifie
```

> **Ce qui reste saisi à la main :** le salaire moyen et la productivité
> d'avant 1950, les taux de cotisation d'avant 1967 et ceux des régimes autres
> que le privé, les montants servis des trois minima — transcrits de leur
> publication, et préférés à toute projection parce qu'ils disent ce qui a été
> payé —, l'âge d'annulation de la décote, le nombre d'années retenues au
> salaire de référence, et les barèmes que personne ne publie en série.
> Les autres tables par génération, elles, ne sont plus saisies : elles sont
> lues dans le texte des articles du code, dans la base LEGI de la DILA.
> `docs/limites.md` dit, pour chaque limite restante, dans quel sens elle joue
> et de combien, et recense les sources essayées sans succès, pour éviter de les
> rechercher deux fois.
> Lire [`docs/limites.md`](docs/limites.md) avant de citer un chiffre.

---

## Organisation

```
data/
  sources.yaml                  manifeste des sources institutionnelles
  reference/
    macro/                      inflation, salaire moyen, productivité, plafond, projections
    mortalite/                  espérances de vie et quotients par âge observés
    regimes/                    37 fiches de régime + schéma + valeurs du point
    legislation/                âges et durées par génération, barèmes des
                                minima, décote de la fonction publique,
                                carrière longue, contribution employeur des
                                régimes publics, profils d'affiliation
  brut/                         téléchargements bruts, non versionnés
  derive/                       calibrations et journal de certification

src/retraite_notionnelle/
  config.py                     toutes les décisions de modélisation, en un seul endroit
  carriere.py                   description d'une carrière, trois niveaux de précision
  donnees/                      chargement, fiabilité, macro, mortalité, régimes
  moteur/                       indexation, âge de référence, conversion, fusion, compte
  scenarios/                    système actuel, comptes notionnels
  simulateur.py                 façade et restitution
  castypes.py                   cas général
  cli.py                        ligne de commande
  web/
    pages.py                    contenu des pages — sans autre dépendance que le moteur
    gabarit.py                  rendu HTML et feuille de style
    application.py              serveur FastAPI et API JSON (dépendances optionnelles)

index.html                      le site : charge les données, puis le moteur JavaScript
.nojekyll                       servir les fichiers sans transformation
moteur/                         ce que le navigateur charge, et rien d'autre
  donnees.json                  séries, tables et régimes (521 Ko, produit par script)
  style.css                     extraite de gabarit.py (produite par script)
  js/                           portage du modèle, sans bibliothèque ni étape de build

docs/
  methodologie.md               ce que le modèle calcule, et pourquoi ainsi
  limites.md                    ce qu'il ne calcule pas, et ce qui reste à certifier

tests/                          224 tests Python
  temoins/                      chiffres et pages figés depuis le modèle Python
  js/                           le portage rejoué contre ces témoins (node --test)
```

---

## Principales options

Elles valent pour toutes les commandes, et se retrouvent dans le formulaire web
sous « Options de modélisation ».

```bash
--indexation      triple_lock_inverse | triple_lock_inverse_nominal | prix | salaires
--age-reference   cliquet_legal | cliquet_puis_esperance_vie | legal_sans_cliquet
--conversion-acquis  reference | liquidation
--cotisation-publique  alignee_sur_le_prive | financement_historique | exclue
--table           unisexe | par_sexe
--projection      cor_central | cor_favorable | cor_defavorable | stagnation
--bascule ANNÉE   année de passage au régime unique (défaut 2026)
--euros ANNÉE     année des euros constants (défaut 2026)
--fiabilite-min   refuse de calculer sous un certain niveau de fiabilité
--json            sortie machine
```

---

## Tests

```bash
python -m pytest tests
```

224 tests couvrant le chargement et la fiabilité des données, la règle de
certification, la calibration des tables de mortalité et sa concordance avec les
tables observées, les propriétés du moteur
(monotonie du diviseur, cliquet de l'âge de référence, règles de fusion), le
comportement des scénarios, le rendu des pages dans les deux modes et la
fraîcheur de ce que charge le site. Aucun test n'accède au réseau : les
sources sont simulées. Les tests du serveur sont ignorés si ses dépendances
optionnelles ne sont pas installées.

Deux d'entre eux lancent `node` pour rejouer le calcul côté JavaScript — les
cas-témoins figés, puis des carrières tirées au hasard ; ils sont ignorés si
`node` est absent. On peut exécuter les premiers seuls :

```bash
node --test tests/js/moteur.test.js
```

---

## Licence

MIT. Les données publiques référencées restent soumises aux licences de leurs
producteurs respectifs (licence ouverte Etalab pour la plupart).
