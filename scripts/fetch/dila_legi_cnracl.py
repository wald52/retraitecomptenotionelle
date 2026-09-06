#!/usr/bin/env python3
"""Contribution employeur de la CNRACL, dans le décret qui la fixe.

    python scripts/fetch/dila_legi_cnracl.py

**Ce script télécharge environ 1,1 Go et met un quart d'heure.**

À quoi elle sert. Les fiches de régime ne portent, pour les régimes publics,
que la RETENUE DE L'AGENT — 7,85 % hier, 11,10 % aujourd'hui. La contribution
de l'employeur est l'autre moitié de l'effort contributif, celle que les
scénarios 4 et 5 portent au compte notionnel : pour un agent territorial ou
hospitalier, elle vaut aujourd'hui trois fois sa retenue, et elle décide donc
de l'essentiel de ce que ces deux scénarios lui servent.

Elle venait d'OpenFisca-France, transcription plafonnée à ``haute``. Or le
*Journal officiel* la porte, et sous une forme consolidée : l'**article 5 du
décret n° 91-613 du 28 juin 1991**, dont la base LEGI garde vingt versions
datées, de 1992 à 2028 — les trois dernières étant la montée en charge décidée
en janvier 2025, que le dépôt tenait jusqu'ici pour une projection.

    « II.-Le taux de la contribution sur les traitements prévue au I de
      l'article 5 du décret du 7 février 2007 relatif à la Caisse nationale de
      retraites des agents des collectivités locales est fixé à 31,65 %. »

TROIS DIFFICULTÉS DE LECTURE

* **le I n'est pas le II.** Le même article fixe d'abord la RETENUE de l'agent
  (7,85 %, puis 11,10 %), ensuite la CONTRIBUTION de l'employeur. Seul le II est
  lu, et la lecture s'arrête à la contribution SUPPLÉMENTAIRE qui le suit — un
  prélèvement distinct, qui finance la compensation entre régimes ;
* **une version porte plusieurs taux, chacun avec sa date.** « 30,40 % pour
  l'année 2014 ; b) 30,45 % pour l'année 2015 ; c) 30,50 % à compter de l'année
  2016 » : chaque taux est daté par ce qui le SUIT immédiatement, jusqu'au taux
  d'après. Lire la date la plus proche du taux, et non la première rencontrée,
  est ce qui distingue une table juste d'une table décalée d'un cran ;
* **le décret de janvier vaut pour l'année entière.** Ces textes paraissent fin
  janvier et s'appliquent aux traitements versés depuis le 1er janvier — le
  décret du 30 janvier 2024 pour les 31,65 % de 2024, celui du 30 janvier 2025
  pour les 34,65 % de 2025. La version consolidée, elle, s'ouvre au 1er février.
  Une version qui entre en vigueur avant le 1er mars sans autre date vaut donc
  à compter du 1er janvier de son année : sans cette règle, 2024 porterait le
  taux de 2023.

L'AVANT-1993 EST DANS L'ARTICLE QU'ON MODIFIAIT, PAS DANS LES DÉCRETS PERDUS

`docs/limites.md` écrivait que ces quarante-cinq années étaient hors de portée :
« ceux d'avant sont dans les décrets que ce dernier a remplacés, et la base ne
les garde pas tous ». C'était chercher au mauvais endroit. Un décret modificatif
ne porte pas le taux, il porte un REMPLACEMENT — « le taux de 13 p. 100 est
remplacé par le taux de 11,20 p. 100 » ; le taux, lui, est dans l'article
modifié, et la base en garde les versions datées. C'est l'**article 3 du décret
n° 47-1846 du 19 septembre 1947**, qui a porté la contribution jusqu'à ce que
celle-ci passe, en octobre 1992, à « un pourcentage fixé par décret ».

**MAIS LA CONTIGUÏTÉ N'EST PAS LA COMPLÉTUDE**, et c'est la leçon de cette
lecture. Quand un décret modificatif manque à la base, la version qu'il aurait
coupée continue sans coupure : la chaîne paraît pleine et saute une valeur. La
preuve est dans la base elle-même — le décret n° 83-36 du 24 janvier 1983 y
figure et dit remplacer « 13 p. 100 », alors que la version qu'il modifie se lit
« 18 p. 100 ». Entre 1977 et 1983, un décret a fait passer le taux de 18 à 13 %
et la base ne l'a pas gardé.

Deux garde-fous en découlent, et ils ne reposent sur aucune date supposée :

* **la contradiction.** Le récupérateur lit les décrets modificatifs, compare
  l'ancien taux qu'ils nomment à celui de la version qu'ils coupent, et refuse
  toute la période d'une version que la base contredit ;
* **la longévité.** Une version qui court plus de quatre ans est refusée. Ce
  taux a bougé tous les un à trois ans sur toute la période que la base
  documente ; une version de quinze ans — celle de 1962 à 1977 — n'a pas tenu
  quinze ans, elle a avalé des décrets perdus.

Il en reste **1984 à 1988**, cinq années dont les versions sont courtes, datées
au jour et que rien ne contredit. Le reste de l'avant-1993 demeure transcrit
d'OpenFisca, au niveau ``haute`` — et l'on sait désormais non pas que la source
manque, mais que la base est trouée, et où.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

RACINE = "https://echanges.dila.gouv.fr/OPENDATA/LEGI/"
SORTIE = Path("data/brut/dila_legi_cnracl.json")

#: Le décret qui porte le taux, et l'article qui le fixe.
DECRET, ARTICLE = "91-613", "5"

#: Le décret de 1947 a porté la contribution jusqu'en octobre 1992, à son
#: article 3, avant qu'elle ne passe à « un pourcentage fixé par décret ».
DECRET_1947, ARTICLE_1947 = "47-1846", "3"

#: L'ancien taux descendait bien plus bas que le moderne : 10,20 % en 1984,
#: quand celui d'aujourd'hui dépasse 30 %. La plage de plausibilité de
#: l'article 5 l'aurait écarté sans rien dire.
TAUX_1947_PLAUSIBLE = (0.05, 0.30)

#: Une version de l'article 3 qui court plus longtemps que cela a très
#: probablement avalé un décret que la base n'a pas gardé : le taux a bougé
#: tous les un à trois ans sur toute la période que la base documente.
DUREE_SUSPECTE_ANS = 4

#: Bornes plausibles du taux employeur : il valait 21,30 % en 1992 et monte à
#: 43,65 % en 2028. Au-delà, la phrase lue parle d'autre chose.
TAUX_PLAUSIBLE = (0.15, 0.50)

#: Une version antérieure à cette date dans l'année vaut pour l'année entière.
#: Les décrets de relèvement paraissent fin janvier, avec effet au 1er janvier.
MOIS_RETROACTIF = 3

TAUX = re.compile(r"(\d{1,2},\d+)\s*(?:%|p\.\s?100)")

#: Les quatre façons dont ces textes datent un taux. On retient celle qui suit
#: le taux au plus près.
QUALIFICATIFS = (
    re.compile(r"à\s+compter\s+(?:du\s+1er\s+janvier|de\s+l['’]ann[ée]e)\s+(\d{4})", re.I),
    re.compile(r"pour\s+l['’]ann[ée]e\s+(\d{4})", re.I),
    re.compile(r"du\s+1er\s+(\w+)\s+(\d{4})\s+au\b", re.I),
    re.compile(r"du\s+1er\s+(\w+)\s+au\s+\d{1,2}\s+\w+\s+(\d{4})", re.I),
)

MOIS = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "août": 8, "aout": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
}

#: Le II commence à la contribution de l'employeur et s'arrête à la
#: contribution supplémentaire, qui est un autre prélèvement.
DEBUT_DU_II = re.compile(r"II\s*\.\s*-?\s*Le taux de la contribution")
FIN_DU_II = re.compile(r"Le taux de la contribution (supplémentaire|prévue au II)")

FILTRE = r"""
import re, sys
NUM = re.compile(r"<NUM>\s*5\s*</NUM>")
DECRET = re.compile(r"D[ée]cret n[o°]\s*91-613 du 28 juin 1991")
# L'article 3 du décret de 1947, et les décrets qui l'ont modifié : les uns
# portent le taux, les autres ce qu'ils remplacent, et il faut les deux.
# Les versions de l'article le nomment par son numéro, les décrets qui le
# modifient par sa date : « l'article 3 du décret du 19 septembre 1947 modifié
# susvisé ». Chercher le seul numéro perdait la moitié des textes, et avec elle
# le contrôle qui rend la lacune démontrable.
ANCIEN = re.compile(r"47-1846|1947-09-19|19 septembre 1947")
REMPLACE = re.compile(r"le taux de [\d,.]+ p\.? ?100 est remplac[ée]", re.I)
BALISES = re.compile(r"<[^>]+>")
tampon = ""
for bloc in iter(lambda: sys.stdin.buffer.read(1 << 20), b""):
    tampon += bloc.decode("utf-8", errors="replace")
    morceaux = tampon.split("<?xml")
    tampon = morceaux.pop()
    for morceau in morceaux:
        texte = re.sub(r"\s+", " ", BALISES.sub(" ", morceau)).strip()
        moderne = NUM.search(morceau) and DECRET.search(texte[:600])
        ancien = ANCIEN.search(texte) and (
            REMPLACE.search(texte) or re.search(r"<NUM>\s*3\s*</NUM>", morceau))
        if not (moderne or ancien):
            continue
        debut = re.search(r"<DATE_DEBUT>(.*?)</DATE_DEBUT>", morceau)
        fin = re.search(r"<DATE_FIN>(.*?)</DATE_FIN>", morceau)
        print("@@@ %s %s" % (debut.group(1) if debut else "?",
                             fin.group(1) if fin else "?"))
        print(texte[:6000])
        sys.stdout.flush()
