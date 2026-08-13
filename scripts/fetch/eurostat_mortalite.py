#!/usr/bin/env python3
"""Récupération des données de mortalité françaises auprès d'Eurostat.

    python scripts/fetch/eurostat_mortalite.py

Deux jeux, deux usages :

* ``demo_mlexpec`` — espérance de vie à 60 et 65 ans. Sert de **contrôle
  croisé** : l'espérance à 65 ans vient de l'OCDE, qui couvre 1960-2024 là où
  Eurostat s'arrête à 1986 (voir scripts/fetch/oecd_esperance_vie.py). Les deux
  sources doivent coïncider, puisque toutes deux reprennent les chiffres INSEE.

* ``demo_mlifetable`` — **quotients de mortalité par âge**, c'est-à-dire les
  vraies tables du moment. C'est ce que le modèle préfère à sa calibration
  paramétrique dès qu'elles sont disponibles : déposées dans
  ``data/reference/mortalite/quotients_periode.csv``, elles priment sur la loi
  de Gompertz-Makeham sans qu'aucune ligne du moteur ne change.

Deux territoires sont demandés, et leur ordre de priorité est délibéré :

* ``FX`` — France métropolitaine, 1986-2012, sur le même champ que les séries
  INSEE du modèle ;
* ``FR`` — France y compris départements d'outre-mer, 1998-2024, qui prolonge.

Avant 1986, Eurostat ne publie rien pour la France : ni l'espérance à 65 ans ni
les quotients par âge. Les tables TD/TV de l'INSEE, seules à remonter plus haut,
ne sont diffusées qu'en tableurs. Voir docs/limites.md §1.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

RACINE_API = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
TERRITOIRES = ("FX", "FR")  # ordre de priorité croissante : FR écrase FX
SEXES = {"M": "H", "F": "F"}

ESPERANCES = f"{RACINE_API}/demo_mlexpec?format=JSON&age=Y60&age=Y65&sex=M&sex=F&unit=YR"
QUOTIENTS = f"{RACINE_API}/demo_mlifetable?format=JSON&sex=M&sex=F&indic_de=PROBDEATH"

SORTIE_ESPERANCES = Path("data/brut/eurostat_esperance_vie.json")
SORTIE_QUOTIENTS = Path("data/brut/eurostat_quotients.json")


def _telecharger(url: str) -> dict:
    demande = urllib.request.Request(
        url, headers={"User-Agent": "retraite-notionnelle/0.1"}
    )
    with urllib.request.urlopen(demande, timeout=300) as reponse:
        return json.loads(reponse.read())


def _coordonnees(charge: dict):
    """Itère sur les valeurs d'une réponse JSON-stat, coordonnées décodées.

    Eurostat renvoie un tableau creux : la position d'une valeur encode les
    coordonnées de toutes les dimensions, de la plus lente à la plus rapide.
    """
    dimensions = charge["id"]
    tailles = charge["size"]
    index = {
        nom: {rang: code
              for code, rang in charge["dimension"][nom]["category"]["index"].items()}
        for nom in dimensions
    }
    for position, valeur in charge["value"].items():
        if valeur is None:
            continue
        reste = int(position)
        point = {}
        for rang in reversed(range(len(dimensions))):
            nom = dimensions[rang]
            point[nom] = index[nom][reste % tailles[rang]]
            reste //= tailles[rang]
        yield point, float(valeur)


def _age_numerique(code: str) -> int | None:
    """Traduit un code d'âge Eurostat en âge entier.

    Les classes ouvertes (``Y_GE85``, ``Y_GE95``) sont écartées : elles ne sont
    pas un quotient à un âge donné, et le modèle doit continuer à traiter la
    queue de table par sa loi paramétrique plutôt que par une valeur agrégée.
    """
    if code == "Y_LT1":
        return 0
    if code.startswith("Y") and code[1:].isdigit():
        return int(code[1:])
    return None


def esperances() -> dict[str, float]:
    serie: dict[str, float] = {}
    for territoire in TERRITOIRES:
        valeurs = {}
        for point, valeur in _coordonnees(_telecharger(f"{ESPERANCES}&geo={territoire}")):
            sexe = SEXES.get(point["sex"])
            if sexe is None:
                continue
            mesure = "e" + point["age"].removeprefix("Y")
            valeurs[f"{point['time']}|{sexe}|{mesure}"] = valeur
        serie.update(valeurs)
        print(f"OK      espérances {territoire} : {len(valeurs)} valeurs")
    return serie


def quotients() -> dict[str, float]:
    serie: dict[str, float] = {}
    for territoire in TERRITOIRES:
        valeurs = {}
        for point, valeur in _coordonnees(_telecharger(f"{QUOTIENTS}&geo={territoire}")):
            sexe = SEXES.get(point["sex"])
            age = _age_numerique(point["age"])
            if sexe is None or age is None:
                continue
            valeurs[f"{point['time']}|{sexe}|{age}"] = valeur
        serie.update(valeurs)
        print(f"OK      quotients {territoire} : {len(valeurs)} valeurs")
    return serie


def _ecrire(chemin: Path, url: str, serie: dict[str, float]) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(
        json.dumps({"source": url, "territoires": list(TERRITOIRES),
                    "serie": dict(sorted(serie.items()))},
                   ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    annees = sorted({int(cle.split("|")[0]) for cle in serie})
    couverture = f"{annees[0]}-{annees[-1]}" if annees else "vide"
    print(f"        {len(serie)} valeurs écrites dans {chemin} ({couverture})")


def main() -> int:
    try:
        _ecrire(SORTIE_ESPERANCES, ESPERANCES, esperances())
        _ecrire(SORTIE_QUOTIENTS, QUOTIENTS, quotients())
    except (urllib.error.HTTPError, urllib.error.URLError) as erreur:
        print(f"Eurostat indisponible : {erreur}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
