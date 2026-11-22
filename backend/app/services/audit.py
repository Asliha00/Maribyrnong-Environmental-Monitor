"""
Audit trail (SEC-12) and security logging without secrets (SEC-27).

`audit_log` is append-only in the database (02_security.sql trigger + grants), so
entries written here cannot later be edited or deleted, even by the app.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from ..db import Transaction

logger = logging.getLogger("backend.security")

# Detail keys that could carry a secret are refused outright (SEC-27).
FORBIDDEN_DETAIL_KEYS = {"password", "new_password", "current_password", "token", "access_token",
                         "refresh_token", "secret", "mfa_secret", "code", "csrf"}
SUSPICIOUS_FAILED_LOGINS = 20          # proposal R18: basic anomaly detection
SUSPICIOUS_WINDOW = timedelta(minutes=10)


def record(tx: Transaction, action: str, user_id: int | None = None, ip: str | None = None,
           detail: dict[str, Any] | None = None) -> None:
    """Append one audit entry and mirror it to the server log (no secrets in either)."""
    detail = detail or {}
    leaked = FORBIDDEN_DETAIL_KEYS & {k.lower() for k in detail}
    if leaked:
        raise ValueError(f"refusing to audit secret-bearing fields: {sorted(leaked)}")
    tx.execute("INSERT INTO audit_log (user_id, action, detail_json, ip_address) VALUES (?, ?, ?, ?)",
               (user_id, action, json.dumps(detail, sort_keys=True), ip))
    logger.info("audit action=%s user_id=%s ip=%s detail=%s", action, user_id, ip, detail)


def flag_failed_login_burst(tx: Transaction, ip: str | None) -> bool:
    """After a failed login: if more than 20 failures happened in 10 minutes, record a
    single 'suspicious_login_activity' entry for the window (SEC-27). Returns True if flagged."""
    since = datetime.now(UTC) - SUSPICIOUS_WINDOW
    failures = tx.fetch_one("SELECT COUNT(*) AS n FROM audit_log WHERE action = ? AND created_at >= ?",
                            ("login_failed", since))["n"]
    if failures <= SUSPICIOUS_FAILED_LOGINS:
        return False
    already = tx.fetch_one("SELECT COUNT(*) AS n FROM audit_log WHERE action = ? AND created_at >= ?",
                           ("suspicious_login_activity", since))["n"]
    if already:
        return False
    record(tx, "suspicious_login_activity", ip=ip,
           detail={"failed_logins_last_10_min": failures, "threshold": SUSPICIOUS_FAILED_LOGINS})
    logger.warning("suspicious login activity: %s failed logins in 10 minutes", failures)
    return True
