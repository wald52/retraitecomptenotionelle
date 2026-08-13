#!/usr/bin/env python3
"""Récupération des valeurs d'achat et de service du point, depuis 1947.

    python scripts/fetch/openfisca_points.py

C'était la dernière grande lacune du modèle. Le scénario « système actuel »
reconstituait la retraite complémentaire à partir d'un **rendement instantané**
saisi à la louche, faute d'avoir l'historique des valeurs du point. Cet
historique existe : il est transcrit, daté circulaire par circulaire, dans
**OpenFisca-France-Pension**, le modèle de retraites de l'administration
française — l'AGIRC depuis avril 1947, l'Ircantec et ses prédécesseurs depuis
1925, l'UNIRS depuis 1949.

Deux grandeurs par régime et par année, plus une troisième :

* **salaire de référence** — le prix d'achat du point : la cotisation divisée
  par lui donne le nombre de points acquis dans l'année ;
* **valeur de service** — ce que rapporte un point de rente annuelle ;
* **taux d'appel** — l'écart entre ce qui est prélevé et ce qui ouvre des
  droits. Depuis 1995, cotiser 125 € n'acquiert que 100 € de points ; c'est un
  prélèvement de solidarité qui ne se voit nulle part ailleurs.

Le rendement instantané que le modèle utilisait n'est donc que le rapport
``valeur_service / (taux_appel × salaire_reference)``. Le calculer plutôt que
l'estimer suffit à corriger la série ; accumuler les points année par année, ce
que fait désormais le moteur, supprime l'approximation.

Arrco avant 1999 — une substitution documentée. Le point Arrco n'a été unifié
qu'en 1999 : avant, chaque caisse adhérente avait le sien. Les valeurs retenues
ici pour 1957-1998 sont celles de l'**UNIRS**, la plus grosse d'entre elles et
celle qu'OpenFisca donne en exemple. Ces lignes portent le niveau ``moyenne``,
et non ``haute`` : ce sont bien des valeurs publiées, mais pas exactement celles
du régime que le modèle appelle « arrco ».

Statut de fiabilité. OpenFisca est une transcription tierce, pas le producteur :
ces valeurs plafonnent au niveau ``haute``. Elles sont recoupées à chaque
exécution de ``scripts/verifier_donnees.py`` contre le repère certifiable que
l'Agirc-Arrco publie pour l'année en cours.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

PENSION = ("https://raw.githubusercontent.com/openfisca/openfisca-france-pension/"
           "master/openfisca_france_pension/parameters/retraites")
FRANCE = ("https://raw.githubusercontent.com/openfisca/openfisca-france/"
          "master/openfisca_france/parameters/prelevements_sociaux")

#: Où trouver chaque grandeur, régime par régime.
#:
#: ``cle`` désigne la sous-section du fichier YAML quand il y en a plusieurs
#: (valeur en euros / valeur en nominal) ; ``None`` quand le fichier porte
#: directement ses valeurs.
SOURCES: dict[str, dict[str, tuple[str, str | None]]] = {
    "agirc": {
        "salaire_reference": (
            f"{PENSION}/secteur_prive/regimes_complementaires/agirc/salaire_de_reference.yaml",
            "salaire_reference_en_euros"),
        "valeur_service": (
            f"{PENSION}/secteur_prive/regimes_complementaires/agirc/point.yaml",
            "valeur_point_en_euros"),
        "taux_appel": (
            f"{FRANCE}/regimes_complementaires_retraite_secteur_prive/agirc/taux_appel.yaml",
            None),
    },
    "arrco": {
        "salaire_reference": (
            f"{PENSION}/secteur_prive/regimes_complementaires/arrco/salaire_de_reference.yaml",
            "salaire_reference_en_euros"),
        "valeur_service": (
            f"{PENSION}/secteur_prive/regimes_complementaires/arrco/point.yaml",
            "valeur_point_en_euros"),
        "taux_appel": (
            f"{FRANCE}/regimes_complementaires_retraite_secteur_prive/arrco/taux_appel.yaml",
            None),
    },
    # Complète « arrco » avant l'unification du point de 1999.
    "unirs": {
        "salaire_reference": (
            f"{PENSION}/secteur_prive/regimes_complementaires/unirs/salaire_de_reference.yaml",
            "salaire_reference_en_euros"),
        "valeur_service": (
            f"{PENSION}/secteur_prive/regimes_complementaires/unirs/point.yaml",
            "valeur_point_en_euros"),
    },
    "agirc_arrco": {
        "salaire_reference": (
            f"{PENSION}/secteur_prive/regimes_complementaires/agirc_arrco/salaire_de_reference.yaml",
            "salaire_reference_prix_achat_valeur_nominale"),
        "valeur_service": (
            f"{PENSION}/secteur_prive/regimes_complementaires/agirc_arrco/point.yaml",
            "valeur_point_en_euros"),
    },
    "ircantec": {
        "salaire_reference": (
            f"{PENSION}/secteur_public/regimes_complementaires/ircantec/salaire_de_reference/"
            "salaire_reference_ircantec.yaml", None),
        "valeur_service": (
            f"{PENSION}/secteur_public/regimes_complementaires/ircantec/valeur_du_point.yaml",
            None),
        "taux_appel": (f"{FRANCE}/cotisations_secteur_public/ircantec/taux_appel.yaml",
                       None),
    },
    "rafp": {
        "salaire_reference": (
            f"{PENSION}/secteur_public/regimes_complementaires/rafp/"
            "valeur_acquisition_point_rafp.yaml", None),
        "valeur_service": (
            f"{PENSION}/secteur_public/regimes_complementaires/rafp/"
            "valeur_service_point_rafp.yaml", None),
    },
    # Régime complémentaire des indépendants, créé en 2013 par fusion des
    # régimes complémentaires des artisans et des commerçants.
    "rci": {
        "salaire_reference": (f"{PENSION}/independants/salref_rci.yaml", None),
        "valeur_service": (
            f"{PENSION}/independants/pt_rci/valeur_point_rci_date.yaml", None),
    },
    "ipacte": {
        "salaire_reference": (
            f"{PENSION}/secteur_public/regimes_complementaires/ircantec/salaire_de_reference/"
            "salaire_reference_ipacte.yaml", None),
        "valeur_service": (
            f"{PENSION}/secteur_public/regimes_complementaires/ircantec/valeur_du_point.yaml",
            None),
    },
    "igrante": {
        "salaire_reference": (
            f"{PENSION}/secteur_public/regimes_complementaires/ircantec/salaire_de_reference/"
            "salaire_reference_igrante.yaml", None),
        "valeur_service": (
            f"{PENSION}/secteur_public/regimes_complementaires/ircantec/valeur_du_point.yaml",
            None),
    },
}

#: Régimes dont le point prolonge celui d'un autre, avec l'année de bascule.
#: L'UNIRS n'est pas « arrco », mais c'est la caisse dont le point a servi de
#: référence avant l'unification de 1999 : ses valeurs comblent 1957-1998.
SUBSTITUTIONS = {"arrco": ("unirs", 1999)}

#: Ce qu'OpenFisca ne porte pas, et qui vient directement du texte.
#:
#: Le taux d'appel Agirc-Arrco est fixé à 127 % par l'accord national
#: interprofessionnel du 17 novembre 2017 : cotiser 7,87 % sur la tranche 1
#: n'ouvre des droits que sur 6,20 %. Une seule valeur, stable depuis 2019.
COMPLEMENTS = {
    "agirc_arrco|2019|taux_appel": 1.27,
}
ORIGINE_COMPLEMENTS = ("Accord national interprofessionnel du 17 novembre 2017, "
                       "article 3 (taux d'appel de 127 %)")

SORTIE = Path("data/brut/openfisca_points.json")
PREMIERE_ANNEE = 1947


def _valeurs(url: str, cle: str | None) -> dict[str, float]:
    """Lit un fichier de paramètres OpenFisca : date d'effet -> valeur."""
    import yaml

    demande = urllib.request.Request(
        url, headers={"User-Agent": "retraite-notionnelle/0.1"}
    )
    with urllib.request.urlopen(demande, timeout=120) as reponse:
        charge = yaml.safe_load(reponse.read().decode("utf-8"))
    noeud = charge if cle is None else charge[cle]
    return {
        str(date_effet): float(contenu["value"])
        for date_effet, contenu in noeud["values"].items()
        if (contenu or {}).get("value") is not None
    }


