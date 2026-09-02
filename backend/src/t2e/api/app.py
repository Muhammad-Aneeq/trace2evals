"""FastAPI app factory.

Serves the API and, when the SPA has been built, the labeling UI from the same origin - so
`t2e label --serve` is a single process with no dev server in the shipped path.

Privacy posture (spec 03 sec 11): binds loopback by default, makes no outbound requests, and
sends no telemetry. The only CORS origin allowed is the local Vite dev server, in development only.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from t2e import __version__
from t2e.api.routes import router
from t2e.config import Settings, get_settings
from t2e.store import init_db

#: Where `npm run build` puts the SPA (see frontend/vite.config.ts).
WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def create_app(settings: Settings | None = None, *, dev: bool = False) -> FastAPI:
    settings = settings or get_settings()

    app = FastAPI(
        title="Trace2Evals",
        version=__version__,
        description=(
            "Turn agent traces into versioned eval cases you own. Local-first, no LLM calls."
        ),
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    if dev:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[settings.dev_cors_origin],
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    init_db(settings)
    app.include_router(router)

    @app.get("/api/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "version": __version__,
            "db": str(settings.resolved_db_path()),
            "ui_built": WEB_DIR.is_dir(),
        }

    _mount_spa(app)
    return app


def _mount_spa(app: FastAPI) -> None:
    """Mount the built SPA, or explain how to build it. Never fail to start over a missing UI."""
    index = WEB_DIR / "index.html"

    if not index.is_file():

        @app.get("/")
        def ui_not_built() -> JSONResponse:
            return JSONResponse(
                status_code=503,
                content={
                    "error": "the labeling UI has not been built",
                    "fix": "run `npm --prefix frontend install && "
                    "npm --prefix frontend run build`, or `make dev` / `./make.ps1 dev` "
                    "for the live-reload dev server",
                    "api": "the API is fully available at /api (docs at /api/docs)",
                },
            )

        return

    assets = WEB_DIR / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/")
    def spa_root() -> FileResponse:
        return FileResponse(index)

    @app.get("/{path:path}")
    def spa_fallback(path: str) -> FileResponse:
        """Client-side routing: serve real files, otherwise hand back index.html."""
        candidate = (WEB_DIR / path).resolve()
        if candidate.is_file() and candidate.is_relative_to(WEB_DIR.resolve()):
            return FileResponse(candidate)
        return FileResponse(index)
