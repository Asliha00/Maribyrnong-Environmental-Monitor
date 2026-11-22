# Restore test 1 of 2 (SEC-18), 2026-10-27

GitHub Actions workflow `restore-test`, run 40468753825, commit b30e436, runner ubuntu-24.04, pg_restore 18.6.
Backup of production (Neon `main`) taken by the read-only `backup_user`, restored into the scratch branch `restore-scratch` (ep-holy-art-a7gjkt8q) as `restore_user`.
Raw log of the two steps, extracted from the job-log archive (secrets appear only as `***`, masked by GitHub):

```
2026-10-27T07:43:04.3725165Z ##[group]Run database/backup/backup.sh backups
2026-10-27T07:43:04.3726373Z database/backup/backup.sh backups
2026-10-27T07:43:04.3787316Z shell: /usr/bin/bash -e {0}
2026-10-27T07:43:04.3787565Z env:
2026-10-27T07:43:04.3788625Z   BACKUP_DATABASE_URL: ***
2026-10-27T07:43:04.3789001Z   BACKUP_ENCRYPTION_KEY: ***
2026-10-27T07:43:04.3789216Z ##[endgroup]
2026-10-27T07:43:22.2058783Z Encrypted backup written: backups/app_20261027T074304Z.dump.enc (7.5M)
2026-10-27T07:43:22.2094877Z ##[group]Run set -o pipefail
2026-10-27T07:43:22.2095168Z set -o pipefail
2026-10-27T07:43:22.2096015Z {
2026-10-27T07:43:22.2096346Z   echo "Restore test $(date -u +%Y-%m-%dT%H:%M:%SZ), commit ${GITHUB_SHA::7}, run ${GITHUB_RUN_ID}"
2026-10-27T07:43:22.2096748Z   echo "pg_restore: $(pg_restore --version)"
2026-10-27T07:43:22.2097022Z   ls -l backups/
2026-10-27T07:43:22.2097286Z   database/backup/restore_test.sh backups/*.dump.enc
2026-10-27T07:43:22.2097606Z } 2>&1 | tee restore_test.log
2026-10-27T07:43:22.2153163Z shell: /usr/bin/bash -e {0}
2026-10-27T07:43:22.2153391Z env:
2026-10-27T07:43:22.2153850Z   BACKUP_ENCRYPTION_KEY: ***
2026-10-27T07:43:22.2154629Z   SCRATCH_DATABASE_URL: ***
2026-10-27T07:43:22.2155523Z   SOURCE_DATABASE_URL: ***
2026-10-27T07:43:22.2155749Z ##[endgroup]
2026-10-27T07:43:22.2240139Z Restore test 2026-10-27T07:43:22Z, commit b30e436, run 40468753825
2026-10-27T07:43:22.2279596Z pg_restore: pg_restore (PostgreSQL) 18.6 (Ubuntu 18.6-1.pgdg24.04+2)
2026-10-27T07:43:22.2292568Z total 7628
2026-10-27T07:43:22.2293344Z -rw-r--r-- 1 runner runner 7806192 Oct 27 07:43 app_20261027T074304Z.dump.enc
2026-10-27T07:43:22.2294184Z -rw-r--r-- 1 runner runner     104 Oct 27 07:43 app_20261027T074304Z.dump.enc.sha256
2026-10-27T07:43:22.2380845Z backups/app_20261027T074304Z.dump.enc: OK
2026-10-27T07:43:23.8909918Z NOTICE:  schema "app" does not exist, skipping
2026-10-27T07:43:57.9743654Z PASS sensors 6 rows
2026-10-27T07:44:00.4661843Z PASS readings 192256 rows
2026-10-27T07:44:02.6551557Z PASS error_log 15 rows
2026-10-27T07:44:04.8652589Z PASS aggregates 355070 rows
2026-10-27T07:44:06.9900462Z PASS exceedances 99 rows
2026-10-27T07:44:09.1437473Z PASS thresholds 4 rows
2026-10-27T07:44:11.3246441Z PASS users 0 rows
2026-10-27T07:44:13.5270881Z PASS audit_log 0 rows
```

## Structure of the restored copy (checked on the scratch branch afterwards, as owner)
```
tables: 15 | RLS on: 15
RLS policies: 30
append-only triggers: ['audit_log_append_only', 'threshold_history_append_only']
indexes: 25
max readings ts: 2026-02-16 12:58:54+00:00
```

## Result
PASS: checksum verified; all 8 compared tables have identical row counts (192,256 readings, 355,070 aggregates, 99 exceedances); RLS, policies and append-only triggers restored.

## Limits
- Grants are not restored (`--no-privileges`, by design). After a real recovery: run `database/02_security.sql`, then `database/verify_security.py`.
- `users` and `audit_log` are empty at this stage (0 = 0). Restore test 2, before final submission, must cover real user and audit rows.
