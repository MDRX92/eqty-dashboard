"""Whale tracker: large wallet-to-wallet EQTY transfers (no swaps, no LP, no mints).

Rules (same as the old Dune dashboard):
  * large transfer  = >= 0.25% of total supply  OR  >= $10k at that day's price
  * pivot by sender = >= 0.50% of total supply  OR  >= $10k
Candidates (>= 100k EQTY) come from queries/08_large_transfers.sql; the USD rule uses the
daily EQTY price (VWAP) computed in market.py.
"""
import csv
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cdp_client import run_query

ROOT = Path(__file__).resolve().parent.parent
LARGE_PCT, PIVOT_PCT, USD_MIN = 0.25, 0.50, 10_000


def load_labels() -> dict[str, str]:
    with open(ROOT / "labels.csv", newline="") as f:
        return {r["address"].lower(): r["label"] for r in csv.DictReader(f)}


def price_on(day: str, vwap: dict[str, float], days: list[str]):
    if day in vwap:
        return vwap[day]
    earlier = [d for d in days if d <= day]
    return vwap[earlier[-1]] if earlier else None


def build(candidates: list[dict], vwap: dict[str, float], total_supply: float) -> dict:
    labels = load_labels()
    days = sorted(vwap)
    supply = total_supply or 291_044_629.0
    rows = []
    for c in candidates:
        eqty = float(c["eqty_amount"])
        day = str(c["time"])[:10]
        px = price_on(day, vwap, days)
        usd = eqty * px if px else None
        pct = eqty / supply * 100
        rows.append({
            "time": c["time"], "tx_hash": c["tx_hash"],
            "sender": c["sender"], "sender_label": labels.get(str(c["sender"]).lower(), ""),
            "recipient": c["recipient"], "recipient_label": labels.get(str(c["recipient"]).lower(), ""),
            "eqty": round(eqty, 2), "pct_supply": round(pct, 3), "usd": round(usd, 2) if usd else None,
        })
    rows.sort(key=lambda r: r["time"], reverse=True)

    large = [r for r in rows if r["pct_supply"] >= LARGE_PCT or (r["usd"] or 0) >= USD_MIN]

    # monthly overview of large transfers
    mon = defaultdict(lambda: {"count": 0, "eqty": 0.0})
    for r in large:
        m = mon[str(r["time"])[:7]]
        m["count"] += 1
        m["eqty"] += r["eqty"]
    monthly = [{"month": k, "count": v["count"], "eqty": round(v["eqty"], 2)} for k, v in sorted(mon.items())]

    # pivot by sender (stricter threshold, like Dune)
    piv = defaultdict(lambda: {"count": 0, "eqty": 0.0, "last": "", "recipients": set()})
    for r in rows:
        if r["pct_supply"] >= PIVOT_PCT or (r["usd"] or 0) >= USD_MIN:
            p = piv[r["sender"]]
            p["count"] += 1
            p["eqty"] += r["eqty"]
            p["last"] = max(p["last"], str(r["time"]))
            p["recipients"].add(r["recipient"])
    pivot = sorted(({"sender": s, "label": labels.get(s.lower(), ""), "count": p["count"],
                     "total_eqty": round(p["eqty"], 2), "avg_eqty": round(p["eqty"] / p["count"], 2),
                     "recipients": len(p["recipients"]), "last": p["last"]} for s, p in piv.items()),
                   key=lambda x: (-x["count"], -x["total_eqty"]))[:50]

    since = str(datetime.now(timezone.utc) - timedelta(days=30))[:10]
    last30 = [r for r in large if str(r["time"])[:10] >= since]
    kpis = {
        "large_30d": len(last30),
        "large_30d_eqty": round(sum(r["eqty"] for r in last30), 2),
        "large_all": len(large),
        "largest_30d": max(last30, key=lambda r: r["eqty"]) if last30 else None,
        "threshold_eqty": round(supply * LARGE_PCT / 100, 0),
    }
    return {"kpis": kpis, "latest": large[:100], "monthly": monthly, "pivot": pivot,
            "rules": {"large_pct": LARGE_PCT, "pivot_pct": PIVOT_PCT, "usd_min": USD_MIN}}


def update(vwap: dict[str, float], total_supply: float) -> dict:
    sql = (ROOT / "queries" / "08_large_transfers.sql").read_text()
    candidates = run_query(sql)
    result = build(candidates, vwap, total_supply)
    print(f"[whales] {len(candidates)} candidates -> {result['kpis']['large_all']} large transfers")
    return result
