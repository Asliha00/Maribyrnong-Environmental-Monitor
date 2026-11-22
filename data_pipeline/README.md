# Data Pipeline: Raw Council CSV → Structured Database

This pipeline converts the raw Ubidots CSV exports supplied by Maribyrnong City Council into a validated relational database that the website's API reads from.

## Where the data lives

| What | Where | Why |
|---|---|---|
| Original council CSVs (unchanged) | Private Vercel Blob store, `raw/<sha256>__<name>` | Source of truth; SHA-256 in the pathname makes tampering detectable |
| Clean readings, aggregates, users, audit log | Neon PostgreSQL (Sydney), private schema `app` | One shared database for the team, the website and the markers |
| Offline copy for development and tests | Local SQLite `data/processed/environment.db` | Works without internet; used by the automated tests |

The pipeline chooses its target from `.env`. If `PIPELINE_DATABASE_URL` is set, it writes to Neon; otherwise it writes to local SQLite. The same code, SQL and validation rules run in both cases. The results were verified to be identical: 192,256 readings, 355,070 aggregate rows and 99 exceedance days on both, with the PostgreSQL load run as the restricted `pipeline_user` against a TLS-only server.

## Quick start

```bash
pip install -r data_pipeline/requirements.txt
cp .env.example .env    # fill in Neon + Blob values (see database/README.md), or leave the DB URL empty for SQLite
# put the council CSV exports in data/raw/
python data_pipeline/etl.py --upload-raw --export-csv   # Neon: archive originals in Blob + load
python data_pipeline/etl.py --sqlite --rebuild           # local offline copy
pytest data_pipeline/tests -v
```

A full load of the six supplied files (~192,000 readings) takes about 20 seconds locally; over the internet to Neon, expect longer. Use Neon's **direct** host for the pipeline, not the `-pooler` host. Run it from a laptop or GitHub Action, never inside a Vercel function. Outputs:

| File | Purpose |
|---|---|
| `data/processed/environment.db` | Local SQLite copy (only when running against SQLite) |
| `data/processed/data_quality_report.md` | Auto-generated evidence of what was cleaned and why |
| `data/processed/readings_clean.csv` | Clean readings (with `--export-csv`) for notebooks / Excel |
| `data/processed/aggregates_daily_monthly.csv` | Daily and monthly summaries (with `--export-csv`) |

## What the raw data looks like

Each file is one sensor, exported from the Ubidots IoT platform, covering 15 Feb 2025 – 16 Feb 2026. Every variable appears as three columns: `created_at_<var>` (upload time), `context_<var>` (always `{}`), and `<var>` (the value). The `timestamp` column is the device measurement time in epoch milliseconds.

There are three device families with different variables and units:

| Family | Sensors | Interval | Variables | Unit quirks |
|---|---|---|---|---|
| `mcc_aq` | MCC-01, MCC-02 | 10 min | temperature, humidity, PM1/2.5/10, NO₂, CO, CO₂, AQI (+ device "last hour" averages) | NO₂/CO assumed ppb |
| `libelium` | Footscray Park ×2, Saltwater Childcare | 15 min | temperature, humidity, PM1/2.5/10, NO₂, CO₂, pressure, battery | NO₂ in **ppm**, pressure in **Pa** |
| `lora_r270` | Nicholson Mall Clock Tower | 15 min | temperature, pressure, battery | pressure already hPa |

