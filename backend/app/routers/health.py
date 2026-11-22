"""Public uptime check (one of the three public routes allowed by SEC-10)."""
from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request) -> dict:
    """Report whether the API and its database are reachable. No versions or hostnames are exposed."""
    db_ok = request.app.state.db.ping()
    return {"status": "ok" if db_ok else "degraded", "database": "ok" if db_ok else "unavailable"}
