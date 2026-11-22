"""
Shared pieces of the administration routes (UC5): the per-admin rate limit and the
audit helper. Every admin action is written to the append-only audit_log (SEC-12).
"""
from __future__ import annotations

from typing import Any

from fastapi import Request

from ..db import Transaction
from ..errors import AppError
from ..security import Session, client_ip
from ..services import audit, rate_limit

ADMIN_PER_USER = rate_limit.Limit("admin:user", 60, 60)   # generous for people, bounded for scripts


def limit(tx: Transaction, session: Session, which: rate_limit.Limit = ADMIN_PER_USER) -> None:
    allowed, retry_after = rate_limit.hit(tx, which, str(session.user_id))
    if not allowed:
        raise AppError(429, "rate_limited", "Too many requests. Please wait a moment and try again.",
                       headers={"Retry-After": str(retry_after)})


def record(tx: Transaction, request: Request, session: Session, action: str, detail: dict[str, Any]) -> None:
    """Audit one admin action (who, when, from where, what changed). Never secrets."""
    audit.record(tx, action, user_id=session.user_id, ip=client_ip(request), detail=detail)
