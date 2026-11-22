#!/usr/bin/env bash
# Fail fast on badly pasted secrets: a value copied as the whole .env line ("NAME=value"),
# or a database URL that is not a postgresql:// URL. Values are never printed.
# Usage: check_secrets.sh VAR_NAME [VAR_NAME ...]   (values are read from the environment)
set -euo pipefail
status=0
for name in "$@"; do
  value="${!name-}"
  if [ -z "$value" ]; then
    echo "::error::$name is empty or not set"; status=1; continue
  fi
  if [[ "$value" =~ ^[A-Z_]+= ]]; then
    echo "::error::$name starts with 'SOMETHING=': paste only the part after '=' from the .env file"; status=1; continue
  fi
  if [[ "$value" =~ ^[[:space:]]|[[:space:]]$ || "$value" == \"* || "$value" == \'* ]]; then
    echo "::error::$name has leading/trailing spaces or quotes"; status=1; continue
  fi
  if [[ "$name" == *DATABASE_URL* && "$value" != postgresql://* ]]; then
    echo "::error::$name must start with postgresql://"; status=1; continue
  fi
  echo "ok: $name"
done
exit $status
