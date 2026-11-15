"""Market data: Uniswap v4 swaps + ETH/USD, stored incrementally, aggregated to site/data/market.json.

Storage (committed to the repo so history survives between runs):
  data/swaps.csv       one row per swap (deduplicated on tx_hash + log_index)
  data/eth_usd.csv     daily ETH/USD (average pool price, on-chain)

First run backfills month by month from 2025-09-01 (~30 queries, once).
Later runs only fetch the last ~2 days (2 queries).
"""
import csv
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

from cdp_client import run_query

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "site" / "data"
QUERIES = ROOT / "queries"

START = date(2025, 9, 1)
EQTY = "0xc71f37d9bf4c5d1e7fe4bccb97e6f30b11b37d29"
MAIN_POOL = "b2f142b923e23ade711c816a543bf1443f3f911fd2effbe9a417ae94bb8f8f25"  # ETH/EQTY 0.3%
ETH_LIKE = {"0x0000000000000000000000000000000000000000", "0x4200000000000000000000000000000000000006"}
USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"

SWAP_FIELDS = ["time", "tx_hash", "log_index", "taker", "pool_id", "eqty_amount", "amount0_raw"]
BUCKETS = [(100, "Micro (under $100)"), (500, "Small ($100–500)"), (2500, "Medium ($500–2.5k)"),
           (10000, "Large ($2.5k–10k)"), (float("inf"), "Whale ($10k+)")]


# ---------------------------------------------------------------- helpers
def month_ranges(start: date, end: date):
    cur = date(start.year, start.month, 1)
    while cur <= end:
        nxt = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
        yield max(cur, start), min(nxt, end + timedelta(days=1))
        cur = nxt


def fetch_range(sql_template: str, start: date, end: date) -> list[dict]:
    """Run a {start}/{end} query; split the range in half if CDP's scan limit is hit."""
    sql = sql_template.replace("{start}", f"{start} 00:00:00").replace("{end}", f"{end} 00:00:00")
    try:
        return run_query(sql)
    except RuntimeError as exc:
        if "scanned more data" in str(exc) and (end - start).days > 1:
            mid = start + timedelta(days=(end - start).days // 2)
            return fetch_range(sql_template, start, mid) + fetch_range(sql_template, mid, end)
        raise


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict], fields: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def load_pools() -> dict[str, dict]:
    with open(ROOT / "pools.csv", newline="") as f:
        return {r["pool_id"]: r for r in csv.DictReader(f) if r["include"] == "1"}


# ---------------------------------------------------------------- sync
def sync_swaps(today: date) -> list[dict]:
    path = DATA / "swaps.csv"
    rows = read_csv(path)
    tmpl = (QUERIES / "07_swaps.sql").read_text()
    if rows:
        last = max(r["time"] for r in rows)[:10]
        ranges = [(date.fromisoformat(last) - timedelta(days=1), today + timedelta(days=1))]
    else:
        ranges = list(month_ranges(START, today))
        print(f"[market] backfilling swaps in {len(ranges)} monthly chunks")
    seen = {(r["tx_hash"], str(r["log_index"])) for r in rows}
    added = 0
    for s, e in ranges:
        for r in fetch_range(tmpl, s, e):
            key = (r["tx_hash"], str(r["log_index"]))
            if key not in seen:
                seen.add(key)
                rows.append({k: r.get(k) for k in SWAP_FIELDS})
                added += 1
    rows.sort(key=lambda r: (r["time"], int(float(r["log_index"]))))
    write_csv(path, rows, SWAP_FIELDS)
    print(f"[market] swaps: +{added}, total {len(rows)}")
    return rows


def sync_eth_usd(today: date) -> dict[str, float]:
    path = DATA / "eth_usd.csv"
    rows = {r["date"]: float(r["eth_usd"]) for r in read_csv(path)}
    tmpl = (QUERIES / "09_eth_usd_daily.sql").read_text()
    if rows:
        ranges = [(date.fromisoformat(max(rows)) - timedelta(days=1), today + timedelta(days=1))]
    else:
        ranges = list(month_ranges(START, today))
        print(f"[market] backfilling ETH/USD in {len(ranges)} monthly chunks")
    for s, e in ranges:
        for r in fetch_range(tmpl, s, e):
            rows[str(r["date"])[:10]] = float(r["eth_usd"])
    write_csv(path, [{"date": d, "eth_usd": v} for d, v in sorted(rows.items())], ["date", "eth_usd"])
    print(f"[market] ETH/USD days: {len(rows)}")
    return rows