"""


class TransfertIncomplet(RuntimeError):
    """Le dump n'a pas été téléchargé en entier."""


def dernier_dump() -> str:
    with urllib.request.urlopen(RACINE, timeout=120) as reponse:
        page = reponse.read().decode("utf-8", errors="replace")
    noms = sorted(set(re.findall(r'href="(Freemium_legi_global_[^"]+\.tar\.gz)"', page)))
    if not noms:
        raise LookupError("aucun dump global dans le répertoire LEGI de la DILA")
    return RACINE + noms[-1]


def contribution_employeur(texte: str) -> str:
    """Le II de l'article, et lui seul."""
    depart = DEBUT_DU_II.search(texte)
    if depart is None:
        return ""
    reste = texte[depart.start() + 10:]
    fin = FIN_DU_II.search(reste)
    return reste[:fin.start()] if fin else reste[:900]


def _date_du_taux(fenetre: str, defaut: date) -> date:
    """Date que porte le texte qui SUIT un taux, ou celle de la version.

    Une version qui s'ouvre avant le 1er mars sans autre date vaut à compter du
    1er janvier : ces décrets paraissent fin janvier et s'appliquent aux
    traitements versés depuis le début de l'année.
    """
    trouvees = []
    for rang, motif in enumerate(QUALIFICATIFS):
        trouve = motif.search(fenetre)
        if trouve is not None:
            trouvees.append((trouve.start(), rang, trouve))
    if not trouvees:
        return date(defaut.year, 1, 1) if defaut.month < MOIS_RETROACTIF else defaut
    _, rang, trouve = min(trouvees)
    if rang < 2:
        return date(int(trouve.group(1)), 1, 1)
    return date(int(trouve.group(2)), MOIS.get(trouve.group(1).lower(), 1), 1)


