# Limites — à lire avant d'utiliser un chiffre

Ce modèle est une charpente complète et fonctionnelle. Ses séries
macroéconomiques sont **certifiées de 1950 à 2025**, ses tables de mortalité sont
celles réellement observées depuis 1986, et son plafond de la Sécurité sociale
remonte à 1931 daté décret par décret — le tout recontrôlé automatiquement contre
les sources. Ce qui précède 1950, et les paramètres propres à chaque régime,
restent saisis à la main. Ce document dit exactement où passe la frontière, pour
qu'aucun résultat ne soit cité sans savoir sur quoi il repose.

---

## Paramètres du scénario 1, et ce qu'ils valent

Le scénario 1 sert d'étalon : ce qui n'y est pas sourcé fragilise tout le reste.
Les trois premières lignes viennent d'en sortir : elles sont désormais
confrontées à la loi elle-même, et non plus saisies de mémoire. Les suivantes
restent saisies depuis les textes, faute d'un chemin automatisable : Légifrance
refuse les requêtes non navigateur et son API demande une clé.

| Paramètre | Valeur retenue | État |
|---|---|---|
| Minimum contributif | ancres 2007 et 2023, 6 958,21 → 8 509,61 €/an | **certifié**, code de la sécurité sociale D. 351-2-1 |
| Minimum contributif majoré | ancres 2007 et 2023, 7 603,41 → 10 170,86 €/an | **certifié**, même article |
| Plafond d'écrêtement du minimum | ancres 2012 et 2014, 1 005 → 1 120 €/mois | **certifié**, D. 173-21-0-0-1 |
| Durée requise par génération | table 1934-1965, 151 → 172 trimestres | reprise des textes, non recontrôlée automatiquement |
| Âge légal par génération | table 1930-1968, 60 → 64 ans | reprise des textes, non recontrôlée automatiquement |
| Âge d'annulation de la décote par génération | table 1930-1955, 65 → 67 ans | reprise des textes, non recontrôlée automatiquement |
| Coefficient de minoration par génération | table 1900-1953, 2,5 → 1,25 % | textes, recoupé à la DREES |
| Années retenues au salaire de référence | table 1934-1948, 10 → 25 années | reprise des textes, non recontrôlée automatiquement |
| Coefficients d'anticipation Agirc-Arrco | deux tables, 1 → 0,78 et 1 → 0,43 | barème publié par la caisse, saisi |
| Plafond de la majoration familiale Agirc-Arrco | 2 367 €/an (novembre 2025) | publié par la caisse, saisi |
| Droits ouverts par motif d'interruption | 9 motifs | principe sourcé, fractions non recontrôlées |

**Le minimum contributif est sorti de cette liste, et c'est la même leçon que
pour la MSA.** Cette page a longtemps écrit qu'il ne figurait « dans aucune
source machine ouverte », que ses montants n'étaient publiés que dans des
circulaires CNAV en PDF, et qu'il n'y avait donc « pas de chemin de
certification automatique à écrire ». C'était faux, et pour la même raison que
la fois précédente : *la donnée est dans la loi, et il fallait chercher par le
numéro d'article.* Deux articles suffisent :

* **D. 351-2-1** du code de la sécurité sociale porte les DEUX montants — le
  minimum, et le minimum majoré au titre des périodes cotisées ;
* **D. 173-21-0-0-1** porte le plafond d'écrêtement de l'article L. 173-2, et
  dit dans la même phrase comment il se revalorise : « aux mêmes dates et dans
  les mêmes proportions que le salaire minimum de croissance ».

`scripts/fetch/dila_legi_minimum_contributif.py` les lit dans la base LEGI, en
flux, comme celui de la MSA.

Trois corrections en découlent, et aucune n'est cosmétique.

1. **Le montant retenu était le mauvais.** La ligne portait 8 796 €/an sous le
   libellé « majoré » : c'est en réalité le minimum NON majoré de 2024. Le
   majoré vaut près d'un cinquième de plus, et c'est lui qui s'applique à une
   carrière complète — c'est-à-dire au cas même que le minimum contributif est
   fait de protéger. Le moteur distingue désormais les deux, sur la condition
   de droit : la durée COTISÉE, dont les trimestres assimilés et ceux de la
   majoration de durée d'assurance sont exclus.
