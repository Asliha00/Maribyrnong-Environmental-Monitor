-- Maribyrnong Environmental Monitoring System - relational schema (SQLITE VERSION)
-- Used for offline development and automated tests only.
-- The production database is Neon PostgreSQL: see database/01_schema.sql.
-- KEEP BOTH FILES IN SYNC: same tables, same columns, same constraints.
-- Table names follow the proposal's Database Design section.

PRAGMA foreign_keys = ON;

-- ---------- Access control (proposal: User Table, Roles Table) ----------
CREATE TABLE IF NOT EXISTS roles (
    role_id      INTEGER PRIMARY KEY,
    role_name    TEXT NOT NULL UNIQUE,
    permissions  TEXT NOT NULL            -- comma-separated permission keys
);

CREATE TABLE IF NOT EXISTS users (
    user_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username             TEXT NOT NULL UNIQUE,
    email                TEXT NOT NULL UNIQUE,
    password_hash        TEXT NOT NULL,   -- bcrypt/argon2, never plaintext
    role_id              INTEGER NOT NULL REFERENCES roles(role_id),
    is_active            INTEGER NOT NULL DEFAULT 1,
    must_change_password INTEGER NOT NULL DEFAULT 1,  -- UC1 first-login flow
    failed_attempts      INTEGER NOT NULL DEFAULT 0,  -- UC1 lock after 5
    locked_until         TEXT,
    mfa_enabled          INTEGER NOT NULL DEFAULT 0,  -- SEC-07: mandatory for administrators
    mfa_secret_encrypted TEXT,                        -- TOTP secret, encrypted by the backend
    mfa_last_used_step   INTEGER,                     -- SEC-07: last accepted TOTP time step (no code reuse)
    tokens_valid_after   TEXT,                        -- SEC-08: tokens issued before this are rejected
    last_login_at        TEXT,
    created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

INSERT OR IGNORE INTO roles (role_id, role_name, permissions) VALUES
 (1, 'General User',          'view_data,filter_data,export_data'),
 (2, 'Environmental Analyst', 'view_data,filter_data,export_data,view_quality'),
 (3, 'System Administrator',  'view_data,filter_data,export_data,view_quality,manage_sensors,manage_users,manage_thresholds');

-- ---------- Sensors (proposal: Sensor Table) ----------
CREATE TABLE IF NOT EXISTS sensors (
    sensor_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sensor_code        TEXT NOT NULL UNIQUE,
    sensor_name        TEXT NOT NULL UNIQUE,  -- UC5: duplicate names rejected
    device_family      TEXT NOT NULL,
    hardware_id        TEXT,
    latitude           REAL,
    longitude          REAL,
    location_verified  INTEGER NOT NULL DEFAULT 0,
    land_use           TEXT NOT NULL,         -- Residential | Industrial | Parkland | Transport corridor | Commercial
    installation_date  TEXT,
    status             TEXT NOT NULL DEFAULT 'Active',  -- Active | Inactive (decommissioned)
    auth_key_hash      TEXT,                  -- UC4 device authentication (live ingestion)
    notes              TEXT,
    first_reading_utc  TEXT,
    last_reading_utc   TEXT,
    sensitive_receptor INTEGER NOT NULL DEFAULT 0   -- e.g. a childcare centre (Insights equity lens)
);

-- Which variables each sensor actually measures (drives the UI variable dropdown)
CREATE TABLE IF NOT EXISTS sensor_variables (
    sensor_id   INTEGER NOT NULL REFERENCES sensors(sensor_id),
    variable    TEXT NOT NULL,
    unit        TEXT NOT NULL,
    raw_column  TEXT NOT NULL,
    PRIMARY KEY (sensor_id, variable)
);

-- ---------- Readings (proposal: Environmental Readings Table, extended) ----------
CREATE TABLE IF NOT EXISTS readings (
    reading_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    sensor_id      INTEGER NOT NULL REFERENCES sensors(sensor_id),
    ts_utc         TEXT NOT NULL,   -- ISO-8601 UTC, e.g. 2025-07-15T04:00:00Z
    ts_local       TEXT NOT NULL,   -- ISO-8601 with Melbourne offset, for display
    temperature_c  REAL,
    humidity_pct   REAL,
    pm1            REAL,
    pm25           REAL,
    pm10           REAL,
    no2_ppb        REAL,
    co_ppb         REAL,
    co2_ppm        REAL,
    pressure_hpa   REAL,
    aqi            REAL,
    battery_v      REAL,
    qc_flags       TEXT,            -- e.g. "humidity_saturated;pm10_spike"
    ingestion_run_id INTEGER REFERENCES ingestion_runs(run_id),
    UNIQUE (sensor_id, ts_utc)      -- duplicate rule from Algorithm 1
);
CREATE INDEX IF NOT EXISTS idx_readings_sensor_ts ON readings(sensor_id, ts_utc);
CREATE INDEX IF NOT EXISTS idx_readings_ts ON readings(ts_utc);

-- ---------- Error log (proposal: Error_Log Table) ----------
-- One row per rejected VALUE (or rejected row), never silently discarded.
CREATE TABLE IF NOT EXISTS error_log (
    error_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    sensor_id    INTEGER REFERENCES sensors(sensor_id),
    ts_utc       TEXT,
    error_type   TEXT NOT NULL,   -- out_of_range | not_fitted | duplicate | invalid_timestamp | unknown_sensor
    variable     TEXT,
    raw_value    TEXT,
    description  TEXT,
    ingestion_run_id INTEGER REFERENCES ingestion_runs(run_id),
    logged_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_error_sensor ON error_log(sensor_id, error_type);

-- ---------- Pre-computed aggregates (proposal: Data Aggregation) ----------
-- Long format: one row per sensor x period x bucket x variable.
CREATE TABLE IF NOT EXISTS aggregates (
    sensor_id          INTEGER NOT NULL REFERENCES sensors(sensor_id),
    period             TEXT NOT NULL,   -- hour | day | month
    bucket_start_local TEXT NOT NULL,   -- e.g. 2025-07-15 14:00 / 2025-07-15 / 2025-07
    season             TEXT NOT NULL,   -- Summer | Autumn | Winter | Spring (southern hemisphere)
    variable           TEXT NOT NULL,
    mean               REAL,
    min                REAL,
    max                REAL,
    n                  INTEGER NOT NULL,
    completeness_pct   REAL,
    is_valid           INTEGER NOT NULL,  -- completeness >= 75%
    qc_mode            TEXT NOT NULL DEFAULT 'all' CHECK (qc_mode IN ('all','clean')),
                                          -- all: every kept value; clean: QC-flagged values left out (DECISIONS D-028)
    PRIMARY KEY (sensor_id, period, bucket_start_local, variable, qc_mode)
);
CREATE INDEX IF NOT EXISTS idx_agg_lookup_qc ON aggregates(period, variable, qc_mode, bucket_start_local);

-- ---------- Thresholds & exceedances (proposal: threshold alerts, risk R24) ----------
CREATE TABLE IF NOT EXISTS thresholds (
    threshold_id INTEGER PRIMARY KEY AUTOINCREMENT,
    variable     TEXT NOT NULL,
    period       TEXT NOT NULL,     -- day (mean) | day_max
    operator     TEXT NOT NULL,     -- > | >=
    value        REAL NOT NULL,
    label        TEXT NOT NULL,
    source       TEXT,
    updated_by   INTEGER REFERENCES users(user_id),
    updated_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE (variable, period, value)
);

-- Append-only history of threshold changes (risk R24, SEC-12)
CREATE TABLE IF NOT EXISTS threshold_history (
    history_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    threshold_id INTEGER NOT NULL REFERENCES thresholds(threshold_id),
    old_value    REAL,
    new_value    REAL NOT NULL,
    reason       TEXT NOT NULL,
    changed_by   INTEGER REFERENCES users(user_id),
    changed_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS exceedances (
    sensor_id          INTEGER NOT NULL REFERENCES sensors(sensor_id),
    threshold_id       INTEGER NOT NULL REFERENCES thresholds(threshold_id),
    date_local         TEXT NOT NULL,
    observed_value     REAL NOT NULL,
    completeness_pct   REAL,
    PRIMARY KEY (sensor_id, threshold_id, date_local)
);

-- ---------- Governance: ingestion runs, reports, audit ----------
CREATE TABLE IF NOT EXISTS ingestion_runs (
    run_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file    TEXT NOT NULL,
    file_sha256    TEXT NOT NULL,
    sensor_id      INTEGER REFERENCES sensors(sensor_id),
    rows_read      INTEGER,
    rows_inserted  INTEGER,
    rows_duplicate INTEGER,
    values_rejected INTEGER,
    values_flagged INTEGER,
    storage_path   TEXT,            -- pathname of the original file in the private Vercel Blob store
    started_at     TEXT NOT NULL,
    finished_at    TEXT
);

CREATE TABLE IF NOT EXISTS reports (          -- proposal: Report Table
    report_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER REFERENCES users(user_id),
    report_type  TEXT NOT NULL,
    format       TEXT NOT NULL,     -- csv | pdf
    filter_json  TEXT NOT NULL,
    row_count    INTEGER,
    created_date TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    file_path    TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (        -- logins, queries, exports, admin changes
    audit_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER REFERENCES users(user_id),
    action      TEXT NOT NULL,
    detail_json TEXT,
    ip_address  TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- Revoked JWTs (logout / password change) until they would have expired (SEC-08)
CREATE TABLE IF NOT EXISTS revoked_tokens (
    jti        TEXT PRIMARY KEY,
    user_id    INTEGER REFERENCES users(user_id),
    expires_at TEXT NOT NULL
);

-- Shared rate-limit counters (SEC-23); see database/01_schema.sql
CREATE TABLE IF NOT EXISTS rate_limits (
    bucket       TEXT NOT NULL,
    window_start TEXT NOT NULL,
    hits         INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (bucket, window_start)
);

-- Single-use 2FA recovery codes (SEC-07, D-037); see database/01_schema.sql
CREATE TABLE IF NOT EXISTS mfa_recovery_codes (
    code_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    selector   TEXT NOT NULL,
    code_hash  TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    used_at    TEXT,
    revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_mfa_recovery_codes_user ON mfa_recovery_codes (user_id, selector);
