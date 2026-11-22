# BUILD PROMPT — Maribyrnong Environmental Equity Dashboard

> **How to use this file:** Open this project folder in Claude Code (or another coding agent) and say:
> *"Read BUILD_PROMPT.md and start Phase 0. Stop at the end of each phase so we can review."*
> Work one phase at a time. After each phase, every team member should read the code and the DECISIONS.md entries so you can explain them in your report, video and viva. Marks in this unit are "subject to student's contribution and performance", so you must be able to defend every design choice yourself.

---

## 1. Context (read this first)


**Project:** *Environmental Equity, Urban Heat & Air Quality Analysis.* A secure web dashboard that turns the council's smart-sensor data into decision support: where is it hottest, where is air quality worst, does green infrastructure (parks) help, which communities are most exposed, and where should new sensors go. The unique value is the move **from monitoring to decision support**, so analysis and insights matter as much as charts.

**Already built — do not rebuild:**
- `data_pipeline/` converts the council's raw CSV exports into a validated database. It writes to **Neon PostgreSQL** when `PIPELINE_DATABASE_URL` is set, otherwise to local SQLite. The original CSVs are archived, hash-verified, in a **private Vercel Blob store**.
- `database/` contains the production schema (`01_schema.sql`), the security hardening (`02_security.sql`: least-privilege roles, RLS, append-only audit log, no access for any other role), `verify_security.py` (about 28 automated checks, including a probe that the database refuses unencrypted connections and, once a Blob token is set, that archived files cannot be read anonymously) and encrypted backup/restore scripts. All of it has been run against a TLS-only PostgreSQL 16 server with a non-superuser owner, like Neon, including negative tests that deliberately break each control.
- `vercel.json` sets the Sydney function region and the browser security headers.

**Hosting (fixed):** the React frontend and the FastAPI backend deploy together as **one Vercel project** on one domain (Sydney region `syd1`). The database is **Neon** (Sydney), added through the Vercel Marketplace. Raw files are in a **private Vercel Blob store**. Everything must also run locally without Vercel (`make dev`).

Before writing any code, read these files in order:

1. `data_pipeline/README.md` (pipeline design, data quirks, decisions)
2. `database/README.md` (how the database and raw-file archive are hosted and locked down)
3. `database/01_schema.sql` (the production database the app uses; `data_pipeline/schema_sqlite.sql` is the identical test copy)
4. `database/02_security.sql` (what the `app_user` role may and may not do)
5. `data_pipeline/config.py` (units, valid ranges, thresholds)
6. `data/processed/data_quality_report.md` (what the real data looks like)
7. §7 of this file (security requirements — they apply to every phase)

If Neon is not configured yet, run `python data_pipeline/etl.py --sqlite --rebuild` to work offline.

**Real data facts to design around:**
- 6 sensors, 15 Feb 2025 – 16 Feb 2026, ~192k readings at 10–15 min intervals.
- Sensors measure different variables. `sensor_variables` says which sensor has what. Never show a variable for a sensor that does not measure it.
- Sensor coordinates are **unverified placeholders** (`location_verified = 0`). Show a visible "location unverified" badge; never present them as exact.
- Completeness varies from 26% to 99%. Always show completeness next to averages and grey out invalid (<75%) buckets.
- Libelium humidity is unreliable (saturation). Show a data-quality note when humidity from those sensors is displayed.

## 2. Tech stack (use exactly this unless you record a reason in DECISIONS.md)