2. **La revalorisation se faisait sur le mauvais index.** Les trois montants
   suivent le SMIC — le plafond depuis février 2014, les deux minima depuis la
   réforme du 14 avril 2023 — et non les prix. Le modèle les indexe maintenant
   sur le SMIC à partir de la date d'effet de l'ancre, sur les prix avant elle,
   règle qui s'appliquait alors.
3. **Ce ne sont pas des séries mais des ancres datées** : le code n'est pas
   modifié chaque année, les montants sont revalorisés par l'effet de la loi —
   et l'article est réécrit plus souvent qu'il n'est revalorisé. Ses versions de
   2009 et de 2020 répètent le montant de 2007 sans y toucher : les retenir
   comme des ancres fraîches remettrait le compteur à zéro et perdrait treize
   ans de revalorisation. Une ancre est donc un montant qui CHANGE, et il n'y
   en a que deux par grandeur.

   C'est ensuite au modèle de porter l'ancre à l'année de liquidation, en
   retenant la PLUS PROCHE — entre deux décrets le montant dérive d'autant plus
   qu'on s'en éloigne, le législateur ayant parfois gelé la revalorisation, ce
   qu'aucun indice ne reproduit. Le contrôle tombe alors à 2 % près sur quinze
   ans et juste sur les années récentes : 8 797 €/an calculés pour 2024 contre
   8 796 publiés, 8 970 pour 2025 contre 8 972, 10 721 pour le majoré contre
   10 720,68, et le plafond de 2014 rapporté au SMIC de 2025 redonne
   1 396 €/mois là où les caisses publient 1 394,86 €. Deux chemins
   indépendants qui se rejoignent.

## Écarts connus avec le droit positif, dans le scénario 1

**Ce qui vient d'être refermé**, et que ce document annonçait encore comme
approché :

- **L'abattement des complémentaires est celui de l'Agirc-Arrco**, et non plus
  la décote du régime de base. Le régime publie deux tables de coefficients
  d'anticipation — l'une indexée sur les trimestres manquants, l'autre sur
  l'âge — et retient la plus avantageuse pour l'assuré. Les deux ne se
  recoupent pas : douze trimestres manquants valent 0,88, quand la décote de la
  base n'en donnerait que 0,85 ; mais dix ans d'anticipation valent 0,43, là où
  elle en donnerait 0,50. L'approximation était donc fausse dans les deux sens.
- **La majoration familiale des complémentaires est plafonnée** : 2 367 € par
  an, revalorisés comme la valeur de service du point, opposables aux assurés
  nés à compter du 2 août 1951. Le plafond porte sur la majoration de LA
  complémentaire, Agirc, Arrco et régime unifié confondus — les plafonner
  séparément l'aurait triplé.
- **Les trimestres de la MDA sont attribués dans un régime.** Ils jouaient sur
  la décote tous régimes confondus mais restaient hors du rapport durée acquise
  / durée requise du régime qui les accorde, ce qui amputait la mère de famille
  d'une part de ce que la MDA est censée lui rendre. Faute de connaître l'année
  de naissance des enfants, ils vont au régime de base où l'assuré a validé le
  plus de trimestres parmi ceux qui portent la MDA : exact pour une carrière
  mono-affiliée, approché pour un polypensionné.
- **La décote est plafonnée à vingt trimestres**, comme le veut le droit. Sans
  ce plafond, un départ dix ans avant l'heure retirait la moitié de la pension
  de base là où le droit n'en retire que le quart. C'est le défaut qui déplaçait
  le plus de chiffres : la pension d'un départ très anticipé monte de 25 %.
- **La décote de la loi Boulin était quatre fois trop forte.** La fiche portait
  5 % par trimestre là où le texte retire 5 *points* par année d'anticipation à
  un taux de 50 %, soit 2,5 % par trimestre. Toutes les liquidations anticipées
  de 1972 à 1982 en étaient faussées.

Ce qui reste approché :

- **Montée en charge des réformes, ce qui n'est pas lu à la génération.** La
  durée requise, l'âge légal d'ouverture, l'âge d'annulation de la décote, le
  coefficient de minoration et le nombre d'années retenues au salaire de
  référence le sont désormais tous les cinq. Restent lus à l'année de
  liquidation les taux de cotisation, et la montée en charge propre à chaque
  régime spécial.
