# Sample exports (Phase 4)

| File | What it is | How it was made |
|---|---|---|
| `sample_report_pm25_daily.pdf` | PDF export (UC3): PM2.5, daily means, 2025-02-16 to 2026-02-16, every sensor, flagged readings excluded | `python backend/scripts/make_sample_export.py` against the local full-year database built from the council CSVs |

The PDF is produced by the same code as `POST /api/reports/export` (`export.gather` + `export.render`).
It contains **aggregated values only** (per-sensor means, minimums, maximums, completeness, and the two
exceedance days), no raw readings. The data is Maribyrnong City Council sensor data: keep this file in
the private repository unless the council agrees to wider sharing.

Regenerating changes the "generated" time on the first page; the numbers change only if the data does.
