"""
Create a local .env for development from .env.example.

* Generates JWT_SECRET and MFA_ENCRYPTION_KEY.
* Blanks the example database URLs (they are placeholders), so the backend and
  pipeline use local SQLite until you paste real Neon URLs in.
* Never overwrites an existing .env.

    python scripts/init_env.py
"""
from __future__ import annotations

import secrets
import sys
from pathlib import Path

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parent.parent
PLACEHOLDER_URL_KEYS = {"APP_DATABASE_URL", "PIPELINE_DATABASE_URL", "BACKUP_DATABASE_URL"}


def build_env(example: str) -> str:
    """Return .env text: generated secrets filled in, placeholder URLs emptied."""
    generated = {
        "JWT_SECRET": secrets.token_urlsafe(48),
        "MFA_ENCRYPTION_KEY": Fernet.generate_key().decode(),
    }
    lines = []
    for line in example.splitlines():
        key, sep, value = line.partition("=")
        key = key.strip()
        if sep and not line.lstrip().startswith("#"):
            # data_pipeline/config.py's minimal loader would keep "  # comment" as part of the value
            value = value.split(" #", 1)[0].strip()
            if key in generated:
                value = generated[key]
            elif key in PLACEHOLDER_URL_KEYS:
                value = ""
            line = f"{key}={value}"
        lines.append(line)
    return "\n".join(lines) + "\n"


def main() -> int:
    target = ROOT / ".env"
    if target.exists():
        print(".env already exists; leaving it unchanged.")
        return 0
    target.write_text(build_env((ROOT / ".env.example").read_text(encoding="utf-8")), encoding="utf-8")
    print("Created .env with generated JWT_SECRET and MFA_ENCRYPTION_KEY (local SQLite mode).")
    print("Never commit it. Set SEED_*_PASSWORD values before seeding users in Phase 1.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
