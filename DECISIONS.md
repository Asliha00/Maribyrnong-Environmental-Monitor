# Architecture Decision Log

One entry per decision: date, decision, options considered, reason. Newest last.

---

## D-001 · 2026-10-27 · Repository root is the starter folder
- **Decision:** the git repository root is `maribyrnong-env-starter/`.
- **Options:** the parent folder `D:\Maribyrnong Environmental Monitor` (which also holds a copy of BUILD_PROMPT.md and an older quality report) · the starter folder.
- **Reason:** `data_pipeline/config.py` and `database/verify_security.py` resolve the project root as the parent of their own folder, so the starter folder must be the root. The parent folder's copies are left outside the repository.

## D-002 · 2026-10-27 · Security headers have one source: `vercel.json`
- **Decision:** the backend reads the `headers` rules from `vercel.json` at start-up and applies them to every response (`backend/app/middleware.py`).
- **Options:** copy the headers into Python (two copies that can drift) · set them in the Vite dev server (tests would not see them) · read `vercel.json`.
- **Reason:** SEC-22 requires the same headers locally so tests can check them. One source means the tested CSP is exactly the deployed CSP; `test_csp_present` asserts equality.

## D-003 · 2026-10-27 · Backend start-up refuses unsafe configuration
- **Decision:** `Settings` (pydantic-settings) fails at start-up when `JWT_SECRET` is missing, short or a placeholder; when `MFA_ENCRYPTION_KEY` is not a valid Fernet key; when `ALLOWED_ORIGINS` contains `*`; when `APP_DATABASE_URL` lacks TLS (reusing `data_pipeline/db.validate_postgres_url`), still has `.env.example` placeholders, or names an owner role (`neondb_owner`, `postgres`, `*_owner`). In production the URL is required and the user must be `app_user`.
- **Reason:** SEC-02, SEC-14, SEC-16. A deployment that is misconfigured should not start at all.

## D-004 · 2026-10-27 · Python dependencies in `requirements.txt` (superseded by D-011)
- **Decision:** runtime dependencies pinned with `==` in `requirements.txt`; dev tools in `requirements-dev.txt`; `pyproject.toml` holds project metadata and pytest/ruff/coverage settings. The Vercel entrypoint setting is decided when the Vercel deployment is configured (Phase 0, Vercel step) after checking current Vercel docs.
- **Reason:** pinned files give reproducible builds and simple `pip-audit -r` (SEC-26); Dependabot updates them.

## D-005 · 2026-10-27 · `make` targets wrap Python scripts
- **Decision:** `make dev` runs `scripts/dev.py` (starts Uvicorn and Vite, stops both on Ctrl+C); `make env` runs `scripts/init_env.py`.
- **Reason:** BUILD_PROMPT requires `make dev`, but GNU make is not installed on our Windows machines. The scripts work everywhere; the Makefile documents the plain command next to each target.

## D-006 · 2026-10-27 · Frontend tooling versions
- **Decision:** React 18.3 (as BUILD_PROMPT §2 specifies, although 19 is current), React Router 7 (`react-router` package), TanStack Query 5, Tailwind 4, Vite 8, Vitest 5, **ESLint 9** (not 10).
- **Reason:** `eslint-plugin-react` 7.37 supports ESLint ≤ 9 only, and we need its `react/no-danger` rule for SEC-22. Revisit when the plugin supports ESLint 10.

## D-007 · 2026-10-27 · ruff security rules on new code; starter pipeline findings recorded, not rewritten
- **Decision:** CI runs `ruff` with the `S` (bandit) rules, including S608, on `backend/` and `scripts/`. `data_pipeline/` and `database/` are not linted in CI yet.
- **Reason:** ruff reports 25 findings in the starter pipeline, 7 of them S608 (SQL built with f-strings). In each case the interpolated parts are table/column names from code constants, and values are still bound as parameters. BUILD_PROMPT §11.2 says not to rewrite pipeline logic without a recorded reason. **TODO (team):** review each S608 site and either add a justified `# noqa: S608` or refactor, then add the pipeline to CI linting.

## D-008 · 2026-10-27 · Nightly backup workflow: skip until secrets exist; scripts executable
- **Decision:** a small `check-secrets` job lets `nightly-backup.yml` skip, not fail, until `BACKUP_DATABASE_URL` and `BACKUP_ENCRYPTION_KEY` are set. The backup scripts are marked executable in git (`100755`).
- **Reason:** without these fixes the starter workflow would fail every night (no secrets yet, and "permission denied" because files committed from Windows lose the executable bit).

## D-009 · 2026-10-27 · `/api/health` reports database reachability
- **Decision:** the public health route runs `SELECT 1` and returns only `ok`/`unavailable`, with no versions or hostnames.
- **Reason:** it proves the deployed function reaches Neon. Note that health probes wake Neon from scale-to-zero, which is acceptable.

## D-010 · 2026-10-27 · Vercel deployment uses Vercel Services (beta)
- **Decision:** `vercel.json` defines two services in one project: `web` (Vite, root `frontend/`, SPA fallback to `index.html`) and `api` (FastAPI, root `.`, `entrypoint: "backend.app.main:app"`). Top-level rewrites send `/api/*` to `api` and everything else to `web`. Region `syd1` and the security headers stay top-level. The `api` bundle excludes the frontend, tests and data folders (`excludeFiles`). `.vercelignore` keeps `.env`, `.venv` and council CSVs out of CLI uploads.
- **Options:** (a) `[tool.vercel] entrypoint` in `pyproject.toml` with FastAPI serving the built frontend (`app.frontend()`); (b) Vercel Services; (c) two Vercel projects.
- **Reason:** Vercel's FastAPI docs (checked 2026-10-27, page dated 2026-08-27) point to Services for "Deploy with a frontend". It keeps one origin (SEC-09 cookies, no CORS), builds the frontend with its own Node toolchain, and leaves room for the Phase 5 Node `blob-upload` route as a third service. (c) would break same-origin. Services is **beta** (available on all plans): risk accepted, fallback is (a).
- **Why the api root is the repo root:** the backend imports `data_pipeline/db.py` and reads `vercel.json`; Vercel's docs do not say that files outside a service root are bundled.
- **Python manifest:** see D-011 (the first build showed Vercel reads `pyproject.toml`).

## D-011 · 2026-10-27 · `pyproject.toml` is the single Python dependency manifest
- **Decision:** pinned runtime dependencies live in `[project].dependencies`, dev tools in `[project.optional-dependencies].dev`. `requirements.txt` and `requirements-dev.txt` are deleted. Local install: `pip install -e ".[dev]"`. Audit: `pip-audit .`. `[tool.setuptools] packages = []`, because the code runs from the repository root, so installing the project installs only its dependencies.
- **Evidence:** the first Vercel build (commit `5bda2ab`) logged "Installing required dependencies from pyproject.toml..." and ignored `requirements.txt`. The `pyproject.toml` it read had no dependencies, so `/api/health` returned 500.
- **Reason:** one list that Vercel, CI, local installs and pip-audit all read; nothing can drift. This also matches BUILD_PROMPT §3 ("pyproject.toml: Vercel Python entrypoint + backend dependencies").

## D-012 · 2026-10-27 · Python 3.12 minimum; `uv.lock` committed
- **Decision:** `requires-python = ">=3.12"`, and `uv.lock` (generated with `uv lock`) is committed.
- **Evidence:** the second Vercel build failed in `uv lock`: pinned `numpy==2.5.4` requires Python ≥ 3.12, but the project declared ≥ 3.11. Vercel already runs 3.12 (from `.python-version`), and so do our laptops and CI.
- **Reason:** BUILD_PROMPT asks for "3.11+", and 3.12 satisfies it. The lock file pins every transitive dependency, so Vercel builds are reproducible (SEC-26 "lock files"). After changing dependencies, run `uv lock` (`pip install uv`).

