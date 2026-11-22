-- =====================================================================
-- Maribyrnong EMS - NEON DATABASE SECURITY HARDENING
-- Run AFTER 01_schema.sql, as the project owner role (neondb_owner), in the
-- Neon SQL Editor or with:  psql "$OWNER_DATABASE_URL" -f database/02_security.sql
-- Safe to re-run.
--
-- Implements:
--   SEC-12  append-only audit_log and threshold_history
--   SEC-13  private schema, RLS on every table, no access for any other role
--   SEC-14  least-privilege database roles (the app never connects as the owner)
--   SEC-18  read-only backup role for encrypted nightly dumps
-- Maps to proposal risks R19 (RBAC misconfiguration) and R20 (cloud storage
-- misconfiguration) and Essential Eight "Restrict administrative privileges".
--
-- Neon notes:
--   * The owner role is a member of neon_superuser but is NOT a Postgres
--     superuser. It can create roles and owns the app schema, so everything
--     below works without superuser rights.
--   * Roles created with SQL do not appear in the Neon Console role list and
--     are copied to new branches. That is expected.
-- =====================================================================
SET search_path TO app;

-- ---------------------------------------------------------------------
-- 1. Three application roles, created WITHOUT login. Step 5 enables login.
--    pipeline_user : used only by data_pipeline/etl.py
--    app_user      : used only by the FastAPI backend
-- ---------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pipeline_user') THEN
    CREATE ROLE pipeline_user NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
    CREATE ROLE app_user NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'backup_user') THEN
    CREATE ROLE backup_user NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
  END IF;
END $$;

ALTER ROLE app_user      SET search_path = app;
ALTER ROLE pipeline_user SET search_path = app;
ALTER ROLE backup_user   SET search_path = app;
-- Matches UC2 "query timeout" (5 s) and limits damage from runaway/abusive queries
ALTER ROLE app_user      SET statement_timeout = '5s';
ALTER ROLE pipeline_user SET statement_timeout = '10min';
-- Vercel functions reach Neon through its pooler, which opens server connections as
-- app_user on demand; keep this comfortably below the compute's max_connections.
ALTER ROLE app_user      CONNECTION LIMIT 40;
ALTER ROLE pipeline_user CONNECTION LIMIT 5;
ALTER ROLE backup_user   CONNECTION LIMIT 2;

-- ---------------------------------------------------------------------
-- 2. Lock the schema down, then grant back only what each role needs
-- ---------------------------------------------------------------------
REVOKE ALL ON SCHEMA app FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA app FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA app FROM PUBLIC;

-- Nobody except the owner and the three roles below may use this database.
-- PUBLIC normally gets CONNECT and TEMP on every database; take both away,
-- then grant CONNECT back explicitly (bulk COPY needs TEMP: the pipeline, and the
-- website's admin CSV upload, D-033).
DO $$
BEGIN
  EXECUTE format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database());
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO app_user, pipeline_user, backup_user', current_database());
  EXECUTE format('GRANT TEMPORARY ON DATABASE %I TO pipeline_user, app_user', current_database());  -- app_user: admin CSV upload stages COPY in a temp table (D-033)
END $$;
-- Nothing may be created in the default public schema (Postgres 15+ already blocks this)
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- Reset the application roles too, so re-running this script removes any stray grants
REVOKE ALL ON ALL TABLES IN SCHEMA app FROM app_user, pipeline_user, backup_user;

GRANT USAGE ON SCHEMA app TO app_user, pipeline_user, backup_user;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA app TO app_user, pipeline_user;

-- backup_user: read-only, used only by the nightly encrypted backup job
GRANT SELECT ON ALL TABLES IN SCHEMA app TO backup_user;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA app TO backup_user;

-- pipeline_user: loads sensor data. Cannot see users, roles, reports or audit_log.
GRANT SELECT, INSERT, UPDATE         ON sensors, ingestion_runs            TO pipeline_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON sensor_variables, readings, error_log,
                                        aggregates, exceedances            TO pipeline_user;
GRANT SELECT, INSERT                 ON thresholds                         TO pipeline_user;
GRANT DELETE                         ON ingestion_runs                     TO pipeline_user; -- --rebuild only