- **Dispositifs de départ anticipé.** Carrières longues, pénibilité, invalidité
  et inaptitude ne sont pas modélisés : un assuré qui liquide tôt subit ici la
  décote, quand le droit l'en dispenserait.

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
| Quotients de mortalité par âge | 1899-1985 | **certifiée** | INED, tables de Vallin et Meslé, âges 0-104 |
| Quotients de mortalité par âge | après 1985, au-delà de 94 ans | absents | calibration paramétrique |
| Minimum contributif et plafond d'écrêtement | ancres de 2007 à 2014 | **certifiée** | DILA, base LEGI, code de la sécurité sociale |
| Plafond Sécurité sociale | 2002-2025 | **certifiée** | INSEE BDM, idbank 000822494 |
| Plafond Sécurité sociale | 1931-2001 | haute | OpenFisca-France, daté décret par décret |
| Taux de cotisation, régime général | 1967-2026 | moyenne | OpenFisca-France, recoupé à chaque exécution |
| Taux de cotisation, autres régimes | tous | moyenne / estimée | Comptes de la Sécurité sociale |
| Valeurs d'achat et de service du point, Ircantec | 1971-2021 | **certifiée** | Caisse des dépôts, qui gère le régime |
| Valeurs d'achat et de service du point, autres | Agirc 1947-2018, Arrco 1949-2018, Agirc-Arrco 2019-2025, RAFP 2005-2021, RCI 2013-2023 | haute | OpenFisca-France-Pension, recoupé à l'INSEE depuis 2001 |
| Valeurs du point, Arrco avant 1999 | 1949-1998 | moyenne | UNIRS, la plus grosse caisse Arrco |
| Valeurs du point, complémentaire des avocats | 2017-2026 | **certifiée** | CNBF, ses barèmes annuels |
| Valeur du point et taux, base des professions libérales | 2021-2025 | **certifiée** | CNAVPL, ses recueils statistiques |
| Valeur de service du point, complémentaire agricole | 2005-2024 | **certifiée** | DILA, base LEGI, code rural `D. 732-166` |
| Valeur du point, base agricole et valeurs d'achat RCO | — | absentes | hors du code ; voir plus bas |

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
python scripts/fetch/dila_legi_msa.py          # point de la complémentaire agricole (lent : 1,1 Go)
python scripts/fetch/dila_legi_minimum_contributif.py  # minimum contributif et plafond (lent aussi)
python scripts/fetch/ined_vallin_mesle.py      # quotients de mortalité d'avant 1986
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
  qu'en fichier tableur. Ce n'est plus le format qui bloque — `lecture_xls.py`
  ouvre les classeurs Excel 97 depuis les tables de mortalité de l'INED — c'est
  l'adresse : la page de l'INSEE qui porte ce tableau ne sert qu'un
  convertisseur, sans lien de téléchargement. Le jour où l'adresse est connue,
  le chemin est court.
* *Quotients de mortalité par âge d'avant 1986* — **trouvés.** Cette page
  écrivait que la Human Mortality Database était « seule à couvrir la France
  depuis 1816 » et que son inscription obligatoire la mettait hors de portée
  d'un script. Elle n'est pas seule : Jacques Vallin et France Meslé ont
  reconstitué les tables françaises de 1806 à 1997, l'INED les a publiées en
  2001, et l'INED en sert librement le contenu du cédérom. Le tableau II-B-1
  donne exactement ce qui manquait — « quotients du moment par année d'âge, de
  0 à 104 ans » — pour les deux sexes.

  Le dépôt en reprend **1899-1985**, soit 18 226 quotients, et laisse à
  Eurostat, producteur de la donnée observée, tout ce qui suit. Les deux
  sources se recouvrent en fait de 1986 à 1997 : sur ces douze années et
  85 âges, elles concordent à un écart médian de 0,4 à 0,7 %. C'est ce
  recoupement qui autorise à les aboucher.

  Le fichier est un classeur Excel 97, format que la bibliothèque standard ne
  sait pas ouvrir. Comme pour les PDF de la CNBF, on a donc écrit le lecteur :
  `scripts/fetch/lecture_xls.py` extrait les nombres d'un fichier composite
  OLE2, en quatre types d'enregistrements BIFF et sans dépendance.

* *Espérance de vie à 65 ans d'avant 1960* — l'INSEE publie e0, e1, e20, e40 et
  e60, jamais e65 ; ni l'OCDE (1960) ni Eurostat (1986) ne remontent plus haut.
  La question a toutefois perdu de son poids : sur 1899-1985, le modèle
  n'estime plus la mortalité, il la lit. L'espérance de vie à 65 ans n'y sert
  plus qu'à calibrer une loi dont ces années n'ont plus besoin, et elle reste
  dérivable des mêmes tables INED si le besoin revient.

