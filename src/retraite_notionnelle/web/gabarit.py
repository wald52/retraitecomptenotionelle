"""Rendu HTML, sans moteur de gabarits.

Le projet n'a qu'une dépendance obligatoire (PyYAML) ; on ne lui en ajoute pas
une pour produire quelques pages. Les fonctions ci-dessous assemblent du HTML
et échappent systématiquement ce qui vient de l'utilisateur.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape

FEUILLE_DE_STYLE = """
:root {
  color-scheme: light dark;
  --fond: #fbfaf7;
  --fond-carte: #ffffff;
  --fond-appui: #f2efe9;
  --texte: #1b1a17;
  --texte-doux: #5c574d;
  --trait: #ddd7cb;
  --accent: #7a2e1e;
  --accent-doux: #f0e2dd;
  --actuel: #3f5c66;
  --retroactif: #a2472e;
  --prospectif: #6a6a4d;
  --financement-public: #7c5a86;
  --acquisition-commune: #35705f;
  --alerte: #8a5a00;
}
@media (prefers-color-scheme: dark) {
  :root {
    --fond: #16151a;
    --fond-carte: #1e1d23;
    --fond-appui: #26252c;
    --texte: #ece9e3;
    --texte-doux: #a5a099;
    --trait: #35333c;
    --accent: #e08b6f;
    --accent-doux: #3a2820;
    --actuel: #8fb2c0;
    --retroactif: #e08b6f;
    --prospectif: #bcbc8e;
    --financement-public: #c39ccd;
    --acquisition-commune: #79bda9;
    --alerte: #e0b062;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--fond);
  color: var(--texte);
  font-family: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
  font-size: 17px;
  line-height: 1.6;
}
main { max-width: 60rem; margin: 0 auto; padding: 0 1.25rem 5rem; }
header.bandeau {
  border-bottom: 1px solid var(--trait);
  background: var(--fond-carte);
  padding: 1.25rem 0 1rem;
  margin-bottom: 2rem;
}
header.bandeau .interieur {
  max-width: 60rem; margin: 0 auto; padding: 0 1.25rem;
  display: flex; flex-wrap: wrap; gap: 0.75rem 1.5rem;
  align-items: baseline; justify-content: space-between;
}
header.bandeau h1 { font-size: 1.2rem; margin: 0; letter-spacing: 0.01em; }
header.bandeau h1 a { color: inherit; text-decoration: none; }
nav a {
  color: var(--texte-doux); text-decoration: none;
  margin-left: 1.1rem; font-size: 0.92rem;
  border-bottom: 1px solid transparent;
}
nav a:hover, nav a[aria-current="page"] {
  color: var(--accent); border-bottom-color: var(--accent);
}
h2 { font-size: 1.35rem; margin: 2.5rem 0 0.75rem; font-weight: 600; }
h3 { font-size: 1.05rem; margin: 1.75rem 0 0.5rem; font-weight: 600; }
p { margin: 0.7rem 0; }
a { color: var(--accent); }
.chapeau { font-size: 1.08rem; color: var(--texte-doux); max-width: 44rem; }
.carte {
  background: var(--fond-carte); border: 1px solid var(--trait);
  border-radius: 6px; padding: 1.25rem 1.4rem; margin: 1.5rem 0;
}
.note {
  border-left: 3px solid var(--accent); background: var(--accent-doux);
  padding: 0.85rem 1.1rem; margin: 1.5rem 0; font-size: 0.95rem;
  border-radius: 0 4px 4px 0;
}
.note.avertissement { border-left-color: var(--alerte); }
.discret { color: var(--texte-doux); font-size: 0.9rem; }
form .grille {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr));
  gap: 1rem 1.5rem;
}
label { display: block; font-size: 0.88rem; color: var(--texte-doux); margin-bottom: 0.25rem; }
label .aide { display: block; font-size: 0.8rem; opacity: 0.8; }
input, select {
  width: 100%; padding: 0.45rem 0.6rem; font: inherit; font-size: 0.95rem;
  color: var(--texte); background: var(--fond); border: 1px solid var(--trait);
  border-radius: 4px;
}
input:focus, select:focus { outline: 2px solid var(--accent); outline-offset: 1px; }
button {
  font: inherit; font-size: 0.98rem; padding: 0.55rem 1.4rem; cursor: pointer;
  color: var(--fond-carte); background: var(--accent);
  border: 1px solid var(--accent); border-radius: 4px;
}
button:hover { opacity: 0.9; }
details { margin-top: 1.25rem; }
summary { cursor: pointer; color: var(--texte-doux); font-size: 0.92rem; }
summary:hover { color: var(--accent); }
details > .grille { margin-top: 1rem; }
.defilant { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 0.95rem; }
th, td { text-align: right; padding: 0.5rem 0.6rem; border-bottom: 1px solid var(--trait); }
th:first-child, td:first-child { text-align: left; }
thead th { font-size: 0.82rem; color: var(--texte-doux); font-weight: 600; }
tbody tr:last-child td { border-bottom: none; }
td.nombre, th.nombre { font-variant-numeric: tabular-nums; }
.scenario { margin: 1.4rem 0; }
.scenario .entete { display: flex; justify-content: space-between; gap: 1rem; align-items: baseline; }
.scenario .titre { font-weight: 600; }
.scenario .montant { font-variant-numeric: tabular-nums; white-space: nowrap; }
.scenario .montant .mensuel { font-size: 1.25rem; }
.scenario .montant .annuel { color: var(--texte-doux); font-size: 0.85rem; }
.barre { height: 12px; background: var(--fond-appui); border-radius: 6px; margin-top: 0.4rem; }
.barre > span { display: block; height: 100%; border-radius: 6px; }
.barre.actuel > span { background: var(--actuel); }
.barre.retroactif > span { background: var(--retroactif); }
.barre.prospectif > span { background: var(--prospectif); }
.barre.financement-public > span { background: var(--financement-public); }
.barre.acquisition-commune > span { background: var(--acquisition-commune); }
.scenario .glose { font-size: 0.88rem; color: var(--texte-doux); margin-top: 0.35rem; }
.fiches { display: grid; grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr)); gap: 1rem; }
.fiche .valeur { font-size: 1.2rem; font-variant-numeric: tabular-nums; }
.fiche .etiquette { font-size: 0.82rem; color: var(--texte-doux); }
.etiquette-fiabilite {
  display: inline-block; font-size: 0.78rem; letter-spacing: 0.04em;
  text-transform: uppercase; padding: 0.15rem 0.5rem; border-radius: 3px;
  background: var(--fond-appui); color: var(--texte-doux);
}
ul.serree { margin: 0.5rem 0; padding-left: 1.2rem; }
ul.serree li { margin: 0.3rem 0; }
footer {
  border-top: 1px solid var(--trait); margin-top: 3rem; padding-top: 1.25rem;
  font-size: 0.88rem; color: var(--texte-doux);
}
.erreur {
  border-left: 3px solid var(--retroactif); background: var(--fond-appui);
  padding: 0.85rem 1.1rem; margin: 1.5rem 0;
}
pre.json {
  background: var(--fond-appui); border: 1px solid var(--trait); border-radius: 4px;
  padding: 0.9rem 1.1rem; overflow-x: auto; max-height: 26rem; overflow-y: auto;
  font-size: 0.82rem; line-height: 1.45;
  font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
}
.chargement { text-align: center; padding: 4rem 1rem; color: var(--texte-doux); }
.chargement .jauge {
  height: 6px; width: min(24rem, 80%); margin: 1.5rem auto 0;
  background: var(--fond-appui); border-radius: 3px; overflow: hidden;
}
.chargement .jauge > span {
  display: block; height: 100%; width: 30%; background: var(--accent);
  animation: glisse 1.4s ease-in-out infinite;
}
@keyframes glisse {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(333%); }
}
body.calcul-en-cours main { opacity: 0.45; transition: opacity 0.2s; }

