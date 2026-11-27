"""Daily update: run the dashboard queries on CDP and write JSON for the static site.

Phase 1: supply, top holders, daily transfers.
Phase 2: holder growth (new / exited / total), cohorts × lifecycle, monthly volume.
Phase 3: market (swaps, price, buy/sell volume, trade sizes) via market.py.
Phase 4: whale transfers (whales.py, called from market.py).
Gate.io: CEX trades + daily candles via gate.py (public API, no CDP queries).
"""
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from cdp_client import run_query
import market

ROOT = Path(__file__).resolve().parent.parent
QUERIES = ROOT / "queries"
OUT = ROOT / "site" / "data"

# query file (without .sql) -> output json name
DAILY_QUERIES = {
    "03_supply": "supply",
    "04_top_holders": "top_holders",
    "01_daily_transfers": "daily_transfers",
    "06_holder_growth": "holder_growth",
    "05_holder_metrics": "holder_metrics",
    "02_monthly_volume": "monthly_volume",
    "10_holder_distribution": "holder_distribution",
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

    # Phase 3: market data (swaps, price). Isolated so a failure never blocks the rest.
    try:
        market.update(now)
    except Exception as exc:
        print(f"[FAIL] market: {exc}", file=sys.stderr)
        failures.append("market")

    # DAO liquidity position (Uniswap v4 LP economics). Isolated like market.
    try:
        import lp
        lp.update(now)
    except Exception as exc:
        print(f"[FAIL] lp: {exc}", file=sys.stderr)
        failures.append("lp")

    # Gate.io (CEX) trades + candles. Public API, no CDP queries. Isolated like market.
    try:
        import gate
        (OUT / "gate.json").write_text(json.dumps(gate.update(now), indent=1))
    except Exception as exc:
        print(f"[FAIL] gate: {exc}", file=sys.stderr)
        failures.append("gate")

    # Wallet labels (manual + automatic) for every address shown on the page.
    try:
        import labels
        labels.update(now)
    except Exception as exc:
        print(f"[FAIL] labels: {exc}", file=sys.stderr)
        failures.append("labels")

    warnings = []
    try:
        import labels as _labels
        warnings = _labels.WARNINGS[:20]
    except Exception:
        pass
    try:
        import gate as _gate
        warnings = (_gate.WARNINGS + warnings)[:20]
    except Exception:
        pass
    (OUT / "meta.json").write_text(
        json.dumps({"updated_at": now, "failed": failures, "warnings": warnings}, indent=1)
    )
    # Fail the workflow only if everything failed (e.g. wrong API key).
    return 1 if len(failures) >= len(DAILY_QUERIES) else 0


if __name__ == "__main__":
    sys.exit(main())
