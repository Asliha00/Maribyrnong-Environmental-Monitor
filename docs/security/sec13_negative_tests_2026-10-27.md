# SEC-13 live negative tests (2026-10-27)

Purpose: prove that the `neon_service` exemption (DECISIONS.md D-017) does not weaken the
"no role outside owner/app_user/pipeline_user/backup_user can connect or use schema app" check.
Each case changed the live Neon database as the owner, ran `database/verify_security.py`,
then restored the database (in a `finally` block) and ran it again. Raw output:

```
N1 intruder role with USAGE on app: [FAIL] SEC-13  no role outside owner/app_user/pipeline_user/backup_user can connect or use schema app - unexpected: ['sec13_intruder']
  restored: [PASS] SEC-13  no role outside owner/app_user/pipeline_user/backup_user can connect or use schema app
N2 direct grant to neon_service: [FAIL] SEC-13  no role outside owner/app_user/pipeline_user/backup_user can connect or use schema app - unexpected: ['neon_service']
  restored: [PASS] SEC-13  no role outside owner/app_user/pipeline_user/backup_user can connect or use schema app
```

| Case | Change | Expected | Result |
|---|---|---|---|
| N1 | `CREATE ROLE sec13_intruder; GRANT USAGE ON SCHEMA app TO sec13_intruder` | FAIL naming the role | FAIL, `['sec13_intruder']` |
| N2 | `GRANT USAGE ON SCHEMA app TO neon_service` | exemption withdrawn, FAIL | FAIL, `['neon_service']` |

Unit tests for the same logic: `database/tests/test_verify_security.py` (5 tests).
Final clean run after both cases: `database_verification.md`, 30 passed, 0 failed, 0 skipped.
