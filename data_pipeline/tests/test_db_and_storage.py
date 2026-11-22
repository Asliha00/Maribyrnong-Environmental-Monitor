"""Tests for the database layer security rules and the Vercel Blob raw-file archive.

The Postgres integration test runs only when TEST_POSTGRES_URL is set, e.g.
  TEST_POSTGRES_URL=postgresql://pipeline_user:...@127.0.0.1:5432/neondb?sslmode=require
"""
import hashlib
import os
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config as C  # noqa: E402
import storage  # noqa: E402
from db import InsecureConnectionError, df_to_rows, is_pooled_neon_host, redact, validate_postgres_url  # noqa: E402


# ---------------------------------------------------------------- SEC-02 TLS enforcement
@pytest.mark.parametrize("url", [
    "postgresql://pipeline_user:S3cure-pass@ep-quiet-sky-123456.ap-southeast-2.aws.neon.tech/neondb",
    "postgresql://pipeline_user:S3cure-pass@ep-quiet-sky-123456.ap-southeast-2.aws.neon.tech/neondb?sslmode=disable",
    "postgresql://pipeline_user:S3cure-pass@ep-quiet-sky-123456.ap-southeast-2.aws.neon.tech/neondb?sslmode=prefer",
])
def test_remote_url_without_tls_is_refused(url):
    with pytest.raises(InsecureConnectionError):
        validate_postgres_url(url)


def test_remote_url_with_default_password_is_refused():
    with pytest.raises(InsecureConnectionError):
        validate_postgres_url("postgresql://postgres:postgres@ep-quiet-sky-123456.ap-southeast-2.aws.neon.tech/neondb?sslmode=require")


@pytest.mark.parametrize("url", [
    "postgresql://pipeline_user:S3cure-pass@ep-quiet-sky-123456.ap-southeast-2.aws.neon.tech/neondb?sslmode=require",
    "postgresql://pipeline_user:S3cure-pass@ep-quiet-sky-123456.ap-southeast-2.aws.neon.tech/neondb?sslmode=verify-full",
    "postgresql://me:x@localhost:5432/dev",  # local development is allowed without TLS
])
def test_secure_urls_accepted(url):
    validate_postgres_url(url)


# ---------------------------------------------------------------- SEC-27 no secrets in logs
def test_redact_hides_password():
    out = redact("postgresql://pipeline_user:VerySecret123@ep-quiet-sky-123456.ap-southeast-2.aws.neon.tech/neondb?sslmode=require")
    assert "VerySecret123" not in out and "****" in out and "pipeline_user" in out


def test_df_to_rows_converts_numpy_and_nan():
    rows = df_to_rows(pd.DataFrame({"a": np.array([1, 2], dtype="int64"), "b": [1.5, np.nan]}))
    assert rows == [(1, 1.5), (2, None)]
    assert type(rows[0][0]) is int


def test_pooled_neon_host_detected():
    assert is_pooled_neon_host("postgresql://u:p@ep-a-1-pooler.ap-southeast-2.aws.neon.tech/neondb?sslmode=require")
    assert not is_pooled_neon_host("postgresql://u:p@ep-a-1.ap-southeast-2.aws.neon.tech/neondb?sslmode=require")
    assert not is_pooled_neon_host("postgresql://u:p@localhost/neondb")


# ---------------------------------------------------------------- SEC-15 raw-file archive (Vercel Blob)
class FakeBlobStore:
    """In-memory stand-in for vercel.blob.sync with the same calls storage.py uses."""

    class BlobError(Exception):
        pass

    class BlobNotFoundError(BlobError):
        pass

    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.calls: list[tuple] = []

    def head_blob(self, name):
        self.calls.append(("head", name))
        if name not in self.objects:
            raise self.BlobNotFoundError(name)
        return types.SimpleNamespace(pathname=name, size=len(self.objects[name]))

    def put_blob(self, name, body, *, access, content_type=None, allow_overwrite=False, **_):
        self.calls.append(("put", name, access, allow_overwrite))
        if name in self.objects and not allow_overwrite:
            raise self.BlobError("already exists")
        self.objects[name] = bytes(body)
        return types.SimpleNamespace(pathname=name, url=f"https://store.private.blob.vercel-storage.com/{name}")

    def get_blob(self, name, *, access):
        self.calls.append(("get", name, access))
        if name not in self.objects:
            raise self.BlobNotFoundError(name)
        return types.SimpleNamespace(body=self.objects[name])

    def query_blobs(self, *, prefix=None, **_):
        return [types.SimpleNamespace(pathname=n) for n in self.objects if n.startswith(prefix or "")]