# ---------------------------------------------------------------- live price
def live_price() -> dict:
    out = {}
    try:
        r = requests.get(f"https://api.geckoterminal.com/api/v2/networks/base/pools/0x{MAIN_POOL}",
                         headers={"accept": "application/json"}, timeout=20).json()["data"]["attributes"]
        # base token of this pool on GeckoTerminal is EQTY
        out["price_usd"] = float(r["base_token_price_usd"])
        out["change_24h_pct"] = float(r.get("price_change_percentage", {}).get("h24") or 0)
        out["liquidity_usd"] = float(r.get("reserve_in_usd") or 0)
        out["source"] = "GeckoTerminal"
    except Exception as exc:
        print(f"[market] GeckoTerminal unavailable: {exc}", file=sys.stderr)
    try:
        eur = requests.get("https://api.coingecko.com/api/v3/simple/price",
                           params={"ids": "usd-coin", "vs_currencies": "eur"}, timeout=20).json()
        out["usd_to_eur"] = float(eur["usd-coin"]["eur"])
    except Exception as exc:
        print(f"[market] EUR rate unavailable: {exc}", file=sys.stderr)
    return out


# ---------------------------------------------------------------- aggregate
def enrich(swaps: list[dict], eth_usd: dict[str, float], pools: dict[str, dict]) -> list[dict]:
    """Add day, side, |eqty| and USD value to each swap."""
    eth_days = sorted(eth_usd)

    def eth_on(day):  # nearest earlier day with a price
        if day in eth_usd:
            return eth_usd[day]
        earlier = [d for d in eth_days if d <= day]
        return eth_usd[earlier[-1]] if earlier else (eth_usd[eth_days[0]] if eth_days else None)

    out, pending = [], []
    for s in swaps:
        pool = pools.get(s["pool_id"])
        if not pool:
            continue
        day = s["time"][:10]
        eqty = float(s["eqty_amount"])
        a0 = abs(float(s["amount0_raw"]))
        c0 = pool["currency0"]
        if c0 in ETH_LIKE:
            px = eth_on(day)
            usd = a0 / 1e18 * px if px else None
        elif c0 == USDC:
            usd = a0 / 1e6
        else:
            usd = None  # e.g. AERO pool: valued at the day's EQTY price below
        row = {"time": s["time"], "day": day, "tx_hash": s["tx_hash"], "taker": s["taker"],
               "pool": pool["note"], "main": s["pool_id"] == MAIN_POOL,
               "side": "buy" if eqty > 0 else "sell", "eqty": abs(eqty), "usd": usd}
        out.append(row)
        if usd is None:
            pending.append(row)

    # Daily VWAP from the main ETH/EQTY pool only: the small USDC pools traded at
    # off-market prices (e.g. ~$1 at launch) and would distort the price series.
    vw = defaultdict(lambda: [0.0, 0.0])
    for r in out:
        if r["main"] and r["usd"] is not None and r["eqty"] > 0:
            vw[r["day"]][0] += r["usd"]
            vw[r["day"]][1] += r["eqty"]
    vwap = {d: u / q for d, (u, q) in vw.items() if q}
    days = sorted(vwap)
    for r in pending:
        earlier = [d for d in days if d <= r["day"]]
        r["usd"] = r["eqty"] * vwap[earlier[-1]] if earlier else 0.0
    return out, vwap


def bucket(usd: float) -> str:
    return next(label for limit, label in BUCKETS if usd < limit)


