# Retraite à comptes notionnels — modèle français rétroactif

Modélisation d'un système de retraite français **en comptes notionnels**,
appliqué rétroactivement depuis l'origine de la répartition, avec trois
scénarios comparables pour n'importe quelle carrière — actif ou retraité.

```
Scénario                                      Courants   Constants   Mensuel    Écart
------------------------------------------------------------------------------------
1. Système actuel                              19,873€     27,810€    2,317€     réf.
2. Notionnel rétroactif (depuis l'origine)      1,212€      1,696€      141€   -93.9%
3. Notionnel à compter de 2026                 19,873€     27,810€    2,317€    +0.0%
```
*Agent de conduite SNCF né en 1955, parti à 50 ans : quinze ans d'anticipation
sur l'âge de référence.*

---

## Démarrer

Aucune dépendance hors PyYAML.

```bash
pip install -e .

# Simuler une carrière
retraite-notionnelle simuler --naissance 1960 --statut salarie_prive_non_cadre \
                             --debut 20 --liquidation 62

# Le cas général : grille cas type × génération
retraite-notionnelle cas-types

# Voir les statuts et les 35 régimes du catalogue
retraite-notionnelle regimes

# La série d'indexation, année par année
retraite-notionnelle indexation --de 1941 --a 2025

# Le régime unique issu de la fusion
retraite-notionnelle fusion

# L'état de fiabilité des données — à lire en premier
retraite-notionnelle donnees
```

En bibliothèque :

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

---

## Deux résultats à connaître avant de lire les chiffres

### 1. La règle d'indexation domine tout le reste

Le triple lock inversé, pris à la lettre, compare deux taux **nominaux**
(inflation, salaire moyen) à un taux **réel** (productivité). Dès que l'inflation
dépasse la productivité — soit presque toute la période 1945-1985 — c'est la
productivité qui l'emporte.

| Règle | Comptes 1941-2025 | Prix | Pouvoir d'achat conservé |
|---|---|---|---|
| Triple lock inversé, littéral | ×4,9 | ×318,6 | **1,5 %** |
| Triple lock inversé, tout en nominal | ×243,7 | ×318,6 | 76,5 % |
| Indexation sur les prix | ×318,6 | ×318,6 | 100 % |

Une cotisation de 1950 ne conserve donc que 1,5 % de sa valeur réelle. Dans le
scénario rétroactif, **l'essentiel de la baisse affichée vient de la règle
d'indexation, pas du passage aux comptes notionnels**.

C'est la règle telle qu'énoncée, appliquée sans correctif. Pour séparer les deux
effets : `--indexation triple_lock_inverse_nominal` (règle homogène, toujours
austère) ou `--indexation prix` (effet propre des comptes notionnels).

### 2. La fusion augmente les cotisations des indépendants

Le régime unique applique 25,74 % sur assiette déplafonnée. Pour les professions
libérales et les indépendants, qui cotisent aujourd'hui moins et sous plafond,
c'est une forte hausse de prélèvement — et donc de pension. C'est la seule ligne
du tableau des cas types qui progresse ; le résultat est correct, mais il traduit
un effort contributif accru, pas un avantage accordé.

---

## Les données

Dix-neuf institutions sont recensées dans [`data/sources.yaml`](data/sources.yaml) :
INSEE, COR, Comité de suivi des retraites, DREES, CNAV, Service des retraites de
l'État, Caisse des dépôts, Direction de la Sécurité sociale, Cour des comptes,
Agirc-Arrco, Union Retraite, CCMSA, CNAVPL, CNBF, DGAFP, Direction du Budget,
ERAFP, Ircantec, caisses des régimes spéciaux, Urssaf.

**Chaque valeur porte son niveau de fiabilité** — `certifiee`, `haute`,
`moyenne`, `estimee` — et la fiabilité d'un résultat est celle de son maillon le
plus faible. `Parametres.fiabilite_minimale` fait échouer la simulation plutôt
que de produire un chiffre trompeur.

> **Aucune série n'est aujourd'hui au niveau `certifiee`.** Les séries longues
> (avant 1990) ont été saisies, pas extraites automatiquement : les portails de
> diffusion ne les exposent pas en API. Les niveaux absolus de pension sont donc
> indicatifs ; les **écarts entre scénarios** sont beaucoup plus robustes.
> Lire [`docs/limites.md`](docs/limites.md) avant de citer un chiffre.

```bash
python scripts/fetch/eurostat_hicp.py      # contrôle croisé de l'inflation
python scripts/fetch/insee_melodi.py --catalogue
python scripts/verifier_donnees.py         # cohérence et vraisemblance
```

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
  brut/                         téléchargements bruts (contrôle)
  derive/                       calibrations mémorisées

src/retraite_notionnelle/
  config.py                     toutes les décisions de modélisation, en un seul endroit
  carriere.py                   description d'une carrière, trois niveaux de précision
  donnees/                      chargement, fiabilité, macro, mortalité, régimes
  moteur/                       indexation, âge de référence, conversion, fusion, compte
  scenarios/                    système actuel, comptes notionnels
  simulateur.py                 façade et restitution
  castypes.py                   cas général
  cli.py                        ligne de commande

docs/
  methodologie.md               ce que le modèle calcule, et pourquoi ainsi
  limites.md                    ce qu'il ne calcule pas, et ce qui reste à certifier

tests/                          64 tests
```

---

## Principales options

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

64 tests couvrant le chargement et la fiabilité des données, la calibration des
tables de mortalité, les propriétés du moteur (monotonie du diviseur, cliquet de
l'âge de référence, règles de fusion) et le comportement des scénarios.

---

## Licence

MIT. Les données publiques référencées restent soumises aux licences de leurs
producteurs respectifs (licence ouverte Etalab pour la plupart).
