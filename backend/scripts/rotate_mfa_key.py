"""
Re-encrypt every stored admin TOTP secret with the NEWEST MFA key (SEC-07; step 3 of
docs/security/secret_rotation.md "MFA_ENCRYPTION_KEY").

    MFA_ENCRYPTION_KEY="NEW_KEY,OLD_KEY" python backend/scripts/rotate_mfa_key.py --dry-run
    MFA_ENCRYPTION_KEY="NEW_KEY,OLD_KEY" python backend/scripts/rotate_mfa_key.py

Run it with the same settings as the website (APP_DATABASE_URL for Neon, or the local SQLite
file), after the variable lists the new key first. Every secret is decrypted with whichever
listed key works and re-encrypted with the first one, in ONE transaction: if any secret
cannot be decrypted, nothing is changed and the script says how many failed. Afterwards the
old key can be removed from the setting. Secrets and keys are never printed.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from cryptography.fernet import InvalidToken  # noqa: E402

import data_pipeline.config  # noqa: E402,F401  (loads .env into the environment, like the pipeline)
from backend.app.config import get_settings  # noqa: E402
from backend.app.db import Database  # noqa: E402
from backend.app.services import audit, mfa  # noqa: E402

SQL_SECRETS = "SELECT user_id, mfa_secret_encrypted FROM users WHERE mfa_secret_encrypted IS NOT NULL"


def rotate(db: Database, key_setting: str, dry_run: bool = False) -> dict[str, int]:
    """Re-encrypt all secrets with the first key. Returns counts; raises if any fail."""
    keys = [k for k in key_setting.split(",") if k.strip()]
    if len(keys) < 2:
        raise SystemExit("MFA_ENCRYPTION_KEY lists one key. Put the NEW key first and the old key second, "
                         "for example NEW_KEY,OLD_KEY, then run this script.")
    cipher = mfa.cipher(key_setting)
    newest = mfa.cipher(keys[0])
    with db.transaction() as tx:
        rows = tx.fetch_all(SQL_SECRETS)
        rotated, failed, already = [], 0, 0
        for row in rows:
            token = row["mfa_secret_encrypted"]
            try:
                newest.decrypt(token.encode())
                already += 1                      # already under the newest key
                continue
            except InvalidToken:
                pass
            try:
                rotated.append((cipher.rotate(token.encode()).decode(), row["user_id"]))
            except InvalidToken:
                failed += 1
        if failed:
            raise SystemExit(f"{failed} stored secret(s) cannot be decrypted with any listed key. Nothing was "
                             "changed. Check that the old key is still listed.")
        if not dry_run:
            for token, user_id in rotated:
                tx.execute("UPDATE users SET mfa_secret_encrypted = ? WHERE user_id = ?", (token, user_id))
            audit.record(tx, "mfa_key_rotated", detail={"re_encrypted": len(rotated),
                                                        "already_current": already})
    return {"secrets": len(rows), "re_encrypted": len(rotated), "already_current": already}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--dry-run", action="store_true", help="count what would change; write nothing")
    args = parser.parse_args(argv)
    settings = get_settings()
    db = Database(settings)
    try:
        counts = rotate(db, settings.mfa_encryption_key, dry_run=args.dry_run)
    finally:
        db.close()
    verb = "would re-encrypt" if args.dry_run else "re-encrypted"
    print(f"{counts['secrets']} stored MFA secret(s): {verb} {counts['re_encrypted']}, "
          f"{counts['already_current']} already under the newest key.")
    if not args.dry_run:
        print("Now set MFA_ENCRYPTION_KEY to the new key only and redeploy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