def aggregate(trades, vwap, live, total_supply):
    today = datetime.now(timezone.utc).date()
    d30 = str(today - timedelta(days=30))
    d90 = str(today - timedelta(days=89))

    # monthly buy/sell
    mon = defaultdict(lambda: {"buy_usd": 0.0, "sell_usd": 0.0, "buy_eqty": 0.0, "sell_eqty": 0.0, "trades": 0})
    main_px = defaultdict(lambda: [0.0, 0.0])
    for t in trades:
        m = mon[t["day"][:7]]
        m[f"{t['side']}_usd"] += t["usd"]
        m[f"{t['side']}_eqty"] += t["eqty"]
        m["trades"] += 1
        if t["main"]:
            main_px[t["day"][:7]][0] += t["usd"]
            main_px[t["day"][:7]][1] += t["eqty"]
    monthly = []
    for k in sorted(mon):
        u, q = main_px.get(k, (0.0, 0.0))
        monthly.append({"month": k, **{x: round(y, 2) for x, y in mon[k].items()},
                        "avg_price": round(u / q, 8) if q else None})

    # daily (last 90 days, every day present; price forward-filled)
    day_agg = defaultdict(lambda: {"buy_usd": 0.0, "sell_usd": 0.0, "trades": 0})
    for t in trades:
        if t["day"] >= d90:
            a = day_agg[t["day"]]
            a[f"{t['side']}_usd"] += t["usd"]
            a["trades"] += 1
    daily, last_px = [], None
    for i in range(90):
        d = str(today - timedelta(days=89 - i))
        last_px = vwap.get(d, last_px) or ([vwap[x] for x in sorted(vwap) if x <= d] or [None])[-1]
        a = day_agg.get(d, {"buy_usd": 0.0, "sell_usd": 0.0, "trades": 0})
        daily.append({"date": d, "price": round(last_px, 8) if last_px else None,
                      "buy_usd": round(a["buy_usd"], 2), "sell_usd": round(a["sell_usd"], 2), "trades": a["trades"]})

    # full daily price history (for the long price chart)
    price_history = [{"date": d, "price": round(p, 8)} for d, p in sorted(vwap.items())]

    # trade-size buckets
    def buckets(rows):
        b = {label: {"bucket": label, "trades": 0, "usd": 0.0} for _, label in BUCKETS}
        for t in rows:
            x = b[bucket(t["usd"])]
            x["trades"] += 1
            x["usd"] = round(x["usd"] + t["usd"], 2)
        return list(b.values())

    last30 = [t for t in trades if t["day"] >= d30]
    price = live.get("price_usd") or (price_history[-1]["price"] if price_history else None)
    kpis = {
        "price_usd": price,
        "price_eur": round(price * live["usd_to_eur"], 8) if price and live.get("usd_to_eur") else None,
        "price_source": live.get("source", "last on-chain trade"),
        "change_24h_pct": live.get("change_24h_pct"),
        "liquidity_usd": live.get("liquidity_usd"),
        "fdv_usd": round(price * total_supply, 0) if price and total_supply else None,
        "volume_30d_usd": round(sum(t["usd"] for t in last30), 2),
        "buy_30d_usd": round(sum(t["usd"] for t in last30 if t["side"] == "buy"), 2),
        "sell_30d_usd": round(sum(t["usd"] for t in last30 if t["side"] == "sell"), 2),
        "trades_30d": len(last30),
        "traders_30d": len({t["taker"] for t in last30}),
        "trades_all": len(trades),
        "volume_all_usd": round(sum(t["usd"] for t in trades), 2),
    }
    recent = [{"time": t["time"], "side": t["side"], "eqty": round(t["eqty"], 2), "usd": round(t["usd"], 2),
               "price": round(t["usd"] / t["eqty"], 8) if t["eqty"] else None, "taker": t["taker"],
               "tx_hash": t["tx_hash"], "pool": t["pool"]}
              for t in sorted(trades, key=lambda t: t["time"], reverse=True)[:100]]
    return {"kpis": kpis, "monthly": monthly, "daily_90d": daily, "price_history": price_history,
            "buckets_all": buckets(trades), "buckets_30d": buckets(last30), "recent_trades": recent}


# ---------------------------------------------------------------- entry
def update(now_iso: str) -> None:
    today = datetime.now(timezone.utc).date()
    swaps = sync_swaps(today)
    eth = sync_eth_usd(today)
    pools = load_pools()
    trades, vwap = enrich(swaps, eth, pools)
    supply_file = OUT / "supply.json"
    total_supply = None
    if supply_file.exists():
        rows = json.loads(supply_file.read_text()).get("rows") or [{}]
        total_supply = rows[0].get("total_supply")
    result = aggregate(trades, vwap, live_price(), total_supply)
    (OUT / "market.json").write_text(json.dumps({"updated_at": now_iso, **result}, indent=1))
    print(f"[market] market.json: {len(trades)} trades, price {result['kpis']['price_usd']}")
