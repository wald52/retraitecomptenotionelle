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

Le modèle calcule **trois scénarios pour une même carrière**, afin qu'ils soient
comparables :

| | Scénario | Ce qu'il mesure |
|---|---|---|
| **1** | Système actuel | Le droit en vigueur, minima et majorations compris. C'est la référence. |
| **2** | Notionnel **rétroactif** depuis 1941 | Contrefactuel : toute la carrière recalculée sur les seules cotisations, comme si la règle avait toujours existé. |
| **3** | Notionnel **à compter de 2026** | Réforme prospective : les droits déjà acquis sont conservés, les règles notionnelles s'appliquent ensuite. |

```
Agent de conduite SNCF né en 1955, parti à 50 ans (quinze ans avant l'âge de référence)

Scénario                                      Courants   Constants   Mensuel    Écart
------------------------------------------------------------------------------------
1. Système actuel                              20,435€     28,611€    2,384€     réf.
2. Notionnel rétroactif (depuis l'origine)      1,300€      1,820€      152€   -93.6%
3. Notionnel à compter de 2026                 20,435€     28,611€    2,384€    +0.0%
```

> **Le scénario 2 n'est pas une proposition de réforme**, et l'écart qu'il
> affiche ne mesure pas l'effet des comptes notionnels. Il vient pour
> l'essentiel de la règle d'indexation retenue — voir
> [« La règle d'indexation domine tout le reste »](#1-la-règle-dindexation-domine-tout-le-reste)
> plus bas. Le modèle permet de séparer les deux effets ; c'est même son
> principal résultat.

---

## Ouvrir le simulateur

### 👉 [wald52.github.io/retraitecomptenotionelle](https://wald52.github.io/retraitecomptenotionelle/)

Rien à installer, rien à lancer : une adresse à ouvrir. Le modèle — le code
Python de ce dépôt et ses données de référence — s'exécute **dans votre
navigateur**, en WebAssembly. Aucune donnée saisie ne quitte votre machine,
puisqu'il n'y a pas de serveur de calcul. Le premier chargement prend environ
trois secondes, les suivants sont immédiats.

Quatre pages : **Simuler** (une carrière, avec le détail du calcul et la
décomposition de l'écart règle par règle), **Cas types** (la grille 12 carrières
× 7 générations), **Méthode**, **Données** (l'état de fiabilité des séries).

L'adresse d'une simulation contient tous ses paramètres — elle peut être citée
ou partagée telle quelle — et chaque résultat est consultable en JSON au bas de
la page.

<details>
<summary>Comment la page fonctionne, et pourquoi ce choix</summary>

`index.html` charge [Pyodide](https://pyodide.org) — CPython compilé en
WebAssembly, versionné dans `moteur/pyodide/` (14 Mo) — puis décompresse
`moteur/simulateur.zip` (109 Ko : le modèle et les données) dans son système de
fichiers virtuel, et appelle le module `retraite_notionnelle.web.navigateur`.

Le site est servi depuis la racine du dépôt, telle quelle : c'est ce que GitHub
Pages publie sans aucun réglage, et `.nojekyll` demande que les fichiers soient
servis sans transformation.

C'est **le même code Python** que la ligne de commande, à la ligne près : pas de
portage en JavaScript qui divergerait du modèle, pas de résultats précalculés
qui figeraient les hypothèses. Rien n'est chargé depuis un CDN ou un service
tiers, ce qu'un test vérifie : le site fonctionne derrière un réseau fermé, et
survivra à la disparition de n'importe quel hébergeur.

Le paquet `moteur/simulateur.zip` est reconstruit par `python scripts/construire_site.py`
après toute modification du code ou des données ; le test `test_le_paquet_est_a_jour`
échoue s'il a été oublié.

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

# Les 22 statuts et les 35 régimes du catalogue
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
| Tous les régimes, actuels **et** disparus | 35 régimes : AGIRC, ARRCO, CANCAVA, ORGANIC, RSI, mines, SEITA, chemins de fer secondaires… |
| Départ trop tôt = pension réduite | Âge de référence **à cliquet** : l'abaissement de 1982 ne le fait pas redescendre |
| Régimes à départ précoce traités au même étalon | SNCF à 50 ans = 15 ans d'anticipation ; Opéra à 40 ans = 25 ans |
| Indexation par triple lock inversé, depuis l'origine | `min(inflation, salaire moyen, productivité réelle)`, appliqué aux comptes **et** aux pensions liquidées |
| Trois résultats comparables | Système actuel / notionnel rétroactif / notionnel prospectif |
| Cas particulier **et** cas général | Simulation individuelle + grille 12 cas types × 7 générations |
| Fusion des régimes au cas le plus défavorable | Âge 64/67, 172 trimestres, carrière entière, assiette déplafonnée, zéro avantage |
| Capitalisation isolée | RAFP et assurances sociales de 1930 dans un compartiment séparé, jamais convertis |
| Suppression des minima | Ni minimum contributif, ni minimum garanti, ni ASPA : peu cotisé, peu de retraite |
| Suppression des avantages | Ni majorations enfants, ni MDA, ni AVPF, ni bonifications, ni réversion, ni trimestres gratuits |
| Tout le monde peut simuler | 22 statuts d'affiliation, cinq informations suffisent |
| Utilisable sans rien installer | Le modèle s'exécute dans le navigateur, sur une simple adresse |

---

## Deux résultats à connaître avant de lire les chiffres

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

---

## Les données

Vingt-deux institutions sont recensées dans [`data/sources.yaml`](data/sources.yaml) :
INSEE, COR, Comité de suivi des retraites, DREES, CNAV, Service des retraites de
l'État, Caisse des dépôts, Direction de la Sécurité sociale, Cour des comptes,
Agirc-Arrco, Union Retraite, CCMSA, CNAVPL, CNBF, DGAFP, Direction du Budget,
ERAFP, Ircantec, caisses des régimes spéciaux, Urssaf, Légifrance, Eurostat.

**Chaque valeur porte son niveau de fiabilité** — `certifiee`, `haute`,
`moyenne`, `estimee` — et la fiabilité d'un résultat est celle de son maillon le
plus faible. `Parametres.fiabilite_minimale` fait échouer la simulation plutôt
que de produire un chiffre trompeur.

Une valeur n'est `certifiee` que si elle a été **confrontée à la source
elle-même**, téléchargée depuis le producteur. C'est le cas de l'inflation, du
salaire moyen et de la productivité de **1950 à 2025**, des espérances de vie
annuelles depuis 1946, et du plafond de la Sécurité sociale depuis 2002 : ces
séries sont recalculées depuis l'API SDMX de la Banque de données
macroéconomiques de l'INSEE, ouverte sans clé d'accès et qui diffuse — contrairement
à l'API Melodi — les séries longues.

```bash
python scripts/fetch/insee_bdm.py               # séries longues INSEE (BDM)
python scripts/fetch/eurostat_esperance_vie.py  # espérance de vie à 65 ans
python scripts/fetch/eurostat_hicp.py           # contrôle croisé de l'inflation

python scripts/verifier_donnees.py              # confronte, sans rien écrire
python scripts/verifier_donnees.py --appliquer  # aligne sur la source et certifie
```

> **Ce qui reste saisi à la main :** les séries d'avant 1950, le plafond
> d'avant 2002, l'espérance de vie à 65 ans d'avant 1986, les quotients de
> mortalité par âge, et tous les paramètres de régime — taux, âges, valeurs de
> point — qui viennent de règlements et non de séries statistiques.
> Lire [`docs/limites.md`](docs/limites.md) avant de citer un chiffre.

---

## Organisation

```
data/
  sources.yaml                  manifeste des sources institutionnelles
  reference/
    macro/                      inflation, salaire moyen, productivité, plafond, projections
    mortalite/                  espérances de vie observées et projetées
    regimes/                    35 fiches de régime + schéma + rendements des points
    legislation/                âges de référence à cliquet, profils d'affiliation
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
    navigateur.py               pont vers la page qui s'exécute dans le navigateur

index.html                      le site : charge Pyodide, puis le simulateur
.nojekyll                       servir les fichiers sans transformation
moteur/
  pyodide/                      CPython compilé en WebAssembly (14 Mo, versionné)
  simulateur.zip                le modèle et les données (109 Ko, reconstruit par script)

docs/
  methodologie.md               ce que le modèle calcule, et pourquoi ainsi
  limites.md                    ce qu'il ne calcule pas, et ce qui reste à certifier

tests/                          124 tests
```

---

## Principales options

Elles valent pour toutes les commandes, et se retrouvent dans le formulaire web
sous « Options de modélisation ».

```bash
--indexation      triple_lock_inverse | triple_lock_inverse_nominal | prix | salaires
--age-reference   cliquet_legal | cliquet_puis_esperance_vie | legal_sans_cliquet
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

124 tests couvrant le chargement et la fiabilité des données, la règle de
certification, la calibration des tables de mortalité, les propriétés du moteur
(monotonie du diviseur, cliquet de l'âge de référence, règles de fusion), le
comportement des scénarios, le rendu des pages dans les deux modes et la
fraîcheur du paquet embarqué dans le site. Aucun test n'accède au réseau : les
sources sont simulées. Les tests du serveur sont ignorés si ses dépendances
optionnelles ne sont pas installées.

---

## Licence

MIT. Les données publiques référencées restent soumises aux licences de leurs
producteurs respectifs (licence ouverte Etalab pour la plupart).
