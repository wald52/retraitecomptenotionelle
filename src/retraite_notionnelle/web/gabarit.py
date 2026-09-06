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
  --retroactif-employeur: #7c5a86;
  --prospectif-employeur: #35705f;
  --alerte: #8a5a00;
  /* Palette des graphiques : neuf teintes, assez distinctes pour se suivre
     empilées, assez proches pour ne pas jurer avec le reste de la page. */
  --serie-1: #3f5c66;
  --serie-2: #a2472e;
  --serie-3: #6a6a4d;
  --serie-4: #7c5a86;
  --serie-5: #35705f;
  --serie-6: #b07d2b;
  --serie-7: #4a6f9c;
  --serie-8: #8a6552;
  --serie-9: #9a9186;
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
    --retroactif-employeur: #c39ccd;
    --prospectif-employeur: #79bda9;
    --alerte: #e0b062;
    --serie-1: #8fb2c0;
    --serie-2: #e08b6f;
    --serie-3: #bcbc8e;
    --serie-4: #c39ccd;
    --serie-5: #79bda9;
    --serie-6: #e0b062;
    --serie-7: #8fabd4;
    --serie-8: #c8a08a;
    --serie-9: #b3aca2;
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
main { max-width: 60rem; margin: 0 auto; padding: 0 1.25rem; }
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
/* Les métiers de la carrière : une boîte par métier, la dernière en pointillé
   parce qu'elle n'en décrit encore aucun — c'est celle qui sert à en ajouter. */
.metiers { display: grid; gap: 0.9rem; margin: 0.9rem 0 0; }
.metier { border: 1px solid var(--trait); border-radius: 4px; padding: 0.9rem 1rem; }
.metier.facultatif { border-style: dashed; }
.metier > .rang {
  margin: 0 0 0.7rem; font-size: 0.78rem; letter-spacing: 0.05em;
  text-transform: uppercase; color: var(--texte-doux);
}
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
.barre.retroactif-employeur > span { background: var(--retroactif-employeur); }
.barre.prospectif-employeur > span { background: var(--prospectif-employeur); }
.scenario .glose { font-size: 0.88rem; color: var(--texte-doux); margin-top: 0.35rem; }
.fiches { display: grid; grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr)); gap: 1rem; }
.fiche .valeur { font-size: 1.2rem; font-variant-numeric: tabular-nums; }
.fiche .etiquette { font-size: 0.82rem; color: var(--texte-doux); }
.etiquette-fiabilite {
  display: inline-block; font-size: 0.78rem; letter-spacing: 0.04em;
  text-transform: uppercase; padding: 0.15rem 0.5rem; border-radius: 3px;
  background: var(--fond-appui); color: var(--texte-doux);
}
/* Graphiques : du SVG écrit à la main, dont seules les couleurs et les tailles
   de texte sont ici. Le tracé lui-même est dans `graphique()`. */