## D-013 · 2026-10-27 · Working Vercel configuration (hello-world) and temporary `ENVIRONMENT=test`
- **Working setup:** project `asli6/maribyrnong-environmental-monitor`, imported from GitHub (production deploys from `main`). Services `web` + `api` as in D-010; dependencies from `uv.lock` (D-011, D-012); function and edge in `syd1` (response header `X-Vercel-Id: syd1::syd1::…`). Evidence: `docs/security/vercel_hello_world_2026-10-27.md`.
- **Environment variables:** `JWT_SECRET` and `MFA_ENCRYPTION_KEY` are generated per environment (Production and Preview get different values) and stored as *Sensitive*. They were piped straight from a generator into `vercel env add`, so no one has seen them.
- **Temporary:** `ENVIRONMENT=test` on Production and Preview until Neon is connected, because `production` correctly refuses to start without `APP_DATABASE_URL` (D-003). `test` sends no CORS headers and reports the database as unavailable. **Must be switched to `production` in the Neon step.**
- **Observed, accepted:** Vercel adds `Access-Control-Allow-Origin: *` to static frontend files by default. These files are public and the browser sends no credentials for them; the API (`/api/*`) sends no CORS headers (SEC-25 test passes live).
- **Known gap (deferred to Phase 2):** `/api/docs` (Swagger UI) loads its JavaScript from a CDN, which our CSP (`script-src 'self'`) blocks. Self-host the Swagger assets or document the API from `/api/openapi.json`. Do not loosen the CSP.

## D-014 · 2026-10-27 · Neon set up; production credentials kept out of the everyday `.env`
- **Done:** Neon project created through the Vercel Marketplace in AWS Sydney (`ap-southeast-2`, PostgreSQL 18.6). `01_schema.sql` and `02_security.sql` were applied as the owner (each in one transaction; executed with psycopg because `psql` is not installed here). `app_user`, `pipeline_user` and `backup_user` were given 43-character random passwords (`secrets.token_urlsafe(32)`). The owner variables the integration injects exist only in the Vercel **Development** environment; Production holds `APP_DATABASE_URL` as `app_user` on the pooled host (Sensitive) and `ENVIRONMENT=production`.
- **Decision:** the role URLs, owner URL and `BACKUP_ENCRYPTION_KEY` live in a separate git-ignored file, `.env.neon`, loaded only for deliberate production operations (verify, data loads, backups). The everyday `.env` stays in SQLite mode.
- **Reason:** `data_pipeline/config.py` makes `PIPELINE_DATABASE_URL` the default target, so keeping it in `.env` would make every casual `etl.py` run write to the production database. BUILD_PROMPT §2 says local development uses SQLite or a Neon `dev` branch.
- **Data load:** `etl.py --upload-raw` as `pipeline_user`: 192,256 readings, 355,070 aggregate rows, 99 exceedance days (identical to SQLite); 6 originals archived as `raw/<sha256>__<name>` in the private Blob store, authenticated with the short-lived Vercel OIDC token from `vercel env pull`.

## D-015 · 2026-10-27 · Backup workflow uses the PostgreSQL 18 client
- **Reason:** Neon runs PostgreSQL 18.6, and `pg_dump` must be at least the server version (the workflow's own note). The starter installed client 17.

## D-016 · 2026-10-27 · `neon_service` role failed SEC-13; Neon Auth disabled (CLOSED by D-017)
- **Finding:** `verify_security.py` reports 26 PASS, 1 FAIL, 1 SKIP. The FAIL: Neon role `neon_service` (member of `neon_superuser` and `neon_auth`; LOGIN, CREATEROLE, BYPASSRLS) can CONNECT and use schema `app`. It arrived with **Neon Auth**, which the integration enabled automatically (also creating schema `neon_auth` and role `neon_auth`). BUILD_PROMPT §2 forbids hosted auth services.
- **Action:** disable Neon Auth in the Neon console, re-run verification. If `neon_service` remains as a Neon platform role, decide (with evidence) whether to exempt it alongside `cloud_admin`/`neon_superuser`. Do not weaken the check without that evidence.

## D-017 · 2026-10-27 · Neon Auth removed; `neon_service` exempted as a Neon platform role, conditionally
- **What happened:** the Vercel → Neon integration enabled **Neon Auth** (Managed Better Auth) by default. Its console page said "Anyone on the web can sign up for your app" and stored users in schema `neon_auth` of our production database, outside our app and audit log. It also added roles `neon_auth` and `neon_service`. BUILD_PROMPT §2 forbids hosted auth. We disabled it in the Neon console with "delete data". Neon removed the `neon_auth` schema some minutes later. Its endpoint now returns errors, and the Vercel `NEON_AUTH_*` variables were removed. A sample table created by the Neon SQL editor (`public.playing_with_neon`, 20 demo rows) was also dropped.
- **What remained:** roles `neon_auth` (no access to our database: CONNECT false, USAGE on `app` false) and `neon_service` (LOGIN, CREATEROLE, BYPASSRLS; member of `neon_superuser`). `neon_service` reaches `app` **only** through `neon_superuser` membership: our ACLs grant it nothing.
- **Decision:** `verify_security.py` treats `neon_service` like Neon's other platform roles (`neon_superuser`, `cloud_admin`, already exempt), but **only while** (a) it is a member of `neon_superuser` and (b) it holds no direct grant on the database, schema `app` or any `app` table. Exact name match only.
- **Options rejected:** dropping or altering the role (Neon-managed: may break the project, and Neon holds its credentials); leaving SEC-13 failing until Neon support responds (blocks Phase 0 for something outside our control).
- **Why this is acceptable:** the provider can always access data it hosts. That trust boundary is already accepted for `cloud_admin`/`neon_superuser` and is covered by Neon's platform controls (SEC-17). Our own roles and grants are still checked without exception.
- **Evidence:** live negative tests N1 (a new intruder role → FAIL) and N2 (a direct grant to `neon_service` → FAIL), both restored to PASS: `docs/security/sec13_negative_tests_2026-10-27.md`. Unit tests in `database/tests/test_verify_security.py`. Final run: 30 passed, 0 failed, 0 skipped (`docs/security/database_verification.md`).
- **Report note:** this is a real example of a cloud default (public sign-up) found by our verification script and removed: proposal risk R20 (cloud misconfiguration).
- **TODO (team):** optionally ask Neon support whether `neon_service` can be removed now that Neon Auth is gone; if it is, remove the exemption.

## D-018 · 2026-10-27 · Preview deployments use a long-lived Neon `dev` branch with its own credentials
- **Decision:** Neon branch `dev` (endpoint `ep-withered-shadow-a7j9ipg3`), created from `main` with data. After branching, `app_user`, `pipeline_user` and `backup_user` on `dev` got new random passwords, kept in git-ignored `.env.neon-dev`. Vercel Preview has `APP_DATABASE_URL` (app_user @ dev pooled, Sensitive) and `ENVIRONMENT=production` (same strict mode as live).
- **Reason:** SEC-30 says previews must never touch the marked data and must have their own secrets. A branch copies roles *and passwords*, so without new passwords a leaked preview credential would open production. A cross-branch login test proves it now cannot. We avoid the integration's automatic per-preview branches because they inject the owner URL (database/README.md).
- **Known limits:** `neondb_owner` has the same password on both branches (Neon-managed; it never goes to Vercel). `dev` is a snapshot of `main` from 2026-10-27. Re-creating it later would also copy real user password hashes (Phase 1+), so treat any re-branch as a decision.
- **Not for restore tests:** `restore_test.sh` drops schema `app` on its target, so it must use a separate scratch branch, never `dev` or `main`.
- **Evidence:** `docs/security/preview_environment_2026-10-27.md`, `docs/security/database_verification_dev_branch.md` (30/30).

## D-019 · 2026-10-27 · Restore tests run in GitHub Actions against a scratch branch with a dedicated role
- **Decision:** `.github/workflows/restore-test.yml` (manual trigger) makes a fresh encrypted backup of production as the read-only `backup_user`, restores it into the Neon branch `restore-scratch` (endpoint `ep-holy-art-a7gjkt8q`), and compares row counts (`database/backup/restore_test.sh`). The target role is `restore_user`, created **only on the scratch branch** (CONNECT + CREATE on the database; checked absent on `main` and `dev`). The workflow refuses to run without a scratch URL or when the target host equals the backup source host.
- **Reason:** the PostgreSQL 18 client tools are not installed on our Windows laptops. GitHub Actions already installs them for the nightly backup, and a run log is dated evidence. Using `neondb_owner` on the scratch branch was rejected because its password is the same on every branch, so it would put the production owner credential into GitHub.
- **Runner pinned to `ubuntu-24.04`** for backup and restore jobs: GitHub is moving `ubuntu-latest` to Ubuntu 26 from 19 October 2026, and the PostgreSQL apt repository may not support a new release immediately.
- **First run (2026-10-27):** stopped by the safety check, "SCRATCH_DATABASE_URL secret not set". No database was touched.
- **Second and third runs:** run 3 failed in the backup step with `pg_dump: error: invalid connection option "BACKUP_DATABASE_URL"`, because the secret had been pasted as the whole `.env` line (`NAME=value`). Added `.github/scripts/check_secrets.sh` to all three database workflows: it fails fast on a `NAME=` prefix, quotes/spaces, or a database URL not starting with `postgresql://`, without printing values. Main reason: a prefixed `BACKUP_ENCRYPTION_KEY` would silently encrypt every backup with the wrong passphrase, making them unrestorable with the stored key.
- **Restore test 1 PASSED (run 40468753825, commit b30e436):** a 7.5 MB encrypted backup passed its checksum; all 8 compared tables restored with identical row counts; RLS (15/15), 30 policies and both append-only triggers were present in the restored copy. Evidence: `docs/security/restore_test_2026-10-27.md`.
- **Recovery runbook note:** the restore uses `--no-privileges`, so after a real recovery, run `02_security.sql` and then `verify_security.py` before pointing the app at the restored database.
- **TODO:** restore test 2 before final submission, once `users` and `audit_log` hold real rows.

## D-020 · 2026-10-27 · Broken `nightly-backup.yml` (invalid YAML) fixed; workflow files now tested
- **What happened:** commit `e1af09e` (D-015, PostgreSQL 18 client) changed a step name to an unquoted value containing `: `, which is invalid YAML. GitHub could not parse the file: it listed the workflow by its path, created a failed run for each of the next 7 pushes, and **no scheduled or manual backup ran** from then until this fix. The restore-test workflow (its own valid file) was unaffected, so restore test 1 stands. The coding agent introduced the error; it was spotted from the GitHub Actions run list.
- **Fix:** step name quoted. New `tests/test_repo_config.py` parses every workflow with PyYAML (now a pinned dev dependency) and checks `vercel.json`. It was shown to fail on the broken file and pass on the fixed one. CI runs it on every push.
- **Lesson:** a scheduled job that cannot start produces no alert of its own. Check the nightly-backup run history (green runs with a `neon-backup-*` artifact) weekly, and record it in the diary.
- **Confirmed:** after the fix, a manual nightly-backup run was green with a `neon-backup-*` artifact (reported by a team member, 2026-10-27).

## D-021 · 2026-10-27 · Dependabot: Actions updated to v7; React 19, React Router 8 and ESLint 10 deferred
- **Applied:** `actions/checkout`, `setup-node`, `setup-python` and `upload-artifact` → v7 in every workflow. Dependabot's 4 PRs were based on an older `main` and conflicted, so the same bumps were applied directly; Dependabot closes PRs whose update is already on `main`. This removes the "Node.js 20 is deprecated" warnings. Confirm on the next CI, nightly-backup and restore-test runs (both backup workflows use upload-artifact).
- **Declined for now (4 PRs):** React 19 + react-dom 19 (BUILD_PROMPT §2 specifies React 18), React Router 8 (belongs with a React upgrade), ESLint 10 (`eslint-plugin-react`, which provides `react/no-danger` for SEC-22, does not support it: D-006). `dependabot.yml` now ignores **major** updates for these packages; minor and patch updates still arrive. Dependabot closed all four itself at 2026-10-27 08:00 UTC, immediately after the ignore rules were pushed ("no longer being updated by Dependabot"), so no `@dependabot ignore` comments were needed. Per PR:
  - **#7** "Bump react and @types/react in /frontend" (18.3.1 → 19.3.1): declined; BUILD_PROMPT §2 specifies React 18, and React 19 must move together with react-dom as one deliberate, recorded upgrade.
  - **#6** "Bump react-dom and @types/react-dom in /frontend" (18.3.1 → 19.3.1): declined; must stay on the same major as react (React 18 per BUILD_PROMPT §2) and cannot be merged on its own.
  - **#8** "Bump react-router from 7.18.4 to 8.5.0": declined; a major router upgrade belongs with any future React 19 decision, not a standalone bump.
  - **#5** "Bump the dev-tooling group" (eslint and @eslint/js 9 → 10): declined; eslint-plugin-react, which enforces `react/no-danger` for SEC-22, does not support ESLint 10 yet (D-006).
- **Applied PRs #1–#4** (upload-artifact, setup-python, setup-node, checkout → v7) were also closed by Dependabot once `main` had the versions. Confirmed in use: nightly-backup run 40610834105 (2026-10-28, commit `ba3fb1b`) passed on `checkout@v7` and `upload-artifact@v7`, artifact `neon-backup-40610834105` (7,809,004 bytes, kept until 2026-11-27).
- **Also:** `.gitignore` now excludes backup files (`*.dump.enc`, `neon-backup-*/`, `backups/`) after a downloaded backup artifact was found inside `docs/security/`. Backups live in GitHub artifact storage (30 days), never in git.

## D-022 · 2026-10-27 · No Neon IP allow-list (accepted risk)
- **Observation:** the Neon project shows "IP restrictions: None set" (`docs/security/screenshots/2026-10-27_neon_project_region_sydney.png`).
- **Decision:** accept for now. Vercel functions on our plan have no fixed outbound IP addresses to allow-list, and IP allow-lists are not part of Neon's free plan as far as we know (to confirm on Neon's pricing page, as database/README.md asks).
- **Mitigation:** every connection needs a role password (43-character random), the server refuses unencrypted connections (SEC-02, live-tested), each role is least-privilege (SEC-14), and credentials are rotated per `docs/security/secret_rotation.md`. Mention this honestly under proposal risk R20 in the technical document.

