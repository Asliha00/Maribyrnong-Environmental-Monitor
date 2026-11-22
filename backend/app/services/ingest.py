"""
Admin CSV upload, server side (BUILD_PROMPT §4.5 step 3; SEC-20, SEC-15).

The browser uploaded the file straight to the private Blob store under `uploads/` (the
Node route `upload/` issued a short-lived, CSV-only, 50 MB token after an admin check).
Here FastAPI:
  1. re-checks the pathname (server-issued form only) and the size before downloading;
  2. sniffs the content: UTF-8 text, no NUL bytes, not a spreadsheet/zip/PDF/HTML file;
  3. requires a header that belongs to the chosen sensor's device family;
  4. parses with pandas only (inside the pipeline's `transform`), never executes anything;
  5. archives the original (`storage.upload_raw`, raw/<sha256>__<name>), ingests it with the
     pipeline's own rules, rebuilds that sensor's aggregates, and deletes the uploads/ copy.
"""
from __future__ import annotations

import csv
import io
import logging
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import ROOT

logger = logging.getLogger("backend.security")

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
SNIFF_BYTES = 64 * 1024
UPLOAD_PATHNAME = re.compile(r"uploads/[A-Za-z0-9][A-Za-z0-9._-]{0,150}\.csv")
BINARY_SIGNATURES = (b"PK\x03\x04", b"%PDF", b"\xd0\xcf\x11\xe0", b"\x89PNG", b"MZ", b"\x7fELF", b"\x1f\x8b")
TIMESTAMP_COLUMN = "timestamp"
EXTRA_KNOWN = {"deviceid"}          # device metadata the pipeline reads (hardware id)


class UploadRejected(Exception):
    """A user-facing reason the file cannot be loaded (HTTP 400)."""


def pipeline():
    """Import the data pipeline (data_pipeline/ uses top-level module names)."""
    path = str(ROOT / "data_pipeline")
    if path not in sys.path:
        sys.path.insert(0, path)
    import config
    import etl
    import storage

    return config, etl, storage


def check_pathname(pathname: str) -> str:
    if not UPLOAD_PATHNAME.fullmatch(pathname) or ".." in pathname:
        raise UploadRejected("This file name is not valid. Please upload the file again.")
    return pathname


def check_size(size: int) -> None:
    if size > MAX_UPLOAD_BYTES:
        raise UploadRejected("The file is larger than 50 MB. Split it into smaller files and upload each one.")
    if size == 0:
        raise UploadRejected("The file is empty.")


def sniff(head: bytes) -> str:
    """Text checks on the first bytes; returns the decoded header line."""
    if head.startswith(BINARY_SIGNATURES):
        raise UploadRejected("This is not a CSV file. Export the data as CSV (comma-separated values) and try again.")
    if b"\x00" in head:
        raise UploadRejected("This is not a CSV text file (it contains binary data).")
    try:
        text = head.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:   # the cut at SNIFF_BYTES may have split one multi-byte character
            text = head[:-3].decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise UploadRejected("The file is not UTF-8 text. Export it as CSV (UTF-8) and try again.") from exc
    first = text.splitlines()[0] if text else ""
    if first.lstrip().startswith(("<", "{", "[")):
        raise UploadRejected("This is not a CSV file. Export the data as CSV and try again.")
    return first


def known_columns(family: str, column_map: dict[str, dict[str, Any]]) -> set[str]:
    """Every column a council export for this device family may contain."""
    raw_vars = set(column_map[family]) | EXTRA_KNOWN
    known = {TIMESTAMP_COLUMN}
    for var in raw_vars:
        for name in (var, f"{var}lasthour"):
            known |= {name, f"created_at_{name}", f"context_{name}"}
    return known