.graphique { margin: 1.3rem 0 1.7rem; }
.graphique svg { display: block; width: 100%; height: auto; overflow: visible; }
.graphique .grille { stroke: var(--trait); stroke-width: 1; }
.graphique .axe { stroke: var(--texte-doux); stroke-width: 1; }
.graphique .courbe {
  fill: none; stroke-width: 2.5;
  stroke-linejoin: round; stroke-linecap: round;
}
.graphique .bande { stroke: none; }
.graphique .graduation {
  fill: var(--texte-doux); font-family: inherit; font-size: 12px;
  font-variant-numeric: tabular-nums;
}
ul.legende {
  list-style: none; margin: 0.6rem 0 0; padding: 0;
  display: flex; flex-wrap: wrap; gap: 0.3rem 1.2rem; font-size: 0.86rem;
}
ul.legende li { display: flex; align-items: baseline; gap: 0.4rem; }
.pastille {
  display: inline-block; flex: none;
  width: 0.7rem; height: 0.7rem; border-radius: 2px;
}
ul.serree { margin: 0.5rem 0; padding-left: 1.2rem; }
ul.serree li { margin: 0.3rem 0; }
footer {
  /* Hors de <main>, le pied porte lui-même la boîte que <main> lui prêtait.
     Le filet doit s'aligner sur le texte : la largeur est donc celle de la
     *zone de contenu* de <main> — 60rem moins ses deux marges intérieures —
     et le padding horizontal reste nul, sans quoi le filet déborderait. */
  width: calc(100% - 2.5rem); max-width: 57.5rem;
  margin: 3rem auto 0; padding: 1.25rem 0 5rem;
  border-top: 1px solid var(--trait);
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
  main { padding: 0 1rem; }
  footer { width: calc(100% - 2rem); padding: 1.25rem 0 4rem; }
  .carte { padding: 1rem 1.1rem; }
  header.bandeau .interieur { gap: 0.4rem 1rem; }
  nav a { margin: 0 1.1rem 0 0; }
  .scenario .entete { flex-direction: column; gap: 0.15rem; }
  .scenario .montant { white-space: normal; }
  .fiches { grid-template-columns: repeat(auto-fit, minmax(8rem, 1fr)); }
  form .grille { gap: 0.9rem; }
  /* Le SVG se réduit avec la page : ses textes, exprimés en unités du viewBox,
     se réduiraient d'autant et deviendraient illisibles. On les grossit donc
     dans le repère pour qu'ils gardent leur taille à l'écran. */
  .graphique .graduation { font-size: 20px; }
}
"""

DEPOT = "https://github.com/wald52/retraitecomptenotionelle"

LIENS = (
    ("/", "Simuler"),
    ("/cas-types", "Cas types"),
    ("/cout", "Coût"),
    ("/methode", "Méthode"),
    ("/donnees", "Données"),
)


def lien(chemin: str, ancre: str = "") -> str:
    """Adresse d'une page interne.

    Le site tient dans une seule page : la navigation passe par l'ancre de
    l'adresse (``#/cas-types``). L'ancre de section, elle, ne peut pas s'y
    ajouter — la place est prise — et n'est acceptée que pour que les appels
    disent vers quoi ils pointent.
    """
    return "#" + chemin


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


# -- graphiques --------------------------------------------------------------
#
# Le dépôt n'a pas de bibliothèque de tracé, et n'en aura pas : le site charge
# ses propres fichiers et rien d'autre. Les graphiques sont donc du SVG écrit à
# la main, en deux exemplaires — ici et dans ``moteur/js/gabarit.js`` —, et
# comparés caractère par caractère par les témoins. D'où deux règles de
# construction qu'il ne faut pas enfreindre :
#
#   * toutes les coordonnées passent par ``nombre_brut``, qui arrondit comme
#     Python le fait, pour que les deux rendus produisent la même chaîne ;
#   * le pas des graduations est cherché par ITÉRATION sur une échelle de
#     valeurs rondes, jamais par un logarithme, dont les deux langages ne
#     garantissent pas le même dernier bit.
#
# Les couleurs sont des variables CSS : le graphique suit le thème clair ou
# sombre sans que rien ne soit recalculé.

#: Cadre de tracé, en unités du ``viewBox``. Le SVG est redimensionné par le
#: navigateur ; ces nombres ne sont donc pas des pixels mais un repère.
LARGEUR_TRACE = 720
HAUTEUR_TRACE = 300
MARGE_GAUCHE = 66
MARGE_DROITE = 24
MARGE_HAUT = 26
MARGE_BAS = 28
#: La marge de droite loge la MOITIÉ de la dernière graduation d'abscisse, qui
#: est centrée sur elle : trop étroite, « 2024 » déborderait du viewBox.

#: Nombre d'intervalles de l'axe vertical. Cinq : assez pour lire, assez peu
#: pour ne pas encombrer, et surtout assez pour qu'un maximum de 427 tienne dans
#: une échelle qui monte à 500 plutôt qu'à 800 — avec quatre intervalles, la
#: moitié du cadre restait vide.
DIVISIONS_Y = 5

#: Échelle des pas de graduation admissibles, multipliée par des puissances de
#: dix. On la parcourt du plus petit au plus grand jusqu'à couvrir la valeur
#: maximale : aucune fonction transcendante n'intervient, donc aucun écart
#: possible entre les deux portages.
PAS_RONDS = (1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0)

#: Écart minimal, en années, entre une décennie graduée et une borne de l'axe.
#: Les bornes sont graduées d'office — ce sont elles qui datent la série —, et
#: une décennie trop proche de l'une d'elles ne fait que chevaucher son
#: étiquette. Six ans : « 2020 » et « 2024 » ne tiennent pas côte à côte sur
#: l'écran d'un téléphone, où les textes du repère sont grossis.
ECART_MINIMAL_GRADUATIONS = 6


@dataclass(frozen=True)
class Serie:
    """Une courbe ou une bande d'un graphique."""

    libelle: str
    #: Valeurs alignées sur les abscisses passées au graphique. ``None`` marque
    #: une année sans valeur : la courbe y est interrompue plutôt qu'inventée.
    valeurs: tuple[float | None, ...]
    #: Expression CSS de la couleur, en général ``var(--...)``.
    couleur: str
    #: Trait discontinu, pour distinguer deux courbes de même famille.
    tirets: bool = False
    #: Glose affichée dans la légende, sous le libellé.
    glose: str = ""


