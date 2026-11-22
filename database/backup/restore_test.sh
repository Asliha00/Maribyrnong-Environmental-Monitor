#!/usr/bin/env bash
# SEC-18: prove a backup can actually be restored (an untested backup is not a backup).
# Restores an encrypted dump into a SCRATCH database and compares row counts with the source.
# Usage: BACKUP_ENCRYPTION_KEY=... SCRATCH_DATABASE_URL=... SOURCE_DATABASE_URL=... ./restore_test.sh file.dump.enc
set -euo pipefail
FILE="${1:?path to .dump.enc}"
: "${BACKUP_ENCRYPTION_KEY:?}"; : "${SCRATCH_DATABASE_URL:?}"; : "${SOURCE_DATABASE_URL:?}"

sha256sum --check "$FILE.sha256"
psql "$SCRATCH_DATABASE_URL" -q -c "DROP SCHEMA IF EXISTS app CASCADE"
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:BACKUP_ENCRYPTION_KEY -in "$FILE" \
  | pg_restore --dbname="$SCRATCH_DATABASE_URL" --no-owner --no-privileges

FAIL=0
for t in sensors readings error_log aggregates exceedances thresholds users audit_log; do
  a=$(psql "$SOURCE_DATABASE_URL"  -tAc "SELECT count(*) FROM app.$t")
  b=$(psql "$SCRATCH_DATABASE_URL" -tAc "SELECT count(*) FROM app.$t")
  if [ "$a" = "$b" ]; then echo "PASS $t $b rows"; else echo "FAIL $t source=$a restored=$b"; FAIL=1; fi
done
exit $FAIL