* *Quotients de mortalité au-delà de 94 ans, depuis 1986* — Eurostat s'arrête à
  94 ans et ses classes ouvertes (85 et plus, 95 et plus) ne sont pas des
  quotients à un âge donné. Au-delà, sur ces années-là, le modèle reprend sa
  loi de Gompertz-Makeham : c'est un raccord assumé, mais il ne concerne plus
  que les années postérieures à 1986. L'INED couvre 1986-1997 jusqu'à 104 ans
  et pourrait combler ces douze années ; on s'en est abstenu pour ne pas
  panacher deux sources sur une même année.

* *Taux de cotisation d'avant octobre 1967 et des régimes autres que le régime
  général* — aucune transcription machine n'existe. Ils viennent des
  ordonnances de 1945 et de leurs modificatifs, saisis à la main. Ont été
  essayés sans succès, pour éviter de refaire le trajet : les barèmes IPP, qui
  sont la source amont d'OpenFisca et ne commencent pas plus tôt que lui pour
  la CNAV (1967) ; et la Banque de données macroéconomiques de l'INSEE, dont la
  série de taux de cotisation vieillesse (idbank 000483633) ne porte que la
  part salariale et ne débute qu'en juillet 1993.
* *Valeur du point de la MSA* — **trouvée, après huit sources infructueuses.**
  Ont été essayés sans succès : OpenFisca-France-Pension (ne modélise pas ce
  régime), les barèmes IPP (même périmètre — c'est la source amont d'OpenFisca,
  ses quarante-cinq feuilles couvrent l'Arrco, l'Agirc, l'UNIRS, PRO-BTP,
  l'Ircantec, la CANCAVA et l'ORGANIC), l'open data de la DREES (cinquante et un
  jeux « retraite », tous des résultats statistiques), le portail open data de la
  Caisse des dépôts (effectifs seulement), data.gouv.fr (les jeux de la MSA sont
  des effectifs de retraités et d'exploitants), la BDM de l'INSEE — qui porte le
  point de l'Agirc et de l'Arrco mais aucun point agricole — les « Chiffres
  utiles » de la MSA, publiés chaque année depuis 2005 mais qui sont un annuaire
  d'effectifs et non un barème, et le site de la caisse, dont les pages de
  barèmes sont construites en JavaScript.

  Elle était pourtant écrite, chaque année depuis 2005, dans le **code rural**,
  à l'article `D. 732-166` :

  > « La valeur de service du point de retraite complémentaire obligatoire
  > mentionnée à l'article L. 732-60 est fixée pour l'année 2013 à
  > 0,336 2 euros. »

  Ce qui manquait n'était pas la donnée mais un **chemin reproductible** vers
  elle : Légifrance sert cet article mais refuse les requêtes automatisées — 403
  sur toute requête non navigateur — et son API demande une clé. La base **LEGI**
  de la DILA, elle, est en accès libre et garde chaque version datée de chaque
  article codifié. `scripts/fetch/dila_legi_msa.py` la lit en flux, sans écriture
  disque, et n'en retient que les dix-neuf versions de cet article. La série
  couvre **2005-2024**, sans trou, et le niveau est celui du producteur : c'est
  la publication officielle, non une transcription.

  Trois pièges de lecture, notés pour qui reprendra le fil : le *Journal
  officiel* aère les décimales par groupes de trois (« 0,336 2 », parfois même
  « 0, 311 9 ») ; la rédaction change trois fois de forme en vingt ans ; et un
  même décret peut fixer deux années d'un coup — c'est ainsi que 2019 et 2021
  entrent dans la série, aucun texte ne leur étant propre. L'année 2022 a reçu
  deux valeurs successives, revalorisée en cours d'année : la convention du
  dépôt retenant le 31 décembre, c'est la seconde qui compte.

  **Ce qui reste ouvert, et une correction.** Cette page a d'abord écrit que la
  RCO ne pouvait pas avoir de prix d'achat, ses points étant attribués par la
  formule `revenus × 100 ÷ (1 820 × SMIC)`. C'est faux : l'article `L. 732-60`
  dispose que « le nombre annuel de points est déterminé en fonction de
  l'assiette […] et des **valeurs d'achat** fixées par l'arrêté mentionné à
  l'article L. 732-60-1 ». La formule était la règle ancienne ; depuis la loi
  d'avenir agricole de 2014, un plan triennal fixe conjointement valeurs de
  service, valeurs d'achat et taux de cotisation. Ces valeurs d'achat ne sont pas
  dans le code — l'arrêté ne le modifie pas — et restent à trouver.

  Le régime de **base** reste lui aussi sans série. Sa retraite proportionnelle
  est en points, dont la valeur n'est entrée dans le code qu'en 2025
  (`R. 732-66`, 4,589 € au 1er janvier 2025 ; le COR donne 4,264 € pour 2023),
  et ses points sont attribués par un barème annuel par tranche de revenu — de
  23 à 113 points — que personne ne publie en série.

  **Le moteur utilise désormais ces valeurs.** La fiche a été scindée : la RCO
  a la sienne, `msa_rco`, et la base garde `msa_non_salaries`. Ce qui a
  débloqué le calcul n'est pas le prix d'achat introuvable mais, là encore, le
  BARÈME EN POINTS, qui est public : cotiser sur l'assiette minimale de
  1 820 SMIC ouvre 100 points, et les points sont proportionnels au-delà, sans
  plafond. Le nombre de points ne dépend donc pas du taux de cotisation, et
  l'absence de série historique de ce taux ne déplace que le flux versé au
  compte notionnel. Restent hors du modèle les points **gratuits** — 66 par an
  aux conjoints et aides familiaux pour les périodes antérieures à 2011, dans
  la limite de 17 années — et le barème du régime de base.

  **La voie légale mène quelque part, mais pas partout.** Les bases ouvertes
  de la DILA ont été dépouillées en flux, sans écriture disque : 12,4 Go de JORF
  puis 9,1 Go de LEGI, quatre passes en tout — deux ciblées, deux larges gardant
  tout article codifié portant une valeur de point, pour ne pas manquer un renvoi
  du type « la valeur mentionnée à l'article L. 643-1 ». Une cinquième passe,
  cette fois indexée non sur le texte mais sur le **numéro d'article**, a fini
  par livrer la série agricole : c'est ce que fait aujourd'hui
  `scripts/fetch/dila_legi_msa.py`. Le bilan, pour ne pas refaire le trajet :

  * la valeur de service du point de la **retraite complémentaire obligatoire
    agricole** est portée par l'article `D. 732-166` du code rural, dont LEGI
    garde les dix-neuf versions datées. C'est une série complète de 2005 à 2024,
    désormais dans le dépôt et certifiée. Chercher le *texte* ne suffisait pas —
    les premières passes n'en avaient tiré que quatre valeurs éparses ; chercher
    le *numéro d'article* les donne toutes, parce que LEGI est organisée par
    version d'article et non par thème ;
  * la **CNAVPL** n'apparaît dans aucun article codifié portant une valeur de
    point, et la passe large n'en trouve pas davantage : la législation
    consolidée ne contient, sous ce libellé, que le point d'indice des pensions
    militaires d'invalidité et celui de la fonction publique. Côté *Journal
    officiel*, la passe large remonte 104 textes portant une valeur de point,
    dont aucun ne mentionne le mot « libérale ». L'explication n'est pas que la
    recherche ait été trop étroite, mais que la donnée cherchée n'y est pas :
    **le décret annuel fixe un coefficient de revalorisation, non un montant.**
    La valeur qui en résulte n'est publiée que par la caisse.

  La leçon vaut d'être retenue : *une base peut contenir la donnée sans que le
  mot cherché y figure*. Ce qui a débloqué la MSA n'est pas une source nouvelle,
  c'est un changement de clé d'entrée.

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

  C'est la seule des trois caisses à rester dans cet état. La CNAVPL et la MSA
  en sont sorties par le même chemin — scinder la fiche, puis lire le barème en
  points plutôt que d'attendre un prix d'achat. Ici le chemin est différent, et
  ce qui manque a changé de nature : **la grille est là.** Le barème que
  `scripts/fetch/cnbf_baremes.py` télécharge déjà porte, outre les deux valeurs
  du point, tout ce qu'il faudrait pour scinder la fiche :

  * la cotisation FORFAITAIRE du régime de base, par année d'ancienneté — 351 €
    la première année, 1 921 € à partir de la sixième et pour les avocats de
    65 ans et plus (barème 2025) ;
  * la cotisation PROPORTIONNELLE de base, 3,20 % du revenu net, plafonnée ;
  * la grille du complémentaire, par classe et par tranche de revenu : trois
    classes (C1, C2, C2+) et cinq tranches, de 7,00 % à 15,10 % en classe C1.

  Ce qui bloque n'est donc plus une donnée mais **deux décisions de
  modélisation**, et elles appartiennent à qui tient le modèle : quelle classe
  retenir par défaut — C1 est l'obligatoire, mais ce n'est pas la plus répandue
  — et comment exprimer des tranches fixées en euros dans un moteur dont toutes
  les assiettes sont en plafonds de la Sécurité sociale. Trancher au jugé
  remplacerait une approximation documentée par une autre qui ne le serait pas ;
  la fiche reste donc agrégée, et le dit.

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

  **Le moteur s'en sert désormais.** Ce qui bloquait n'était pas la donnée mais
  la forme du barème : le régime n'attribue pas un nombre de points
  proportionnel à la cotisation, mais **525 points au maximum sur la tranche 1
  et 25 sur la tranche 2**, soit 550 depuis 2015 — 450 et 100 avant. Un
  plafonnement en points est une règle de calcul, pas une colonne à ajouter :
  il a fallu l'écrire dans le moteur, sous la forme d'un champ `points_maximum`
  qui dit combien de points ouvre une assiette donnée. La fiche est scindée en
  ses deux tranches, qui se recouvrent depuis 2015 comme le fait la cotisation.
  Le nombre de points ne dépend alors pas du taux de cotisation, ce qui est
  heureux : c'est le barème que la caisse publie, pas le prix d'achat.
  Reste hors du modèle la période 1949-2003, assise sur des classes
  forfaitaires dont la grille n'est pas publiée : ces années restent au
  rendement instantané.

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

- **régimes en points** — la pension est calculée en points, sur l'historique
  réel des valeurs d'achat et de service (Agirc depuis 1947, Arrco depuis 1949,
  Ircantec depuis 1949), avec conversion des points aux fusions. S'y ajoutent
  depuis peu deux régimes dont le barème n'est pas un prix d'achat mais un
  NOMBRE DE POINTS par tranche d'assiette : le régime de base des professions
  libérales (525 points au plafond, 25 sur la seconde tranche) et la
  complémentaire agricole (100 points pour 1 820 SMIC). Restent au rendement
  instantané la CNBF, le RCI et le RAFP — pour le RCI et le RAFP faute d'un prix
  d'achat publié, pour la CNBF parce que sa fiche agrège un régime de base
  forfaitaire et un complémentaire en points qu'il faudrait scinder d'abord ;
