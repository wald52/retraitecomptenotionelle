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
| **1** | Système actuel | Le droit en vigueur, minima et majorations compris. C'est la référence. Le total affiché est celui de la **répartition seule** : ce qui relève de la capitalisation (RAFP) est servi à part, à l'identique dans les cinq scénarios. |
| **2** | Notionnel **rétroactif** depuis 1941 | Contrefactuel : toute la carrière recalculée sur les seules cotisations, comme si la règle avait toujours existé. |
| **3** | Notionnel **à compter de 2026** | Réforme prospective : les droits déjà acquis sont figés — au contributif seul, avantages non contributifs retirés — puis convertis en capital, et les règles notionnelles s'appliquent ensuite. Qui a liquidé avant la bascule garde sa pension telle quelle : c'est ce qui distingue ce scénario du **2**. |
| **4** | Le scénario **2**, part patronale comprise | Le même compte rétroactif, la cotisation de l'employeur en plus : celle de la fiche pour le privé, celle réellement versée — jusqu'à 82,28 % du traitement en 2026 — pour le public. |
| **5** | Le scénario **3**, part patronale comprise | Le même compte prospectif, droits acquis conservés, avec la même part patronale en plus. |

Les comptes sont revalorisés, par défaut, sur la croissance de la **masse
salariale** — l'assiette des cotisations, donc le rendement qu'un système en
répartition peut servir sans changer son taux de cotisation. Sept autres règles
sont disponibles, dont le **triple lock inversé** qui a donné son cahier des
charges à ce dépôt : `indexation=triple_lock_inverse`. Le choix pèse lourd,
et le simulateur affiche d'office ce qu'il déplace.

Les scénarios **2 et 3 ne portent au compte que la part salariale** — ce que
l'assuré a supporté lui-même, la même grandeur pour tous les statuts. Les
scénarios **4 et 5 y ajoutent la part patronale**. Pour un non-salarié, qui n'a
pas d'employeur, les quatre se réduisent à deux.

```python
from retraite_notionnelle import Parametres
from retraite_notionnelle.simulateur import Simulateur

simulateur = Simulateur(Parametres())
print(simulateur.simuler(simulateur.carriere_simple(
    annee_naissance=1955, sexe="H", affiliation="agent_sncf",
    age_debut=20, age_liquidation=50,
    niveau_salaire=1.1, profil_carriere="ascendant",
)).tableau())
```

```
Agent de conduite SNCF né en 1955, parti à 50 ans (quinze ans avant l'âge de référence)

Scénario                                                  Courants   Constants   Mensuel    Écart
------------------------------------------------------------------------------------------------
1. Système actuel                                          22,479€     31,472€    2,623€     réf.
2. Notionnel rétroactif, part salariale                     2,131€      2,983€      249€   -90.5%
3. Notionnel dès 2026, part salariale                      22,479€     31,472€    2,623€    +0.0%
4. Notionnel rétroactif, salariale + patronale              5,390€      7,546€      629€   -76.0%
5. Notionnel dès 2026, salariale + patronale               22,479€     31,472€    2,623€    +0.0%
```

> Les scénarios 4 et 5 sont les scénarios 2 et 3, à une différence près et une
> seule : **ce qui alimente le compte**. Même carrière, même indexation, même
> liquidation, mêmes droits acquis figés à la bascule. L'écart entre 2 et 4
> mesure donc exactement une chose — ce que verse l'employeur.
>
> Les scénarios 3 et 5 sont ici identiques au système actuel parce que cet agent
> a liquidé en 2005, avant la bascule : ses droits sont intégralement acquis.

