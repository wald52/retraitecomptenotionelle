"""Serveur FastAPI : routage et API JSON.

Tout le contenu vient de :mod:`.pages`, partagé avec la version qui s'exécute
dans le navigateur. Ce module ne fait que router.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from ..castypes import calculer_cas_types
from ..config import Parametres
from ..donnees.chargement import DonneeInsuffisante
from . import gabarit as g
from .pages import Contexte, ErreurSaisie, Saisie, rendre, statuts


def creer_application(parametres: Parametres | None = None) -> FastAPI:
    """Construit l'application. Les données sont chargées à la première requête."""
    contexte = Contexte(base=parametres or Parametres())
    application = FastAPI(
        title="Retraite à comptes notionnels",
        description=(
            "Simulateur d'un système de retraite français en comptes notionnels, "
            "appliqué rétroactivement depuis l'origine de la répartition."
        ),
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    def html(chemin: str, request: Request | None = None) -> HTMLResponse:
        parametres_requete = dict(request.query_params) if request else {}
        titre, corps = rendre(contexte, chemin, parametres_requete)
        return HTMLResponse(g.page(titre, corps, chemin))

    @application.get("/", response_class=HTMLResponse)
    def accueil(request: Request) -> HTMLResponse:
        return html("/", request)

    @application.get("/cas-types", response_class=HTMLResponse)
    def page_cas_types() -> HTMLResponse:
        return html("/cas-types")

    @application.get("/methode", response_class=HTMLResponse)
    def page_methode() -> HTMLResponse:
        return html("/methode")

    @application.get("/donnees", response_class=HTMLResponse)
    def page_donnees() -> HTMLResponse:
        return html("/donnees")

    # -- API ----------------------------------------------------------------

    @application.get("/api/statuts")
    def api_statuts() -> JSONResponse:
        return JSONResponse(statuts(contexte))

    @application.get("/api/simuler")
    def api_simuler(request: Request) -> JSONResponse:
        try:
            saisie = Saisie.depuis_requete(dict(request.query_params))
            return JSONResponse(contexte.simuler(saisie).dictionnaire())
        except ErreurSaisie as erreur:
            return JSONResponse({"erreur": str(erreur)}, status_code=422)
        except DonneeInsuffisante as erreur:
            return JSONResponse({"erreur": str(erreur)}, status_code=409)
        except (KeyError, ValueError) as erreur:
            return JSONResponse({"erreur": str(erreur)}, status_code=400)

    @application.get("/api/cas-types")
    def api_cas_types() -> JSONResponse:
        return JSONResponse(calculer_cas_types(contexte.simulateur()).dictionnaire())

    return application
