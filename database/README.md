# Neon + Vercel Blob setup (one person does this once, about 30 minutes)

Two managed services hold the project's data:

* **Neon PostgreSQL** holds sensors, clean readings, aggregates, users and the audit log, in a private `app` schema.
* A **private Vercel Blob store** holds the original council CSV files, unchanged. Each file's pathname starts with its SHA-256 hash (`raw/<sha256>__<name>`), so tampering is detectable.

Neither is reachable without credentials. The website reaches both only through the FastAPI backend on Vercel.

## 1. Create the Neon database through Vercel

1. In your Vercel project, open **Storage → Create Database → Neon** (from the Marketplace).
2. Choose the **AWS Sydney (ap-southeast-2)** region, so council and user data stays in Australia (Privacy Act, APP 8).
3. Connect it to the project. Vercel adds `DATABASE_URL` (pooled) and `DATABASE_URL_UNPOOLED` (direct). Those use the **owner** role (`neondb_owner`), which can do anything, so the app must not use them. Steps 3–4 create restricted roles instead.
4. In the Neon Console, check that the **Data API is off** (it is off by default). Turn on **MFA** on every team member's Vercel and Neon account.
5. In Vercel, set the functions region to **Sydney (`syd1`)**, next to the database. This is in `vercel.json`.

## 2. Create the private Blob store

In the same project, open **Storage → Create Storage → Blob** and set access to **Private**. Connect it to the project; on Vercel the SDK then uses short-lived OIDC tokens automatically. For your laptop and GitHub Actions, copy the read-write token from the store's `.env.local` tab into `BLOB_READ_WRITE_TOKEN`.

## 3. Create the schema and lock it down

Use the owner connection string (`DATABASE_URL_UNPOOLED`) as `OWNER_DATABASE_URL`, in your `.env` only:

```bash
psql "$OWNER_DATABASE_URL" -v ON_ERROR_STOP=1 -f database/01_schema.sql
psql "$OWNER_DATABASE_URL" -v ON_ERROR_STOP=1 -f database/02_security.sql
```

You can paste both files into the Neon SQL Editor instead. `02_security.sql` creates three roles with no login yet: `app_user`, `pipeline_user` and `backup_user`. It grants each only what it needs, turns on row-level security, makes the audit log append-only, and stops any other role connecting.

## 4. Give the three roles passwords and build their URLs

Generate three passwords with `python -c "import secrets; print(secrets.token_urlsafe(32))"`. Then run the three `ALTER ROLE ... WITH LOGIN PASSWORD` lines at the bottom of `02_security.sql`.

Build each URL from the owner URL by swapping the user and password:

| Variable | Role | Host | Used by |
|---|---|---|---|
| `APP_DATABASE_URL` | `app_user` | **pooled** (`...-pooler...neon.tech`) | FastAPI on Vercel |
| `PIPELINE_DATABASE_URL` | `pipeline_user` | **direct** | `etl.py` on a laptop or in GitHub Actions |
| `BACKUP_DATABASE_URL` | `backup_user` | **direct** | nightly backup job |

Keep `?sslmode=require` on every URL. `verify-full` is stricter and works if your machine has standard CA certificates.

Put `APP_DATABASE_URL` and the other backend secrets into **Vercel → Settings → Environment Variables**, with different values for Preview and Production. The pipeline URL never goes into Vercel.

## 5. Verify, then load the data

```bash
cp .env.example .env                  # fill in; never commit .env
pip install -r data_pipeline/requirements.txt
python database/verify_security.py    # every check must PASS before loading data
python data_pipeline/etl.py --upload-raw --export-csv
```

The full year of council data loads in under a minute and uses about **125 MB**, well inside Neon's free 0.5 GB.

Everyone else on the team has nothing to do: the data is already in Neon. To rebuild a local SQLite copy from the archived originals, run `python data_pipeline/etl.py --from-storage --sqlite`.

The pipeline runs from a laptop or a GitHub Action, never inside a Vercel function. A full rebuild is longer than a request should take, and it needs the direct host.

## 6. Backups

* Add the repository secrets `BACKUP_DATABASE_URL` and `BACKUP_ENCRYPTION_KEY`. The workflow `.github/workflows/nightly-backup.yml` then makes an encrypted dump every night and keeps it for 30 days.
* Test a restore **before the progress report and again before final submission** with `database/backup/restore_test.sh`, into a scratch database such as a Neon branch or local PostgreSQL. Save the output as evidence.
* Keep `BACKUP_ENCRYPTION_KEY` in the password manager. Without it, the backups cannot be restored.
* Neon's point-in-time restore is an extra safety net, but its free-tier history window is short, and it sits with the same provider. That's why we keep our own copies too.

## Operational notes

* **No pausing.** Neon compute scales to zero after about 5 idle minutes. The first query afterwards takes a moment longer while it wakes, but the data is always there. Nothing needs keeping alive before demos or marking.
* **Preview deployments.** Point Preview's `APP_DATABASE_URL` at a separate long-lived Neon branch called `dev` (Neon Console → Branches). That way pull-request previews never touch the marked data. Branches copy the roles and grants, so run `verify_security.py` against `dev` once. Avoid the integration's automatic per-preview branches: they inject the owner URL, which the app must never use.
* **Free-tier limits change.** Check Neon's and Vercel's pricing pages before the progress report and before submission, and record what you checked in `DECISIONS.md`.
* **If a secret leaks** (committed, screenshotted, pasted in chat), rotate it immediately. Use `ALTER ROLE ... PASSWORD` for database roles; regenerate the Blob token in Vercel. Then update Vercel and GitHub secrets and record the incident in `DECISIONS.md`.