> **Le scénario 2 n'est pas une proposition de réforme**, et l'écart qu'il
> affiche ne mesure pas l'effet des comptes notionnels. Deux raisons, et aucune
> des deux n'est le passage au notionnel. La première : il ne porte au compte
> que la part salariale — un système notionnel réel serait alimenté par la
> cotisation entière, et c'est le scénario 4 qui la porte. La seconde, plus
> lourde encore : la règle d'indexation retenue, voir
> [« La règle d'indexation domine tout le reste »](#1-la-règle-dindexation-domine-tout-le-reste)
> plus bas. Le modèle permet de séparer ces effets ; c'est même son principal
> résultat.

---

## Ouvrir le simulateur

### 👉 [wald52.github.io/retraitecomptenotionelle](https://wald52.github.io/retraitecomptenotionelle/)

Rien à installer, rien à lancer : une adresse à ouvrir. Le modèle et ses données
de référence s'exécutent **dans votre navigateur**. Aucune donnée saisie ne
quitte votre machine, puisqu'il n'y a pas de serveur de calcul. Le premier
chargement transfère 221 Ko compressés (812 Ko bruts) et prend quelques dixièmes
de seconde ; les suivants sont immédiats.

Quatre pages : **Simuler** (une carrière — en un ou plusieurs métiers —, avec le détail du calcul, la
décomposition de l'écart règle par règle et la cascade qui mène du scénario 1 au
scénario 3), **Cas types** (la grille 12 carrières × 7 générations),
**Méthode**, **Données** (l'état de fiabilité des séries).

L'adresse d'une simulation contient tous ses paramètres — elle peut être citée
ou partagée telle quelle — et chaque résultat est consultable en JSON au bas de
la page.

<details>
<summary>Comment la page fonctionne, et comment on sait qu'elle dit vrai</summary>

`index.html` charge deux choses : `moteur/donnees.json` (533 Ko — les séries, les
tables de mortalité observées de 1899 à 2024, les 37 fiches de régime) et
`moteur/js/`, un portage du modèle en JavaScript sans aucune bibliothèque. Le site est servi depuis la racine
du dépôt, telle quelle : c'est ce que GitHub Pages publie sans aucun réglage, et
`.nojekyll` demande que les fichiers soient servis sans transformation. Rien
n'est chargé depuis un CDN ou un service tiers, ce qu'un test vérifie : le site
fonctionne derrière un réseau fermé, et survivra à la disparition de n'importe
quel hébergeur.

Le site a d'abord exécuté le Python lui-même, par [Pyodide](https://pyodide.org).
C'était le choix le plus sûr — un seul code — mais il faisait télécharger
13,5 Mo d'interpréteur pour faire tourner 263 Ko de modèle, soit cinquante fois le
poids de ce qu'on voulait exécuter.

Le risque d'un portage, c'est qu'il déplace un chiffre sans que rien n'échoue.
Il est traité de front : **le Python de `src/` reste la référence**, et
`scripts/construire_temoins.py` fige depuis lui 122 simulations complètes et le
HTML des quatre pages, dans `tests/temoins/`. `node --test` rejoue le tout côté
JavaScript et compare valeur par valeur — 10 526 nombres, dont 97,7 % identiques
au bit près, l'écart maximal étant de quelques *ulp* (2 · 10⁻¹⁵ ; un *ulp* vaut
2 · 10⁻¹⁶, la précision d'un flottant). Les pages, elles, sont comparées caractère par caractère : le
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

## Ouvrir le site en local

Le site est un ensemble de fichiers statiques, servis depuis la racine du dépôt.
N'importe quel serveur de fichiers suffit — il n'y a pas de serveur de calcul,
et rien à construire au préalable :

```bash
python -m http.server 8000        # puis http://127.0.0.1:8000
```

## En Python, hors du site

Le site expose le modèle en quatre pages. Pour l'interroger autrement — un
calcul par lots, une variante de paramètres, un chiffre à vérifier à la main —
le modèle de référence s'appelle directement. La seule dépendance est PyYAML.

```bash
pip install -e .
```

```python
from retraite_notionnelle import Parametres
from retraite_notionnelle.castypes import calculer_cas_types
from retraite_notionnelle.simulateur import Simulateur

simulateur = Simulateur(Parametres())

# Simuler une carrière : cinq informations suffisent
carriere = simulateur.carriere_simple(
    annee_naissance=1960, sexe="H", affiliation="salarie_prive_non_cadre",
    age_debut=20, age_liquidation=62,
)
print(simulateur.simuler(carriere).tableau())

# Au mois près — la date de liquidation commande les mois cotisés de l'année
# du départ, les trimestres qu'ils valident et le diviseur actuariel
simulateur.carriere_simple(
    annee_naissance=1961, mois_naissance=9, sexe="H",
    affiliation="salarie_prive_non_cadre",
    age_debut=20 + 6 / 12, age_liquidation=64 + 7 / 12,
)

# Plusieurs métiers dans une vie : chacun court jusqu'au début du suivant,
# le dernier jusqu'à la liquidation
from retraite_notionnelle.carriere import Metier

print(simulateur.simuler(simulateur.carriere_parcours(
    annee_naissance=1975, sexe="H", age_liquidation=64,
    metiers=[
        Metier("salarie_prive_non_cadre", age_debut=21, niveau_salaire=0.9),
        Metier("contractuel_public", age_debut=34, niveau_salaire=0.8),
        Metier("artisan", age_debut=47, niveau_salaire=1.5),
    ],
)).tableau())

# Le cas général : grille cas type × génération
print(calculer_cas_types(simulateur).tableau())

# Les 22 statuts et les 37 régimes du catalogue
for regime in simulateur.catalogue:
    print(f"{regime.code:<26} {regime.famille:<22} {regime.nom}")
```

Le tableau de bord des données — l'état de fiabilité de chaque série, à lire en
premier — est la page **Données** du site. En Python,
`journal_certification(Parametres().racine_donnees)` produit la même matière.

## En bibliothèque

```python
from retraite_notionnelle import Parametres
from retraite_notionnelle.simulateur import Simulateur

simulateur = Simulateur(Parametres())
carriere = simulateur.carriere_simple(
    annee_naissance=1975, mois_naissance=4, sexe="F",
    affiliation="fonctionnaire_etat",
    age_debut=23, age_liquidation=64 + 7 / 12, part_primes=0.20,
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
| Indexation par triple lock inversé, depuis l'origine | `min(inflation, salaire moyen, productivité réelle)`, appliqué aux comptes en constitution. Le modèle s'arrête à la liquidation : il ne revalorise pas les pensions servies, et n'en calcule qu'une, dans les euros de l'année de départ |
| Cinq résultats comparables | Système actuel / notionnel rétroactif / notionnel prospectif sur la part salariale, puis les deux mêmes comptes notionnels part patronale comprise |
| Cas particulier **et** cas général | Simulation individuelle + grille 12 cas types × 7 générations |
| Fusion des régimes au cas le plus défavorable | Âge 64/67, 172 trimestres, carrière entière, assiette déplafonnée, zéro avantage |
| Droits acquis respectés à la bascule | Conversion à l'âge de référence par défaut — le seul endroit où l'âge de départ pèse sur les droits d'avant la bascule, donc ce qui empêche de gagner à partir tôt ; l'âge de départ effectif est offert en variante, et la cascade de calcul est affichée |
| Statuts comparables au même étalon | Les fiches publiques ne portent que la retenue de l'agent ; elle est alignée sur l'effort contributif total du privé, sans quoi on compare un demi-effort à un effort entier |
| Part salariale et part patronale distinguées, pour tous | `part_salariale` dans chaque fiche de salariés — 40,87 % au régime général en 2023, 40 % à l'Agirc-Arrco —, et `sans_employeur` sur les cinq statuts qui cotisent seuls |
| Part employeur du public, quand elle est publiée | Taux implicite de l'État 1995-2005, taux appelé par le CAS « Pensions » 2006-2026, CNRACL depuis 1948, SNCF 2007-2018 — portés au compte par les scénarios 4 et 5, et le modèle dit sur combien d'années il a dû s'en passer |
| Capitalisation hors comparaison | Le RAFP et les assurances sociales de 1930 sont PROVISIONNÉS : leur rente sort d'un placement, non de la cotisation des actifs. Une réforme de la répartition ne les atteint pas — ils sont donc retirés des **cinq** totaux et servis à l'identique, à leur propre barème, affichés à côté |
| Le mois, là où le droit le date | Date de liquidation, année d'entrée et année de départ portées au compte au prorata de leurs mois, trimestres bornés aux trimestres civils écoulés, diviseur lu à l'âge exact, circulaire de revalorisation en vigueur à la date, générations que la loi coupe au 1<sup>er</sup> juillet 1951 et au 1<sup>er</sup> septembre 1961. Le pas du moteur reste l'année, parce que les séries le sont — voir [« Le mois, là où le droit le date »](docs/limites.md#le-mois-là-où-le-droit-le-date) |
| Trimestres acquis par le revenu, pas par le temps | 150 SMIC horaires depuis 2014, 200 avant : un temps très partiel valide moins de quatre trimestres |
| Motif d'interruption lu, pas seulement enregistré | Un chômage indemnisé ouvre des points complémentaires financés par l'UNEDIC ; un chômage non indemnisé n'ouvre rien |
| Étalon fidèle au droit, minima compris | Le scénario 1 sert le minimum contributif (au taux plein, deux prorata, écrêté), le minimum garanti de la fonction publique, l'ASPA, la majoration pour enfants, les trimestres accordés au titre des enfants — MDA du régime général et des régimes alignés, bonification de la fonction publique —, la surcote parentale de 2023, l'AVPF et la garantie minimale de points de l'Agirc |
| Décote propre à la fonction publique | Article L. 14 : coefficient et âge d'annulation montent en charge de 2006 à 2020, et cet âge est la limite d'âge du grade, non 67 ans |
| Chaque régime liquide sur ses années | Le salaire de référence ne balaie plus toute la carrière : un polypensionné ne liquide pas sa pension civile sur son dernier salaire privé |
| Le droit ouvre-t-il ce départ ? | Âge légal du régime ou carrière longue ; sinon le montant est marqué comme un contrefactuel, pas une pension servie |
| Suppression des minima | Ni minimum contributif, ni minimum garanti, ni ASPA : peu cotisé, peu de retraite |
| Suppression des avantages | Ni majorations enfants, ni MDA, ni AVPF, ni bonifications, ni réversion, ni trimestres gratuits |
| Tout le monde peut simuler | 22 statuts d'affiliation, cinq informations suffisent |
| Une carrière, plusieurs métiers | On faisait autrefois le même métier toute sa vie, c'est devenu l'exception : la carrière se décrit comme une suite de métiers, chacun avec son statut et son niveau de revenu, et chaque changement fait passer d'un régime à un autre. L'année du changement revient au métier qui en occupe le plus de mois — les régimes liquident à l'année —, mais le revenu porté au compte reste la somme de ce que les deux ont payé |
| Utilisable sans rien installer | Le modèle s'exécute dans le navigateur, sur une simple adresse |
| Étalon confronté à une seconde implémentation | Le régime général du scénario 1 est rejoué par **OpenFisca-France-Pension**, écrit par d'autres à partir des mêmes textes : durée d'assurance, trimestres de décote, taux et proratisation concordent exactement sur dix profils, et la confrontation a fait trouver une erreur de chaque côté |
| Salaires revalorisés par la circulaire, pas par une règle | Les coefficients qui revalorisent les salaires portés au compte sont LUS dans les circulaires de la Cnav — dix colonnes publiées, perceptions depuis 1930 : la règle « les salaires jusqu'en 1986, les prix depuis » les sur-revaluait de 12 % sur quarante ans, et le salaire de référence retient les N *meilleures* années — changer les coefficients change lesquelles |
| Deux durées là où le droit en a deux | La durée requise pour le taux plein (L. 161-17-3) et la durée maximale prise en compte par la proratisation (R. 351-6), que le modèle confondait |
| Points convertis à leur vraie unité | Les coefficients des fusions sont LUS dans les accords — un point Arrco vaut un point Agirc-Arrco, un point Agirc en vaut 0,347798289 —, et l'unification Arrco de 1999 est traitée comme le changement d'unité qu'elle est |
| Portage vérifié, pas cru sur parole | Le site rejoue 122 simulations témoins figées depuis le modèle Python |

---

## Trois résultats à connaître avant de lire les chiffres

### 1. La règle d'indexation domine tout le reste

Le modèle revalorise **par défaut les comptes sur la croissance de la masse
salariale** — le taux d'équilibre de la répartition, celui que la théorie des
comptes notionnels désigne (voir §1 ter). Ce n'est pas la règle qui a motivé ce
dépôt : celle-là, le **triple lock inversé**, est à un paramètre de distance
(`indexation=triple_lock_inverse`). Un défaut doit être ce qu'on retient faute
d'instruction contraire, pas ce qu'on cherche à démontrer — et c'est bien la
règle demandée qui produit les écarts les plus spectaculaires.

Le triple lock inversé, pris à la lettre, compare deux taux **nominaux**
(inflation, salaire moyen) à un taux **réel** (productivité). Dès que l'inflation
dépasse la productivité — soit presque toute la période 1945-1985 — c'est la
productivité qui l'emporte.

| Règle | Comptes 1941-2025 | Prix | Pouvoir d'achat conservé |
|---|---|---|---|
| Triple lock inversé, littéral | ×4,9 | ×322,2 | **1,5 %** |
| Moyenne des trois taux | ×175,7 | ×322,2 | 54,5 % |
| Triple lock inversé, tout en nominal | ×223,3 | ×322,2 | 69,3 % |
| Indexation sur les prix | ×322,2 | ×322,2 | 100 % |
| Médiane des trois taux | ×397,6 | ×322,2 | 123,4 % |
| **Revalorisation réellement pratiquée** | **×1 538,2** | ×322,2 | **477,4 %** |
| Masse salariale (règle d'équilibre) | ×3 685,1 | ×322,2 | 1 143,7 % |
| PIB nominal | ×3 442,3 | ×322,2 | 1 068,6 % |
| PIB nominal, lissé sur 5 ans (Italie) | ×4 152,7 | ×322,2 | 1 288,8 % |

Une cotisation de 1950 ne conserve donc que 1,5 % de sa valeur réelle. Dans le
scénario rétroactif, **l'essentiel de la baisse affichée vient de la règle
d'indexation, pas du passage aux comptes notionnels**.

C'est la règle telle qu'énoncée, appliquée sans correctif. Pour séparer les deux
effets : `indexation=triple_lock_inverse_nominal` (règle homogène, toujours
austère) ou `indexation=revalorisation_portee_au_compte` (effet propre des
comptes notionnels). Chaque simulation web affiche cette décomposition d'office.

La dernière ligne du tableau est la seule qui ne soit pas une hypothèse : c'est
le coefficient que les arrêtés annuels ont réellement appliqué aux salaires
portés au compte, celui dont le scénario 1 se sert pour son salaire de
référence. Il vaut ×1 538, près de cinq fois les prix, parce que le régime
général a revalorisé sur les **salaires** jusqu'en 1986 et sur les prix
seulement depuis 1987. Ce README, la documentation et le site ont longtemps
désigné `indexation=prix` comme la règle qui neutralise l'indexation :
c'était faux d'un facteur cinq, et cela imputait aux comptes notionnels un
écart qui venait encore du choix de la revalorisation.

Ce que la correction déplace est plus modeste que ce facteur cinq ne le
suggère, et il faut le dire aussi : les cotisations d'une carrière se
concentrent sur ses dernières années — en euros courants, une année de fin de
carrière pèse dix à trente fois une année de début —, et c'est là que les deux
règles coïncident. Sur le scénario rétroactif, pour un salarié du privé non
cadre entré à 20 ans et parti à 62 :

| Génération | Carrière | Ligne de référence « Prix » | Ligne corrigée | Écart |
|---|---|---|---|---|
| 1920 | 1940-1982 | -90,8 % | -84,6 % | **+6,2 pt** |
| 1930 | 1950-1992 | -88,8 % | -86,1 % | +2,6 pt |
| 1945 | 1965-2007 | -84,5 % | -84,3 % | +0,1 pt |
| 1958 | 1978-2020 | -79,9 % | -80,4 % | **-0,5 pt** |
| 1990 | 2010-2052 | -77,6 % | -77,6 % | -0,1 pt |

L'écart change même de signe pour les carrières entièrement postérieures à
1987 : depuis 1990 les arrêtés ont revalorisé un peu moins vite que les prix
(×1,69 contre ×1,80), l'indexation légale étant assise sur l'inflation de
l'année précédente. L'erreur portait donc sur l'indice cumulé et sur ce qu'on
en disait, pas sur l'ordre de grandeur des résultats — mais une ligne de
référence fausse reste une ligne de référence fausse, et c'est sur elle que
reposait la phrase « l'écart entre la ligne Prix et le système actuel mesure
l'effet propre des comptes notionnels ».

### 1 bis. Le minimum n'est pas la seule statistique : médiane et moyenne

Le minimum de trois séries est une règle sévère par construction. Deux variantes
gardent **exactement les mêmes trois termes** et ne changent que ce qu'on en
retient — `indexation=mediane_trois_taux` et `indexation=moyenne_trois_taux`.
Elles isolent donc le coût du choix du minimum, à termes inchangés. Le résultat
n'est pas celui qu'on attend :

- la **médiane** est presque toujours l'inflation (43 années sur 85) ou le
  salaire moyen (20) : deux taux **nominaux**. Elle suit donc les prix et les
  dépasse même légèrement — ×397,6 contre ×322,2 — parce que le salaire moyen
  l'emporte quand la productivité est forte. Sur les 85 années, elle ne passe
  sous l'inflation que 18 fois, contre 61 pour le minimum. **Ce n'est plus une
  règle d'austérité** ; c'est, en pratique, une indexation prix-salaires ;
- la **moyenne** est plus sévère que la médiane, et même que les prix — ×175,7,
  soit 54,5 % du pouvoir d'achat. La raison n'est pas la statistique mais le
  mélange : la moyenne incorpore **un tiers de productivité réelle chaque
  année**, y compris pendant les années à dix ou vingt points d'inflation, là où
  le minimum et la médiane ne retiennent le terme réel que les années où il
  gagne. Le taux obtenu n'est en outre celui d'aucun agrégat observé.

Autrement dit : si l'objectif est d'adoucir la règle sans la vider, la médiane
le fait ; la moyenne, elle, est un objet composite dont la sévérité vient d'un
artefact de construction plutôt que d'un choix assumé. Les deux sont disponibles
dans le formulaire, et le tableau « D'où vient l'écart » de chaque simulation
les affiche côte à côte.

### 1 ter. La règle que la théorie désigne : la masse salariale

Les six règles précédentes sont des choix. Il en existe une septième qui n'en
est pas un : en répartition, le rendement qu'un système peut servir sans changer
son taux de cotisation est **la croissance de son assiette** — la masse
salariale, soit le salaire moyen multiplié par l'emploi salarié (Samuelson 1958,
Aaron 1966). C'est le taux d'indexation des comptes notionnels suédois,
italiens, polonais et lettons, à des variantes près, et c'est le seul candidat
qui découle d'un argument plutôt que d'une intention.

`indexation=masse_salariale` la sert, depuis les salaires et traitements bruts
des comptes nationaux (D11, INSEE, idbank 011785411, certifiés depuis 1950).
Sur 1941-2025 elle vaut **×3 685, soit onze fois les prix** : l'emploi salarié a
doublé depuis 1950, et cette croissance-là s'ajoute chaque année à celle des
salaires. C'est de très loin la règle la plus généreuse du tableau — une règle
d'équilibre, pas une règle d'austérité.

Deux réserves, à lire avant de s'en servir :

- **elle crédite le compte d'un rendement collectif, alors que les scénarios 2
  et 3 n'y versent qu'une cotisation partielle.** Le taux d'équilibre est celui
  du système entier ; y adosser la seule part salariale mélange deux périmètres.
  C'est aux scénarios 4 et 5, qui portent la cotisation entière, qu'elle se
  compare sans biais — et l'écart au système actuel y passe de -81 % à -51 %
  pour la génération 1930, de -69 % à -41 % pour 1945 ;
- **1930-1949 est estimé**, faute de comptes nationaux : ces vingt années
  supposent l'emploi salarié constant et reprennent la variation du salaire
  moyen. La fiabilité `estimee` le dit et se propage jusqu'au résultat.

Pour les curieux, une neuvième règle : **`indexation=pib_nominal`**,
l'assiette la plus large — elle capte ce que la masse salariale perd quand la
valeur ajoutée se déplace vers les revenus non salariaux.

### 1 quater. Le lissage pluriannuel, qui n'est pas une règle

Le lissage applique une moyenne glissante de N années au taux que la règle
produit — **n'importe laquelle des neuf**, et N est libre, de 1 à 30 ans. Ce
n'est donc pas une dixième règle
mais un réglage orthogonal, et il répond à une question que le choix de la règle
ne pose pas : la **loterie de cohorte**.

Sur le PIB nominal brut, une cotisation de 1980 vaut ×5,44 à une liquidation de
2019 et **×5,18 en 2020** : attendre un an fait *perdre*, parce que l'année
traversée s'est mal passée. Rien dans la carrière ne le justifie — c'est le
calendrier qui tranche. Avec `lissage=5`, le recul disparaît (×6,64 puis
×6,71) : le trou de 2020 est absorbé par les quatre années qui l'entourent. Sur
1950-2025, le PIB nominal brut compte deux années où liquider plus tard rapporte
moins ; lissé sur trois ou cinq ans, aucune.

C'est le mécanisme des comptes notionnels italiens —
`indexation=pib_nominal&lissage=5` **est** la règle italienne, dont le modèle
ne reprend que le taux, pas le reste du système (décalage de publication de
deux ans, coefficients de transformation, planchers). Mais rien n'oblige à le
réserver au PIB : le lissage s'applique aussi bien au triple lock inversé qu'à
la masse salariale.

Une réserve de lecture, valable pour toutes les lignes lissées du tableau
ci-dessus : sur quatre-vingts ans, une moyenne glissante **n'est pas neutre**.
Elle revient à mesurer la croissance depuis une base reculée d'environ la moitié
de la fenêtre, ce qui gonfle le cumul d'une vingtaine de pour cent à cinq ans —
sans qu'aucune série ait changé. Sur une carrière, l'écart entre lissé et non
lissé reste d'un à deux points (règle par défaut, génération 1930 : -81,5 % sans
lissage, -80,2 % à trois ans, -79,1 % à cinq).

Et un résultat qui recadre tout le reste : même sous cette règle, le scénario
rétroactif reste 70 à 81 % en dessous du système actuel (scénario 2), et 28 à
51 % en dessous avec la cotisation entière (scénario 4). L'indexation explique
donc une part importante de l'écart, mais pas la totalité : le reste tient à ce
que le système actuel sert plus qu'un compte strictement contributif.

### 2. La fusion augmente les cotisations des indépendants

Le régime unique applique 25,73 % sur assiette déplafonnée. Pour les professions
libérales et les indépendants, qui cotisent aujourd'hui moins et sous plafond,
c'est une forte hausse de prélèvement — et donc de pension. C'est la seule ligne
du tableau des cas types qui progresse ; le résultat est correct, mais il traduit
un effort contributif accru, pas un avantage accordé.

### 3. La part patronale pèse plus lourd que la part salariale

Une cotisation retraite a deux parts, et le modèle sait maintenant les
distinguer **symétriquement**, public et privé. C'est ce qui sépare les
scénarios 2 et 3 des scénarios 4 et 5, et rien d'autre.

Cela n'a pas toujours été possible. Les fiches de régime ne portaient pas la
même grandeur selon le secteur : le total salarié + employeur pour le privé, la
seule retenue de l'agent pour la fonction publique. Le modèle refermait cet
écart de périmètre par une convention — prêter au public la part employeur du
privé — qui rendait les statuts comparables au prix d'un chiffre inventé. Deux
séries l'en dispensent :

- **`part_salariale`** dans les fiches : la fraction du taux que l'assuré
  supporte. 40,87 % au régime général en 2023, 40 % à l'Agirc-Arrco par la règle
  40-60 de l'ANI du 17 novembre 2017, 100 % pour un non-salarié qui paie tout.
- **La contribution employeur du public**, que le dépôt soutenait introuvable
  avant 2006. C'était vrai de l'État, et faux du reste : la CNRACL est une
  caisse depuis 1947 et publie son taux depuis 1948 ; l'État a un taux
  *implicite* reconstitué par le PLF 2011 depuis 1995 ; depuis 2006 le taux est
  appelé par décret — 49,90 %, puis 74,28 % de 2013 à 2024, 78,28 % en 2025 et
  **82,28 % en 2026** ; la SNCF publie ses composantes T1 et T2 de 2007 à 2018.

```python
comparaison = simulateur.simuler(simulateur.carriere_simple(
    annee_naissance=1975, sexe="F", affiliation="fonctionnaire_etat",
    age_debut=22, age_liquidation=64,
    part_primes=0.2, profil_carriere="ascendant",
))
print(comparaison.tableau())

# Le détail par régime du scénario 1, que la page « Simuler » affiche aussi
for pension in comparaison.actuel.pensions_par_regime:
    print(f"{pension.regime:<28} {pension.montant:>10,.0f} €   {pension.detail}")
```

```
Fonctionnaire d'État née en 1975, 20 % de primes, partie à 64 ans

Scénario                                                  Courants   Constants   Mensuel    Écart
------------------------------------------------------------------------------------------------
1. Système actuel                                          42,656€     34,043€    2,837€     réf.
2. Notionnel rétroactif, part salariale                     8,241€      6,577€      548€   -80.7%
3. Notionnel dès 2026, part salariale                      25,690€     20,503€    1,709€   -39.8%
4. Notionnel rétroactif, salariale + patronale             45,509€     36,321€    3,027€    +6.7%
5. Notionnel dès 2026, salariale + patronale               31,176€     24,881€    2,073€   -26.9%

Qui verse la cotisation, en euros courants cumulés :
  part salariale           138,298 €   scénarios 2 et 3
  part patronale           524,169 €   soit 79% du total
  total                    662,467 €   scénarios 4 et 5
  contribution employeur publique trouvée sur 29 année(s)
```

L'employeur verse ici 79 % du total. C'est l'ordre de grandeur d'un taux
d'**équilibre**, et c'est la limite du scénario 4 : 82,28 % ne signifie pas
qu'un fonctionnaire acquiert 82 % de son traitement en droits nouveaux, mais
qu'il faut aujourd'hui cette contribution pour payer les pensions
d'aujourd'hui — démographie et engagements hérités compris.

Trois limites à connaître. Pour le public, la série n'existe que pour trois
régimes : douze autres voient leur part patronale **estimée** par l'effort d'un
salarié du privé, et le modèle affiche sur combien d'années. L'État n'est
couvert qu'à partir de 1995. Enfin, à compter de la bascule le régime unique
remplace tous les régimes : après 2026 la part patronale est celle du statut
pivot privé, et non celle d'un employeur public qui, par construction, n'existe
plus.

Un quatrième réglage conserve l'ancienne convention, comme contrefactuel :
`part_cotisation=totale_alignee` prête au public la part employeur du privé,
et fait retrouver à un fonctionnaire et à un salarié de même rémunération
exactement la même pension.

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

Quand deux institutions publient le même chiffre, quatre critères disent
laquelle aller chercher : le **producteur** prime sur le repreneur, l'**observé**
sur le projeté, le **montant servi** sur le montant calculé, le **recontrôlable**
sur le saisi. Ils sont écrits en tête de
[`data/sources.yaml`](data/sources.yaml) et détaillés dans
[`docs/methodologie.md`](docs/methodologie.md). Ce n'est pas un classement
d'institutions mais de natures de données : l'INSEE pour ce qu'il **mesure**, le
COR pour ce qu'il **décide**.

| Donnée | Période certifiée | Producteur |
|---|---|---|
| Inflation, salaire moyen, masse salariale, productivité | 1950-2025 | INSEE, Banque de données macroéconomiques |
| Espérance de vie à 0 et 60 ans | 1946-2025 | INSEE |
| Espérance de vie à 65 ans | 1960-2024 | OCDE (l'INSEE ne la publie pas) |
| Espérances de vie projetées | 2026-2125 | INSEE, projections de population 2026 (dérivées de ses quotients par âge) |
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
| Valeurs du point de l'Agirc | 1947-2018 | Agirc-Arrco, sa compilation des valeurs de point |
| Valeurs du point de l'Arrco, et de l'UNIRS qui en tient lieu avant 1999 | 1999-2018 et 1961-1998 | Agirc-Arrco, la même compilation |
| Durée maximale prise en compte par la proratisation, par génération | avant 1944 à 1947 | code de la sécurité sociale `R. 351-6`, base LEGI |
| Heures de SMIC à cotiser pour valider un trimestre | 1972 et 2014 | code de la sécurité sociale `R. 351-9`, base LEGI |

Deux séries de plus sont reprises automatiquement d'**OpenFisca-France**, le
modèle socio-fiscal de l'administration — le plafond de la Sécurité sociale
depuis 1931, et le point d'indice de la fonction publique depuis 1960 avec le
barème du minimum garanti. Ce sont des transcriptions du *Journal officiel* et
des circulaires, pas des sources primaires : elles plafonnent au niveau `haute`.

**Les valeurs du point de l'Agirc et de l'Arrco en venaient aussi, et elles
viennent désormais de la caisse qui les a décidées.** Elles pèsent, dans la
pension d'un salarié du privé, plus lourd que tous les autres barèmes réunis, et
la fédération publie chaque automne l'historique complet des siens — le régime
unifié depuis 2019, l'Agirc depuis 1947, l'Arrco depuis 1999, et les caisses
qu'elle a fédérées, dont l'UNIRS dont le barème tient lieu de point Arrco avant
l'unification. Ces 260 valeurs sont donc lues chez le producteur, et le
recontrôle a confirmé la transcription à cinq centièmes de millime près — l'écart
tenant à ce qu'elle arrondissait la conversion en euros quand le document donne
le franc exact. Elles restent en outre recoupées à la série que l'INSEE publie
depuis 2001 : sur les 42 années communes, les deux ne divergent pas une fois.

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
python scripts/fetch/openfisca_regime_general.py  # contre-expertise du scénario 1
python scripts/fetch/cnav_revalorisation_salaires.py  # revalorisation des salaires portés au compte
python scripts/fetch/agirc_arrco_valeurs_point.py  # valeurs du point, par la fédération

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
  web/
    pages.py                    contenu des pages — sans autre dépendance que le moteur
    gabarit.py                  rendu HTML et feuille de style

index.html                      le site : charge les données, puis le moteur JavaScript
.nojekyll                       servir les fichiers sans transformation
moteur/                         ce que le navigateur charge, et rien d'autre
  donnees.json                  séries, tables et régimes (533 Ko, produit par script)
  style.css                     extraite de gabarit.py (produite par script)
  js/                           portage du modèle, sans bibliothèque ni étape de build

docs/
  methodologie.md               ce que le modèle calcule, et pourquoi ainsi
  limites.md                    ce qu'il ne calcule pas, et ce qui reste à certifier

tests/                          243 tests Python
  temoins/                      chiffres et pages figés depuis le modèle Python,
                                et le relevé d'OpenFisca-France-Pension qui sert
                                de contre-expertise au scénario 1
  js/                           le portage rejoué contre ces témoins (node --test)
```

---

## Principales options

Ce sont les champs de `Parametres`. Le formulaire du site les expose sous
« Options de modélisation », et l'adresse de la page les porte tous : une
simulation se cite telle quelle.

```python
mode_indexation        ModeIndexation.{TRIPLE_LOCK_INVERSE
                       | TRIPLE_LOCK_INVERSE_NOMINAL | MEDIANE_TROIS_TAUX
                       | MOYENNE_TROIS_TAUX | REVALORISATION_PORTEE_AU_COMPTE
                       | PRIX | SALAIRES | MASSE_SALARIALE | PIB_NOMINAL}
                       défaut : MASSE_SALARIALE
lissage_indexation     moyenne glissante appliquée à la règle choisie (défaut 1,
                       aucun lissage). PIB_NOMINAL lissé sur 5 ans est la règle
                       italienne
mode_age_reference     ModeAgeReference.{CLIQUET_LEGAL
                       | CLIQUET_PUIS_ESPERANCE_VIE | LEGAL_SANS_CLIQUET}
age_conversion_droits_acquis  AgeConversionDroitsAcquis.{REFERENCE | LIQUIDATION}
part_cotisation        PartCotisation.{SALARIALE | TOTALE | TOTALE_ALIGNEE}
table_conversion       TableConversion.{UNISEXE | PAR_SEXE}
scenario_projection    cor_reference | cor_productivite_basse
                       | cor_productivite_haute   (défaut : cor_reference,
                       scénario de référence du COR, productivité 0,7 %)
annee_bascule          année de passage au régime unique (défaut 2026)
annee_euros_constants  année des euros constants (défaut 2026)
fiabilite_minimale     refuse de calculer sous un certain niveau de fiabilité
```

`Comparaison.dictionnaire()` donne le résultat en structure de données plutôt
qu'en tableau — c'est ce que la page publie sous « Les résultats complets en
JSON ».

---

## Tests

```bash
python -m pytest tests
```

282 tests couvrant le chargement et la fiabilité des données, la règle de
certification, la calibration des tables de mortalité et sa concordance avec les
tables observées, les propriétés du moteur
(monotonie du diviseur, cliquet de l'âge de référence, règles de fusion), le
comportement des scénarios, le rendu des pages et la fraîcheur de ce que charge
le site. Aucun test n'accède au réseau : les sources sont simulées.

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
