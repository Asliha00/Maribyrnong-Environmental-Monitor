"""
API documentation at /api/docs, served under the site's strict CSP (SEC-22).

FastAPI's built-in page loads Swagger UI from a CDN and starts it with an inline
script; our CSP (`script-src 'self'`) blocks both. These files are self-hosted
(backend/app/static/swagger/README.md) and started from an external init.js.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request

STATIC = Path(__file__).resolve().parent / "static" / "swagger"
DOCS_PATH = "/api/docs"
ASSETS_PATH = "/api/docs/static"

PAGE = f"""<!doctype html>
<html lang="en-AU">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Maribyrnong Environmental Monitor API</title>
  <link rel="stylesheet" href="{ASSETS_PATH}/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="{ASSETS_PATH}/swagger-ui-bundle.js"></script>
  <script src="{ASSETS_PATH}/init.js"></script>
</body>
</html>
"""


async def docs_page(request: Request) -> HTMLResponse:
    return HTMLResponse(PAGE)


def add_docs(app: FastAPI) -> None:
    """Register the docs page and its static assets (create the app with docs_url=None)."""
    app.router.add_route(DOCS_PATH, docs_page, methods=["GET"], include_in_schema=False)
    app.mount(ASSETS_PATH, StaticFiles(directory=STATIC), name="docs-static")