def check_header(header_line: str, family: str, column_map: dict[str, dict[str, Any]]) -> list[str]:
    """The header must be this family's: a timestamp, at least one of its measurements,
    and no column the family does not have (catches files for the wrong sensor)."""
    columns = [c.strip() for c in next(csv.reader(io.StringIO(header_line)), [])]
    if TIMESTAMP_COLUMN not in columns:
        raise UploadRejected("The file has no 'timestamp' column, so it is not a council sensor export.")
    known = known_columns(family, column_map)
    unknown = [c for c in columns if c not in known and not c.startswith("date (")]
    if unknown:
        shown = ", ".join(sorted(unknown)[:5]) + (" …" if len(unknown) > 5 else "")
        raise UploadRejected(f"The columns do not match this sensor's device type ({family}). "
                             f"Unexpected columns: {shown}. Check that you chose the right sensor.")
    if not set(columns) & set(column_map[family]):
        raise UploadRejected("The file has no measurement columns for this sensor's device type.")
    return columns


RANDOM_SUFFIX = re.compile(r"-[0-9a-f]{32}(?=\.csv$)")


def original_name(pathname: str) -> str:
    """'uploads/mcc-1_device-<32 hex>.csv' -> 'mcc-1_device.csv': the file's own name, without
    directories or the browser's random suffix, so a re-upload of an identical file matches its
    existing archive copy (raw/<sha256>__<name>) instead of being archived again."""
    return RANDOM_SUFFIX.sub("", Path(pathname).name)


def ingest_upload(app_settings: Any, pathname: str, sensor: dict[str, Any], force: bool,
                  oidc_token: str | None) -> dict[str, Any]:
    """Run steps 1-5. Returns the run summary. Raises UploadRejected for a bad file."""
    if oidc_token:   # the Blob SDK reads the per-request OIDC token from its header context
        from vercel.headers import set_headers

        set_headers({"x-vercel-oidc-token": oidc_token})
    config, etl, storage = pipeline()
    check_pathname(pathname)
    started = time.perf_counter()
    try:
        check_size(storage.upload_size(pathname))
        with tempfile.TemporaryDirectory(prefix="upload-") as tmp:
            local = Path(tmp) / original_name(pathname)     # server-chosen location
            storage.download_upload(pathname, local)
            check_size(local.stat().st_size)
            with local.open("rb") as fh:
                header = sniff(fh.read(SNIFF_BYTES))
            check_header(header, sensor["device_family"], config.COLUMN_MAP)
            url = app_settings.app_database_url or f"sqlite:///{app_settings.sqlite_path.resolve().as_posix()}"
            conn = etl.connect(url)
            try:
                registry = pd.DataFrame([{**sensor, "file_match": None}])
                stats = etl.ingest_file(conn, local, registry, force=force, upload_raw=True,
                                        sensor=registry.iloc[0])
                if stats is None:
                    raise UploadRejected("This file has already been loaded. Tick 'Load again' to re-process it "
                                         "(readings already in the database are skipped).")
                run = conn.query_df("SELECT run_id, rows_inserted, storage_path FROM ingestion_runs "
                                    "WHERE sensor_id = ? ORDER BY run_id DESC LIMIT 1",
                                    (int(sensor["sensor_id"]),)).iloc[0]
                loaded = time.perf_counter()
                etl.build_aggregates(conn, sensor_id=int(sensor["sensor_id"]))
                conn.commit()
            finally:
                conn.close()
    finally:
        try:
            storage.delete_upload(pathname)
        except storage.StorageError:   # never hide the real outcome; the copy is only temporary
            logger.warning("could not delete upload %s", pathname)
    return {"run_id": int(run.run_id), "sensor_code": sensor["sensor_code"], "rows_read": int(stats["rows_read"]),
            "rows_inserted": int(run.rows_inserted), "rows_duplicate": int(stats["rows_duplicate"]),
            "rows_already_stored": int(stats["rows_kept"]) - int(run.rows_inserted),
            "values_rejected": int(stats["values_rejected"]), "values_flagged": int(stats["values_flagged"]),
            "archived": bool(run.storage_path), "seconds_loading": round(loaded - started, 1),
            "seconds_total": round(time.perf_counter() - started, 1)}