/* Téléphone : le montant passe sous l'intitulé du scénario plutôt que de se
   serrer contre lui, et la page respire un peu moins large. */
@media (max-width: 34rem) {
  body { font-size: 16px; }
  main { padding: 0 1rem 4rem; }
  .carte { padding: 1rem 1.1rem; }
  header.bandeau .interieur { gap: 0.4rem 1rem; }
  nav a { margin: 0 1.1rem 0 0; }
  .scenario .entete { flex-direction: column; gap: 0.15rem; }
  .scenario .montant { white-space: normal; }
  .fiches { grid-template-columns: repeat(auto-fit, minmax(8rem, 1fr)); }
  form .grille { gap: 0.9rem; }
}
"""

DEPOT = "https://github.com/wald52/retraitecomptenotionelle"

#: « serveur » : les pages sont servies par FastAPI, une adresse par page.
#: « navigateur » : la navigation se fait par l'ancre de l'adresse
#: (``#/cas-types``), comme sur le site. Le rendu est identique dans les deux
#: cas ; seuls les liens changent. Le second mode sert à produire les témoins
#: que doit retrouver le portage JavaScript.
MODE = "serveur"

LIENS = (
    ("/", "Simuler"),
    ("/cas-types", "Cas types"),
    ("/methode", "Méthode"),
    ("/donnees", "Données"),
)


def dans_le_navigateur() -> bool:
    return MODE == "navigateur"


def lien(chemin: str, ancre: str = "") -> str:
    """Adresse d'une page interne, selon le mode de service."""
    if dans_le_navigateur():
        return "#" + chemin
    return chemin + (f"#{ancre}" if ancre else "")