def nombre_brut(valeur: float, decimales: int = 1) -> str:
    """Nombre à l'anglaise, pour un attribut SVG — jamais pour du texte lu."""
    return f"{valeur:.{decimales}f}"


def pas_graduation(maximum: float, divisions: int = DIVISIONS_Y) -> float:
    """Plus petit pas rond dont ``divisions`` intervalles couvrent ``maximum``."""
    if maximum <= 0:
        return 1.0
    base = 1e-9
    while base < 1e12:
        for facteur in PAS_RONDS:
            pas = base * facteur
            if pas * divisions >= maximum:
                return pas
        base *= 10.0
    return base


def _abscisse(annee: int, premiere: int, derniere: int) -> float:
    largeur = LARGEUR_TRACE - MARGE_GAUCHE - MARGE_DROITE
    if derniere == premiere:
        return MARGE_GAUCHE + largeur / 2
    return MARGE_GAUCHE + largeur * (annee - premiere) / (derniere - premiere)


def _ordonnee(valeur: float, sommet: float) -> float:
    hauteur = HAUTEUR_TRACE - MARGE_HAUT - MARGE_BAS
    if sommet <= 0:
        return HAUTEUR_TRACE - MARGE_BAS
    return HAUTEUR_TRACE - MARGE_BAS - hauteur * valeur / sommet


def _graduations_x(premiere: int, derniere: int) -> list[int]:
    """Décennies comprises dans la plage, plus les deux bornes."""
    annees = [a for a in range(premiere, derniere + 1) if a % 10 == 0]
    if premiere not in annees:
        annees.insert(0, premiere)
    if derniere not in annees:
        annees.append(derniere)
    # Deux graduations trop proches se chevauchent : on retire la décennie
    # voisine plutôt que la borne, qui porte l'information.
    return [
        a for a in annees
        if a in (premiere, derniere)
        or (a - premiere >= ECART_MINIMAL_GRADUATIONS
            and derniere - a >= ECART_MINIMAL_GRADUATIONS)
    ]


def _chemin(serie: Serie, annees: tuple[int, ...], sommet: float) -> str:
    """Chemin SVG d'une courbe, interrompu là où la série n'a pas de valeur."""
    morceaux: list[str] = []
    commence = False
    for annee, valeur in zip(annees, serie.valeurs):
        if valeur is None:
            commence = False
            continue
        x = nombre_brut(_abscisse(annee, annees[0], annees[-1]))
        y = nombre_brut(_ordonnee(valeur, sommet))
        morceaux.append(f"{'M' if not commence else 'L'}{x} {y}")
        commence = True
    return " ".join(morceaux)


def _bande(basses: list[float], hautes: list[float],
           annees: tuple[int, ...], sommet: float) -> str:
    """Chemin fermé d'une bande empilée : le dessus à l'aller, le dessous au retour."""
    aller = [
        f"{'M' if rang == 0 else 'L'}"
        f"{nombre_brut(_abscisse(annee, annees[0], annees[-1]))} "
        f"{nombre_brut(_ordonnee(haute, sommet))}"
        for rang, (annee, haute) in enumerate(zip(annees, hautes))
    ]
    retour = [
        f"L{nombre_brut(_abscisse(annee, annees[0], annees[-1]))} "
        f"{nombre_brut(_ordonnee(basse, sommet))}"
        for annee, basse in zip(reversed(annees), reversed(basses))
    ]
    return " ".join(aller + retour) + " Z"


