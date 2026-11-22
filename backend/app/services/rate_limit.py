"""
Database-backed rate limiting (SEC-23).

Vercel runs many short-lived function instances, each with its own memory, so an
in-memory limiter would let every instance allow the full quota. A fixed-window
counter in the shared `rate_limits` table is seen by all instances:

    INSERT ... ON CONFLICT (bucket, window_start) DO UPDATE SET hits = hits + 1 RETURNING hits

The upsert is a single atomic statement on both PostgreSQL and SQLite.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ..db import Transaction

STALE_AFTER = timedelta(days=1)


@dataclass(frozen=True)
class Limit:
    name: str
    max_hits: int
    window_seconds: int


LOGIN_PER_IP = Limit("login:ip", 5, 60)            # SEC-23: login 5/min/IP
MFA_VERIFY_PER_USER = Limit("mfa:user", 5, 60)     # brute force on 6-digit codes
PASSWORD_CHANGE_PER_USER = Limit("pwchange:user", 5, 60)


def hit(tx: Transaction, limit: Limit, key: str, now: datetime | None = None) -> tuple[bool, int]:
    """Count one request. Returns (allowed, seconds until the window resets)."""
    now = now or datetime.now(UTC)
    epoch = int(now.timestamp())
    start = datetime.fromtimestamp(epoch - epoch % limit.window_seconds, UTC)
    row = tx.fetch_one(
        """INSERT INTO rate_limits (bucket, window_start, hits) VALUES (?, ?, 1)
           ON CONFLICT (bucket, window_start) DO UPDATE SET hits = rate_limits.hits + 1
           RETURNING hits""",
        (f"{limit.name}:{key}", start))
    retry_after = limit.window_seconds - epoch % limit.window_seconds
    return row["hits"] <= limit.max_hits, retry_after


def purge_stale(tx: Transaction, now: datetime | None = None) -> int:
    """Delete windows older than a day (called opportunistically on login)."""
    cutoff = (now or datetime.now(UTC)) - STALE_AFTER
    return tx.execute("DELETE FROM rate_limits WHERE window_start < ?", (cutoff,))