@pytest.fixture
def fake_blob(monkeypatch):
    store = FakeBlobStore()
    monkeypatch.setattr(storage, "_blob", lambda: store)
    monkeypatch.setattr(C, "BLOB_READ_WRITE_TOKEN", "vercel_blob_rw_test")
    return store


def test_upload_is_private_and_never_overwrites(tmp_path, fake_blob):
    f = tmp_path / "sensor.csv"
    f.write_text("timestamp,temperature\n1,2\n")
    path = storage.upload_raw(f, "abc123")
    assert path == "raw/abc123__sensor.csv"
    put = [c for c in fake_blob.calls if c[0] == "put"][0]
    assert put[2] == "private"          # access="private"
    assert put[3] is False              # allow_overwrite=False


def test_upload_of_identical_file_is_not_an_error(tmp_path, fake_blob):
    f = tmp_path / "sensor.csv"
    f.write_text("x")
    storage.upload_raw(f, "abc")
    assert storage.upload_raw(f, "abc") == "raw/abc__sensor.csv"
    assert sum(c[0] == "put" for c in fake_blob.calls) == 1


def test_object_name_strips_directories(tmp_path):
    assert storage.object_name("h", "../../etc/passwd") == "raw/h__passwd"


def test_download_verifies_integrity(tmp_path, fake_blob):
    body = b"timestamp,temperature\n1,20\n"
    good = hashlib.sha256(body).hexdigest()
    fake_blob.objects[f"raw/{good}__sensor.csv"] = body
    fake_blob.objects[f"raw/{'0' * 64}__tampered.csv"] = body
    out = storage.download_raw(f"raw/{good}__sensor.csv", tmp_path)
    assert out.read_bytes() == body and out.name == "sensor.csv"
    with pytest.raises(storage.StorageError, match="Integrity check failed"):
        storage.download_raw(f"raw/{'0' * 64}__tampered.csv", tmp_path)


def test_list_returns_only_archived_csvs(fake_blob):
    fake_blob.objects.update({"raw/a__x.csv": b"", "raw/notes.txt": b"", "other/b__y.csv": b""})
    assert storage.list_raw() == ["raw/a__x.csv"]


def test_storage_requires_configuration(monkeypatch):
    monkeypatch.setattr(C, "BLOB_READ_WRITE_TOKEN", "")
    monkeypatch.delenv("VERCEL_OIDC_TOKEN", raising=False)
    with pytest.raises(storage.StorageError, match="BLOB_READ_WRITE_TOKEN"):
        storage.list_raw()


# ---------------------------------------------------------------- Postgres integration
@pytest.mark.skipif(not os.environ.get("TEST_POSTGRES_URL"), reason="TEST_POSTGRES_URL not set")
def test_postgres_bulk_insert_respects_duplicates_under_rls():
    from db import Database
    db = Database(os.environ["TEST_POSTGRES_URL"])
    sid = db.scalar("SELECT sensor_id FROM sensors ORDER BY sensor_id LIMIT 1")
    ts = "2030-01-01T00:00:00Z"
    cols = ["sensor_id", "ts_utc", "ts_local", "temperature_c"]
    rows = [(sid, ts, "2030-01-01T11:00:00+1100", 20.0)]
    try:
        assert db.bulk_insert("readings", cols, rows, conflict_cols=["sensor_id", "ts_utc"]) == 1
        assert db.bulk_insert("readings", cols, rows, conflict_cols=["sensor_id", "ts_utc"]) == 0
    finally:
        db.conn.rollback()
        db.close()