**The raw files contain no location data.** Coordinates and land-use categories live in `config/sensors.csv`. Current values are approximate placeholders with `location_verified = 0`; confirm them with the council and update the file (or via the website's admin panel).

## Pipeline stages

The pipeline follows **Extract → Transform/Validate → Load → Aggregate**, implemented in `etl.py`.

1. **Sensor registry sync** (`sync_sensor_registry`). Upserts `config/sensors.csv` into the `sensors` table. Each raw file is matched to a sensor by a filename substring; an unmatched file is logged as `unknown_sensor` and skipped (proposal Algorithm 1, step 1).
2. **Timestamp parsing.** `timestamp` (epoch ms) is converted to UTC. `created_at_*` is ignored because on the MCC units it is upload time and lags the measurement by up to ~20 minutes. Readings are stored as `ts_utc` (for querying) and `ts_local` (Australia/Melbourne, DST-aware, for display). Unparseable timestamps are logged as `invalid_timestamp` (Algorithm 1, step 2).
3. **Column mapping and unit conversion.** Raw columns are mapped to canonical names with units in the column name (`no2_ppb`, `pressure_hpa`) so no one has to guess units later. Libelium NO₂ is ×1000 (ppm→ppb) and pressure ×0.01 (Pa→hPa). Device-computed `*lasthour` columns are dropped so every sensor is averaged by the same method.
4. **Duplicate removal.** Same sensor + same second → first record kept, duplicate logged (Algorithm 1, step 4). The database also enforces `UNIQUE(sensor_id, ts_utc)`.
5. **"Not fitted" detection.** If ≥95% of a column is exactly 0, the sensor module is treated as absent rather than reporting perfectly clean air. The column is nulled and one summary error is logged. This caught CO₂ on both Footscray Park units.
6. **Range validation** (Algorithm 1, step 3). Values outside physically plausible ranges (`config.VALID_RANGES`) are set to null and each one is logged to `error_log` with its raw value. Temperature, humidity, PM2.5 and PM10 ranges are taken directly from the proposal's pseudocode.
7. **Quality flags.** Suspicious but possible values are **kept** and marked in `qc_flags`:
   - `humidity_saturated`: humidity = 100%. The Libelium units sit at 100% for 33–55% of all readings, which indicates condensation on the sensor rather than real conditions.
   - `temperature_flatline`: identical temperature for ≥12 consecutive readings (a frozen sensor).
   - `pm*_spike`: value > 10× the local rolling median and above a floor. Flagged rather than deleted because smoke and traffic events are real and are exactly what the council wants to see (proposal risk R10).
8. **Archive and load.** With `--upload-raw`, the original file is first stored in the private Vercel Blob store as `raw/<sha256>__<filename>`. It is never overwritten; `--from-storage` re-downloads the files and verifies each hash. Readings are then inserted with `ON CONFLICT DO NOTHING`, recording which `ingestion_run` produced each row and where the original is stored. On PostgreSQL, rows are bulk-loaded with `COPY` into a temporary table and then inserted, because PostgreSQL does not allow `COPY` directly into tables protected by row-level security. Each file's SHA-256 is recorded, so re-running on the same file does nothing (idempotent).
9. **Aggregation** (`build_aggregates`). Hourly, daily and monthly mean/min/max/count per sensor per variable, bucketed in **local** time so a "day" is a Melbourne calendar day. Each bucket gets a `completeness_pct` (readings received ÷ readings expected) and `is_valid = completeness ≥ 75%`. Saturated humidity is excluded from humidity averages. Season uses southern-hemisphere months.
10. **Exceedances.** Valid daily aggregates are compared with the `thresholds` table (NEPM 24-hour PM2.5 and PM10 standards, and hot/extreme-heat day triggers). Thresholds live in the database so administrators can change them with an audit trail (risk R24).
11. **Quality report.** `data_quality_report.md` summarises every rejection and flag per sensor, which is ready-made evidence for the Technical Implementation Document.

## Key design decisions and justification

| Decision | Alternative rejected | Why |
|---|---|---|
| Reject individual values, not whole rows | Proposal's Algorithm 1 returns on first bad value (drops row) | One bad pressure reading would otherwise delete a valid temperature. Documented deviation from the proposal. |
| Flag spikes instead of deleting | Statistical outlier removal | Real pollution events must stay visible (risk R10); analysts can filter flags out. |
| Wide `readings` table, long `aggregates` table | Fully long (EAV) readings | Wide matches the proposal's schema and makes raw export simple; long aggregates let the API serve any variable with one query. |
| Pre-computed aggregates | Aggregate on every request | Meets the proposal's 3-second dashboard target on a year of 10-minute data. |
| 75% completeness rule | Average whatever exists | A daily mean from 3 hours of data is not comparable to a 24-hour standard. Leeds/Hopkins reports only ~26% of expected readings, so most of its days are invalid. This is itself a finding about sensor coverage (risk R09). |
| Neon PostgreSQL for the shared database, SQLite for tests | Local SQLite only; Supabase; MongoDB | One shared, backed-up, encrypted-at-rest (AES-256) database matches the proposal's cloud-hosting and scalability requirements. Neon integrates natively with Vercel, scales to zero instead of pausing, and fits comfortably in the free tier (~125 MB of 512 MB). Supabase's free projects pause after a week idle, a risk during marking. Relational PostgreSQL matches the approved relational design; a document store would contradict it. SQLite keeps tests fast and offline. |
| Private `app` schema, dedicated least-privilege roles | One owner login for everything; Neon's Data API | The owner role can do anything; separate roles mean a leaked app password cannot drop tables, rewrite readings or read the audit log. A private schema, RLS and a disabled Data API leave no route in except through our backend. |
| Archive original CSVs in a private Vercel Blob store | Keep them only on team laptops; store them inside Neon | Provenance (proposal Data Governance): every reading can be traced back to an unchanged, hash-verified original. Blob keeps ~60 MB of files out of the database's 0.5 GB allowance. |
| Units in column names | Separate unit column | Makes unit errors visible in every query and export. |

## Findings from the current data (see the quality report for full numbers)

- **Coverage is uneven.** MCC-01, MCC-02 and Saltwater are ~99% complete; Nicholson Mall ~81% (one ~58-day outage); Footscray Park Amenities ~65%; Leeds/Hopkins ~26%.
- **Libelium humidity is unreliable** because of saturation. Use MCC units for humidity analysis.
- **CO₂ is not fitted** on either Footscray Park unit; Saltwater's CO₂ baseline (~380 ppm) sits slightly below global background, suggesting a calibration offset.
- **Error codes exist**: Nicholson Mall reports 356,597.83 hPa / 122.88 °C together twice (removed).
- **Units need council confirmation**: MCC NO₂/CO units, and all sensor locations.

## Security built into the pipeline

| Control | Where | Test |
|---|---|---|
| Remote database connections must use TLS (`sslmode=require`) and a non-default password | `db.validate_postgres_url` | `test_remote_url_without_tls_is_refused` |
| Passwords are redacted from printed connection strings | `db.redact` | `test_redact_hides_password` |
| The pipeline connects as `pipeline_user`, which cannot read users or the audit log | `database/02_security.sql` | `database/verify_security.py` |
| Originals are stored privately and never overwritten | `storage.py` | `test_upload_is_private_and_never_overwrites`, `test_object_name_strips_directories` |
| Downloaded originals are hash-verified | `storage.download_raw` | `test_download_verifies_integrity` |
| The SQL operator taken from the thresholds table is allow-listed before use | `build_aggregates` | covered by the end-to-end test |

## Adding new data later

Drop a new export into `data/raw/` and run `python data_pipeline/etl.py --upload-raw`. Already-ingested files are skipped, overlapping readings are ignored by the unique constraint, and aggregates are rebuilt. To add a new sensor, add a row to `config/sensors.csv` with a `file_match` substring from its filename.
