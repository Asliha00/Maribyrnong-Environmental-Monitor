"""
Archive of the original council CSV files in a PRIVATE Vercel Blob store (SEC-15).

The original exports are the source of truth for every reading, so they are kept
unchanged. Each pathname is  raw/<sha256>__<original name>  so any later tampering
or corruption is detectable when a file is downloaded again (Data Governance).

Private stores require authentication for every read and write; there is no
public URL. Credentials:
  * on Vercel: short-lived OIDC tokens, added automatically when the store is
    connected to the project (preferred - they rotate themselves);
  * on a laptop or in GitHub Actions: BLOB_READ_WRITE_TOKEN in .env / secrets.
The token is server-side only. It must never appear in frontend code.

Uses the official `vercel` Python SDK (synchronous API).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import config as C


class StorageError(RuntimeError):
    pass


def _blob():
    """Import lazily so the pipeline runs offline (SQLite) without the SDK installed."""
    try:
        from vercel.blob import sync as blob
    except ImportError as e:  # pragma: no cover - exercised only without the dependency
        raise StorageError("Install the Vercel SDK: pip install 'vercel>=0.12'") from e
    return blob


def _require_config():
    import os
    # On Vercel the website authenticates with OIDC: BLOB_STORE_ID is set and the token
    # arrives per request (the x-vercel-oidc-token header, handed to the SDK by the caller).
    if not (C.BLOB_READ_WRITE_TOKEN or os.environ.get("VERCEL_OIDC_TOKEN") or os.environ.get("BLOB_STORE_ID")):
        raise StorageError("Set BLOB_READ_WRITE_TOKEN in .env (Vercel -> Storage -> your private "
                           "Blob store -> .env.local tab) to use the raw-file archive.")


def object_name(sha256: str, filename: str) -> str:
    """Pathname inside the store. Only the base filename is used (no path traversal)."""
    return f"{C.RAW_PREFIX}{sha256}__{Path(filename).name}"


def upload_raw(path: Path, sha256: str) -> str:
    """Archive an original CSV once and return its pathname. Never overwrites:
    if the same pathname exists, the content is identical (the hash is in the name)."""
    _require_config()
    blob = _blob()
    name = object_name(sha256, path.name)
    try:
        blob.head_blob(name)
        return name  # identical file already archived
    except blob.BlobNotFoundError:
        pass
    try:
        result = blob.put_blob(name, path.read_bytes(), access="private",
                               content_type="text/csv", allow_overwrite=False)
    except blob.BlobError as e:
        raise StorageError(f"Upload of {path.name} failed: {e}") from e
    return result.pathname


def list_raw() -> list[str]:
    """Pathnames of every archived CSV."""
    _require_config()
    blob = _blob()
    try:
        return [b.pathname for b in blob.query_blobs(prefix=C.RAW_PREFIX) if b.pathname.endswith(".csv")]
    except blob.BlobError as e:
        raise StorageError(f"Listing the raw-file archive failed: {e}") from e


def download_raw(name: str, dest_dir: Path) -> Path:
    """Download one archived file and verify its SHA-256 matches the hash in its name."""
    _require_config()
    blob = _blob()
    try:
        body = blob.get_blob(name, access="private").body
    except blob.BlobError as e:
        raise StorageError(f"Download of {name} failed: {e}") from e
    base = name.removeprefix(C.RAW_PREFIX)
    if "__" not in base:
        raise StorageError(f"{name} is not an archived raw file (expected <sha256>__<name>)")
    expected, original = base.split("__", 1)
    actual = hashlib.sha256(body).hexdigest()
    if actual != expected:
        raise StorageError(f"Integrity check failed for {name}: sha256 {actual} != {expected}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / Path(original).name
    out.write_bytes(body)
    return out


# --------------------------------------------------------------------------- admin uploads (§4.5)
UPLOAD_PREFIX = "uploads/"


def _upload_name(name: str) -> str:
    """Only server-issued upload pathnames: uploads/<safe name>.csv, no directories (SEC-20)."""
    import re
    if not re.fullmatch(r"uploads/[A-Za-z0-9][A-Za-z0-9._-]{0,150}\.csv", name) or ".." in name:
        raise StorageError("Not an upload pathname")
    return name


def upload_size(name: str) -> int:
    """Size in bytes of an uploaded file (before downloading it)."""
    _require_config()
    blob = _blob()
    try:
        return int(blob.head_blob(_upload_name(name)).size)
    except blob.BlobNotFoundError as e:
        raise StorageError("The uploaded file was not found. Please upload it again.") from e
    except blob.BlobError as e:
        raise StorageError(f"Reading the upload failed: {e}") from e


def download_upload(name: str, dest: Path) -> Path:
    """Download an uploaded file to `dest` (a server-chosen temporary path)."""
    _require_config()
    blob = _blob()
    try:
        dest.write_bytes(blob.get_blob(_upload_name(name), access="private").body)
    except blob.BlobError as e:
        raise StorageError(f"Downloading the upload failed: {e}") from e
    return dest


def delete_upload(name: str) -> None:
    """Remove the uploads/ copy once it has been ingested (or rejected)."""
    _require_config()
    blob = _blob()
    try:
        blob.delete_blob(_upload_name(name))
    except blob.BlobNotFoundError:
        pass
    except blob.BlobError as e:
        raise StorageError(f"Deleting the upload failed: {e}") from e