-- app_user: the website backend
GRANT SELECT                         ON roles                              TO app_user;
GRANT SELECT, INSERT, UPDATE         ON ingestion_runs, sensor_variables   TO app_user;  -- admin CSV upload (§4.5, D-033); no DELETE
GRANT SELECT, INSERT                 ON readings, error_log                TO app_user;  -- live ingestion (UC4); never UPDATE/DELETE readings
GRANT SELECT, INSERT, UPDATE, DELETE ON aggregates, exceedances            TO app_user;  -- incremental aggregation
GRANT SELECT, INSERT, UPDATE         ON users, sensors, thresholds, reports TO app_user; -- no DELETE: deactivate/decommission instead
GRANT SELECT, INSERT, DELETE         ON revoked_tokens                     TO app_user;  -- delete = purge expired entries
GRANT SELECT, INSERT, UPDATE, DELETE ON rate_limits                        TO app_user;  -- shared counters (SEC-23)
GRANT SELECT, INSERT                 ON audit_log, threshold_history       TO app_user;  -- append-only
GRANT SELECT, INSERT                 ON mfa_recovery_codes                 TO app_user;  -- 2FA recovery codes (D-037)
GRANT UPDATE (used_at, revoked_at)   ON mfa_recovery_codes                 TO app_user;  -- mark used/replaced only; no DELETE

-- ---------------------------------------------------------------------
-- 3. Row Level Security on EVERY table (defence in depth). Only the two
--    application roles get policies; any other role sees nothing.
-- ---------------------------------------------------------------------
DO $$
DECLARE t TEXT;
BEGIN
  FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'app' LOOP
    EXECUTE format('ALTER TABLE app.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS app_roles_all ON app.%I', t);
    EXECUTE format('CREATE POLICY app_roles_all ON app.%I TO app_user, pipeline_user USING (true) WITH CHECK (true)', t);
    EXECUTE format('DROP POLICY IF EXISTS backup_read ON app.%I', t);
    EXECUTE format('CREATE POLICY backup_read ON app.%I FOR SELECT TO backup_user USING (true)', t);
  END LOOP;
END $$;

-- ---------------------------------------------------------------------
-- 4. Tamper protection: audit_log and threshold_history cannot be changed
--    or deleted by ANY role (even postgres) without first dropping this trigger.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION app.prevent_modification() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% is append-only; % is not permitted', TG_TABLE_NAME, TG_OP;
END $$;

DROP TRIGGER IF EXISTS audit_log_append_only ON app.audit_log;
CREATE TRIGGER audit_log_append_only BEFORE UPDATE OR DELETE ON app.audit_log
  FOR EACH ROW EXECUTE FUNCTION app.prevent_modification();

DROP TRIGGER IF EXISTS threshold_history_append_only ON app.threshold_history;
CREATE TRIGGER threshold_history_append_only BEFORE UPDATE OR DELETE ON app.threshold_history
  FOR EACH ROW EXECUTE FUNCTION app.prevent_modification();

-- ---------------------------------------------------------------------
-- 5. MANUAL STEP - enable login with strong, unique passwords.
--    Generate each password with:  python -c "import secrets; print(secrets.token_urlsafe(32))"
--    (Neon requires high-entropy passwords for roles created with SQL; these qualify.)
--    Store them ONLY in your .env files, Vercel environment variables, GitHub secrets
--    and the team password manager. Never commit them.
--
--    ALTER ROLE pipeline_user WITH LOGIN PASSWORD '<paste generated password>';
--    ALTER ROLE app_user      WITH LOGIN PASSWORD '<paste generated password>';
--    ALTER ROLE backup_user   WITH LOGIN PASSWORD '<paste generated password>';
--
-- 6. Build connection strings from the owner URL Neon gave you, swapping the user and password:
--      pooled   host  ...-pooler.<region>.aws.neon.tech  -> APP_DATABASE_URL (Vercel backend)
--      direct   host  ...<region>.aws.neon.tech          -> PIPELINE_DATABASE_URL, BACKUP_DATABASE_URL
--    Keep ?sslmode=require (or verify-full) on every URL.
--
-- 7. Then run:  python database/verify_security.py   (all checks must PASS)
-- ---------------------------------------------------------------------