## D-023 · 2026-10-28 · gitleaks false positive in `.env.example` ignored by fingerprint
- **Finding:** the first manual `security` run failed in `gitleaks`: rule `generic-api-key`, `.env.example` line 27, commit `1dd4e80` (the starter), entropy 3.83, value redacted.
- **Review:** line 27 is `JWT_SECRET=` with **no value**; `.env.example` has not changed since the initial commit. The rule matched across the line break and treated the next line (`MFA_ENCRYPTION_KEY=` plus its help comment) as the secret. No real secret was ever committed, so nothing needed rotating.
- **Decision:** add `.gitleaksignore` with that single fingerprint (commit:file:rule:line) and a comment. Rejected: allow-listing `.env.example` or disabling `generic-api-key`, since either would hide a real secret pasted there later. Any future gitleaks finding is reviewed the same way: rotate first if real, fingerprint-ignore only if proven false.

## D-024 · 2026-10-28 · Branch protection and GitHub secret scanning unavailable on the free private repo
- **Evidence:** `gh api …/branches/main/protection` returns 403 "Upgrade to GitHub Pro or make this repository public"; secret scanning and push protection report `n/a` (`docs/security/github_plan_limits_2026-10-28.md`).
- **Options:** (a) make the repo public: rejected (council project, security evidence); (b) GitHub Pro through the free GitHub Student Developer Pack, then enable a ruleset on `main` requiring the `ci` checks and pull requests; (c) accept with compensating controls.
- **Decision for now:** (c), recorded honestly in the technical document. Compensating controls: `ci` + `security` (including gitleaks over full history) on every push, Vercel's per-deployment history and instant rollback. **TODO (repository owner):** apply for the Student Developer Pack; if granted, enable branch protection/rulesets and push protection, screenshot them, and update this entry.

## D-025 · 2026-10-28 · Phase 1 choices and schema change
- **Team choices (2026-10-28):** password hashing **argon2id** (`argon2-cffi`), OWASP's first choice, memory-hard (SEC-04). Common-password list: **SecLists `10k-most-common.txt`** (MIT licence), bundled in `backend/app/data/` with its source noted (SEC-05). **Demo-admin MFA for markers deferred to Phase 8**; MFA is built strictly now (SEC-07).
- **Schema change (BUILD_PROMPT §11.4):** `users.mfa_last_used_step` (last accepted TOTP time step, so a code cannot be reused inside its 30 s window: SEC-07) and `users.tokens_valid_after` (tokens issued earlier are rejected, so a password change or deactivation ends **every** session, not only the one whose `jti` is revoked: SEC-08). Added to both `database/01_schema.sql` (with idempotent `ALTER TABLE … ADD COLUMN IF NOT EXISTS` for existing databases) and `data_pipeline/schema_sqlite.sql`.
- **Applied** to Neon `main` and `dev` as the owner (01 + 02 re-run); `verify_security.py` **30/30 on both** afterwards (reports refreshed 2026-10-28). The `restore-scratch` branch is not migrated; each restore test recreates its schema from a fresh production backup.

