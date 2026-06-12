"""
Exporterar all data till CSV-filer i data/export/.
Körs av GitHub Actions efter varje insamling.
CSV är git-vänligt: ändringar syns tydligt i diff.
"""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from storage import database as db
from config import DATA_DIR

EXPORT_DIR = DATA_DIR / "export"
EXPORT_DIR.mkdir(exist_ok=True)

db.init_db()


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"  {path.name}: {len(rows)} rader")


def main():
    print("Exporterar till CSV…")

    write_csv(
        EXPORT_DIR / "listrantor.csv",
        db.get_list_rates(limit=50000),
    )

    with db._conn() as con:
        avg_rows = [dict(r) for r in con.execute(
            "SELECT * FROM avg_rates ORDER BY rate_date DESC, bank, period_key"
        ).fetchall()]
    write_csv(EXPORT_DIR / "snittrantor.csv", avg_rows)

    with db._conn() as con:
        ref_rows = [dict(r) for r in con.execute(
            "SELECT * FROM reference_rates ORDER BY rate_date DESC, series_key"
        ).fetchall()]
    write_csv(EXPORT_DIR / "referensrantor.csv", ref_rows)

    write_csv(EXPORT_DIR / "mina_erbjudanden.csv", db.get_my_offers())

    write_csv(EXPORT_DIR / "varningar.csv", db.get_warnings(acknowledged=False, limit=1000))

    print("CSV-export klar.")


if __name__ == "__main__":
    main()