| Layer | Choice | Reason |
|---|---|---|
| Backend | **Python 3.11+, FastAPI**, Uvicorn | Same language as the pipeline; auto-generated OpenAPI docs at `/docs` serve as API documentation |
| Hosting | **Vercel**, one project, region `syd1`: the Vite build is served as static files and FastAPI runs as a Python Vercel Function under `/api/*`, on the **same origin**. Point Vercel at the app with `[tool.vercel] entrypoint = "backend.app.main:app"` in `pyproject.toml` (or Vercel's current equivalent; confirm against the Vercel FastAPI docs in Phase 0) | Same origin means no CORS in production and simple `SameSite=Strict` cookies; Sydney keeps latency to Neon low and data in Australia |
| Database | **Neon PostgreSQL** (Sydney), private schema `app`, accessed **only by the backend** via `psycopg` 3 as the `app_user` role on Neon's **pooled** host (`APP_DATABASE_URL`, `sslmode=require`). Tests run against SQLite (`schema_sqlite.sql`) plus an optional Postgres integration suite | Shared, backed-up, encrypted-at-rest relational DB matching the proposal's design; native Vercel integration; scales to zero instead of pausing; least privilege enforced by the database itself |
| DB access | Repository layer with **parameterised queries only** (reuse `data_pipeline/db.py` or SQLAlchemy Core). **Serverless rules:** set `prepare_threshold=None` (PgBouncer transaction pooling); open connections lazily and keep any pool tiny (max 2–3 per instance), because every Vercel instance has its own; never rely on session state (`SET`, temp tables, advisory locks) surviving between transactions | SQL-injection protection; pooler compatibility; avoids exhausting Neon connections |
| Raw file storage | **Private Vercel Blob store** via `data_pipeline/storage.py` (Python `vercel` SDK). On Vercel it authenticates with short-lived OIDC tokens automatically; `BLOB_READ_WRITE_TOKEN` only for laptops/CI, **server-side only** | Provenance of every reading (Data Governance); no public URLs exist for private blobs |
| Auth | **Our own** bcrypt/argon2 password hashing, **JWT** access tokens (30 min) + refresh, role claims. **Do not use a hosted auth service** (Neon Auth, Clerk, Auth0) | Proposal Algorithms 3 & 4 must be implemented and explainable by the team; risk R18 |
| Security extras | Database-backed rate limiting (`rate_limits` table, shared by all Vercel instances) plus one Vercel Firewall rate-limit rule on login; security headers + CSP in `vercel.json`; **mandatory TOTP MFA for administrators** (`pyotp`); `cryptography` (Fernet) for MFA secrets | Proposal: rate limiting, Essential Eight MFA; in-memory limiters such as `slowapi` cannot see other serverless instances; see §7 |
| PDF export | `reportlab` (server-side) with a matplotlib chart embedded | UC3 PDF reports |
| Frontend | **React 18 + Vite + TypeScript**, React Router, TanStack Query | Standard, well-documented, fast dev loop |
| Map | **Leaflet** (`react-leaflet`) + OpenStreetMap tiles | Free, no API key; municipal map with markers + heat layer |
| Charts | **Recharts** (time series, bar, box-style) + a custom SVG calendar/hour-of-day heatmap | Covers time-series and heat-map requirements |
| Styling | Tailwind CSS, accessible colour palette (WCAG AA contrast), light/dark | Usability NFR |
| Tests | `pytest` + `httpx` TestClient (backend), Vitest + React Testing Library (frontend), **Playwright** end-to-end | Rubric: "thorough testing"; Playwright also auto-captures user-manual screenshots |
| Run | **Deployed:** the Vercel URL. **Local:** `make dev` (Uvicorn + Vite dev server with a `/api` proxy, so local is also same-origin) against SQLite or a Neon `dev` branch. Docker is optional, not required | Markers can use the live site or run it themselves |

## 3. Target repository structure

```
/
├── BUILD_PROMPT.md            (this file)
├── README.md                  (setup + run in <5 commands, demo logins)
├── DECISIONS.md               (architecture decision log: date, decision, options, reason)
├── .env.example               (exists — copy to .env, never commit .env)
├── vercel.json                (exists — region + security headers; add rewrites/functions config in Phase 0)
├── pyproject.toml             (Vercel Python entrypoint + backend dependencies)
├── Makefile                   (make dev / test / lint)
├── .github/workflows/         (nightly-backup.yml exists; add ci.yml, security.yml)
├── data/ data_pipeline/       (exists)
├── database/                  (exists — Neon schema, security, verification, backup)
├── backend/
│   ├── app/
│   │   ├── main.py            (app factory, middleware, routers)
│   │   ├── config.py          (settings from .env, never hard-coded secrets)
│   │   ├── db.py
│   │   ├── security.py        (hashing, JWT, role guard dependency)
│   │   ├── routers/           (auth, sensors, readings, analysis, reports, admin, ingest)
│   │   ├── services/          (query builder, analysis, export, ingestion validation)
│   │   └── schemas.py         (Pydantic request/response models)
│   ├── scripts/seed_users.py
│   └── tests/
├── frontend/
│   ├── src/{pages,components,api,hooks,lib}
│   └── tests/
├── api/blob-upload.ts         (tiny Node function: issues admin-only Blob client-upload tokens, §4.5)
├── e2e/                       (Playwright tests + screenshot script)
└── docs/
    ├── USER_MANUAL.md
    ├── TECHNICAL_IMPLEMENTATION.md
    ├── screenshots/
    ├── diagrams/              (Mermaid: architecture, ERD, sequences — update from proposal)
    ├── security/              (evidence: verify_security output, test reports, restore test)
    ├── POSTER_CONTENT.md
    └── VIDEO_SCRIPT.md
```

## 4. Functional requirements (from the approved proposal — implement all)

Use the **exact user-facing messages in quotes**; they come from the proposal's use cases, and matching them demonstrates traceability.

### 4.1 Authentication & roles (UC1, Algorithms 3–4)
- Login by email + password → JWT. Roles from DB: *General User*, *Environmental Analyst*, *System Administrator* (permissions in `roles.permissions`).
- Invalid → "Invalid email or password". **5 consecutive failures → 15-minute lock** and message prompting the user to contact the administrator.
- Deactivated → "Your account has been deactivated. Please contact your administrator."
- First login (`must_change_password = 1`) → forced password change screen (min 12 chars, strength meter, common-password check — SEC-05).
- **Administrators must enrol and use TOTP MFA** (authenticator app) before any admin page works (SEC-07).
- Expired token → redirect to login with "Your session has expired. Please log in again."
- Every protected endpoint uses a `require_permission("...")` dependency (Algorithm 4). Non-admin hitting admin routes → **HTTP 403** and UI "You do not have permission to access this page."
- Log every login/logout/failure to `audit_log`.
- Seed script creates three demo accounts (one per role) with passwords from `.env`, printed in README for markers.

### 4.2 Dashboard (UC2)
Layout: **map (left/top) · filter panel · visualisation panel**. Must be usable on a laptop at 1366×768 and on a tablet.
- **Map:** all active sensors as markers coloured by the selected variable's latest value (colour scale + legend). Unverified locations get a dashed outline. Clicking a marker opens the **sensor panel**: name, land use, latest readings with units, "last updated" timestamp (local time), completeness badge, link to the sensor's history page.
- **Filter panel:**
  - Variable dropdown built from `sensor_variables` (temperature, humidity, PM1, PM2.5, PM10, NO₂, CO, CO₂, pressure — with units).
  - Time resolution: **Hourly · Daily · Monthly · Seasonal** + **custom date range** calendar (bounded to data range).
  - Land-use checkboxes: Residential, Industrial, Parkland, Transport corridor, Commercial.
  - Sensor search by code or name (typeahead). "Sensor not found." if no match.
  - Toggle: "Exclude flagged readings" (qc_flags), default on for charts.
  - **Apply Filter** and **Reset** buttons. Show a loading indicator during requests.
- Errors: "No data available for the selected filters." / "Invalid date range selected." / timeout after 5 s → "The request is taking longer than expected. Please try again." / network failure → retry message advising to contact the system administrator.
- **Visualisations:**
  1. Multi-sensor **time-series** line chart (one line per sensor, threshold reference lines, invalid buckets greyed).
  2. **Spatial heat map**: map colour/heat layer for the filtered period's mean per sensor.
  3. **Temporal heat map**: hour-of-day × month grid (diurnal and seasonal patterns).
  4. **Threshold alerts** panel: list of exceedance days from `exceedances`, sortable, with a badge count.
  5. Summary cards: mean / min / max / completeness for the selection.

### 4.3 Insights page (the project's unique value — proposal "Project Aims")
A page written for council planners (non-technical) that computes and explains, from the database:
1. **Long-term trends:** monthly mean per variable per sensor with a simple linear trend and its direction.
2. **Spatial disparities:** ranking of sensors by mean temperature, hot-day count, PM2.5 mean and exceedance days, grouped by land use.
3. **Seasonal & daily patterns:** seasonal means; average diurnal curve per sensor (hour-of-day).
4. **Green infrastructure effect:** compare **Parkland** sensors vs non-park sensors on matched hours (only hours where both have valid data). Show mean difference in °C, the difference during hot afternoons (12:00–18:00 on hot days), and a plain-English caveat about sample size and placement bias.
5. **Equity lens:** highlight sensitive receptors (e.g. Saltwater Childcare Centre) and their exposure relative to others.
6. **Sensor network recommendations:** flag sensors with <75% completeness, variables not fitted, and land-use categories with no/one sensor → suggested placements.
7. **Recommendations list** generated from rules (e.g. "Parkland sites were on average X °C cooler during hot afternoons → prioritise canopy near <hottest sensor>"). Each recommendation shows the evidence number it is based on.
Every number on this page must come from a query; never hard-code findings. Include a "Methodology & limitations" expander.

### 4.4 Export & reports (UC3, Algorithm 2)
- **Export** button disabled with tooltip "Please apply a filter before exporting." until a filter is applied.
- Format prompt: **CSV** (the filtered, aggregated rows, with units in headers, plus a metadata header block: filters, generated time, data source, completeness caveat) or **PDF** (title, filters, summary table sorted by mean descending as in Algorithm 2 with Normal/Threshold exceeded status, chart image, exceedance list, data-quality notes, page numbers).
- Over 50,000 rows → warning "This export contains a large amount of data and may take a moment to prepare." with confirm/cancel.
- Success: "Your export is ready." Failure: "Export failed. Please try again or contact your administrator."
- Log to `reports` and `audit_log` (user, time, filters, format).

### 4.5 Administration (UC5 + user and threshold management)
- **Sensor management** (admin only): list, register, edit, decommission (soft: `status='Inactive'`, history retained, confirm dialog).
  - Validation: unique name → "A sensor with this name already exists. Please use a unique name."; coordinates must be decimal degrees inside Maribyrnong bounds (approx. lat −37.835 to −37.760, lon 144.840 to 144.925) → red fields and "Please enter valid GPS coordinates within the municipality boundary."; land use from list; auth key shown **once** on creation and stored hashed.
  - Success: "Sensor registered successfully"; marker appears on map immediately.
  - Admins can tick **location verified** after confirming with the council.
- **User management:** create, deactivate/reactivate, change role, reset password (forces change on next login).
- **Threshold management:** edit threshold values with a required reason; keep history (threshold change log, risk R24) and recompute exceedances.
- **Data quality page** (Analyst + Admin): per-sensor completeness calendar, error_log browser with filters, ingestion run history, flag counts. Reuse the queries from `write_quality_report` in `etl.py`.
- **CSV upload:** council exports are 2–21 MB, but **Vercel rejects function request bodies over 4.5 MB**, so the file must not pass through FastAPI. Use a Vercel Blob **client upload**:
  1. The browser calls `upload()` from `@vercel/blob/client` with `access: 'private'` and `handleUploadUrl: '/api/blob-upload'`.
  2. `api/blob-upload.ts` (the only Node function) uses `handleUpload`. In `onBeforeGenerateToken` it forwards the request's cookies to `GET /api/auth/check?permission=manage_sensors` and refuses unless that returns 200. It also restricts `allowedContentTypes` to CSV, sets `maximumSizeInBytes` to 50 MB, and puts the file under `uploads/` with a random suffix. The Python SDK cannot issue client-upload tokens, which is why this one route is Node.
  3. The browser then calls `POST /api/admin/ingest-upload {pathname}`. FastAPI downloads the blob, validates it (SEC-20), archives the original with `storage.upload_raw`, calls `etl.ingest_file`, then rebuilds aggregates **for that sensor only** (add a `sensor_id` filter to `build_aggregates`), and shows the run summary. Give this route `maxDuration` 300 s (the Hobby maximum) and test it with the largest real file (21 MB); if it cannot finish well inside the limit, hand the job to a GitHub Actions `workflow_dispatch` run and show its status instead. Delete the `uploads/` copy afterwards.
- All admin actions → `audit_log`.

### 4.6 Sensor ingestion API (UC4)
`POST /api/ingest` for live devices: header `X-Device-Id` + `X-Device-Key` (compared to `auth_key_hash`), JSON body `{timestamp (ISO-8601), temperature, humidity, pm25, pm10, ...}`.
- Unknown device/bad key → **401**, logged with source IP.
- **Reuse the validation logic from `data_pipeline/etl.py`** (refactor shared rules into an importable module if needed, so batch and live ingestion use one rule set).
- Out-of-range → value logged to `error_log`, **HTTP 200** returned (no alert loops). Duplicate → ignored, logged, 200. Inactive sensor → rejected.
- Update the affected hourly/daily aggregates incrementally and check thresholds.
- Provide `scripts/simulate_sensor.py` that replays a day of real readings to this endpoint (for the demo video).

## 5. API contract (extend the proposal's table; all JSON; all documented in OpenAPI)

| Method & path | Role | Purpose |
|---|---|---|
| POST `/api/auth/login`, `/api/auth/refresh`, `/api/auth/logout`, `/api/auth/change-password` | public / any | UC1 |
| POST `/api/auth/mfa/setup`, `/api/auth/mfa/verify` | any (required for admins) | SEC-07 |
| GET `/api/me` | any | current user + permissions |
| GET `/api/sensors` | any | list with latest values, variables, completeness |
| GET `/api/sensors/{id}` | any | detail + latest readings |
| GET `/api/readings` | any | `variable, resolution(hour/day/month/season/raw), start, end, land_use[], sensor_ids[], exclude_flagged` → series per sensor (auto-select `aggregates` table; raw only for ≤7 days) |
| GET `/api/analysis/summary`, `/trends`, `/diurnal`, `/green-infrastructure`, `/disparities`, `/recommendations` | any | Insights page |
| GET `/api/exceedances` | any | threshold alerts |
| POST `/api/reports/export` | export_data | CSV/PDF stream |
| GET/POST/PUT/DELETE `/api/admin/sensors` | manage_sensors | UC5 |
| GET/POST/PUT `/api/admin/users` | manage_users | user admin |
| GET/PUT `/api/admin/thresholds` | manage_thresholds | R24 |
| GET `/api/quality/*` | view_quality | data-quality page |
| GET `/api/auth/check?permission=` | any | 200/403 only; used by `api/blob-upload.ts` to authorise client uploads |
| POST `/api/blob-upload` | manage_sensors (via check) | issues a short-lived private Blob client-upload token (Node function) |
| POST `/api/admin/ingest-upload` | manage_sensors | ingest a CSV already uploaded to Blob |
| POST `/api/ingest` | device key | UC4 |
| GET `/api/health` | public | uptime check |

Standard error body: `{ "error": { "code": "...", "message": "<user-facing message>" } }`.

## 6. Non-functional requirements (verify each with a test or measurement, and record results)
- **Performance:** dashboard filter responses < 3 s at p95; ingestion < 2 s. Write `backend/tests/test_performance.py` that times the key endpoints on the full year of data and prints p50/p95/p99; record results in the technical doc. Also measure the **deployed** site with a small script: report warm p95 separately from the first request after idle. Neon compute and Vercel functions both start cold after inactivity, so the first request is slower. Explain this honestly in the technical doc rather than hiding it.
- **Security:** see **§7 Security requirements**. Every SEC item is mandatory, has a named test, and maps to the proposal's risks and the Essential Eight.
- **Privacy (APP / Privacy Act 1988):** collect only name/email/role; never log passwords or tokens; privacy notice link in the footer.
- **Usability & accessibility:** keyboard navigable, labelled form controls, colour-blind-safe palettes, units on every number, plain-English tooltips for PM2.5, NEPM, completeness, etc. A first-time user should manage core tasks without training.
- **Data governance:** never mutate `readings` values from the app; all changes go through audit-logged admin actions.
- **Maintainability:** type hints, docstrings on every public function, small modules, linting (`ruff`, `eslint`, `prettier`), and CI (GitHub Actions running all tests on push).
- Target **≥80% backend test coverage** (`pytest --cov`) and report it.

## 7. Security requirements

Every item below is a **mandatory task with a named test**. Status key:
- **DONE**: implemented and tested in the starter project. Do not remove it; extend it where noted.
- **BUILD**: the coding agent implements it in the phase shown.
- **PLATFORM**: provided by Neon, Vercel or GitHub. Record the evidence (settings screenshot, documentation link) in `docs/security/`.

Backend security tests live in `backend/tests/security/` and must run in CI. The two mapping tables at the end of this section (proposal risks R17–R20, and the ACSC Essential Eight) are copied into `docs/TECHNICAL_IMPLEMENTATION.md` §6 with the actual test results filled in.

### 7.1 Transport security

| ID | Requirement → task | Test / evidence | Phase | Status |
|---|---|---|---|---|
| SEC-01 | **HTTPS only.** Vercel serves HTTPS and redirects HTTP automatically (PLATFORM). `vercel.json` adds `Strict-Transport-Security: max-age=31536000; includeSubDomains`. Every external URL the app uses (Blob, OSM tiles) is `https://`. | `test_security_headers.py::test_hsts_header` (against the app, plus a post-deploy smoke test against the live URL); `verify_security.py` SEC-01 (Blob URL); SSL Labs grade screenshot of the deployed site | 0, 7 | DONE (`vercel.json`) / BUILD (tests) / PLATFORM |
| SEC-02 | **Encrypted database connections.** Remote URLs without `sslmode=require` or with a default password are refused by our code, and Neon refuses non-TLS connections server-side. | `test_remote_url_without_tls_is_refused` (pipeline); `verify_security.py` SEC-02 attempts an `sslmode=disable` connection with each role's real credentials and **must be refused** (negative-tested: it FAILS when the server allows plaintext). The backend must call `validate_postgres_url` at start-up: `test_config.py::test_backend_refuses_insecure_db_url` | 0 | DONE (pipeline + check) / BUILD (backend) |
| SEC-03 | **Authenticated, replay-resistant device ingestion (UC4).** 256-bit random device key, shown once, stored as a SHA-256 hash and compared in constant time (`hmac.compare_digest`). Reject payloads with a timestamp more than ±5 minutes from server time, and payloads from inactive sensors. | `test_ingest_security.py`: `::test_bad_key_401_and_logged_with_ip`, `::test_stale_timestamp_rejected`, `::test_replayed_payload_is_duplicate`, `::test_decommissioned_sensor_rejected`, `::test_key_not_stored_in_plaintext` | 6 | BUILD |

### 7.2 Authentication

| ID | Requirement → task | Test / evidence | Phase | Status |
|---|---|---|---|---|
| SEC-04 | **Password storage.** bcrypt (cost ≥ 12) or argon2id; never log, return or store plaintext. | `test_auth.py::test_password_is_hashed`, `::test_hash_uses_strong_params` | 1 | BUILD |
| SEC-05 | **Password policy.** Minimum 12 characters; reject passwords on a bundled common-password list (top 10,000) and passwords containing the username or email. Forced change on first login and after an admin reset. | `test_auth.py::test_short_password_rejected`, `::test_common_password_rejected`, `::test_first_login_forces_change` | 1 | BUILD |
| SEC-06 | **Brute-force and enumeration protection.** Lock the account for 15 minutes after 5 failures. Unknown email and wrong password return the **same message and status**, and roughly the same response time (hash a dummy password for unknown emails). | `test_auth.py::test_lockout_after_5_failures`, `::test_unknown_email_same_response_as_wrong_password` | 1 | BUILD |
| SEC-07 | **MFA for administrators (TOTP).** Admins must enrol an authenticator app before any `manage_*` permission works. The TOTP secret is stored Fernet-encrypted (`MFA_ENCRYPTION_KEY`) in `users.mfa_secret_encrypted`. Codes are single-use within their 30-second window. | `test_mfa.py::test_admin_without_mfa_gets_403_on_admin_routes`, `::test_wrong_code_rejected`, `::test_code_reuse_rejected`, `::test_secret_encrypted_at_rest` | 1 | BUILD |
| SEC-08 | **Token lifecycle.** Access JWT 30 minutes; refresh token 8 hours, rotated on every use. Each token has a `jti`; logout, password change and deactivation add it to `revoked_tokens`. Validate signature, `exp`, `iss`/`aud` and the algorithm (pin HS256 or RS256, reject `none`). Purge expired `revoked_tokens` rows daily. | `test_tokens.py::test_expired_token_401`, `::test_revoked_token_401_after_logout`, `::test_alg_none_rejected`, `::test_tampered_token_rejected`, `::test_deactivated_user_token_rejected` | 1 | BUILD |
| SEC-09 | **Browser token storage + CSRF.** Tokens go in `HttpOnly; Secure; SameSite=Strict` cookies (same origin on Vercel makes `Strict` workable), never in `localStorage` or JSON bodies read by JavaScript. State-changing requests require a CSRF token (double-submit cookie + `X-CSRF-Token` header). | `test_csrf.py::test_post_without_csrf_header_403`, `::test_login_sets_httponly_secure_cookie`; Playwright `e2e/security.spec.ts::no tokens in localStorage` | 1 | BUILD |

### 7.3 Authorisation and governance

| ID | Requirement → task | Test / evidence | Phase | Status |
|---|---|---|---|---|
| SEC-10 | **Deny by default.** Every route declares a `require_permission(...)` dependency. Only `/api/health`, `/api/auth/login` and `/api/ingest` (device auth) are public. | `test_rbac.py::test_every_route_is_protected` enumerates `app.routes` and fails if any route outside the allow-list lacks the dependency | 1 | BUILD |
| SEC-11 | **Role × endpoint permission matrix** (proposal R19: "maintain permission matrix, automated access tests"). Keep `docs/security/permission_matrix.md` in sync with the tests. | `test_rbac.py::test_permission_matrix`: one parametrised case per (role, endpoint), asserting 200/403/401. Also checks that a General User cannot escalate their role via `PUT /api/admin/users/{self}` | 1, 5 | BUILD |
| SEC-12 | **Tamper-evident audit trail.** Log logins, failures, exports, queries and every admin action. `audit_log` and `threshold_history` are append-only (no grants plus a trigger that blocks even `postgres`). `app_user` cannot UPDATE or DELETE readings, or DELETE users. | `verify_security.py` SEC-12 (8 checks); `test_audit.py::test_admin_actions_logged`, `::test_export_logged` | DB: 0; app: 1–5 | DONE (database) / BUILD (app logging) |

### 7.4 Database, storage and hosting platform

| ID | Requirement → task | Test / evidence | Phase | Status |
|---|---|---|---|---|
| SEC-13 | **No public database access.** Tables live in the private `app` schema; RLS is on for every table; `PUBLIC` has no `CONNECT` on the database; no role other than the owner and the three app roles can connect or use `app`; Neon's **Data API stays disabled**. Add `.github/workflows/security.yml` running `verify_security.py` weekly (proposal R20: "monthly posture scans"). | `verify_security.py` SEC-13: RLS on all 15 tables; intruder-role check; Data API roles absent. Negative test performed: adding an `intruder` role, disabling RLS on one table or creating an `anonymous` role each makes the script FAIL | 0 | DONE |
| SEC-14 | **Least-privilege database roles.** The backend connects as `app_user` (pooled host), the pipeline as `pipeline_user` and backups as `backup_user` (direct host). **Never** as `neondb_owner`, and never with the `DATABASE_URL` Vercel injects for the owner: delete or ignore those injected variables. `app_user` has a 5-second `statement_timeout` (matches UC2) and a connection limit. | `verify_security.py` SEC-14: no superuser/createrole/createdb/bypassrls/`neon_superuser` membership; cannot create, alter or drop tables; pipeline cannot read `users` or `audit_log`; `test_config.py::test_backend_refuses_owner_role` (start-up fails if the URL's user is the schema owner) | 0 | DONE (DB) / BUILD (backend check) |
| SEC-15 | **Private raw-file archive.** Originals live in a **private** Vercel Blob store as `raw/<sha256>__<name>`, are never overwritten, and are hash-verified on download. Private blobs have no public URL. If the UI offers raw-file download, stream it through an admin-only FastAPI route with `Cache-Control: private, no-store`; never expose the blob URL or token to the browser. Client uploads (§4.5) are issued only after an admin permission check, CSV only, ≤ 50 MB. | `test_upload_is_private_and_never_overwrites`, `test_download_verifies_integrity`, `test_object_name_strips_directories`; `verify_security.py` SEC-15: the store is private, an anonymous GET of an archived file is refused; `test_blob_upload.py::test_non_admin_cannot_get_upload_token` (BUILD) | 0, 5 | DONE (archive) / BUILD (upload route) |
| SEC-16 | **Secrets management.** Secrets only in `.env` (git-ignored), **Vercel environment variables** (mark them *Sensitive*; separate Preview and Production values), GitHub Actions secrets and the team password manager. The Blob token and the owner/pipeline/backup URLs are never given to the Vercel project; on Vercel, Blob access uses OIDC. Settings fail fast at start-up if a secret is missing or still a placeholder. Enable GitHub secret scanning + push protection; add a `gitleaks` pre-commit hook and CI job. Document the rotation procedure in `docs/security/secret_rotation.md`. | `verify_security.py` SEC-16; `test_config.py::test_missing_jwt_secret_fails_startup`; CI step: `grep -rE "neon\.tech|BLOB_READ_WRITE|vercel_blob_rw" frontend/dist` must find nothing; gitleaks CI green | 0 | DONE (checks) / BUILD (CI, backend) |
| SEC-17 | **Encryption at rest.** Neon encrypts all data at rest with AES-256 (PLATFORM). Backups are additionally encrypted by us (SEC-18). MFA secrets are field-encrypted (SEC-07). For the Blob store, cite only what Vercel's current documentation states about encryption at rest; do not assume. | Evidence: Neon security documentation link + project region screenshot in `docs/security/`; Vercel Blob documentation link | 0 | PLATFORM |
| SEC-18 | **Regular, tested, encrypted backups.** Nightly `pg_dump` of `app` by the read-only `backup_user` over Neon's direct host, encrypted with AES-256 (PBKDF2, 200k iterations), with a SHA-256 checksum and 30-day retention. The key is stored separately from the backups. Test a restore at least twice (progress report, final submission). | `database/backup/restore_test.sh` (restores into a scratch DB and compares row counts: verified with 192,256 readings); `verify_security.py` SEC-18: backup role is read-only; nightly workflow run history | 0, 7 | DONE (scripts) / BUILD (enable workflow, record restore tests) |

### 7.5 Input, output and browser security

| ID | Requirement → task | Test / evidence | Phase | Status |
|---|---|---|---|---|
| SEC-19 | **Injection prevention.** Parameterised SQL only. Identifiers (column or variable names) come from allow-lists such as `CANONICAL_UNITS`, never from user input. Validate every request with Pydantic (types, enums, date ranges, max list sizes). | `test_injection.py`: SQL-injection payloads in every filter parameter (`' OR 1=1--`, `pm25; DROP TABLE`, unicode tricks) return 422/400 and the DB is unchanged; `ruff` rule `S608` (SQL string building) enabled in CI | 2 | BUILD |
| SEC-20 | **Safe file upload.** Admin CSV upload (via Blob client upload, §4.5): 50 MB limit and CSV-only content type enforced when the upload token is issued; then FastAPI re-checks the size, sniffs the content, requires a header matching a known device family, and parses with pandas only (never executed). Server-generated pathnames only (no path traversal). Rate limited. The `uploads/` copy is deleted after ingestion. | `test_upload.py::test_oversize_rejected`, `::test_non_csv_rejected`, `::test_path_traversal_filename_neutralised`, `::test_unknown_columns_rejected`, `::test_non_admin_403` | 5 | BUILD |
| SEC-21 | **CSV formula-injection protection.** In exports, prefix any cell starting with `= + - @` (or tab or carriage return) with `'`, following OWASP guidance, so Excel does not execute it. | `test_export.py::test_formula_cells_escaped` (sensor named `=HYPERLINK(...)`) | 4 | BUILD |
| SEC-22 | **XSS and browser hardening.** Rely on React escaping; ban `dangerouslySetInnerHTML` (ESLint `react/no-danger` = error). Headers come from `vercel.json` (already written): `Content-Security-Policy` (`default-src 'self'`; `script-src 'self'`; `img-src 'self' data: https://*.tile.openstreetmap.org`; `connect-src 'self'` plus the Vercel Blob upload hosts; `frame-ancestors 'none'`; `object-src 'none'`), `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `Permissions-Policy`, `X-Frame-Options: DENY`. Keep the CSP as tight as the working app allows; if the Blob client upload needs another host, add exactly that host and record why. Run the same headers in local dev (FastAPI middleware or the Vite server) so tests see them. | `test_security_headers.py::test_csp_present`, `::test_nosniff`; post-deploy smoke test reads the live headers; ESLint CI; Playwright `security.spec.ts::sensor name with <script> renders as text` and `::no CSP violations in console` | 0, 3 | DONE (`vercel.json`) / BUILD |
| SEC-23 | **Rate limiting / abuse.** Login 5/min/IP, ingest 60/min/device, export 10/min/user, upload 5/hour/admin. Implement with the **`rate_limits` table** (fixed window, `INSERT ... ON CONFLICT DO UPDATE SET hits = hits + 1 RETURNING hits`, purge old windows daily), because each Vercel instance has its own memory. Add one **Vercel Firewall** rate-limit rule on `POST /api/auth/login` as an outer layer (Hobby allows one rule per project). Use the client IP from Vercel's `x-forwarded-for`/`x-real-ip` header, never a client-supplied header. Return 429 with a user-friendly message. | `test_rate_limit.py::test_login_429_after_limit`, `::test_export_429`, `::test_limit_shared_across_two_app_instances` (two TestClients, one database); Firewall rule screenshot | 1, 2 | BUILD / PLATFORM |
| SEC-24 | **Safe error handling.** A global exception handler returns `{error:{code,message}}` with no stack traces, SQL or file paths; full details go to the server log with a correlation ID shown to the user. `DEBUG` off outside development. | `test_errors.py::test_500_has_no_stacktrace`, `::test_error_includes_correlation_id` | 0 | BUILD |
| SEC-25 | **CORS.** Production is same-origin, so the backend sends **no** CORS headers there. Local development allows only `ALLOWED_ORIGINS` (the Vite dev server); credentials only for listed origins; never a wildcard. | `test_security_headers.py::test_no_cors_headers_in_production`, `::test_disallowed_origin_no_cors_headers` | 0 | BUILD |

### 7.6 Supply chain, platform, monitoring and privacy

| ID | Requirement → task | Test / evidence | Phase | Status |
|---|---|---|---|---|
| SEC-26 | **Patch applications.** Pin dependencies (lock files); Dependabot for pip, npm and GitHub Actions; CI runs `pip-audit` and `npm audit --audit-level=high` and **fails on high/critical findings**. Patch critical issues within 48 hours and others within 2 weeks; record exceptions in DECISIONS.md. | CI job `security.yml` green; Dependabot PR history; `docs/security/dependency_audit.md` snapshot at submission | 0 | BUILD |
| SEC-27 | **Security logging without secrets.** Log auth events, 401/403 bursts, lockouts, ingest rejections and admin actions. Never log passwords, tokens, keys or full connection strings (use `redact`). Flag more than 20 failed logins in 10 minutes as a suspicious-activity entry, shown on the admin data-quality page (proposal R18 "anomaly detection", basic level). | `test_redact_hides_password` (DONE); `test_logging.py::test_password_never_logged` (capture logs during login); `::test_failed_login_burst_flagged` | 1, 7 | DONE (pipeline) / BUILD |
| SEC-28 | **Patch operating systems / runtimes.** Vercel patches the function runtime and Neon patches the database servers (PLATFORM). Pin the Python version (`.python-version`) and Node version (`engines`), and move to supported versions when the platforms deprecate old ones. If you add Docker for local use, pin slim base images, run as non-root and scan with Trivy. | Platform documentation links in `docs/security/`; runtime versions recorded in the technical doc; Trivy CI job only if Docker is used | 0 | PLATFORM / BUILD |
| SEC-29 | **Privacy (Privacy Act 1988 / APPs) and breach readiness.** Collect only name, email and role. Add a privacy notice page (purpose, storage location in Sydney, access and correction). Admins can deactivate users and export a user's data on request. Write `docs/security/incident_response.md`: steps for a suspected breach, key rotation, and assessing notification under the Notifiable Data Breaches scheme. | `test_privacy.py::test_user_endpoint_returns_minimal_fields`; document review checklist in DoD | 7 | BUILD |
| SEC-30 | **Deployment and environment separation.** Turn on Vercel **Deployment Protection** so preview URLs need a Vercel login. Preview deployments use a separate Neon `dev` branch and their own secrets; production secrets exist only in the Production environment. Production deploys only from `main` after CI passes (branch protection, required checks). | Screenshots of Deployment Protection and environment variable scopes; GitHub branch-protection screenshot; `verify_security.py` run against the `dev` branch | 0 | PLATFORM / BUILD |

### 7.7 Mapping to proposal risks R17–R20

| Risk (proposal) | Proposal mitigation | Implemented by | Evidence | Honest scope note |
|---|---|---|---|---|
| **R17** Unencrypted or insecure transmission exposes sensor metadata or user information | HTTPS/TLS 1.2+, reject HTTP, encrypt sensor-to-cloud flows, rotate certificates quarterly, intrusion detection | SEC-01, SEC-02, SEC-03, SEC-09 | Header tests, live plaintext-refusal probe (`verify_security.py`), TLS-refusal unit tests, SSL Labs screenshot | Certificates are managed and auto-renewed by Vercel and Neon (PLATFORM), not rotated manually. A full intrusion-detection system is out of scope; SEC-27 provides basic suspicious-activity detection. |
| **R18** Weak authentication or token leakage compromises access | Short-lived JWT, MFA, secrets vault, API key rotation every 90 days, anomaly detection | SEC-04 – SEC-09, SEC-16, SEC-23, SEC-27 | `test_auth`, `test_mfa`, `test_tokens`, `test_csrf`, gitleaks CI | A password manager, Vercel *Sensitive* environment variables and GitHub secrets replace a dedicated vault; Blob access on Vercel uses short-lived OIDC tokens, which rotate automatically. Rotation is a documented procedure plus a rotate-device-key admin action, not a scheduled 90-day job. |
| **R19** RBAC misconfiguration exposes sensitive dashboards | Permission matrix, quarterly audits, automated access tests, log admin actions | SEC-10, SEC-11, SEC-12, SEC-14 | `test_every_route_is_protected`, `test_permission_matrix`, `verify_security.py` SEC-12/14 | Automated tests run on every push, which is stronger than a quarterly manual audit. |
| **R20** Cloud storage misconfiguration exposes data | Block public access, encrypt at rest, monthly posture scans, least privilege | SEC-13, SEC-14, SEC-15, SEC-16, SEC-17, SEC-18, SEC-30 | `verify_security.py` (database checks + private-Blob probe), weekly `security.yml`, negative-test results | Posture scanning is our own targeted script, not a commercial CSPM tool. |

### 7.8 Mapping to the ACSC Essential Eight

The Essential Eight is written for Microsoft Windows-based networks. We apply each strategy **by analogy** to a cloud web application and target **Maturity Level One** where it applies. Say this explicitly in the technical document rather than claiming full compliance.

| Essential Eight strategy | How it applies to this system | Controls | Evidence | Status |
|---|---|---|---|---|
| Patch applications | Python/npm dependencies, GitHub Actions | SEC-26 | `security.yml` audits, Dependabot history | BUILD |
| Patch operating systems | Vercel function runtime and Neon servers are patched by the platforms; we pin and update runtime versions | SEC-28 | Platform documentation; runtime versions in the technical doc | PLATFORM |
| Multi-factor authentication | App administrators; Vercel, Neon and GitHub team accounts | SEC-07 (+ setup guide) | `test_mfa.py`; screenshots of MFA enabled on Vercel/Neon/GitHub accounts | BUILD |
| Restrict administrative privileges | App RBAC, admin-only MFA, least-privilege DB roles, owner role never used by the app, Blob token server-only, preview protection | SEC-10, SEC-11, SEC-14, SEC-16, SEC-30 | RBAC tests; `verify_security.py` SEC-14 | DONE (DB) / BUILD (app) |
| Application control | Web analogue: only allow-listed scripts run in the browser (CSP); only locked, audited dependencies are installed | SEC-22, SEC-26 | CSP header test; lock files | BUILD (partial, by analogy) |
| Restrict Microsoft Office macros | **Not applicable** (no Office documents are produced or processed). Closest related control: CSV exports cannot trigger Excel formulas | SEC-21 | `test_formula_cells_escaped` | N/A |
| User application hardening | Harden the browser attack surface; disable unused platform features (Neon Data API) | SEC-01, SEC-09, SEC-13, SEC-22, SEC-25 | Header tests; Data API disabled screenshot | DONE (headers, database) / BUILD |
| Regular backups | Nightly encrypted backups, 30-day retention, restore tested, read-only backup role, key stored separately | SEC-18 | `restore_test.sh` output; workflow history | DONE (scripts) / BUILD (schedule + records) |

### 7.9 Security evidence pack (for the technical document and the video)
Maintain `docs/security/` containing:
- the latest `database_verification.md`;
- pytest security suite output;
- dependency audit output;
- restore test logs (dated);
- the permission matrix;
- platform screenshots (Neon and Vercel regions, private Blob store, Data API off, Deployment Protection, environment-variable scopes, Firewall rule, MFA on accounts);
- `secret_rotation.md` and `incident_response.md`.

The demo video should show three short security moments: an admin MFA prompt, a General User receiving "You do not have permission to access this page.", and `verify_security.py` passing.

## 8. Build phases (stop after each for team review)

| Phase | Deliverable | Done when |
|---|---|---|
| **0 · Setup** | Repo skeleton, README, DECISIONS.md, CI (tests, lint, gitleaks, pip-audit/npm audit), backend `/api/health`, settings validation (incl. refusing the owner role), security headers in local dev, CORS for dev only, global error handler; frontend shell with routing. Neon + private Blob set up per `database/README.md`. **Deploy a hello-world of the real structure to Vercel first** (static frontend + FastAPI `/api/health` on one domain, region `syd1`, headers from `vercel.json` visible) before building features, and record the working configuration in DECISIONS.md. **Security:** SEC-01, 02, 13–18, 22, 24–26, 28, 30 | `make dev` runs both; the Vercel URL serves the shell and `/api/health`; CI green; `verify_security.py` all PASS against Neon |
| **1 · Auth & RBAC** | UC1 complete, seed users, role guard, admin MFA, cookies + CSRF, token revocation, audit logging, login/change-password/MFA UI. **Security:** SEC-04–12, 23, 27 | security tests for these IDs pass |
| **2 · Data API** | sensors, readings (all resolutions), exceedances endpoints on Neon as `app_user` (pooled host). **Security:** SEC-19, 23 | API, injection and performance tests pass, locally and against the deployed site |
| **3 · Dashboard** | map, filter panel, 5 visualisations, sensor panel, all UC2 messages. **Security:** SEC-22 (frontend) | Playwright: login → filter → chart renders; XSS spec passes |
| **4 · Export** | CSV + PDF, all UC3 behaviours. **Security:** SEC-21 | export tests; sample PDF committed to `docs/` |
| **— 80% checkpoint —** | **Progress report demo.** Phases 0–4 done and polished = all key user functionality working, security foundations in place | Record a 2-min demo; first restore test logged; update diary |
| **5 · Admin** | sensors, users, thresholds (+ history), data-quality page, CSV upload via Blob client upload (§4.5). **Security:** SEC-11, 12, 15, 20 | UC5 tests, upload security tests, admin E2E; the 21 MB council file ingests on the deployed site |
| **6 · Insights & ingestion** | Insights page (§4.3), `/api/ingest`, simulator. **Security:** SEC-03 | analysis unit tests; ingest security tests |
| **7 · Hardening** | full security suite, live `verify_security.py`, second restore test, SEC-27/29 docs, security evidence pack (§7.9), accessibility pass, empty/error/loading states, coverage ≥80% | all tests green; every SEC item DONE or PLATFORM with evidence |
| **8 · Documentation** | §10 deliverables | marker can install and use the app from docs alone |

At the start of each phase, restate the plan in 5–10 bullets. At the end: run all tests, update `DECISIONS.md`, and list anything deferred.

