"""
Database access for the backend.

* Neon (production): psycopg 3 on the **pooled** host as `app_user`. Neon's
  pooler runs PgBouncer in transaction mode, so server-side prepared statements
  are disabled (`prepare_threshold=None`) and no session state (SET, temp tables,
  advisory locks) is relied on between transactions. Every Vercel instance has
  its own pool, so the pool is tiny and opened lazily.
* SQLite (local development and tests): the file built by
  `python data_pipeline/etl.py --sqlite --rebuild`.

Queries are written with `?` placeholders and translated for psycopg, the same
convention as data_pipeline/db.py. Only parameterised SQL is allowed (SEC-19).
Rows come back as dicts and timestamps as timezone-aware `datetime` on both engines,
so service code never branches on the dialect.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from .config import Settings

POOL_MAX_SIZE = 2


def to_datetime(value: Any) -> datetime | None:
    """Normalise a timestamp column (Postgres datetime or SQLite ISO text) to aware UTC."""
    if value is None or isinstance(value, datetime):
        return value.astimezone(UTC) if isinstance(value, datetime) else None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _sqlite_param(value: Any) -> Any:
    # SQLite stores timestamps as ISO-8601 UTC text (schema_sqlite.sql convention)
    if isinstance(value, datetime):
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return value


class Transaction:
    """One connection, one transaction: commits when the `with` block succeeds."""

    def __init__(self, conn: Any, dialect: str):
        self._conn = conn
        self._dialect = dialect

    def _run(self, sql: str, params: Sequence[Any]):
        if self._dialect == "postgres":
            return self._conn.execute(sql.replace("?", "%s"), params)
        return self._conn.execute(sql, [_sqlite_param(p) for p in params])

    def fetch_all(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        """All rows as dicts."""
        return [dict(r) for r in self._run(sql, params).fetchall()]

    def fetch_one(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        """First row as a dict, or None."""
        row = self._run(sql, params).fetchone()
        return dict(row) if row is not None else None

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        """Run a statement; return the number of affected rows."""
        return self._run(sql, params).rowcount


class Database:
    """Opens connections on demand; one instance per app."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.dialect = "postgres" if settings.uses_postgres else "sqlite"
        self._pool = None

    def _get_pool(self):
        if self._pool is None:
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool  # lazy: SQLite users need not connect

            self._pool = ConnectionPool(
                self.settings.app_database_url,
                min_size=0,
                max_size=POOL_MAX_SIZE,
                kwargs={"prepare_threshold": None, "row_factory": dict_row},
                open=True,
            )
        return self._pool

    @contextmanager
    def transaction(self) -> Iterator[Transaction]:
        """Yield a Transaction; commit on success, roll back on error."""
        if self.dialect == "postgres":
            # The pool's context manager commits on success and rolls back on error
            with self._get_pool().connection() as conn:
                yield Transaction(conn, "postgres")
            return
        # mode=rw: fail instead of silently creating an empty database file
        conn = sqlite3.connect(f"{self.settings.sqlite_path.resolve().as_uri()}?mode=rw", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            yield Transaction(conn, "sqlite")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def fetch_all(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        """Run one parameterised query in its own transaction."""
        with self.transaction() as tx:
            return tx.fetch_all(sql, params)

    def fetch_one(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        with self.transaction() as tx:
            return tx.fetch_one(sql, params)

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        with self.transaction() as tx:
            return tx.execute(sql, params)

    def ping(self) -> bool:
        """True if the database answers a trivial query."""
        try:
            return self.fetch_one("SELECT 1 AS ok") == {"ok": 1}
        except Exception:  # noqa: BLE001 - health check reports any failure as "down"
            return False

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool = None