def _sommet(series: tuple[Serie, ...], empile: bool) -> tuple[float, float]:
    """Sommet de l'axe vertical et pas de graduation."""
    if empile:
        maximum = max(
            (sum(v for v in colonne if v is not None)
             for colonne in zip(*(s.valeurs for s in series))),
            default=0.0,
        )
    else:
        maximum = max(
            (v for serie in series for v in serie.valeurs if v is not None),
            default=0.0,
        )
    pas = pas_graduation(maximum)
    return pas * DIVISIONS_Y, pas


def graphique(titre: str, annees: tuple[int, ...], series: tuple[Serie, ...],
              unite: str = "", empile: bool = False, decimales: int = 0,
              legende: bool = True) -> str:
    """Graphique en courbes, ou en bandes empilées si ``empile``.

    ``titre`` n'est pas affiché : il est le texte alternatif du SVG, c'est-à-dire
    ce que lit une synthèse vocale. Ce que voit l'œil est dans la légende et
    dans la phrase qui précède le graphique.
    """
    if not annees or not series:
        return ""

    sommet, pas = _sommet(series, empile)
    gauche = nombre_brut(_abscisse(annees[0], annees[0], annees[-1]))
    droite = nombre_brut(_abscisse(annees[-1], annees[0], annees[-1]))

    lignes = []
    for division in range(DIVISIONS_Y + 1):
        valeur = pas * division
        y = nombre_brut(_ordonnee(valeur, sommet))
        lignes.append(
            f'<line class="grille" x1="{gauche}" y1="{y}" x2="{droite}" y2="{y}"/>'
            f'<text class="graduation" x="{nombre_brut(MARGE_GAUCHE - 6)}" y="{y}" '
            f'dy="0.32em" text-anchor="end">{nombre(valeur, decimales)}</text>'
        )
    base = nombre_brut(_ordonnee(0.0, sommet))
    for annee in _graduations_x(annees[0], annees[-1]):
        x = nombre_brut(_abscisse(annee, annees[0], annees[-1]))
        lignes.append(
            f'<text class="graduation" x="{x}" '
            f'y="{nombre_brut(HAUTEUR_TRACE - MARGE_BAS + 16)}" '
            f'text-anchor="middle">{annee}</text>'
        )

    traces = []
    if empile:
        # La PREMIÈRE série est la bande du BAS : la légende se lit alors dans
        # l'ordre du graphique, de bas en haut, et non à l'envers.
        cumul = [0.0 for _ in annees]
        for serie in series:
            hautes = [
                bas + (valeur or 0.0) for bas, valeur in zip(cumul, serie.valeurs)
            ]
            traces.append(
                f'<path class="bande" fill="{serie.couleur}" '
                f'd="{_bande(cumul, hautes, annees, sommet)}"/>'
            )
            cumul = hautes
    else:
        for serie in series:
            tirets = ' stroke-dasharray="5 4"' if serie.tirets else ""
            traces.append(
                f'<path class="courbe" stroke="{serie.couleur}"{tirets} '
                f'd="{_chemin(serie, annees, sommet)}"/>'
            )

    unite_html = (
        f'<text class="graduation" x="{nombre_brut(MARGE_GAUCHE - 6)}" '
        f'y="{nombre_brut(MARGE_HAUT - 10)}" text-anchor="end">{escape(unite)}</text>'
        if unite else ""
    )
    legende_html = _legende(series) if legende else ""
    return (
        f'<figure class="graphique">'
        f'<svg viewBox="0 0 {LARGEUR_TRACE} {HAUTEUR_TRACE}" role="img" '
        f'aria-label="{escape(titre)}">'
        f"{''.join(lignes)}{''.join(traces)}"
        f'<line class="axe" x1="{gauche}" y1="{base}" x2="{droite}" y2="{base}"/>'
        f"{unite_html}"
        f"</svg>{legende_html}</figure>"
    )


def _legende(series: tuple[Serie, ...]) -> str:
    entrees = "".join(
        f'<li><span class="pastille" style="background:{serie.couleur}"></span>'
        f"<span>{escape(serie.libelle)}"
        + (f' <span class="discret">{escape(serie.glose)}</span>' if serie.glose else "")
        + "</span></li>"
        for serie in series
    )
    return f'<ul class="legende">{entrees}</ul>'
