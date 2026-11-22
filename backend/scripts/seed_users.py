"""
Create the two demo accounts, one per role: Analyst and Administrator (DECISIONS.md D-035).

    python backend/scripts/seed_users.py              # local SQLite (from .env)
    python backend/scripts/seed_users.py --reset      # also reset passwords of existing demo accounts

Passwords come only from SEED_ADMIN_PASSWORD and SEED_ANALYST_PASSWORD and must pass
the SEC-05 policy. They are never printed.
Demo accounts start with must_change_password = 0 so every marker can log in with
the documented password. The demo administrator still has to enrol MFA
(how markers get past MFA is decided in Phase 8: DECISIONS.md D-025).
Writes go through the app's own database role (app_user on Neon), as for any user.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import data_pipeline.config  # noqa: E402,F401  (loads .env into the environment, like the pipeline)
from backend.app.config import get_settings  # noqa: E402
from backend.app.db import Database  # noqa: E402
from backend.app.passwords import hash_password, policy_violations  # noqa: E402
from backend.app.services import audit  # noqa: E402

DEMO_ACCOUNTS = [
    # (username, email, role_id, password variable)
    ("demo_analyst", "demo.analyst@example.org", 2, "SEED_ANALYST_PASSWORD"),
    ("demo_admin", "demo.admin@example.org", 3, "SEED_ADMIN_PASSWORD"),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true", help="reset passwords and lockouts of existing demo accounts")
    args = parser.parse_args(argv)

    settings = get_settings()
    passwords = {}
    for username, email, _, var in DEMO_ACCOUNTS:
        value = os.environ.get(var, "")
        if not value:
            print(f"{var} is not set (see .env.example).")
            return 1
        problems = policy_violations(value, username, email)
        if problems:
            print(f"{var} does not meet the password policy: {' '.join(problems)}")
            return 1
        passwords[username] = value

    db = Database(settings)
    with db.transaction() as tx:
        for username, email, role_id, _ in DEMO_ACCOUNTS:
            existing = tx.fetch_one("SELECT user_id FROM users WHERE username = ?", (username,))
            if existing is None:
                row = tx.fetch_one(
                    """INSERT INTO users (username, email, password_hash, role_id, must_change_password)
                       VALUES (?, ?, ?, ?, 0) RETURNING user_id""",
                    (username, email, hash_password(passwords[username]), role_id))
                audit.record(tx, "user_seeded", user_id=row["user_id"], detail={"username": username})
                print(f"created  {username} <{email}>")
            elif args.reset:
                tx.execute("""UPDATE users SET password_hash = ?, failed_attempts = 0, locked_until = NULL,
                              is_active = 1 WHERE user_id = ?""",
                           (hash_password(passwords[username]), existing["user_id"]))
                audit.record(tx, "user_seed_reset", user_id=existing["user_id"], detail={"username": username})
                print(f"reset    {username} <{email}>")
            else:
                print(f"exists   {username} <{email}> (use --reset to reset its password)")
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
