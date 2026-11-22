# Database and storage security verification
_Run 2026-11-15 23:51 UTC by database/verify_security.py_

**34 passed, 0 failed, 0 skipped**

| ID | Check | Result | Detail |
|---|---|---|---|
| SEC-02 | pipeline URL requires TLS and a non-default password | PASS |  |
| SEC-02 | app URL requires TLS and a non-default password | PASS |  |
| SEC-02 | database refuses an unencrypted pipeline connection | PASS | refused (OperationalError) |
| SEC-02 | database refuses an unencrypted app connection | PASS | refused (OperationalError) |
| SEC-14 | pipeline connects as a dedicated non-admin role (pipeline_user) | PASS | super/createrole/createdb/bypassrls/neon_superuser = [False, False, False, False, False] |
| SEC-14 | app connects as a dedicated non-admin role (app_user) | PASS | super/createrole/createdb/bypassrls/neon_superuser = [False, False, False, False, False] |
| SEC-14 | app_user cannot create tables | PASS | InsufficientPrivilege |
| SEC-14 | app_user cannot drop tables | PASS | InsufficientPrivilege |
| SEC-14 | app_user cannot alter tables | PASS | InsufficientPrivilege |
| SEC-14 | pipeline_user cannot read users (password hashes) | PASS | InsufficientPrivilege |
| SEC-14 | pipeline_user cannot read audit_log | PASS | InsufficientPrivilege |
| SEC-14 | pipeline_user cannot read 2FA recovery codes | PASS | InsufficientPrivilege |
| SEC-12 | app_user can append to audit_log | PASS | statement succeeded |
| SEC-12 | app_user cannot UPDATE audit_log | PASS | InsufficientPrivilege |
| SEC-12 | app_user cannot DELETE audit_log | PASS | InsufficientPrivilege |
| SEC-12 | app_user cannot UPDATE sensor readings | PASS | InsufficientPrivilege |
| SEC-12 | app_user cannot DELETE sensor readings | PASS | InsufficientPrivilege |
| SEC-12 | app_user cannot DELETE users (deactivate only) | PASS | InsufficientPrivilege |
| SEC-12 | app_user holds no UPDATE/DELETE/TRUNCATE grants on audit_log, threshold_history, readings | PASS |  |
| SEC-14 | app_user table privileges match 02_security.sql exactly | PASS |  |
| SEC-14 | app_user may UPDATE only ['revoked_at', 'used_at'] on mfa_recovery_codes | PASS | updatable columns: ['revoked_at', 'used_at'] |
| SEC-14 | app_user may create temp tables (upload COPY) but no schemas | PASS | TEMP=True CREATE=False |
| SEC-12 | even the owner role cannot UPDATE audit_log (trigger) | PASS | RaiseException |
| SEC-18 | backup_user can read all app tables | PASS | statement succeeded |
| SEC-18 | backup_user is read-only (cannot INSERT) | PASS | InsufficientPrivilege |
| SEC-18 | backup_user is read-only (cannot DELETE) | PASS | InsufficientPrivilege |
| SEC-13 | row-level security enabled on all 16 app tables | PASS |  |
| SEC-13 | no role outside owner/app_user/pipeline_user/backup_user can connect or use schema app | PASS |  |
| SEC-13 | Neon Data API is not enabled (no API roles present) | PASS |  |
| SEC-15 | raw-file archive is a PRIVATE Blob store | PASS | 28rdqluwujbpdmfk.private.blob.vercel-storage.com |
| SEC-15 | anonymous request for an archived CSV is refused | PASS | HTTP 403 |
| SEC-01 | Blob delivery URL uses HTTPS | PASS |  |
| SEC-16 | .env is listed in .gitignore | PASS |  |
| SEC-16 | .env is not tracked by git | PASS |  |
