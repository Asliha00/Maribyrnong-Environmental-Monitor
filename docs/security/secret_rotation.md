# Secret inventory and rotation (SEC-16)

Every secret the system uses, where it lives, and how to replace it. Rotate a secret
**immediately** if it was committed, screenshotted, pasted into chat or email, or
visible in a video, and record the incident in `DECISIONS.md` (database/README.md,
"If a secret leaks").

Local files (all git-ignored, never committed or shared except through the team password manager):

| File | Holds |
|---|---|
| `.env` | local development settings (SQLite mode): `JWT_SECRET`, `MFA_ENCRYPTION_KEY` |
| `.env.local` | written by `vercel env pull`: Neon owner URLs (Development scope), short-lived `VERCEL_OIDC_TOKEN` |
| `.env.neon` | production (Neon `main`) role URLs, owner URL, `BACKUP_ENCRYPTION_KEY`, `BLOB_READ_WRITE_TOKEN` |
| `.env.neon-dev` | Neon `dev` branch role URLs (Preview deployments) |
| `.env.neon-scratch` | `restore_user` URL on the `restore-scratch` branch |

## Inventory

| Secret | Stored in | Used by |
|---|---|---|
| `app_user` password, `main` | `.env.neon`; Vercel Production `APP_DATABASE_URL`; GitHub `VERIFY_APP_DATABASE_URL` | deployed backend, weekly verification |
| `pipeline_user` password, `main` | `.env.neon`; GitHub `VERIFY_PIPELINE_DATABASE_URL` | data loads, weekly verification |
| `backup_user` password, `main` | `.env.neon`; GitHub `BACKUP_DATABASE_URL`, `VERIFY_BACKUP_DATABASE_URL` | nightly backup, restore test, verification |
| `app_user` / `pipeline_user` / `backup_user` passwords, `dev` | `.env.neon-dev`; Vercel Preview `APP_DATABASE_URL` | preview deployments |
| `restore_user` password, `restore-scratch` | `.env.neon-scratch`; GitHub `SCRATCH_DATABASE_URL` | restore test |
| `neondb_owner` password (same on all branches) | `.env.neon`, `.env.local`; Vercel **Development** scope only | running `database/*.sql`, owner checks |
| `JWT_SECRET` | Vercel Production and Preview (different values, Sensitive); local `.env` | signing access/refresh tokens (Phase 1) |
| `MFA_ENCRYPTION_KEY` | Vercel Production and Preview (different values, Sensitive); local `.env` | encrypting admin TOTP secrets (Phase 1) |
| `BACKUP_ENCRYPTION_KEY` | `.env.neon`; GitHub `BACKUP_ENCRYPTION_KEY`; **team password manager** | encrypting backups |
| `SEED_USER_PASSWORD`, `SEED_ANALYST_PASSWORD`, `SEED_ADMIN_PASSWORD` | `.env` (local), `.env.neon-dev` (dev branch), `.env.neon` (production); different values per environment | demo accounts created by `backend/scripts/seed_users.py`; publication for markers decided in Phase 8 |
| `BLOB_READ_WRITE_TOKEN` | `.env.neon`; GitHub `BLOB_READ_WRITE_TOKEN` | pipeline uploads from laptops/CI, Blob checks in verification |
| Vercel OIDC token | issued by Vercel automatically, short-lived | Blob access from the deployed app; nothing to rotate |

## Rotation procedures

Generate new random values with `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
After changing anything database-related, run `python database/verify_security.py` with the
matching `.env.neon*` file loaded and keep the report.

### Application role on a branch (`app_user`, `pipeline_user`, `backup_user`, `restore_user`)
1. As the owner, on **that branch's** host: `ALTER ROLE <role> WITH PASSWORD '<new>';`
   (or Neon console → Roles). Passwords are per branch: changing `main` does not change `dev`.
2. Update the matching `.env.neon*` file.
3. Update every place in the inventory that holds it (Vercel variable with `--force`, GitHub secret; **value only, no `NAME=`**: the workflows reject that).
4. For `app_user`: redeploy (Vercel → Deployments → Redeploy) and check `/api/health` shows `"database":"ok"`.
5. Run `verify_security.py`. For `backup_user`, also run the nightly-backup workflow by hand.

### `neondb_owner`
Reset it in the Neon console (Roles). It is shared by all branches, so update `OWNER_DATABASE_URL`
in `.env.neon` and run `vercel env pull .env.local --environment=development`. The owner credential
is never in Vercel Production/Preview or GitHub.

### `JWT_SECRET`
Replace with `vercel env add JWT_SECRET production --sensitive --force` (and `preview`), then redeploy.
Effect once Phase 1 is live: every session ends and users log in again. Acceptable after a leak.

### `MFA_ENCRYPTION_KEY`
The setting accepts several Fernet keys, comma-separated, **newest first** (`MultiFernet`,
`backend/app/services/mfa.py`, DECISIONS.md D-026). New secrets are encrypted with the first key;
any listed key can decrypt.
1. Generate a new key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
2. Set the variable to `NEW_KEY,OLD_KEY` in Vercel (Production and Preview separately, Sensitive) and redeploy.
   Administrators can still log in: old secrets decrypt with the old key.
3. Re-encrypt stored secrets with the new key: with the same settings as the site (and the
   variable set to `NEW_KEY,OLD_KEY`), run `python backend/scripts/rotate_mfa_key.py --dry-run`,
   then without `--dry-run`. It re-encrypts every `users.mfa_secret_encrypted` in one
   transaction (nothing changes if any secret cannot be read), records `mfa_key_rotated` in the
   audit log, and never prints secrets or keys. Tested in `backend/tests/test_rotate_mfa_key.py`.
4. After re-encryption, set the variable to `NEW_KEY` only and redeploy.

### `BACKUP_ENCRYPTION_KEY`
1. Generate a new key; update the GitHub secret, `.env.neon` and the password manager.
2. **Keep the old key** in the password manager until every backup made with it has expired
   (artifacts are kept 30 days). Otherwise those backups cannot be restored.
3. Run nightly-backup and restore-test by hand to prove the new key works.

### Demo-account passwords (`SEED_*`)
Generate new values in the matching `.env*` file, then run `python backend/scripts/seed_users.py --reset`
with that file loaded. `--reset` also clears lockouts and reactivates the demo accounts.

### `BLOB_READ_WRITE_TOKEN`
Regenerate it in Vercel (Storage → the Blob store), then update `.env.neon` and the GitHub secret.
The deployed app does not use it (OIDC), so no redeploy is needed.

## Schedule
There is no fixed rotation calendar (risk R18 scope note in BUILD_PROMPT §7.7): secrets are
rotated after any suspected exposure, when a team member leaves, and once before final submission.
Record each rotation in `PROGRESS_DIARY.md`.