def taux_par_date(versions: list[tuple[str, str, str]]) -> dict[date, float]:
    """Taux de contribution employeur par date d'effet.

    Les versions sont lues dans l'ordre où elles entrent en vigueur : une
    rédaction plus récente qui redate un taux l'emporte sur l'ancienne, comme
    le fait le droit.
    """
    par_date: dict[date, float] = {}
    for debut, _, texte in sorted(versions):
        if DECRET not in texte[:600] and "91-613" not in texte[:600]:
            continue
        bloc = contribution_employeur(texte)
        if not bloc:
            continue
        try:
            entree = date.fromisoformat(debut)
        except ValueError:
            continue
        trouves = list(TAUX.finditer(bloc))
        for rang, trouve in enumerate(trouves):
            fin = trouves[rang + 1].start() if rang + 1 < len(trouves) else len(bloc)
            valeur = float(trouve.group(1).replace(",", ".")) / 100
            if not TAUX_PLAUSIBLE[0] <= valeur <= TAUX_PLAUSIBLE[1]:
                continue
            par_date[_date_du_taux(bloc[trouve.end():fin][:140], entree)] = valeur
    return par_date


#: « leur contribution, qui est fixée à 10,20 p. 100 des rémunérations soumises
#: à retenue » — l'article 3 du décret de 1947, dans chacune de ses versions.
TAUX_1947 = re.compile(
    r"contribution[^.]{0,80}?(?:qui est|est)?\s*fix[ée]e?\s*[àa]\s*"
    r"(\d+(?:[,.]\d+)?)\s*p\.? ?100",
    re.I)

