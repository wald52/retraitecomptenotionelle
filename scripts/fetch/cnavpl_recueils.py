#!/usr/bin/env python3
"""Récupération de la valeur du point des professions libérales, chez la CNAVPL.

    python scripts/fetch/cnavpl_recueils.py

Aucune base ne porte cette valeur, et ce n'est pas faute d'avoir cherché : deux
dépouillements de la législation consolidée et deux du *Journal officiel* — 34
gigaoctets au total — n'en trouvent aucune trace. L'explication tient à la
mécanique du régime : le décret annuel fixe un **coefficient de revalorisation**,
pas un montant, et la valeur qui en résulte n'est publiée que par la caisse.

Elle l'est dans son **recueil statistique**, un annuaire d'une soixantaine de
pages paru chaque année, sous une phrase invariable :

    « La valeur du point est fixée à 0,6540 au 1er janvier 2025. »

Le même recueil donne la règle d'acquisition, qui est ce dont un modèle en
points a besoin pour convertir une cotisation en droits :

* la cotisation est proportionnelle au revenu, sur deux tranches — T1 de 0 à un
  plafond de la Sécurité sociale, T2 de 0 à cinq plafonds ;
* le taux de T1 et celui de T2 sont donnés en toutes lettres ;
* **525 points** au maximum sur T1, **25** sur T2, soit 550 — depuis 2015, et
  c'est la seule des cinq grandeurs que ce script ne lit pas : elle n'apparaît
  que dans un tableau dont la mise en page ne se laisse pas relire de façon
  sûre. Elle figure en commentaire du fichier de référence, avec sa source.

Le prix d'achat d'un point de T1 s'en déduit — taux × plafond ÷ 525 — mais ce
calcul appartient au moteur, pas au récupérateur : on ne verse ici que ce que la
caisse écrit.

Les recueils antérieurs à 2021 emploient une autre mise en page, où la valeur
n'est plus dans une phrase mais dans un graphique. La série commence donc en
2021.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lecture_pdf import _flux, _hexa, _litteral, _objets, _polices, JETONS  # noqa: E402

RACINE = "https://www.cnavpl.fr/documents"

#: Les recueils statistiques mis en ligne, avec l'identifiant de téléchargement
#: que le gestionnaire de documents du site attribue à chacun.
RECUEILS = {
    2021: "recueil-statistique-2021/?wpdmdl=263987",
    2022: "recueil-statistique-2022/?wpdmdl=300287",
    2023: "recueil-statistique-2023/?wpdmdl=300881",
    2024: "recueil-statistique-2024/?wpdmdl=301244",
    2025: "recueil-statistique-2025/?wpdmdl=301471",
}

# Les accents disparaissent dans certains millésimes, où la police n'expose pas
# de table ToUnicode complète : les motifs les rendent facultatifs.
VALEUR = re.compile(r"valeurdupointestfix[ée]{0,2}e?à?(\d+[,.]\d+)")
TAUX = re.compile(
    r"[Ll]etauxdelapremi[èe]retrancheestde(\d+[,.]\d+)%,"
    r"celuidelasecondetrancheestde(\d+[,.]\d+)%"
)
SORTIE = Path("data/brut/cnavpl_recueils.json")


def texte_colle(octets: bytes) -> str:
    """Tout le texte du document, espaces ôtés.

    Le recueil est un annuaire mis en pages sur plusieurs colonnes, avec des
    graphiques : reconstituer ses lignes n'a pas de sens. Seules comptent ici
    deux phrases, qu'on retrouve en collant le texte et en cherchant dedans.
    """
    tables = _polices(octets)
    morceaux: list[str] = []
    for objet in _objets(octets).values():
        contenu = _flux(objet)
        if not contenu or (b"Tj" not in contenu and b"TJ" not in contenu):
            continue
        police = None
        for jeton in JETONS.finditer(contenu):
            if jeton.group("tf"):
                police = jeton.group(9)
            elif jeton.group("hex"):
                morceaux.append(_hexa(jeton.group("hex"), tables.get(police)))
            elif jeton.group("txt"):
                morceaux.append(_litteral(jeton.group("txt")[1:-1]))
    return re.sub(r"\s+", "", "".join(morceaux))


def _nombre(texte: str) -> float:
    return float(texte.replace(",", "."))


def main() -> int:
    serie: dict[str, float] = {}
    valeurs: dict[int, float] = {}
    for annee, chemin in sorted(RECUEILS.items()):
        url = f"{RACINE}/{chemin}"
        try:
            demande = urllib.request.Request(
                url, headers={"User-Agent": "retraite-notionnelle/0.1"}
            )
            with urllib.request.urlopen(demande, timeout=300) as reponse:
                octets = reponse.read()
        except (urllib.error.HTTPError, urllib.error.URLError) as erreur:
            print(f"ÉCHEC   recueil {annee} : {erreur}", file=sys.stderr)
            return 1

        texte = texte_colle(octets)
        point, taux = VALEUR.search(texte), TAUX.search(texte)
        if not point:
            print(f"IGNORÉ  recueil {annee} : la phrase attendue est absente")
            continue
        valeurs[annee] = _nombre(point.group(1))
        serie[f"cnavpl|{annee}|valeur_service"] = valeurs[annee]
        detail = ""
        if taux:
            serie[f"cnavpl|{annee}|taux_t1"] = _nombre(taux.group(1)) / 100
            serie[f"cnavpl|{annee}|taux_t2"] = _nombre(taux.group(2)) / 100
            detail = f", tranches {taux.group(1)} % et {taux.group(2)} %"
        print(f"OK      {annee} : valeur du point {valeurs[annee]} €{detail}")

    croissantes = sorted(valeurs)
    for precedente, courante in zip(croissantes, croissantes[1:]):
        if valeurs[courante] <= valeurs[precedente]:
            print(f"\nSérie incohérente, rien n'est écrit : la valeur du point recule "
                  f"de {precedente} ({valeurs[precedente]}) à {courante} "
                  f"({valeurs[courante]})", file=sys.stderr)
            return 1

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(
        json.dumps({
            "source": RACINE,
            "recupere_le": date.today().isoformat(),
            "recueils": {str(a): f"{RACINE}/{c}" for a, c in sorted(RECUEILS.items())},
            "note": "régime de base des professions libérales, en points depuis 2004 ; "
                    "525 points au maximum sur T1 et 25 sur T2, non relus par ce "
                    "script (tableau non relisible de façon sûre)",
            "serie": dict(sorted(serie.items())),
        }, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"\n{len(serie)} valeurs écrites dans {SORTIE}")
    print(f"Couverture {croissantes[0]}-{croissantes[-1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
