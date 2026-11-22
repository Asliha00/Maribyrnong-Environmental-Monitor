"""
FastAPI application factory.

Run locally:  uvicorn backend.app.main:app --reload   (or `make dev`)
On Vercel the same `app` object runs as a Python function under /api/*.
"""
from __future__ import annotations

import logging

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import ROOT, Settings, get_settings
from .db import Database
from .docs import add_docs
from .errors import register_error_handlers
from .middleware import SecurityMiddleware, load_vercel_headers
from .routers import (
    admin_sensors,
    admin_thresholds,
    admin_uploads,
    admin_users,
    analysis,
    auth,
    data,
    health,
    ingest,
    quality,
    reports,
)
from .security import verify_csrf

VERCEL_JSON = ROOT / "vercel.json"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. Tests pass their own Settings; production reads the environment."""
    settings = settings or get_settings()
    logging.basicConfig(level=logging.INFO)

    app = FastAPI(
        title="Maribyrnong Environmental Monitor API",
        version="0.1.0",
        debug=False,  # never render debug tracebacks, in any environment (SEC-24)
        docs_url=None,  # self-hosted Swagger UI instead (docs.py, works under our CSP)
        redoc_url=None,
        openapi_url="/api/openapi.json",
        swagger_ui_oauth2_redirect_url=None,  # no OAuth in the docs: no extra public route
        # SEC-09: every state-changing request must carry the CSRF token, on every route
        dependencies=[Depends(verify_csrf)],
    )
    app.state.settings = settings
    app.state.db = Database(settings)

    register_error_handlers(app)
    app.include_router(health.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(data.router, prefix="/api")
    app.include_router(reports.router, prefix="/api")
    app.include_router(admin_sensors.router, prefix="/api")
    app.include_router(admin_users.router, prefix="/api")
    app.include_router(admin_thresholds.router, prefix="/api")
    app.include_router(quality.router, prefix="/api")
    app.include_router(admin_uploads.router, prefix="/api")
    app.include_router(ingest.router, prefix="/api")
    app.include_router(analysis.router, prefix="/api")
    add_docs(app)

    # CORS only for the Vite dev server. Production is same-origin, so the
    # backend sends no CORS headers there at all (SEC-25).
    if settings.environment == "development":
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.allowed_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE"],
            allow_headers=["Content-Type", "X-CSRF-Token"],
        )
    # Added last so it is the outermost layer and also covers CORS and error responses
    app.add_middleware(SecurityMiddleware, header_rules=load_vercel_headers(VERCEL_JSON))
    return app


app = create_app()