#: « le taux de 13 p. 100 est remplacé par le taux de 11,20 p. 100 » — ce que
#: dit un décret modificatif, et ce qui permet de le confronter à la version
#: qu'il coupe.
#: L'article 3, et lui seul : le même décret en a d'autres, dont l'article 2
#: qui porte la retenue de l'agent.
ARTICLE_3 = re.compile(r"Article 3\s+(?:MODIFIE|VIGUEUR|ABROGE|PERIME)")

#: Le décret de 1947 lui-même, et non un texte qui le cite. La distinction
#: n'est pas théorique : une loi de 1957 et un décret de 2004 le citent en
#: référence, et les compter pour des versions de son article 3 ouvrait dans la
#: chaîne des ruptures qui n'existent pas. Le titre d'une version étant le
#: premier élément de son corps, on ne le cherche qu'au début.
TITRE_1947 = re.compile(r"D[ée]cret n[°o]\s*47-1846 du 19 septembre 1947")
DEBUT_DU_CORPS = 300


def _est_du_decret_de_1947(texte: str) -> bool:
    """Vrai si le texte EST une version du décret de 1947, non un texte qui le cite."""
    corps = texte.split("AUTONOME", 1)[-1]
    return bool(TITRE_1947.search(corps[:DEBUT_DU_CORPS]) and ARTICLE_3.search(texte))

REMPLACEMENT = re.compile(
    r"le taux de (\d+(?:[,.]\d+)?) p\.? ?100 est remplac[ée] par "
    r"(?:le taux de )?(\d+(?:[,.]\d+)?) p\.? ?100",
    re.I)


def _versions_de_1947(
        versions: list[tuple[str, str, str]]) -> dict[date, tuple[date, float]]:
    """Taux de l'article 3 du décret de 1947, par version datée au jour."""
    lues: dict[date, tuple[date, float]] = {}
    for debut, fin, texte in versions:
        if not _est_du_decret_de_1947(texte):
            continue
        trouve = TAUX_1947.search(texte)
        if trouve is None:
            continue
        try:
            ouverture, fermeture = date.fromisoformat(debut), date.fromisoformat(fin)
        except ValueError:
            continue
        valeur = float(trouve.group(1).replace(",", ".")) / 100
        if not TAUX_1947_PLAUSIBLE[0] <= valeur <= TAUX_1947_PLAUSIBLE[1]:
            continue
        lues[ouverture] = (fermeture, valeur)
    return lues


def _versions_contredites(
        lues: dict[date, tuple[date, float]],
        versions: list[tuple[str, str, str]]) -> tuple[set[date], list[str]]:
    """Les versions qu'un décret modificatif de la base dément.

    Un décret qui écrit « le taux de 13 p. 100 est remplacé par le taux de
    11,20 p. 100 » nomme l'ancien taux : si la version qu'il coupe ne se lit pas
    ainsi, c'est qu'un décret intermédiaire manque à la base, et toute la
    période de cette version est douteuse.
    """
    suspectes: set[date] = set()
    dits: list[str] = []
    for debut, _, texte in versions:
        modification = REMPLACEMENT.search(texte)
        if modification is None:
            continue
        try:
            prise = date.fromisoformat(debut)
        except ValueError:
            continue
        ancien = float(modification.group(1).replace(",", ".")) / 100
        precedentes = [d for d in lues if d < prise <= lues[d][0]]
        if not precedentes:
            continue
        coupee = max(precedentes)
        if abs(lues[coupee][1] - ancien) > 1e-9:
            suspectes.add(coupee)
            dits.append(
                f"version du {coupee} : elle se lit {lues[coupee][1]:.2%}, mais "
                f"un décret du {prise} dit remplacer {ancien:.2%} — un texte "
                "intermédiaire manque à la base")
    return suspectes, dits


