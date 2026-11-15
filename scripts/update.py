"""Daily update: run the dashboard queries on CDP and write JSON for the static site.

Phase 1 (walking skeleton): supply, top holders and daily transfers.
More queries (holder growth, swaps, whales, price) are added in the next phases.
"""
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from cdp_client import run_query

ROOT = Path(__file__).resolve().parent.parent
QUERIES = ROOT / "queries"
OUT = ROOT / "site" / "data"

# query file (without .sql) -> output json name
DAILY_QUERIES = {
    "03_supply": "supply",
    "04_top_holders": "top_holders",
    "01_daily_transfers": "daily_transfers",
}


def load_labels() -> dict[str, dict]:
    with open(ROOT / "labels.csv", newline="") as f:
        return {row["address"].lower(): row for row in csv.DictReader(f)}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    labels = load_labels()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    failures = []

    for query_file, name in DAILY_QUERIES.items():
        sql = (QUERIES / f"{query_file}.sql").read_text()
        try:
            rows = run_query(sql)
        except Exception as exc:  # keep going; keep yesterday's file for this block
            print(f"[FAIL] {query_file}: {exc}", file=sys.stderr)
            failures.append(query_file)
            continue

        if name == "top_holders":
            for row in rows:
                label = labels.get(str(row.get("address", "")).lower())
                row["label"] = label["label"] if label else ""
                row["type"] = label["type"] if label else ""

        (OUT / f"{name}.json").write_text(
            json.dumps({"updated_at": now, "rows": rows}, indent=1)
        )
        print(f"[OK] {query_file}: {len(rows)} rows -> {name}.json")

    (OUT / "meta.json").write_text(
        json.dumps({"updated_at": now, "failed": failures}, indent=1)
    )
    # Fail the workflow only if everything failed (e.g. wrong API key).
    return 1 if len(failures) == len(DAILY_QUERIES) else 0


if __name__ == "__main__":
    sys.exit(main())
