"""
Thin database layer so the same pipeline code runs against:

  * Neon (hosted PostgreSQL) - production / shared team database
  * SQLite                   - offline development and automated tests

Neon gives two hosts for the same database:
  * pooled  (...-pooler.<region>.aws.neon.tech) - PgBouncer in transaction mode;
    used by the Vercel backend, which opens many short-lived connections.
  * direct  (...<region>.aws.neon.tech)         - a real session; used by this
    pipeline (bulk COPY + temp tables) and by pg_dump backups.

All SQL in etl.py is written with `?` placeholders and portable syntax
(ON CONFLICT ... DO NOTHING / DO UPDATE, RETURNING), which both engines support.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", ""}
SECURE_SSLMODES = {"require", "verify-ca", "verify-full"}


class InsecureConnectionError(ValueError):
    """Raised when a remote Postgres URL does not enforce TLS (SEC-02)."""


def validate_postgres_url(url: str) -> None:
    """Refuse remote database connections that are not encrypted in transit (risk R17)."""
    parsed = urlparse(url)
    sslmode = parse_qs(parsed.query).get("sslmode", [""])[0]
    if parsed.hostname not in LOCAL_HOSTS and sslmode not in SECURE_SSLMODES:
        raise InsecureConnectionError(
            "Remote database URL must include ?sslmode=require (or verify-full). "
            "Unencrypted connections to the hosted database are not allowed.")
    if parsed.password in {"password", "postgres", "changeme", ""} and parsed.hostname not in LOCAL_HOSTS:
        raise InsecureConnectionError("Refusing to connect with an empty or default database password.")


def is_pooled_neon_host(url: str) -> bool:
    """True for Neon's PgBouncer host, e.g. ep-x-123-pooler.ap-southeast-2.aws.neon.tech."""
    host = urlparse(url).hostname or ""
    return host.endswith(".neon.tech") and "-pooler." in host


def redact(url: str) -> str:
    """Hide the password when printing a connection string (SEC-27: no secrets in logs)."""
    return re.sub(r"(://[^:/@]+:)[^@]+@", r"\1****@", url)


class Database:
    def __init__(self, url: str):
        self.url = url
        if url.startswith(("postgres://", "postgresql://")):
            import psycopg  # imported lazily so SQLite-only users need not install it
            validate_postgres_url(url)
            self.dialect = "postgres"
            # prepare_threshold=None: server-side prepared statements break under
            # PgBouncer transaction pooling (Neon's pooled host), so never use them.
            self.conn = psycopg.connect(url, prepare_threshold=None)
            # Each role also has search_path=app as a role default (02_security.sql),
            # which is what keeps pooled connections pointed at the right schema.
            self.conn.execute("SET search_path TO app")
            if is_pooled_neon_host(url):
                print("  note: pooled Neon host detected; bulk loads work best on the direct host")
        else:
            path = Path(url.removeprefix("sqlite:///"))
            path.parent.mkdir(parents=True, exist_ok=True)
            self.dialect = "sqlite"
            self.path = path
            self.conn = sqlite3.connect(path)
            self.conn.execute("PRAGMA foreign_keys = ON")
            self.conn.execute("PRAGMA journal_mode = WAL")

    # -- helpers -----------------------------------------------------------
    def _sql(self, sql: str) -> str:
        return sql.replace("?", "%s") if self.dialect == "postgres" else sql

    def execute(self, sql: str, params=()):
        cur = self.conn.cursor()
        cur.execute(self._sql(sql), params)
        return cur

    def executemany(self, sql: str, rows):
        cur = self.conn.cursor()
        cur.executemany(self._sql(sql), rows)
        return cur

    def scalar(self, sql: str, params=()):
        row = self.execute(sql, params).fetchone()
        return row[0] if row else None

    def query_df(self, sql: str, params=()) -> pd.DataFrame:
        cur = self.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=cols)

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()

    def apply_schema(self, schema_path: Path):
        text = schema_path.read_text(encoding="utf-8")
        if self.dialect == "sqlite":
            self.conn.executescript(text)
        else:
            self.conn.execute(text)
        self.commit()

    # -- bulk load ---------------------------------------------------------
    def bulk_insert(self, table: str, columns: list[str], rows: list[tuple],
                    conflict_cols: list[str] | None = None) -> int:
        """
        Insert many rows quickly. If conflict_cols is given, rows that would violate
        that unique key are skipped (duplicate rule). Returns number of rows inserted.
        Postgres uses COPY into a temp table, then INSERT (fast over the network to Neon).
        """
        if not rows:
            return 0
        cols = ", ".join(columns)
        if self.dialect == "sqlite":
            before = self.conn.total_changes
            conflict = f" ON CONFLICT ({', '.join(conflict_cols)}) DO NOTHING" if conflict_cols else ""
            self.conn.executemany(
                f"INSERT INTO {table} ({cols}) VALUES ({', '.join(['?'] * len(columns))}){conflict}", rows)
            return self.conn.total_changes - before

        # COPY is not allowed directly into tables with row-level security (every app
        # table has RLS - SEC-13), so stage rows in a temp table, then INSERT...SELECT.
        cur = self.conn.cursor()
        tmp = f"tmp_{table}"
        cur.execute(f"CREATE TEMP TABLE {tmp} AS SELECT {cols} FROM {table} WITH NO DATA")
        with cur.copy(f"COPY {tmp} ({cols}) FROM STDIN") as cp:
            for r in rows:
                cp.write_row(r)
        conflict = f" ON CONFLICT ({', '.join(conflict_cols)}) DO NOTHING" if conflict_cols else ""
        cur.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM {tmp}{conflict}")
        inserted = cur.rowcount
        cur.execute(f"DROP TABLE {tmp}")
        return inserted


def df_to_rows(df: pd.DataFrame) -> list[tuple]:
    """DataFrame -> list of tuples of plain Python values (NaN -> None, numpy -> native)."""
    obj = df.astype(object).where(df.notna(), None)
    return [tuple(v.item() if hasattr(v, "item") else v for v in row) for row in obj.itertuples(index=False, name=None)]