def serie_de_1947(versions: list[tuple[str, str, str]]) -> tuple[dict[int, float],
                                                                 list[str]]:
    """Contribution employeur d'avant 1993, là où la chaîne est sûre.

    La règle du dépôt s'applique — le taux en vigueur au 1er JANVIER —, sans la
    tolérance du « décret de janvier » que les textes modernes justifient : rien
    n'assure qu'un décret de 1983 pris le 25 janvier valait pour l'année
    entière, et le supposer déplacerait 1983 de 1,3 point.

    Une année n'est rendue que si quatre conditions tiennent :

    * une version la couvre au 1er janvier ;
    * cette version n'est pas contredite par un décret modificatif de la base ;
    * elle n'a pas couru assez longtemps pour avoir avalé un texte perdu ;
    * la chaîne ne se rompt pas dans l'année — ni par un trou entre deux
      versions, ni parce qu'une version cesse de porter un taux, comme celle
      d'octobre 1992 qui renvoie à « un pourcentage fixé par décret ».
    """
    lues = _versions_de_1947(versions)
    suspectes, dits = _versions_contredites(lues, versions)
    for ouverture, (fermeture, _) in sorted(lues.items()):
        if (fermeture - ouverture).days > DUREE_SUSPECTE_ANS * 366:
            suspectes.add(ouverture)
            dits.append(f"version du {ouverture} : "
                        f"{(fermeture - ouverture).days // 365} ans sans "
                        "modification, elle a probablement avalé un décret")

    # Les ruptures de la chaîne : un trou entre deux versions, ou une version
    # qui cesse de porter un taux. L'une et l'autre interdisent l'année.
    ouvertures = sorted(lues)
    ruptures = {lues[o][0] for o in ouvertures if lues[o][0] not in lues}
    ruptures |= {d for d, _ in _bornes(versions) if d not in lues}

    serie: dict[int, float] = {}
    for annee in range(min(o.year for o in ouvertures) if ouvertures else 0,
                       (max(lues[o][0].year for o in ouvertures) + 1)
                       if ouvertures else 0):
        premier = date(annee, 1, 1)
        couvrantes = [o for o in ouvertures if o <= premier < lues[o][0]]
        if not couvrantes or couvrantes[-1] in suspectes:
            continue
        rompues = [r for r in ruptures if premier <= r < date(annee + 1, 1, 1)]
        if rompues:
            dits.append(f"{annee} : la chaîne se rompt au {min(rompues)}")
            continue
        serie[annee] = lues[couvrantes[-1]][1]
    return serie, dits


def _bornes(versions: list[tuple[str, str, str]]) -> list[tuple[date, date]]:
    """Toutes les versions datées de l'article 3, qu'elles portent un taux ou non.

    Celle d'octobre 1992 n'en porte plus : « leur contribution qui est égale à
    un pourcentage fixé par décret ». Elle marque la fin de ce que cet article
    dit, et l'année où elle s'ouvre n'est donc pas rendue.
    """
    bornes = []
    for debut, fin, texte in versions:
        if not _est_du_decret_de_1947(texte):
            continue
        try:
            bornes.append((date.fromisoformat(debut), date.fromisoformat(fin)))
        except ValueError:
            continue
    return bornes


def serie_annuelle(par_date: dict[date, float]) -> dict[int, float]:
    """Taux en vigueur au 1er janvier de chaque année, la règle du dépôt."""
    dates = sorted(par_date)
    if not dates:
        return {}
    serie: dict[int, float] = {}
    for annee in range(dates[0].year, dates[-1].year + 1):
        applicables = [d for d in dates if d <= date(annee, 1, 1)]
        if applicables:
            serie[annee] = par_date[applicables[-1]]
    return serie


