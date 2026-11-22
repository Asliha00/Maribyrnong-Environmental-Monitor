# CLAUDE.md — instructions for every coding session

## Source of truth
Follow **`BUILD_PROMPT.md`**. It is the full specification for this project (NIT3004 capstone, client Maribyrnong City Council).
- Before writing code in a new session, read the files listed in BUILD_PROMPT.md §1, in that order.
- §7 (security requirements SEC-01…SEC-30) applies to **every** phase.
- §11 lists the rules for the coding agent. They are not optional.
- When this file and BUILD_PROMPT.md disagree, BUILD_PROMPT.md wins.

## Work one phase at a time (§8)
- Do one phase only. Never start the next phase without the team's approval.
- **Start of phase:** restate the plan in 5–10 bullets and wait for approval before coding.
- **End of phase:** run the full test suite, update `DECISIONS.md`, list everything deferred, give the team the 5-bullet "what you need to understand about this code" summary, then stop for review.
- Ambiguous requirement: pick the option most consistent with the proposal, record it in `DECISIONS.md`, and carry on.

## Never fabricate
- No invented data, findings, sensor locations, test results, coverage or performance numbers, screenshots, meeting attendance or team contributions.
- Every number must be computed from the database or from a real run. Anything not known yet is marked `TODO`.
- Report failures honestly. A failing or skipped test gets reported as failing or skipped.

## Hard rules (from §11, repeated because they are easy to break)
- Parameterised SQL only. Identifiers come from allow-lists (e.g. `CANONICAL_UNITS`), never from user input.
- A schema change goes into **both** `database/01_schema.sql` and `data_pipeline/schema_sqlite.sql`. Then re-run `02_security.sql` and `verify_security.py`. A table without RLS and grants is a failed build.
- The app connects to Neon only as `app_user` on the pooled host. Never as `neondb_owner`, and never through the `DATABASE_URL`/`DATABASE_URL_UNPOOLED` the Vercel integration injects.
- No secrets in code, logs, screenshots or commits. `.env` stays git-ignored.
- The frontend never talks to Neon or the Blob store directly. The only exception is the admin client upload in §4.5. Tokens never go in `localStorage`.
- Read existing files before changing them. Record any change to `data_pipeline/` logic in `DECISIONS.md`.
- Every feature ships with tests.

## Local environment (Windows)
- Python: `python` on PATH is the Microsoft Store alias, so create the venv with `py -3.12 -m venv .venv`, then use `.venv/Scripts/python`.
- Offline database until Neon is connected: `python data_pipeline/etl.py --sqlite --rebuild` (needs the council CSVs in `data/raw/`, which are git-ignored).
- Pipeline tests: `python -m pytest data_pipeline/tests -v`.
