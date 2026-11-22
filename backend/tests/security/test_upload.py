"""SEC-20 safe file upload (admin CSV upload, §4.5 step 3) and the ingest it triggers.

The Blob store is replaced by an in-memory fake (`store`), so the tests exercise the real
checks, the real pipeline (SQLite) and the real per-sensor aggregate rebuild.
"""
import json

import pytest

from backend.app.routers import admin_uploads
from backend.app.services import ingest
from backend.tests.conftest import admin_with_mfa, audit_actions, email_of, login, post
from backend.tests.test_data_api import data_db  # noqa: F401 - fixture

URL = "/api/admin/ingest-upload"
MCC_HEADER = ("timestamp,created_at_temperature,context_temperature,temperature,created_at_pm25,context_pm25,pm25,"
              "created_at_deviceid,context_deviceid,deviceid,date (Australia/Sydney)")
LIBELIUM_HEADER = ("timestamp,created_at_batteryvoltage,context_batteryvoltage,batteryvoltage,created_at_pressure,"
                   "context_pressure,pressure,created_at_temperature,context_temperature,temperature")


def mcc_csv(rows: int = 48, start_ms: int = 1_754_006_400_000) -> bytes:
    """A small council-style MCC export: one reading every 10 minutes from 2025-08-01 00:00 UTC
    (10:00 in Melbourne)."""
    lines = [MCC_HEADER]
    for i in range(rows):
        ts = start_ms + i * 600_000
        lines.append(f"{ts},{ts},{{}},{12 + i % 5}.0,{ts},{{}},{4 + i % 3}.0,{ts},{{}},863663063792742.0,x")
    return ("\n".join(lines) + "\n").encode()