def depouiller(url: str) -> list[tuple[str, str, str]]:
    lecture = subprocess.Popen(
        ["curl", "-sS", "--max-time", "7200", url], stdout=subprocess.PIPE
    )
    detar = subprocess.Popen(
        ["tar", "-xzO"], stdin=lecture.stdout, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    lecture.stdout.close()
    filtre = subprocess.Popen(
        [sys.executable, "-c", FILTRE], stdin=detar.stdout,
        stdout=subprocess.PIPE, text=True,
    )
    detar.stdout.close()
    sortie, _ = filtre.communicate()
    # Un transfert coupé ne se voit pas dans ce qui a été lu : le dépouillement
    # rend une série plus courte, et les contrôles de continuité la trouvent
    # bonne — un dump à moitié lu n'a pas de trou, il a une fin prématurée.
    # C'est arrivé, et rien ne l'avait dit.
    if lecture.wait() != 0:
        raise TransfertIncomplet(
            f"curl s'est interrompu (code {lecture.returncode}) : le dump n'a "
            "pas été lu en entier, et la série qu'on en tirerait serait muette "
            "sur ce qui manque")

    versions = []
    for bloc in sortie.split("@@@ ")[1:]:
        entete, _, corps = bloc.partition("\n")
        dates = (entete.strip().split() + ["?", "?"])[:2]
        versions.append((dates[0], dates[1], corps))
    return versions


def main() -> int:
    try:
        url = dernier_dump()
    except (urllib.error.HTTPError, urllib.error.URLError, LookupError) as erreur:
        print(f"ÉCHEC   répertoire LEGI : {erreur}", file=sys.stderr)
        return 1

    print(f"Dump      {url.rsplit('/', 1)[-1]}")
    print("Lecture en flux d'environ 9 Go décompressés : comptez un quart d'heure.\n")
    try:
        versions = depouiller(url)
    except TransfertIncomplet as erreur:
        print(f"ÉCHEC   {erreur}", file=sys.stderr)
        return 1
    par_date = taux_par_date(versions)
    serie = serie_annuelle(par_date)
    if not serie:
        print(f"ÉCHEC   aucune version de l'article {ARTICLE} du décret {DECRET} lue",
              file=sys.stderr)
        return 1

    annees = sorted(serie)
    for precedente, courante in zip(annees, annees[1:]):
        if serie[courante] < serie[precedente]:
            print(f"ÉCHEC   le taux recule de {precedente} à {courante} : "
                  f"{serie[precedente]:.2%} puis {serie[courante]:.2%}",
                  file=sys.stderr)
            return 1

    # L'avant-1993, dans l'article que les décrets perdus modifiaient. Ce qui
    # est écarté l'est pour une raison écrite, et la raison est imprimée.
    ancienne, dits = serie_de_1947(versions)
    for dit in dits:
        print(f"ÉCARTÉ  {dit}")
    for annee in sorted(ancienne):
        if annee in serie:
            print(f"ÉCHEC   {annee} : les deux décrets la portent", file=sys.stderr)
            return 1
    serie.update(ancienne)
    annees = sorted(serie)

    for annee in annees:
        print(f"OK      {annee} : contribution employeur {serie[annee]:.2%}")

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(
        json.dumps({
            "source": url,
            "article": f"décret n° {DECRET} du 28 juin 1991, article {ARTICLE}, II ; "
                       f"décret n° {DECRET_1947} du 19 septembre 1947, "
                       f"article {ARTICLE_1947}",
            "recupere_le": date.today().isoformat(),
            "versions_lues": len(versions),
            "note": "taux de la contribution employeur due à la CNRACL, en vigueur "
                    "au 1er janvier de l'année. Le I du même article porte la "
                    "retenue de l'agent et la contribution supplémentaire qui suit "
                    "le II est un autre prélèvement : ni l'un ni l'autre n'est lu. "
                    "Les années d'avant 1993 viennent de l'article 3 du décret de "
                    "1947, celui que les décrets abrogés modifiaient — et seules "
                    "celles dont la version est courte et que rien dans la base ne "
                    "contredit : une version qui a avalé un décret perdu court "
                    "sans coupure et fait paraître pleine une chaîne trouée. Le "
                    "reste demeure transcrit d'OpenFisca.",
            "serie": {str(annee): valeur for annee, valeur in sorted(serie.items())},
        }, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"\n{len(versions)} versions lues, {len(serie)} années écrites dans {SORTIE}")
    print(f"Couverture {annees[0]}-{annees[-1]} ; "
          f"{serie[annees[0]]:.2%} puis {serie[annees[-1]]:.2%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
