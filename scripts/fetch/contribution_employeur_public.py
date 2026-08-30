#!/usr/bin/env python3
"""Récupération de la contribution EMPLOYEUR des régimes publics.

    python scripts/fetch/contribution_employeur_public.py

Le modèle ne stocke, pour la fonction publique et les régimes spéciaux, que la
retenue de l'agent : 7,85 % hier, 11,10 % aujourd'hui. La part de l'employeur y
manquait, et le dépôt affirmait qu'elle ne pouvait pas y figurer — que rien
n'existait avant la création du compte d'affectation spéciale « Pensions » en
2006. C'est faux pour deux des trois grands régimes concernés, et à moitié faux
pour le troisième.

Quatre séries sont récupérées ici, de trois natures différentes.

**État, taux explicite, depuis 2006** — le taux de contribution employeur des
pensions civiles, fixé décret par décret depuis la LOLF. Le Service des
retraites de l'État, qui appelle la cotisation, en publie l'historique complet
dans une fiche PDF. C'est le producteur : cette série est certifiable.

**État, taux implicite, 1995-2005** — avant 2006 il n'y avait pas de taux : les
pensions étaient payées sur crédits budgétaires. Mais l'annexe « pensions » au
projet de loi de finances pour 2011 en a RECONSTITUÉ un a posteriori, en
simulant le compte du régime, et publie la série depuis 1995 (tableau p. 26).
OpenFisca-France la transcrit. Reconstitution d'une part, transcription tierce
de l'autre : elle ne dépasse pas le niveau `haute`, et son périmètre est moins
complet que celui du CAS — la rupture 1995-2005 → 2006 ne mesure donc pas une
vraie chute du coût des droits.

**CNRACL, taux réel, depuis 1948** — la fonction publique territoriale et
hospitalière n'a jamais eu ce problème : la CNRACL est une caisse, ses employeurs
lui versent une cotisation, et son taux est fixé par décret depuis 1947.

**SNCF, taux réel, 2007-2018** — la contribution de l'entreprise a deux
composantes, fixées par arrêté annuel : T1, calée sur ce que coûteraient les
mêmes salariés au régime général et à l'Arrco-Agirc, et T2, qui finance les
droits spécifiques du régime et son déséquilibre démographique. La somme des
deux est ce que l'employeur verse ; leur SÉPARATION est exactement la
distinction que les scénarios 4 et 5 du modèle mettent en jeu.

Convention annuelle : **le taux en vigueur au 1er janvier**, comme pour toutes
les autres séries de taux du dépôt (cf. ``openfisca_cotisations.py``). Une
modification en cours d'année ne prend donc effet qu'au 1er janvier suivant.
Deux abattements d'un mois y échappent volontairement — décembre 2009 et
décembre 2013, où le taux de l'État est tombé à 40,14 % et 44,28 % pour solder
l'exercice : ce sont des régularisations de trésorerie, pas des taux d'appel.
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

from lecture_pdf import lignes_pdf  # noqa: E402

SORTIE = Path("data/brut/contribution_employeur_public.json")

#: Fiche du Service des retraites de l'État : l'historique des taux appelés,
#: employeur par employeur, du 1er janvier 2006 à aujourd'hui.
URL_SRE = ("https://retraitesdeletat.gouv.fr/files/files/Professionnels/CAS/"
           "Fiches/Historique%20taux%20cotisations.pdf")

RACINE_OPENFISCA = (
    "https://raw.githubusercontent.com/openfisca/openfisca-france/master/"
    "openfisca_france/parameters/prelevements_sociaux/cotisations_secteur_public"
)

#: Paramètres OpenFisca à charger : nom -> (chemin, forme du fichier).
#: ``valeurs`` = fichier ``values:`` ; ``bareme`` = fichier ``brackets:``.
PARAMETRES_OPENFISCA = {
    "implicite_etat": ("retraite/taux_implicite.yaml", "valeurs"),
    "cnracl": ("cnracl/employeur/cnracl.yaml", "bareme"),
    "sncf_t1": ("sncf/regime_de_retraite/cotisations_employeur/t1.yaml", "valeurs"),
    "sncf_t2": ("sncf/regime_de_retraite/cotisations_employeur/t2.yaml", "valeurs"),
}

#: Première année du CAS « Pensions » : avant elle, le taux de l'État est
#: reconstitué et non appelé.
PREMIERE_ANNEE_CAS = 2006


# -- lecture des paramètres OpenFisca ---------------------------------------


def _telecharger(url: str) -> bytes:
    demande = urllib.request.Request(
        url, headers={"User-Agent": "retraite-notionnelle/0.1"}
    )
    with urllib.request.urlopen(demande, timeout=120) as reponse:
        return reponse.read()


def _dates_valeurs(texte: str, forme: str) -> dict[str, float]:
    """Table date d'effet -> taux, quelle que soit la forme du fichier.

    Une valeur ``null`` signifie « le paramètre cesse d'exister » : la date est
    conservée avec la valeur ``None`` pour que la série s'arrête là, au lieu de
    prolonger indéfiniment le dernier taux connu.
    """
    import yaml

    charge = yaml.safe_load(texte)
    brut = charge["brackets"][0]["rate"] if forme == "bareme" else charge["values"]
    table: dict[str, float | None] = {}
    for cle, contenu in brut.items():
        valeur = (contenu or {}).get("value")
        table[str(cle)] = None if valeur is None else float(valeur)
    return table


def _en_vigueur(table: dict[str, float | None], annee: int) -> float | None:
    """Taux applicable au 1er janvier de l'année, ``None`` si le paramètre est
    éteint ou pas encore né."""
    anterieures = [cle for cle in sorted(table) if cle[:10] <= f"{annee}-01-01"]
    return table[anterieures[-1]] if anterieures else None


def _serie_annuelle(table: dict[str, float | None]) -> dict[str, float]:
    premiere = min(int(cle[:4]) for cle in table)
    derniere = max(int(cle[:4]) for cle in table)
    serie = {}
    for annee in range(premiere, derniere + 1):
        taux = _en_vigueur(table, annee)
        if taux is not None:
            serie[str(annee)] = round(taux, 6)
    return serie


# -- lecture de la fiche du Service des retraites de l'État ------------------

LIGNE_SRE = re.compile(r"^(\d\d)/(\d\d)/(\d{4})((?:\d+,\d+%){4,})")
POURCENTAGE = re.compile(r"(\d+),(\d+)%")


def _taux_explicites(pdf: bytes) -> dict[str, float]:
    """Taux de contribution employeur de l'État pour un agent CIVIL, par année.

    La fiche est un tableau à quatorze colonnes, une par situation d'emploi.
    Les quatre premières décrivent l'employeur État : retenue de l'agent,
    contribution employeur d'un agent civil, contribution d'un militaire,
    contribution ATI. C'est la deuxième qui nous intéresse — les militaires ont
    leur propre taux, plus du double, et le modèle ne distingue pas les corps.

    Seules les lignes datées du 1er janvier sont retenues : les deux lignes de
    décembre sont des abattements de fin d'exercice, pas des taux d'appel.
    """
    serie: dict[str, float] = {}
    for ligne in lignes_pdf(pdf):
        trouve = LIGNE_SRE.match(ligne.replace(" ", ""))
        if not trouve:
            continue
        jour, mois, annee = trouve.group(1), trouve.group(2), trouve.group(3)
        if (jour, mois) != ("01", "01"):
            continue
        taux = [float(f"{e}.{d}") / 100.0 for e, d in POURCENTAGE.findall(trouve.group(4))]
        serie[annee] = round(taux[1], 6)
    return serie


# -- assemblage --------------------------------------------------------------


def main() -> int:
    try:
        pdf = _telecharger(URL_SRE)
    except (urllib.error.HTTPError, urllib.error.URLError) as erreur:
        print(f"ÉCHEC   fiche SRE : {erreur}", file=sys.stderr)
        return 1
    explicite = _taux_explicites(pdf)
    if len(explicite) < 15:
        print(f"ÉCHEC   fiche SRE : {len(explicite)} années lues, "
              "la mise en page a dû changer", file=sys.stderr)
        return 1
    print(f"OK      explicite_etat          {len(explicite)} années "
          f"({min(explicite)}-{max(explicite)}), source SRE")

    tables: dict[str, dict[str, float | None]] = {}
    for nom, (chemin, forme) in PARAMETRES_OPENFISCA.items():
        try:
            texte = _telecharger(f"{RACINE_OPENFISCA}/{chemin}").decode("utf-8")
        except (urllib.error.HTTPError, urllib.error.URLError) as erreur:
            print(f"ÉCHEC   {nom} : {erreur}", file=sys.stderr)
            return 1
        tables[nom] = _dates_valeurs(texte, forme)
        print(f"OK      {nom:<24} {len(tables[nom])} dates d'effet, source OpenFisca")

    series = {nom: _serie_annuelle(table) for nom, table in tables.items()}

    # L'État : le taux implicite s'arrête où le taux appelé commence.
    implicite = {a: t for a, t in series["implicite_etat"].items()
                 if int(a) < PREMIERE_ANNEE_CAS}

    # La SNCF : T1 + T2, et seulement les années où les deux sont publiés.
    sncf = {
        annee: round(taux + series["sncf_t2"][annee], 6)
        for annee, taux in series["sncf_t1"].items()
        if annee in series["sncf_t2"]
    }

    # Recoupement : sur 2006-2025, la transcription OpenFisca des décrets doit
    # dire la même chose que la fiche du producteur. Un écart signale que l'une
    # des deux lectures est fausse, et il vaut mieux le savoir tout de suite.
    ecarts = []
    try:
        civils = _serie_annuelle(_dates_valeurs(
            _telecharger(
                f"{RACINE_OPENFISCA}/retraite/pension/employeur/civils/pension.yaml"
            ).decode("utf-8"), "bareme"))
    except (urllib.error.HTTPError, urllib.error.URLError):
        civils = {}
    for annee, taux in sorted(civils.items()):
        if annee in explicite and abs(explicite[annee] - taux) > 1e-6:
            ecarts.append(f"{annee} : SRE {explicite[annee]:.2%}, OpenFisca {taux:.2%}")
    if ecarts:
        print("SUSPECT recoupement SRE / OpenFisca :", file=sys.stderr)
        for ecart in ecarts:
            print(f"        {ecart}", file=sys.stderr)
    else:
        print(f"OK      recoupement             {len(civils)} années identiques "
              "entre la fiche SRE et OpenFisca")

    contenu = {
        "recupere_le": date.today().isoformat(),
        "source_explicite": URL_SRE,
        "source_openfisca": RACINE_OPENFISCA,
        "note": "taux employeur en vigueur au 1er janvier de chaque année ; "
                "part de l'employeur seule, la retenue de l'agent restant dans "
                "les fiches de régime",
        "series": {
            "fonction_publique_etat_explicite": explicite,
            "fonction_publique_etat_implicite": implicite,
            "cnracl": series["cnracl"],
            "sncf": sncf,
        },
        "recoupement_openfisca": {"ecarts": ecarts, "annees": len(civils)},
    }
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(json.dumps(contenu, ensure_ascii=False, indent=1),
                      encoding="utf-8")

    print()
    for nom, serie in contenu["series"].items():
        if serie:
            print(f"{nom:<40} {len(serie):>3} années "
                  f"{min(serie)}-{max(serie)}, "
                  f"de {min(serie.values()):.2%} à {max(serie.values()):.2%}")
    print(f"\nÉcrit dans {SORTIE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