## D-026 · 2026-10-28 · Phase 1 authentication design choices
- **Session length:** access token 30 min; refresh token 8 h, rotated on every use, and the rotated token keeps the **original** expiry, so a session can never exceed 8 h (BUILD_PROMPT gives the lifetimes but not whether rotation extends them; the stricter reading was chosen).
- **Refresh-token reuse = theft:** presenting an already-rotated refresh token ends every session of that user (`tokens_valid_after = now`) and is audited (`refresh_token_reuse`).
- **Token age at millisecond precision:** JWT `iat` carries milliseconds (RFC 7519 allows fractional NumericDate) and `users.tokens_valid_after` is stored to the millisecond; comparisons use integer milliseconds. With whole seconds, a session created in the same second as a password change survived it. The bug was found by `test_password_change_ends_other_sessions` and fixed before release.
- **Permissions re-read per request:** the guard loads the user and role from the database on each request instead of trusting role claims in the token, so deactivation, role changes and password changes apply immediately (one indexed lookup per request).
- **Public routes:** health, login, refresh (authenticated by its own cookie) and logout (must work with an expired access token; only revokes the caller's tokens). Enforced by `test_every_route_is_protected` plus a negative test. CSRF is global; only login and the future device-ingest route are exempt.
- **Lockout vs enumeration trade-off:** unknown emails and wrong passwords return the same 401 message, status and timing (dummy argon2id check). The UC1-required lock message, however, can only appear for an existing account; accepted because the proposal requires that message, and the per-IP rate limit (5/min) bounds probing.
- **Expired-row purge:** `revoked_tokens` and stale `rate_limits` rows are deleted opportunistically on each login, not by a daily scheduler, avoiding an extra secret-protected cron endpoint. Expired tokens are already rejected by their own `exp`, so leftover rows are harmless.
- **MFA key rotation:** `MFA_ENCRYPTION_KEY` may list several Fernet keys (newest first, `MultiFernet`), which resolves the Phase 0 TODO in `secret_rotation.md`.
- **Demo accounts** (`seed_users.py`) start with `must_change_password = 0` so markers can use documented passwords; real accounts created by admins (Phase 5) start with it set.
- **Playwright e2e** runs locally against SQLite with seeded users (`make e2e`). It is not in CI yet: CI has no council data. To add in Phase 3 with a small fixture database.

## D-027 · 2026-10-28 · gitleaks allow-list for invented test passphrases
- **Finding:** `security` run on `8907c75`/`9796807` failed: gitleaks `generic-api-key` flagged three lines in `backend/tests/` holding invented test passphrases (e.g. `Tram-Lantern-Quartz-58`). They are not secrets and have never been used anywhere.
- **Decision:** `.gitleaks.toml` keeps every default rule and adds one allow-list that applies only when **both** the path is under `backend/tests/` or `e2e/` **and** the value matches `Word-Word-Word-NN`. Rejected: fingerprint entries (a new one for every edit of a test line); allow-listing the test folders wholesale (a real key pasted into a test would be missed).
- **Convention:** test passphrases use the `Word-Word-Word-NN` shape; any other secret-like test value must be justified or removed.

## D-028 · 2026-10-28 · "Exclude flagged readings": a clean aggregate variant (pipeline + schema change)
- **Team choice:** aggregates exist in two variants, `qc_mode = 'all'` (unchanged: every kept value; saturated humidity already excluded) and `qc_mode = 'clean'` (also leaves out each value whose **own** variable carries a QC flag: `pmX_spike` → that PM column, `temperature_flatline` → temperature, `humidity_saturated` → humidity). The dashboard toggle (default on for charts) reads `clean`.
- **Options rejected:** computing clean buckets on the fly from raw readings (duplicates the completeness logic in SQL; slower over long ranges); applying the toggle to the raw ≤7-day view only (would not match "default on for charts").
- **Pipeline change (BUILD_PROMPT §11.2):** `build_aggregates` now produces both variants through one helper, `_aggregate_rows`; `flag_hits` maps a flag to its variable by name prefix. The existing `all` rows are byte-for-byte the same counts as before (338,354 hourly, 16,121 daily, 595 monthly). Exceedances, the quality report and the CSV export still read `all`: an official-style exceedance count uses every valid measurement, including possible real smoke events (risk R10). New tests: `test_flag_hits_maps_flags_to_their_own_variable`, `test_clean_aggregates_leave_out_flagged_values`.
- **Schema change (§11.4):** `aggregates.qc_mode` (CHECK `all|clean`) joins the primary key; index `idx_agg_lookup_qc (period, variable, qc_mode, bucket_start_local)` replaces `idx_agg_lookup`. Both schema files; `01_schema.sql` migrates existing databases idempotently.
- **Applied 2026-10-28:** Neon `dev` then `main` (owner: 01 + 02; `pipeline_user`: aggregates rebuilt); `verify_security.py` 30/30 on both. Real-data effect: 563 buckets differ between variants; 13 hourly buckets have no clean data (every value flagged).
- **Revised the same day: sparse clean rows.** The first build stored a full clean copy (710,127 rows) and grew each branch to 277 MB, about double the estimate given when the option was chosen, and close to Neon's free-plan storage with the `dev` branch rewritten too. 354,494 of the 355,057 clean rows were identical to their `all` row. With the team's agreement, `build_aggregates` now stores a clean row **only where it differs** (`_clean_differences`), plus an explicit empty row (`n = 0`, no values, invalid) where a bucket has no clean data. **Readers use the clean row when present and fall back to the `all` row otherwise.** Result: 576 clean rows (355,646 in total), and after `VACUUM (FULL, ANALYZE) app.aggregates` each branch is 124 MB (smaller than before Phase 2, as dead rows from earlier rebuilds were also cleared). Test added: `test_fully_flagged_bucket_gets_empty_clean_row`.
- **Phase 6 note:** live ingestion must update both variants incrementally.

## D-029 · 2026-10-28 · Data API design choices (Phase 2)
- **Endpoints:** `GET /api/meta` (added to the §5 table: filter-panel options), `/api/sensors`, `/api/sensors/{id}`, `/api/readings`, `/api/exceedances`. Permissions per team choice: `filter_data` for `/api/readings`, `view_data` for the rest.
- **Dashboard variables:** the nine of BUILD_PROMPT §4.2. AQI and battery voltage stay in the database but are device diagnostics, not offered on the dashboard. A variable is never returned for a sensor that does not measure it (`sensor_variables`).
- **No dynamic SQL (SEC-19):** every statement is a fixed literal; sensor, land-use and variable filters are applied in Python after one bounded query (6 sensors, so this is cheap), avoiding a dynamically built `IN (...)` list; the reading column is chosen from the `VARIABLES` allow-list.
- **Limits:** raw readings ≤ 7 days (§5). **Hourly ≤ 92 days**: a full year of hourly points for six sensors is ~6 MB of JSON, over Vercel's 4.5 MB function response limit; 92 days measured 1.4 MB. ≤ 20 sensor ids per request. 120 data requests per minute per user (shared database limiter).
- **Seasons:** built from daily rows of the requested range, one bucket per actual season (December belongs to the summer that ends the next year, e.g. "Summer 2025–26"); mean weighted by reading count; completeness = mean daily completeness over every calendar day of the season inside the range, with missing days counted as 0; valid if ≥ 75%.
- **Completeness shown per sensor:** average daily completeness over the whole data period per variable, plus valid days and days with data: the same measure as the data-quality report.
- **Latest reading:** the sensor's most recent stored reading row; a variable rejected in that row shows as `null` rather than an older value.
- **"No data" and invalid range:** returned as errors with the exact UC2 messages (404 `no_data`, 400 `invalid_date_range`), so the frontend shows server text verbatim, as for UC1.
- **Audit:** `/api/readings` and `/api/exceedances` write a `data_query` entry with the filters (SEC-12 "queries"); meta and sensors (loaded on every page view) are not audited.
- **Performance (local, full year, SQLite in-process):** every key query p95 ≤ 116 ms (`docs/performance/local_2026-10-28.md`). Deployed timings: `scripts/measure_latency.py`, run by a team member (it signs in).

## D-030 · 2026-10-28 · /api/docs: self-hosted Swagger UI under the strict CSP
- **Problem (deferred in D-013):** FastAPI's default docs page loads Swagger UI from a CDN and starts it with an inline script; `script-src 'self'` blocks both, so the documentation page was blank on the deployed site.
- **Decision:** keep the CSP; self-host `swagger-ui-bundle.js` and `swagger-ui.css` from npm `swagger-ui-dist` **5.33.2** (Apache-2.0, published 2026-10-12, the newest release at least two weeks old) in `backend/app/static/swagger/`, started by our own external `init.js`. `backend/app/docs.py` serves the page and the assets (`/api/docs`, `/api/docs/static/*`).
- **Evidence:** `test_docs.py` (no inline script, no third-party origin, assets served same-origin, no path traversal); a browser load under the CSP rendered every endpoint with no console errors.
- **Access:** the docs page and `/api/openapi.json` stay public, as before (they describe routes, not data); every data route still requires a permission.

## D-031 · 2026-10-29 · Dashboard design choices (Phase 3)
- **Spatial heat map (team choice):** each sensor is a circle coloured, and slightly sized, by the period mean; nothing is interpolated between sensors. Six approximate, unverified points cannot support a continuous surface, and a blur would invite planners to read invented values as measured. The map's other mode colours circles by the latest reading.
- **Temporal heat map:** new `GET /api/heatmap` (filter_data; same validation, audit, rate limit, injection and matrix coverage as `/api/readings`). Cells are reading-count-weighted means of **valid** hourly aggregates only, for up to 366 days (≤ 13 × 24 cells, ~20 KB). Full real year: ~0.8 s locally.
- **Colour (data-viz method, validator run):** sensors take the reference categorical palette in fixed slot order by sensor code (colour follows the sensor, never its rank or the filter). Light and dark six-slot sets pass every hard check (worst adjacent CVD ΔE 9.1 light / 8.4 dark; normal-vision 19.6 / 19.3). Light mode has a contrast warning for three slots (< 3:1), so **every chart has a table view** and a legend (the method's required relief). Magnitude uses one blue ramp, light to dark. Status red is used only for alerts, always with an icon and words.
- **Threshold lines:** drawn only where the statistic matches what is plotted (24-hour standards over **daily means**). Hot-day triggers apply to daily **maximums**, so they are not drawn over means; they appear in the alerts panel.
- **Invalid buckets** (< 75% complete) are drawn as grey dashed segments with a legend entry. Line markers are dropped for more than 16 points, because dense markers made solid lines look dashed (seen in the first screenshots).
- **UC2 client messages:** data requests time out after **5 s** ("The request is taking longer than expected. Please try again."); a failed connection says to try again and contact the system administrator; both offer "Try again". Server messages (no data, invalid range) are shown verbatim. Login and auth calls have no timeout (cold start + deliberate argon2id cost).
- **Accessibility:** a keyboard-usable sensor list sits under the map (Leaflet circle markers cannot take focus); tooltips explain PM2.5, NEPM, completeness, flagged readings and unverified locations; units on every number; light/dark themes.
- **Libraries:** `react-leaflet` **4.2.1** because 5.x requires React 19 (React 18 per BUILD_PROMPT §2); Leaflet 1.9.4; Recharts 3.10.1; all at least two weeks old. OpenStreetMap tiles with attribution (already allowed by the CSP).
- **Browser tests:** run against the **production build** served by `vite preview` with the exact `vercel.json` headers (the dev server does not apply the CSP to pages), on a **synthetic fixture database** (`backend/scripts/make_fixture_db.py`: four invented sensors, one named with an XSS payload). One UI login per role is saved and reused, since logging in per test hits the 5-per-minute login limit (SEC-23 working as designed). The suite now runs in CI with throwaway, masked secrets generated per run.
- **Known:** the production JavaScript bundle is ~900 KB before compression (Recharts + Leaflet).
## D-032 · 2026-10-29 · Export design (Phase 4, UC3 / Algorithm 2, SEC-21)
- **One endpoint, `POST /api/reports/export`** (`export_data`; all three roles hold it), taking the dashboard's applied filters plus `format` (csv/pdf). The same allow-lists and range limits as `GET /api/readings` apply. Unknown JSON fields are rejected, and so is any `file_path`. The file is built on request and streamed back as an attachment with a server-chosen name made only of validated values. Nothing is stored, so `reports.file_path` stays NULL. A POST rather than a GET so the global CSRF check covers it and filters never land in URLs or logs as query strings.
- **When Export unlocks (team choice):** the button stays disabled (`aria-disabled`, still focusable, with the tooltip "Please apply a filter before exporting.") until the user presses **Apply Filter** at least once, even with the defaults unchanged. Reset locks it again.
- **CSV:** a metadata block (filters, generated time in Melbourne time, data source, the 75% completeness caveat, the response notes, row count), a blank line, then one row per sensor per period, with units in the headers (`mean (°C)`). Raw exports add a `flagged` column. UTF-8 with a byte-order mark so Excel shows °C and µg/m³.
- **SEC-21:** `export.safe_cell` prefixes `'` to any **text** cell starting with `= + - @`, a tab or a carriage return (OWASP CSV injection), in data rows and in the metadata block. **Numbers stay numbers:** `-3.2` is written as a number, not escaped. Escaping a negative temperature would turn it into text in Excel, and a number cell cannot carry a formula.
- **PDF (reportlab + matplotlib, BUILD_PROMPT §2):**
  - Contents: title, filters, a summary table sorted by mean descending with a status column, a chart image in the dashboard's colours (invalid periods as grey hollow markers, 24-hour standards only on daily means), the exceedance list (first 200), data-quality notes, and "Page X of Y" on every page.
  - Status: "Threshold exceeded" if the sensor has any exceedance of a standard for this variable in the range, otherwise "Normal". For a variable with no standard it says **"No standard set"**, because "Normal" would claim a judgement we cannot make.
  - Text uses DejaVu Sans (shipped inside matplotlib), since Helvetica has no NO₂/CO₂ subscripts. matplotlib runs headless (`Agg`) with its cache in the temp dir, because Vercel's file system is read-only outside /tmp.
  - All text passed to reportlab is escaped, because its Paragraph understands markup; a test uses a sensor named `<b>…</b> & <script>`.
- **Large exports:** if a request would produce more than 50,000 rows, the server answers 409 `large_export` with the UC3 warning and the row count. The client shows Continue/Cancel and resends with `confirm_large=true`. With today's six sensors the largest export (hourly, 92 days) is about 13,000 rows, so the warning is a guard for a larger network. Vercel's response limit is 4.5 MB, so a file over 4 MB is refused with 413 and a plain message rather than being cut off.
- **Logging and limits:** a delivered file writes a `reports` row (user, type `readings`, format, filters, row count, time) and an `audit_log` entry `report_export`. A failure writes `report_export_failed` and returns the UC3 message "Export failed. Please try again or contact your administrator." Exports are limited to 10 per minute per user, because rendering a PDF costs much more than a JSON query.
- **Client messages:** "Your export is ready." on success. Server messages that tell the user what to change (no data, invalid range, too large, rate limited) are shown as sent. Server errors, timeouts (60 s) and lost connections show the UC3 failure message.
- **Dependencies:**
  - reportlab **5.0.1** and matplotlib **3.11.2**, both at least two weeks old.
  - Pillow **13.0.0**, although it is only 13 days old: `pip-audit` reports three CVEs in 12.3.0 that 13.0.0 fixes, so security wins over the age rule.
  - pypdf **6.21.4** (dev only, tests read the PDFs): the only release without known CVEs.
- **Sample PDF (team choice: real data):** `docs/samples/sample_report_pm25_daily.pdf`, regenerated by `backend/scripts/make_sample_export.py` with the API's own `gather` + `render` code. It contains aggregates only, from the council data in this private repository.

## D-033 · 2026-10-30 · Administration and CSV upload (Phase 5)
- **Database rights for the upload (team choice).** Admin uploads are processed by the website, which connects as `app_user`.
  - `app_user` now has `INSERT`/`UPDATE` (never `DELETE`) on `ingestion_runs` and `sensor_variables`.
  - It also has `TEMPORARY` on the database, because the pipeline's bulk `COPY` stages rows in a temp table: COPY cannot write directly into tables with row-level security.
  - We chose this over a second credential (`pipeline_user`, which can delete readings) on the web tier, and over a GitHub Actions job. Each alternative either widens what a leaked Vercel secret could do, or adds a GitHub token and slower feedback.
  - `verify_security.py` now compares `app_user`'s privileges on every table with an exact expected matrix (any drift in either direction fails) and checks TEMP without CREATE. A unit test keeps that matrix identical to `02_security.sql`. Applied to Neon `dev` and `main` on 2026-10-29: 32/32 checks pass on both.
- **Device keys** for live sensors (Phase 6) are 256 random bits, shown once at registration or rotation, and stored as `sha256$<hex>`. A password needs a slow hash (argon2id) because people choose guessable ones; a random 256-bit key cannot be guessed. A slow hash would also add about 0.5 s to every live reading. Comparison will be constant-time.
- **User management:** temporary passwords are random (128 bits), shown once and must be changed at the next login. Any access change (role, deactivation, password or MFA reset) sets `tokens_valid_after`, which signs the user out everywhere. Administrators cannot change their own role, deactivate themselves, or reset their own password or MFA through these routes, so nobody approves their own access change and the last administrator cannot lock everyone out.
- **Threshold changes:**
  - A reason (10–500 characters) is required and goes into the append-only `threshold_history`.
  - That threshold's exceedances are recomputed with the pipeline's own rule (valid daily aggregates, `all` variant), using one fixed SQL statement per statistic and operator.
- **Pipeline changes (recorded per BUILD_PROMPT §11):**
  - `ingest_file(..., sensor=)` takes the admin's chosen sensor instead of matching the file name.
  - `build_aggregates(conn, sensor_id=)` rebuilds one sensor only (§4.5).
  - `seed_thresholds` treats a threshold as existing if one with the same label, or the same (variable, period, value), is already there. Before, a rebuild after an admin edit would have added the original back. A one-sensor rebuild does not seed at all.
  - `storage.py` gained upload helpers restricted to `uploads/<name>.csv` and accepts OIDC credentials (`BLOB_STORE_ID` plus the per-request token).
- **CSV upload design (§4.5, SEC-15, SEC-20):**
  - **Token route:** a separate Vercel Service `upload/` (Hono, the only Node code) issues *presigned* private upload URLs with `handleUploadPresigned` + `issueSignedToken`. That flow works with Vercel OIDC, so no long-lived Blob token sits on the server (`handleUpload` needs a read-write token).
  - **Permission check:** the route asks FastAPI `GET /api/auth/check?permission=manage_sensors` over a private service binding (`API_INTERNAL_URL`), forwarding only the access cookie, after its own double-submit CSRF check.
  - **Token limits:** CSV only, 50 MB, 10-minute lifetime, one exact pathname of the form `uploads/<safe name>-<32 hex random>.csv`, no overwrite. The random part comes from the browser's `crypto`; the server checks the form.
  - **Server checks before loading:** FastAPI re-checks the pathname and size, sniffs the content (UTF-8, no NUL bytes, not zip/xlsx/PDF/HTML/executable), and requires every column to belong to the chosen sensor's device family. That also catches a file loaded against the wrong sensor. It then parses with pandas only, archives the original under `raw/`, ingests, rebuilds that sensor and deletes the `uploads/` copy, even when the file is rejected.
  - **Limits and logging:** 5 uploads per 10 minutes per admin; every outcome is audited (`upload_ingested`, `upload_rejected` with the reason, `upload_failed` with the error type only).
  - **Timing:** the 21 MB council file took 3.2 s locally (SQLite).
- **Supply chain:**
  - `@vercel/blob` 2.8.2 (frontend and `upload/`) pulls `zod` 4.1.11 through `@vercel/oidc` → `@vercel/cli-config`, which has a high-severity advisory. An npm `overrides` pin to `zod` 4.6.7 fixes it. `npm audit` would have downgraded `@vercel/blob` to a version without the presigned flow instead.
  - `hono` 4.13.13 (4.13.14 was days old).
- **CI's frontend secret scan** now matches secret *values* (Blob read-write tokens, Neon hosts, `postgres://` URLs) rather than the variable name `BLOB_READ_WRITE_TOKEN`, which the Blob client SDK mentions in an error message. gitleaks flagged a made-up temporary password in a Vitest fixture: it was replaced, and that one commit's finding is ignored by fingerprint (`.gitleaksignore`).
- **Browser tests:** `make_fixture_db.py` adds `e2e_admin` with MFA already enrolled. Its TOTP secret is fresh per build and written to a git-ignored file. The admin spec signs in with a real TOTP code and runs in its own Playwright project after the others, because it changes the shared fixture data.
- **Found in the deployed upload test (2026-10-30/31), all fixed with regression tests:**
  - *Admin tabs looped* (`/admin/sensors/upload/sensors/…`): inside the `admin/*` splat route, React Router 7 resolves relative links against the current URL. Tabs and redirects now use absolute paths; Vitest clicks every tab from every tab, and the browser test navigates by clicking.
  - *Blob store connected for Development only*: Preview and Production had no `BLOB_STORE_ID`, so no OIDC access. The team connected the store to all three environments (still private, no read-write token on Vercel). The token route now logs the reason and answers 503 instead of a vague 400.
  - *CSP blocked the upload*: `connect-src https://vercel.com/api/blob` without a trailing slash matches only that exact path; the SDK uploads to `/api/blob/?pathname=…` and `/api/blob/mpu`. The CSP now allows the prefix `https://vercel.com/api/blob/` and nothing else on vercel.com; a repo test checks the CSP against those URLs.
  - *Archive name kept the browser's random suffix*, so re-uploading an identical file archived a second copy instead of matching `raw/<sha256>__<name>`. The suffix is now dropped. One duplicate copy of the MCC-01 export remains in the private store from the test; it was left for the team to delete if wanted.
  - *The summary* now shows "Already in the database (skipped)" (rows offered minus rows inserted), separately from repeated rows inside the file.
  - *Authenticator entries* for Production and Preview looked identical (same email), so a Preview login was tried with the production code. Non-production entries are now named "Maribyrnong Monitor (Preview)". On the team's request, the dev branch's `demo_admin` 2FA was reset once (audited as maintenance; production untouched).
- **Deployed result (Preview, Neon `dev`, 2026-10-31):** the 21.5 MB MCC-01 export (50,756 rows, "Load again") was uploaded, checked, archived and processed in **19.9 s**. That is 14.5 s to download, check and load, plus 5.4 s to rebuild the sensor, well inside the 300 s limit, so the GitHub Actions fallback is not needed. The `uploads/` copy was deleted, an `upload_ingested` audit entry was written, and 93 values were flagged.

## D-034 · 2026-10-31 · Live ingestion and Insights (Phase 6)
- **`POST /api/ingest` (UC4, SEC-03):**
  - **Device authentication:** `X-Device-Id` (sensor code) and `X-Device-Key`, checked against the stored SHA-256 hash with `hmac.compare_digest`. An unknown device is compared against a dummy hash, so response timing does not reveal which codes exist.
  - **Refusals:** a bad key gets 401, audited (`ingest_rejected`) with the source IP and never the key. More than 10 failures a minute from one address get 429. A decommissioned sensor gets 403. A timestamp more than 5 minutes from server time gets 400 (replay protection; ISO-8601 with an offset is required).
  - **Body:** JSON of up to 4 KB, using the device family's own field names only (unknown field, non-number, boolean or NaN gets 422).
  - **Accepted but recorded:** a reading for a second already stored is ignored, logged and answered 200 "duplicate". Out-of-range values go to `error_log` with the rest stored and 200. Each device may send 60 readings a minute.
  - **Route shape:** the route is public in the role matrix because devices authenticate with their own key, not a user session, and it is CSRF-exempt for the same reason.
- **One rule set for files and devices (pipeline change, recorded per §11):**
  - `etl.transform` was split into `reject_out_of_range` and `quality_flags`, so it now shares those two rules with `etl.transform_live`. The real files give identical results before and after: MCC-01 50,756 rows, 93 flagged; SALT-CC 16,932 flagged, 1 rejected.
  - A live reading is checked together with the sensor's previous 12 readings, so flatline and spike flags see the same neighbours as a file load. "Not fitted" needs a whole file and is not applied to single readings.
  - `etl.sensor_aggregate_rows` (taken out of `build_aggregates`) recomputes the touched hour, day and month in both variants from that month's readings, then that day's exceedances. A full month for MCC-01 (about 4,400 readings) takes 146–182 ms locally.
  - A new sensor's first reading registers the variables it measures.
- **Simulator (team choice):** `scripts/simulate_sensor.py` replays one real day from a council CSV to the Preview or a local server, posting to a dedicated demo sensor. Each reading is re-stamped with the current time, as the replay rule requires, so it never targets production. It reads the key from `SIM_DEVICE_KEY` or a prompt and never prints it. It can send Vercel's protection-bypass header from `VERCEL_AUTOMATION_BYPASS_SECRET` to reach a protected Preview.
- **Sensitive sites as data:** a new column `sensors.sensitive_receptor` in both schemas, with an idempotent `ALTER` for Postgres and `etl.migrate_sqlite` for existing SQLite files. Admins can set it with a checkbox, and the registry marks SALT-CC.
- **Insights method:**
  - **Data used:** valid buckets only, flagged values left out.
  - **Comparing sites on the same days:** for each site and day, its value minus the average of the other sites that day, with a 95% t-interval over days. The real data showed why a plain average is wrong: FP-AMEN has 55 valid days in December–February but 4–9 in each winter month, so its plain average ranked it hottest. On the same days it is 0.36 °C *cooler* than the others. Sites with fewer than 30 matched days are listed but not ranked.
  - **Hot days (team choice):** days on which the hottest valid site reached the admin-editable "Hot day" threshold (35 °C; 24 days in the data). A site's figure is the share of those days on which it reported and also reached it.
  - **Parks:** matched hours only. Mean difference with an interval over days, because hours within a day are not independent. Hot afternoons are 12:00–18:00 on hot days. The caveats are written from the numbers (sensor counts, valid-hour shares, sample size, unverified locations).
  - **Trends (team choice):** the OLS slope of valid monthly means, plus the slope of the difference from the other sites, which removes the shared season. "Rising" or "falling" is shown only when the whole 95% interval is on one side of zero.
  - **Recommendations:** rules over these numbers, each carrying its evidence. No cooling claim is made unless the interval excludes zero. A sensitive site is called "more exposed" only on the same rule.
  - **Statistics module:** `services/stats.py` (no new dependency); t critical values from the standard table up to 30 degrees of freedom, 1.96 above.
- **Computation and caching:** all six `/api/analysis/*` endpoints read one computation, cached per instance until the data version changes (last reading, ingestion runs, thresholds, sensor attributes) or 10 minutes pass. Full year locally: 0.43–0.61 s to compute, about 18 ms cached. The browser allows 15 s for these calls (instead of the 5 s data timeout) for the first computation on a cold server.
- **Insights page:** a diverging blue/red pair (data-viz method) with a grey midpoint for "not distinguishable"; every difference is also given in words, and every chart has a table view. No sentence states a finding without numbers from the API; a Vitest test renders the page from two opposite worlds, and a pytest test does the same through the API.
- **Database migration, 2026-10-31 (team-approved order):**
  1. `sensors.sensitive_receptor INTEGER NOT NULL DEFAULT 0` was applied first to Neon `dev` (`ep-withered-shadow-a7j9ipg3`), with SALT-CC marked (1 row, audited) and `verify_security.py` **32/32**. The code was then deployed to a Preview from branch `phase-6` (`9c1fef3`) and checked by the team.
  2. Before production, the team created the restore point **`pre-phase6`** (`ep-dry-unit-a7fjox02`) from `main`. A read-only check confirmed it reports that endpoint, has no `sensitive_receptor` column, and matches `main` exactly: 6 sensors, 192,256 readings, 355,646 aggregates, 99 exceedances, 3 users, 293 audit entries.
  3. The same steps then ran on `main` (`ep-misty-resonance-a708y9zl`): `01_schema.sql` + `02_security.sql` as the owner, SALT-CC marked (1 row, audited), `verify_security.py` **32/32**.
  4. Finally `phase-6` was fast-forwarded into `main`, and production redeployed: health ok, the new endpoints refuse anonymous callers.
  - **Rollback, if ever needed:** restore `main` from `pre-phase6` in the Neon console and redeploy `c0affd6`. The column is additive with a default, so the previous code would also run against the migrated database.

## D-035 · 2026-11-03 · Two roles (Analyst, Administrator); login page redesign
- **Two roles.** The proposal's use cases define two actors, the **Council Analyst** and the
  **Administrator**, so the system now has two roles: Environmental Analyst and System
  Administrator. "General User" appears only in the proposal's front-end section and is treated as
  the Analyst. BUILD_PROMPT §4.1 listed three roles; this decision supersedes that line.
  - **Database:** the `roles` row 1 "General User" stays (unchanged in both schema files), because
    existing user records and audit entries refer to it. No schema change, so no migration.
  - **API:** `RoleId` in `schemas.py` accepts only 2 and 3. Creating a user or changing a role to 1
    gets 422 (`test_retired_general_user_role_cannot_be_given`).
  - **Admin UI:** the role lists offer only the two roles. An old role-1 record shows
    "General User (retired)" as a disabled choice, so it can be moved to a current role but not given.
  - **Demo accounts:** `seed_users.py` and the E2E fixture no longer create `demo_user`;
    `SEED_USER_PASSWORD` is gone from `.env.example` and CI. The fixture adds a **deactivated**
    analyst (`fixture.inactive@example.org`) so the browser suite checks that a deactivated
    account cannot log in.
  - **Existing `demo_user` on Neon:** deactivated, never deleted (SEC-12, audit history). `dev`
    first; `main` only after the team says so.
    - `dev` (`ep-withered-shadow-a7j9ipg3`), 2026-11-03, as `app_user`: `is_active` 1 → 0 and
      `tokens_valid_after` set (signed out everywhere); audit entry 127 `user_updated` with the
      reason. All 3 users still present.
    - `main` (`ep-misty-resonance-a708y9zl`), 2026-11-04 after the team's go-ahead, as `app_user`:
      the same change, audit entry 548 `user_updated`. All 3 users still present.
    - Code: `ui-roles` (`a9c139b`, `2775c96`) fast-forwarded into `main` on 2026-11-04. Production
      redeployed and checked: `/login` 200 under the CSP, both illustrations served from our own
      domain, no "General User" role option in the bundle, health ok, anonymous `/api/me` 401.
  - **Tests:** the permission matrix (`test_rbac.py`, `docs/security/permission_matrix.md`) now
    has the columns anonymous / Analyst / Admin without MFA / Admin with MFA. Tests that used a
    General User now use an Analyst, or the retired role where the point is an old record.
- **Header:** shows the role label ("Analyst" or "Administrator", from `role` in `/api/me`)
  instead of the username, so usernames and emails never appear in screenshots or the demo video.
- **Login page:** two columns from the team's illustration (`frontend/src/assets/login-illustration.webp`,
  converted from the team's 349 KB PNG (original kept in `docs/design/`) to a 16 KB WebP and bundled, so it is served from our own domain
  under the existing CSP). The page keeps the site's Tailwind colours, radius and dark mode rather
  than the mockup's colours. It adds a show/hide password button and "Forgot password?", which
  says "Please contact your administrator to reset your password." (accounts are created and reset
  by administrators; there is no self-service reset). There is no role toggle (the role comes from
  the account) and no "Remember me" (sessions follow SEC-08). The button reads "Sign in", in the
  site's sentence case. All UC1 messages, CSRF and lockout behaviour are unchanged; the existing
  login tests keep their assertions with the new heading and button names. Below the `md`
  breakpoint the illustration is hidden. It is decorative (`alt=""`). `e2e/login.spec.ts` checks
  AA text contrast (≥ 4.5:1) in light and dark mode, keyboard order, visible focus and the CSP.

## D-036 · 2026-11-04 · Login page: light and dark artwork (supersedes the login part of D-035)
- **Artwork:** the team's final illustrations, `frontend/src/assets/login-illustration-{light,dark}.png`,
  are kept unedited. The team replaced both on 2026-11-04 with versions whose artwork has the same
  near-square layout: light 1672×941, artwork 0.99:1; dark 2170×725, artwork 1.18:1 (the first dark
  export was a 1.47:1 banner and looked stretched next to the light one). Light is served as a
  lossless, pixel-identical WebP (931 KB). Dark is served as a transparent-background WebP (525 KB,
  see "No seam"). Both are bundled by Vite, so they come from our own domain under the existing
  CSP. The earlier pastel WebP and its PNG in `docs/design/` were removed.
- **Theme:** the same mechanism as the rest of the site, `prefers-color-scheme` (there is no site
  toggle). A `<picture>` source with that media query means the browser downloads only the active
  theme's image, and because the switch is pure CSS there is no flash of the wrong theme. The E2E
  test checks that only the matching image is requested.
- **Colours** are named tokens in `index.css` (`--login-*`, exposed as `bg-login-page`,
  `text-login-accent`, …), with light and dark values; there are no raw hex values in the component.
  No existing site token matched these values. Measured contrast (`docs/screenshots/fixture/login_contrast.json`):
  - light: button text 5.09, link 5.09, label 5.09, heading 17.04, subtitle 7.58;
  - dark: button text 10.99, link 9.92, label 9.92, heading 16.13, subtitle 7.14.

  The teal #037A85 already passes AA on white, so it was not darkened.
- **Showing only the artwork:** both files have large empty space beside the artwork. Only the
  artwork area plus a small margin is shown (light: x 49–1006 of 1672, cropped by the browser; dark:
  x 101–955, cropped by the script). Both are shown at their true shape, with no stretching (a
  vertical stretch was tried for the first dark export and dropped). Both themes use the same
  columns (58/42) and the same illustration height, so the card and the artwork's top sit in the
  same place: 778 px tall on a 1900×920 screen.
- **No seam:**
  - **Light:** the page background matches the artwork's measured edge colour, #EBF3FE, with no
    glow. A soft straight-edge feather (`.login-art-mask`) fades only the background margin. An oval
    mask was tried first; it trimmed the artwork into a round blob and was dropped.
  - **Dark:** the page is flat #040E25; the transparent artwork carries its own glow.
  - **Dark: fixed at the cause, the asset.** The dark artwork's background is not exactly the page
    colour. With the first export it differed from #040E25 by 13–20 levels along the edges and up to
    39 at the top, where the glow reached the file edge. That made a faint rectangle that masks
    could only blur, and they faded the outer cityscape. Instead,
    `scripts/make_login_dark_art.py` builds `login-illustration-dark-transparent.webp` from the
    unmodified PNG. It finds the artwork itself, so a new export needs only a re-run:
    - **Colour to alpha** against the page navy, so each pixel drawn over the page reproduces the
      original. Red is left out of the "darker" side, because the page's red is only 4.
    - **Glow only** (low opacity) is faded to zero along an ellipse. A rectangular fade was tried
      and still left a box; the solid artwork is never faded.

    Checked on the current export: every solid artwork pixel is within 0.9 levels of the original
    (green/blue; red within 1.6), every edge pixel is fully transparent, and the background bands of
    the 1440 px screenshot are flat. The dark mask and the extra page glow were
    removed.
  - **Dark card:** no blue border (transparent, still 1 px, so nothing moves); separation by a
    subtle shadow (black at 35%, 0 12px 40px). Light mode is unchanged: its screenshots are
    pixel-identical before and after.
- **Illustration size (enlarged at the team's request):** the left column is 58% of a page up to
  1720 px wide. The illustration fills it up to 880 px (light) or 1040 px (dark) wide, and never more
  than about 86% of the window height, so it never causes scrolling.
- **Behaviour unchanged:** login call, CSRF, lockout, redirects, UC1 messages, show/hide and
  "Forgot password?". The Sign in button is still disabled while a field is empty, now shown at 85%
  opacity (it was 50–60%) so that it reads like the reference. Hover transitions are off under
  `prefers-reduced-motion`.


## D-037 · 2026-11-16 · Single-use 2FA recovery codes for administrators
- **Why:** markers need to sign in as an administrator, but the authenticator lives on one phone.
  Turning MFA off or sharing a bypass would weaken SEC-07. Recovery codes keep two factors.
- **What a code is:** a NIST SP 800-63B "look-up secret". 10 per set, each 16 characters of
  Crockford base32 (no I, L, O or U; a typed O, I or L is read as 0, 1, 1), shown as
  `XXXX-XXXX-XXXX-XXXX`. The first 4 characters are a selector that only finds the row; the
  other 12 are the secret (60 bits from Python's `secrets`).
- **Storage:** only an argon2id hash of the secret, with the same parameters as passwords (D-025).
  NIST requires salted, slow hashing for secrets under 112 bits. Thanks to the selector, checking a
  code costs one hash, and an unknown selector still costs one (dummy) hash, so timing does not
  reveal it. Codes never appear in logs, audit details or API responses after the one that creates them.
- **SEC-07 kept:**
  - A code replaces the 6-digit authenticator code, never the password: it is accepted only on
    `POST /api/auth/mfa/recovery`, after the password step, by a signed-in user.
  - Only accounts that already have 2FA set up can use one (`mfa_not_set_up` otherwise), so codes
    cannot be used to skip enrolment.
  - A successful code gives the same MFA session as an authenticator code; every `manage_*`
    permission still needs that session.
  - Codes and authenticator codes share one limit (5 tries a minute per user), so they cannot be
    combined to guess faster. Failures are audited (`mfa_recovery_failed`).
- **Single use:** the code is marked used by `UPDATE … WHERE used_at IS NULL AND revoked_at IS NULL`,
  and accepted only if that changed one row, so two simultaneous attempts cannot both succeed (tested).
- **When codes are created:**
  - the first set is returned once by the first successful `POST /api/auth/mfa/verify` (enrolment);
  - Change password → Account security shows how many are left and can generate a new set, which
    cancels every unused code. Both need a session that already passed 2FA.

  Already-enrolled admins (like `demo_admin` on production) need no re-enrolment: they generate
  their first set from that section after one authenticator sign-in.
- **Showing them:** a "save once" screen with Copy and Download (a local `.txt`, made in the
  browser) and an "I have saved these codes" checkbox before Continue. After a recovery sign-in
  with 3 or fewer codes left, the app tells the user to generate a new set.
- **Reset 2FA** (the admin action) also cancels the user's codes. The design said "deletes"; it
  cancels them instead (`revoked_at`), because the table has no DELETE grant and used/cancelled
  codes stay for the audit trail.
- **Database:** new table `mfa_recovery_codes` (`code_id`, `user_id` → `users` ON DELETE CASCADE,
  `selector`, `code_hash`, `created_at`, `used_at`, `revoked_at`), in both schema files.
  `02_security.sql` gives `app_user` SELECT and INSERT, plus UPDATE of `used_at` and `revoked_at`
  only; no DELETE. RLS comes from the existing loop over every table; `pipeline_user` has no access;
  `backup_user` reads it like every table.
  - `verify_security.py` checks the column-level grant separately, because `has_table_privilege`
    does not see column grants. It also checks that `pipeline_user` cannot read the table.
- **Handing codes to markers:** give the demo admin's email, password and a few unused codes in the
  confidential submission notes only, never in the repo, README or video. Generate a new set after
  marking, which cancels the old ones.
- **Rollout:** Neon `dev` first (01 + 02 as the owner, then `verify_security.py`: 34 passed, 0 failed,
  2026-11-16). The team tested the Preview. Restore point `pre-recovery-codes` on `main` (endpoint
  `ep-tiny-dew-a72ggaf8`) checked read-only: identical to `main` (3 users, 192,256 readings, last audit
  entry 691, no recovery-code table). With the team's approval, 01 + 02 were applied to `main` as the owner;
  `verify_security.py` on `main`: 34 passed, 0 failed (`docs/security/database_verification.md`). The code
  reaches production only when the branch is merged.
  - **Rollback:** the table is additive and unused by the current production code. If needed, restore
    `main` from `pre-recovery-codes` in the Neon console.
- **Also fixed:** the 2FA page navigated home in the same tick as it updated the signed-in user, so
  the route guard could see the old, unverified user and send the page back to `/mfa`. It now
  leaves only once the verified user is in the auth state. A new frontend test caught this.
- **Where it lives (2026-11-16, at the team's request):** first shipped as an Administration tab
  ("Two-factor"), then moved to an "Account security" section on the Change password page.
  - The proposal's Administration (UC5) covers sensors, users, thresholds and data upload. Recovery
    codes are a setting for your own sign-in (UC1, SEC-07), so they belong next to the password.
  - The Administration tabs are back to exactly the four in the proposal.
  - The section shows only for accounts with 2FA set up whose session passed it, so Analysts never
    see it. The 2FA sign-in page keeps "Use a recovery code instead".
  - Frontend only: no API or database change.
- **Beyond the proposal:** recovery codes were not in the original proposal. They were added to
  SEC-07 so markers can sign in as an administrator without the team's phone, without turning
  MFA off.
