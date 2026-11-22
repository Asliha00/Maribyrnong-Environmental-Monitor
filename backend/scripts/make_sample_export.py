"""
Build the committed sample export (BUILD_PROMPT §8 Phase 4) from the local full-year database,
with the same code the API uses (`export.gather` + `export.render`).

    python backend/scripts/make_sample_export.py [--db data/processed/environment.db]

Writes docs/samples/sample_report_pm25_daily.pdf: PM2.5, daily means, the whole data range,
every sensor, flagged readings excluded. It contains only aggregated values (no raw rows).
The database is opened read-only.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.db import Transaction  # noqa: E402
from backend.app.services import data, export  # noqa: E402

OUT = ROOT / "docs" / "samples" / "sample_report_pm25_daily.pdf"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "processed" / "environment.db")
    args = parser.parse_args()
    conn = sqlite3.connect(f"{args.db.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        tx = Transaction(conn, "sqlite")
        span = data.meta(tx)["data_range"]
        start, end = date.fromisoformat(span["first_day"]), date.fromisoformat(span["last_day"])
        gathered = export.gather(tx, "pm25", "day", start, end, [], [], True)
    finally:
        conn.close()
    pdf = export.render("pdf", gathered)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(pdf)
    print(f"{OUT.relative_to(ROOT)}: {len(pdf):,} bytes, {export.row_count(gathered.result):,} rows summarised, "
          f"{gathered.exceedances['total']} exceedances, {start} to {end}")


if __name__ == "__main__":
    main()