class FakeStore:
    """uploads/<name> -> bytes; records what the code did with it."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.deleted: list[str] = []
        self.archived: list[str] = []
        self.downloads = 0
        self.size_override: int | None = None

    def install(self, monkeypatch):
        _, _, storage = ingest.pipeline()

        def upload_size(name):
            storage._upload_name(name)
            if name not in self.files:
                raise storage.StorageError("The uploaded file was not found. Please upload it again.")
            return self.size_override if self.size_override is not None else len(self.files[name])

        def download_upload(name, dest):
            self.downloads += 1
            dest.write_bytes(self.files[storage._upload_name(name)])
            return dest

        def delete_upload(name):
            self.deleted.append(name)
            self.files.pop(name, None)

        def upload_raw(path, digest):
            name = storage.object_name(digest, path.name)
            self.archived.append(name)
            return name

        for fn in (upload_size, download_upload, delete_upload, upload_raw):
            monkeypatch.setattr(storage, fn.__name__, fn)


@pytest.fixture
def store(monkeypatch):
    s = FakeStore()
    s.install(monkeypatch)
    return s


@pytest.fixture
def admin(client, make_user, db_conn, data_db):  # noqa: F811
    admin_with_mfa(client, make_user, db_conn)
    return client


def _upload(client, store, content: bytes, name="uploads/mcc-export-Ab12Cd.csv", sensor_id=1, **extra):
    store.files[name] = content
    return post(client, URL, {"pathname": name, "sensor_id": sensor_id, **extra})


# ---------- success path ----------
def test_upload_ingests_archives_rebuilds_and_deletes(admin, store, db_conn):
    db_conn.execute("UPDATE aggregates SET mean = -999 WHERE sensor_id = 2")   # marker on another sensor
    db_conn.commit()
    r = _upload(admin, store, mcc_csv())
    assert r.status_code == 200, r.text
    summary = r.json()["summary"]
    assert summary["rows_read"] == 48 and summary["rows_inserted"] == 48 and summary["archived"] is True
    assert summary["rows_already_stored"] == 0
    assert store.deleted == ["uploads/mcc-export-Ab12Cd.csv"] and store.files == {}
    assert len(store.archived) == 1 and store.archived[0].startswith("raw/")
    run = db_conn.execute("SELECT * FROM ingestion_runs ORDER BY run_id DESC").fetchone()
    assert run["sensor_id"] == 1 and run["finished_at"] and run["rows_inserted"] == 48
    hourly = db_conn.execute("SELECT COUNT(*) FROM aggregates WHERE sensor_id = 1 AND period = 'hour' "
                             "AND variable = 'temperature_c' AND qc_mode = 'all' "
                             "AND bucket_start_local >= '2025-08-01'").fetchone()[0]
    assert hourly == 8                                                  # 48 readings x 10 min = 8 hours
    assert db_conn.execute("SELECT COUNT(*) FROM aggregates WHERE sensor_id = 2 AND mean <> -999 "
                           "AND mean IS NOT NULL").fetchone()[0] == 0   # other sensors untouched
    assert db_conn.execute("SELECT hardware_id FROM sensors WHERE sensor_id = 1").fetchone()[0] == "863663063792742"
    entry = audit_actions(db_conn, "upload_ingested")[0]
    assert entry["sensor_code"] == "A-01" and entry["rows_inserted"] == 48 and entry["file"] == "mcc-export-Ab12Cd.csv"


def test_same_file_twice_needs_load_again(admin, store, db_conn):
    assert _upload(admin, store, mcc_csv()).status_code == 200
    r = _upload(admin, store, mcc_csv())
    assert r.status_code == 400 and "already been loaded" in r.json()["error"]["message"]
    r = _upload(admin, store, mcc_csv(), force=True)
    assert r.status_code == 200 and r.json()["summary"]["rows_inserted"] == 0   # duplicates skipped
    assert r.json()["summary"]["rows_already_stored"] == 48
    assert db_conn.execute("SELECT COUNT(*) FROM readings WHERE sensor_id = 1 AND ts_utc >= '2025-08'") \
        .fetchone()[0] == 48


# ---------- SEC-20 ----------
def test_oversize_rejected(admin, store, db_conn):
    store.size_override = 50 * 1024 * 1024 + 1
    r = _upload(admin, store, mcc_csv())
    assert r.status_code == 400 and "larger than 50 MB" in r.json()["error"]["message"]
    assert store.downloads == 0 and store.deleted == ["uploads/mcc-export-Ab12Cd.csv"]
    assert audit_actions(db_conn, "upload_rejected")[0]["reason"].startswith("The file is larger")


@pytest.mark.parametrize("content", [b"PK\x03\x04" + b"\x00" * 100,            # xlsx (zip)
                                     b"%PDF-1.7\n" + b"x" * 100,                 # PDF
                                     b"\xd0\xcf\x11\xe0" + b"\x00" * 100,        # old .xls
                                     b"MZ\x90\x00" + b"\x00" * 100,              # Windows executable
                                     b"timestamp,temperature\n1\x00,2\n",       # binary inside "CSV"
                                     b"<html><script>alert(1)</script></html>",
                                     b'{"timestamp": 1}',
                                     "timestamp,température\n".encode("latin-1"),  # not UTF-8
                                     b""])
def test_non_csv_rejected(admin, store, db_conn, content):
    r = _upload(admin, store, content)
    assert r.status_code == 400, r.text
    assert db_conn.execute("SELECT COUNT(*) FROM ingestion_runs").fetchone()[0] == 0
    assert store.deleted == ["uploads/mcc-export-Ab12Cd.csv"]


@pytest.mark.parametrize("pathname", ["uploads/../../etc/passwd.csv", "../uploads/x.csv", "raw/abc__x.csv",
                                      "uploads/a/b.csv", "uploads/x.csv.exe", "uploads/x.CSV ", "/uploads/x.csv",
                                      "uploads\\x.csv", "uploads/.hidden.csv", "uploads/x%2F..%2Fy.csv",
                                      "uploads/" + "a" * 160 + ".csv"])
def test_path_traversal_filename_neutralised(admin, store, db_conn, pathname):
    """Only server-issued uploads/<name>.csv pathnames are accepted: nothing outside uploads/
    (e.g. the raw/ archive) can be read or deleted through this route."""
    r = post(admin, URL, {"pathname": pathname, "sensor_id": 1})
    assert r.status_code in (400, 422)
    assert store.downloads == 0 and store.deleted == []


def test_archive_name_never_contains_directories():
    assert ingest.original_name("uploads/mcc-export-Ab12Cd.csv") == "mcc-export-Ab12Cd.csv"
    # the browser's random suffix is dropped, so an identical re-upload matches its archive copy
    uploaded = "uploads/mcc---1_1_device_RTG7DUBK4D-4b66616272561aa8a7619aa90f230622.csv"
    assert ingest.original_name(uploaded) == "mcc---1_1_device_RTG7DUBK4D.csv"
    _, _, storage = ingest.pipeline()
    assert storage.object_name("ab" * 32, "../../x.csv") == f"raw/{'ab' * 32}__x.csv"


def test_unknown_columns_rejected(admin, store, db_conn):
    # a Libelium export loaded against an MCC sensor: the wrong sensor is caught
    r = _upload(admin, store, (LIBELIUM_HEADER + "\n1754000000000,1,{},3.9,1,{},101300,1,{},12\n").encode())
    assert r.status_code == 400
    assert "do not match this sensor's device type (mcc_aq)" in r.json()["error"]["message"]
    assert "batteryvoltage" in r.json()["error"]["message"]
    # columns from nowhere
    r = _upload(admin, store, b"timestamp,=cmd|' /C calc'!A0,password\n1,2,3\n")
    assert r.status_code == 400 and "Unexpected columns" in r.json()["error"]["message"]
    # no timestamp column
    r = _upload(admin, store, b"temperature,pm25\n12,4\n")
    assert r.status_code == 400 and "no 'timestamp' column" in r.json()["error"]["message"]
    assert db_conn.execute("SELECT COUNT(*) FROM ingestion_runs").fetchone()[0] == 0


def test_header_rules_unit():
    _, _, _ = ingest.pipeline()
    config, _, _ = ingest.pipeline()
    assert ingest.check_header(MCC_HEADER, "mcc_aq", config.COLUMN_MAP)[0] == "timestamp"
    with pytest.raises(ingest.UploadRejected):
        ingest.check_header("timestamp,created_at_temperature", "mcc_aq", config.COLUMN_MAP)   # no measurement


def test_non_admin_403(client, make_user, db_conn, data_db, store):  # noqa: F811
    for role in ("analyst", "admin"):          # this admin has not passed MFA
        client.cookies.clear()
        login(client, email_of(db_conn, make_user(role=role)))
        r = _upload(client, store, mcc_csv())
        assert r.status_code == 403
    assert store.downloads == 0 and store.deleted == []
    assert db_conn.execute("SELECT COUNT(*) FROM ingestion_runs").fetchone()[0] == 0


def test_inactive_or_unknown_sensor(admin, store, db_conn):
    db_conn.execute("UPDATE sensors SET status = 'Inactive' WHERE sensor_id = 1")
    db_conn.commit()
    assert _upload(admin, store, mcc_csv()).status_code == 409
    assert _upload(admin, store, mcc_csv(), sensor_id=99).status_code == 404
    assert store.downloads == 0


def test_unexpected_failure_is_safe_and_audited(admin, store, db_conn, monkeypatch):
    _, etl, _ = ingest.pipeline()

    def boom(*args, **kwargs):
        raise RuntimeError("disk full at /var/task/secret")

    monkeypatch.setattr(etl, "build_aggregates", boom)
    r = _upload(admin, store, mcc_csv())
    assert r.status_code == 500
    assert r.json()["error"]["message"] == admin_uploads.MSG_FAILED
    assert admin_uploads.MSG_FAILED == "The file could not be loaded. Please try again or contact your administrator."
    assert "secret" not in r.text
    assert audit_actions(db_conn, "upload_failed")[0]["error"] == "RuntimeError"
    assert store.deleted == ["uploads/mcc-export-Ab12Cd.csv"]


def test_uploads_are_rate_limited(admin, store, monkeypatch):
    monkeypatch.setattr(admin_uploads, "UPLOADS_PER_ADMIN", admin_uploads.rate_limit.Limit("upload:user", 2, 600))
    codes = [_upload(admin, store, b"not,a,council,file\n1,2,3,4\n").status_code for _ in range(3)]
    assert codes == [400, 400, 429]


def test_hostile_json_fields(admin, store):
    for body in ({"pathname": "uploads/x.csv", "sensor_id": "1 OR 1=1"},
                 {"pathname": "uploads/x.csv", "sensor_id": 1, "storage_path": "raw/"},
                 {"pathname": ["uploads/x.csv"], "sensor_id": 1}):
        assert post(admin, URL, body).status_code == 422
    assert json.dumps(store.deleted) == "[]"