def _annualiser(bareme: dict[str, float]) -> dict[int, float]:
    """Valeur en vigueur au 31 décembre de chaque année.

    Le salaire de référence change au 1er janvier, la valeur de service au 1er
    avril autrefois, au 1er novembre aujourd'hui. Retenir la dernière valeur
    entrée en vigueur dans l'année, c'est prendre « la valeur du point de
    l'année N » au sens où les circulaires l'entendent, sans avoir à traiter
    différemment les deux calendriers.
    """
    dates = sorted(bareme)
    if not dates:
        return {}
    resultat = {}
    # Borné à la dernière année publiée, jamais prolongé : un régime fermé
    # cesse d'avoir une valeur du point, et c'est cette fin qui déclenche la
    # conversion de ses points dans son successeur.
    for annee in range(int(dates[0][:4]), int(dates[-1][:4]) + 1):
        applicables = [d for d in dates if d[:4] <= str(annee)]
        if applicables:
            resultat[annee] = bareme[applicables[-1]]
    return resultat


def main() -> int:
    brut: dict[str, dict[str, dict[int, float]]] = {}
    for regime, grandeurs in SOURCES.items():
        brut[regime] = {}
        for grandeur, (url, cle) in grandeurs.items():
            try:
                brut[regime][grandeur] = _annualiser(_valeurs(url, cle))
            except (urllib.error.HTTPError, urllib.error.URLError) as erreur:
                print(f"ÉCHEC   {regime}/{grandeur} : {erreur}", file=sys.stderr)
                return 1
        couvertures = {g: len(v) for g, v in brut[regime].items()}
        print(f"OK      {regime:<14} {couvertures}")

    # Substitution : l'UNIRS comble l'Arrco avant l'unification du point.
    for cible, (remplacant, bascule) in SUBSTITUTIONS.items():
        for grandeur, valeurs in brut.get(remplacant, {}).items():
            amont = {a: v for a, v in valeurs.items() if a < bascule}
            brut[cible][grandeur] = {**amont, **brut[cible].get(grandeur, {})}
            print(f"        {cible}/{grandeur} complété par {remplacant} "
                  f"sur {min(amont, default='-')}-{bascule - 1}")

    serie: dict[str, float] = {}
    substitues: list[str] = []
    for regime, grandeurs in brut.items():
        for grandeur, valeurs in grandeurs.items():
            for annee, valeur in sorted(valeurs.items()):
                if annee < PREMIERE_ANNEE:
                    continue
                serie[f"{regime}|{annee}|{grandeur}"] = round(valeur, 6)
    for cible, (remplacant, bascule) in SUBSTITUTIONS.items():
        substitues = [cle for cle in serie
                      if cle.startswith(f"{cible}|") and int(cle.split("|")[1]) < bascule]

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(
        json.dumps({
            "source": PENSION,
            "recupere_le": date.today().isoformat(),
            "regle_annuelle": "valeur en vigueur au 31 décembre de l'année",
            "substitutions": {c: {"par": r, "jusqu_a": b - 1}
                              for c, (r, b) in SUBSTITUTIONS.items()},
            "cles_substituees": sorted(substitues),
            "origine_complements": ORIGINE_COMPLEMENTS,
            "complements": COMPLEMENTS,
            "serie": dict(sorted(serie.items())),
        }, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"\n{len(serie)} valeurs écrites dans {SORTIE}")
    print(f"{len(substitues)} d'entre elles substituées depuis l'UNIRS")
    print(f"{len(COMPLEMENTS)} complément(s) saisi(s) depuis le texte")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
