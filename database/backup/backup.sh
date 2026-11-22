#!/usr/bin/env bash
# SEC-18: encrypted backup of the app schema (Essential Eight: Regular backups).
# Usage: BACKUP_DATABASE_URL=... BACKUP_ENCRYPTION_KEY=... ./backup.sh [output_dir]
# Use Neon's direct host, not the -pooler host: pg_dump needs a real session.
# Neon's own point-in-time restore is a second safety net, but its free-tier history
# window is short and it lives with the same provider, so we keep our own copies too.
# Produces app_YYYYmmddTHHMMSSZ.dump.enc (AES-256, PBKDF2) + a .sha256 checksum.
# The unencrypted dump never touches disk.
set -euo pipefail
: "${BACKUP_DATABASE_URL:?set BACKUP_DATABASE_URL (backup_user on the DIRECT Neon host, sslmode=require)}"
: "${BACKUP_ENCRYPTION_KEY:?set BACKUP_ENCRYPTION_KEY (32+ random characters)}"
OUT_DIR="${1:-./backups}"
mkdir -p "$OUT_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FILE="$OUT_DIR/app_${STAMP}.dump.enc"

# --enable-row-security: backup_user is subject to RLS (read policy grants it all rows)
pg_dump "$BACKUP_DATABASE_URL" --schema=app --format=custom --no-owner --no-privileges \
        --enable-row-security \
  | openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass env:BACKUP_ENCRYPTION_KEY -out "$FILE"

sha256sum "$FILE" > "$FILE.sha256"
echo "Encrypted backup written: $FILE ($(du -h "$FILE" | cut -f1))"
