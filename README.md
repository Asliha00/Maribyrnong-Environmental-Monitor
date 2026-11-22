# Maribyrnong Environmental Equity Dashboard (NIT3004 Capstone)

A secure web dashboard that turns Maribyrnong City Council's smart-sensor data into decision support on urban heat, air quality and green infrastructure.

**Hosting:** website and API on **Vercel** (Sydney), database on **Neon PostgreSQL** (Sydney), original council CSVs in a **private Vercel Blob store**. Everything also runs locally against SQLite.


## Run it locally

Needs Python 3.12+, Node 22+, and the council CSV exports copied into `data/raw/` (not in git).

```bash
python -m venv .venv && . .venv/bin/activate     # Windows: py -3.12 -m venv .venv; .venv\Scripts\activate
make install    # pip install -e ".[dev]" && npm ci --prefix frontend
make env        # creates .env with generated secrets (SQLite mode); never commit it
make db         # builds data/processed/environment.db from data/raw/ (~15 s)
make seed       # demo accounts (set SEED_*_PASSWORD in .env first; min 12 chars)
make dev        # API on :8000 + dashboard on http://localhost:5173
```

No `make` (e.g. Windows)? Each Makefile target lists its plain command: `python scripts/init_env.py`, `python data_pipeline/etl.py --sqlite --rebuild`, `python scripts/dev.py`.

| Command | What it does |
|---|---|
| `make test` | Backend + pipeline tests with coverage (pytest), frontend tests (Vitest) |
| `make lint` | ruff (incl. SQL-injection rule S608), ESLint (incl. `react/no-danger`), Prettier |
| `make e2e` | Playwright browser tests against the local app (needs `make db` and `make seed`) |
| `make audit` | `pip-audit` and `npm audit --audit-level=high` |

API documentation (OpenAPI) is served at `/api/docs`.

Demo logins: two accounts, one per role (Environmental Analyst and System Administrator, the two actors in the proposal's use cases; DECISIONS.md D-035), are created by `make seed`. Their published passwords and how markers handle administrator MFA are decided in Phase 8 (DECISIONS.md D-025).

## Shared database and file archive (Neon + Blob)

One team member sets these up once, following `database/README.md`: add Neon and a private Blob store to the Vercel project, run `01_schema.sql` and `02_security.sql`, then run `python database/verify_security.py` until every check passes. Then load the data with `python data_pipeline/etl.py --upload-raw --export-csv`.

## Repository map

| Folder / file | What it is |
|---|---|
| `BUILD_PROMPT.md` | Full build specification, including §7 security requirements (SEC-01 to SEC-30) |
| `CLAUDE.md` | Rules for AI coding sessions (follow BUILD_PROMPT.md, one phase at a time, never fabricate) |
| `DECISIONS.md` | Architecture decision log  |
| `backend/` | FastAPI app (`backend/app/main.py`) and its tests |
| `frontend/` | React 18 + Vite + TypeScript dashboard |
| `data_pipeline/` | Raw council CSV to validated database (Neon or SQLite), with tests |
| `database/` | Neon schema, security hardening, verification script, encrypted backup/restore |
| `vercel.json` | Sydney region and browser security headers (also applied locally by the backend) |
| `.github/workflows/` | CI, security scans, nightly encrypted backup |