- **montée en charge des réformes** — cinq paramètres sont désormais lus à la
  génération : durée requise, âge d'ouverture, âge d'annulation de la décote,
  coefficient de minoration et nombre d'années retenues au salaire de référence.
  Restent lus à l'année de liquidation les taux de cotisation et la montée en
  charge propre à chaque régime spécial ;
- **revalorisation des salaires portés au compte** — les coefficients annuels
  suivent désormais les salaires jusqu'en 1986 et les prix depuis 1987, comme
  l'ont fait les arrêtés. La règle des prix appliquée à toute la période
  minorait le salaire de référence des carrières commencées avant 1987 ;
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
| Avocats (CNBF) | fiche à scinder en base forfaitaire et complémentaire en points ; barème forfaitaire par tranche d'ancienneté |
| Régimes spéciaux résiduels | paramètres saisis au niveau `estimee`, à certifier auprès de chaque caisse |
| Non-salariés agricoles | barème de points du régime de base (23 à 113 points par tranche de revenu, non publié) ; points gratuits de la RCO |

Le catalogue compte **36 régimes**, actuels et disparus. Il est structurellement
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
  que `scripts/verifier_donnees.py --appliquer` COMPLÈTE au lieu de le
  remplacer : les récupérateurs sont indépendants et lents, on ne lance
  presque jamais les treize d'un coup, et réécrire le journal à partir des
  seules sources présentes ce jour-là effaçait la trace de toutes les autres.
- 166 tests couvrent le chargement, la fiabilité, la règle de certification, la
  concordance des tables de mortalité observées avec les espérances publiées, les
  propriétés du moteur et le comportement des scénarios : `python -m pytest tests`.
  Aucun test n'accède au réseau : les sources sont simulées.