def navigation(chemin_actif: str = "/") -> str:
    return "".join(
        f'<a href="{lien(chemin)}"'
        + (' aria-current="page"' if chemin == chemin_actif else "")
        + f">{escape(libelle)}</a>"
        for chemin, libelle in LIENS
    )


def entete(chemin_actif: str = "/") -> str:
    return f"""<header class="bandeau"><div class="interieur">
  <h1><a href="{lien('/')}">Retraite à comptes notionnels</a></h1>
  <nav>{navigation(chemin_actif)}</nav>
</div></header>"""


def pied() -> str:
    return f"""<footer>
  <p>Modèle ouvert, code et données sur <a href="{DEPOT}">GitHub</a> (licence MIT).
  Les montants sont bruts, exprimés en euros constants de l'année de référence.
  Les séries d'avant 1950 et les paramètres de régime restent saisis à la main :
  <a href="{DEPOT}/blob/main/docs/limites.md">lire les limites</a> avant de citer un chiffre.</p>
</footer>"""


def page(titre: str, corps: str, chemin_actif: str = "/") -> str:
    """Document complet — utilisé par le serveur ; le navigateur n'en prend que le corps."""
    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(titre)} — Retraite en comptes notionnels</title>
<style>{FEUILLE_DE_STYLE}</style>
</head>
<body>
{entete(chemin_actif)}
<main>
{corps}
{pied()}
</main>
</body>
</html>"""


# -- fragments ---------------------------------------------------------------


def nombre(valeur: float, decimales: int = 2) -> str:
    """Nombre \u00e0 la fran\u00e7aise : virgule d\u00e9cimale, espace ins\u00e9cable des milliers."""
    return f"{valeur:,.{decimales}f}".replace(",", "\u202f").replace(".", ",")


def euros(montant: float) -> str:
    """Montant en euros."""
    return nombre(montant, 0) + "\u202f\u20ac"


def pourcentage(valeur: float, signe: bool = False, decimales: int = 1) -> str:
    texte = nombre(valeur * 100, decimales)
    if signe and valeur >= 0:
        texte = "+" + texte
    return texte + "\u202f%"


_GROUPES = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?")
_DECIMAL = re.compile(r"\d+\.\d+")
_AVANT_POURCENT = re.compile(r"(\d)%")


def franciser(texte: str) -> str:
    """Convertit les nombres à l'anglaise produits par le moteur.

    « 17,542 € × rendement 6.00% » devient « 17 542 € × rendement 6,00 % ».
    Le moteur formate ses libellés de calcul pour un terminal ; la page web les
    présente à un lecteur francophone, pour qui « 17,542 » se lit 17,5.
    """
    texte = _GROUPES.sub(lambda m: m.group(0).replace(",", "\u202f"), texte)
    texte = _DECIMAL.sub(lambda m: m.group(0).replace(".", ","), texte)
    return _AVANT_POURCENT.sub("\\1\u202f%", texte)


def champ(nom: str, libelle: str, valeur: str, aide: str = "",
          type_: str = "text", **attributs: str) -> str:
    supplement = "".join(
        f' {cle.rstrip("_").replace("_", "-")}="{escape(str(val))}"'
        for cle, val in attributs.items()
    )
    aide_html = f'<span class="aide">{escape(aide)}</span>' if aide else ""
    return (
        f'<div><label for="{nom}">{escape(libelle)}{aide_html}</label>'
        f'<input type="{type_}" id="{nom}" name="{nom}" '
        f'value="{escape(str(valeur))}"{supplement}></div>'
    )


def liste(nom: str, libelle: str, options: list[tuple[str, str]],
          selection: str, aide: str = "") -> str:
    choix = "".join(
        f'<option value="{escape(code)}"'
        + (" selected" if code == selection else "")
        + f">{escape(texte)}</option>"
        for code, texte in options
    )
    aide_html = f'<span class="aide">{escape(aide)}</span>' if aide else ""
    return (
        f'<div><label for="{nom}">{escape(libelle)}{aide_html}</label>'
        f'<select id="{nom}" name="{nom}">{choix}</select></div>'
    )


@dataclass
class Cellule:
    """Cellule de tableau portant une teinte de fond proportionnelle à sa valeur."""

    html: str
    intensite: float = 0.0

    def style(self) -> str:
        if not self.intensite:
            return ""
        # Teintes calibrées pour rester lisibles sur fond clair comme sur fond
        # sombre : rouge = pension plus faible, vert-de-gris = pension plus forte.
        couleur = "162, 71, 46" if self.intensite < 0 else "90, 116, 80"
        alpha = min(abs(self.intensite), 1.0) * 0.30
        return f' style="background: rgba({couleur}, {alpha:.2f})"'


def tableau(entetes: list[str], lignes: list[list[str | Cellule]],
            classes_colonnes: list[str] | None = None) -> str:
    classes = classes_colonnes or ["" for _ in entetes]
    tete = "".join(
        f'<th class="{cls}" scope="col">{escape(titre)}</th>'
        for titre, cls in zip(entetes, classes)
    )
    corps = "".join(
        "<tr>" + "".join(
            f'<td class="{cls}"'
            + (cellule.style() if isinstance(cellule, Cellule) else "")
            + ">"
            + (cellule.html if isinstance(cellule, Cellule) else cellule)
            + "</td>"
            for cellule, cls in zip(ligne, classes)
        ) + "</tr>"
        for ligne in lignes
    )
    return (
        f'<div class="defilant"><table><thead><tr>{tete}</tr></thead>'
        f"<tbody>{corps}</tbody></table></div>"
    )


def fiche(etiquette: str, valeur: str) -> str:
    return (
        f'<div class="fiche"><div class="valeur">{valeur}</div>'
        f'<div class="etiquette">{escape(etiquette)}</div></div>'
    )
