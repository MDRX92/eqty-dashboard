"""DAO liquidity position in the main ETH/EQTY Uniswap v4 pool (daily refreshable).

The DAO seeded the pool at launch (2025-10-10) with a single full-range position
(wallet 0xa0f71c..., confirmed DAO) and never withdrew. This computes, per day:
  - the position's token split (ETH / EQTY) and USD value (liquidity math)
  - the "just HODL" value of the originally deposited tokens
  - impermanent loss = position value - HODL value
  - estimated fees = pool swap volume x 0.3% x the position's liquidity share, while in range

ModifyLiquidity events are stored incrementally in data/lp_modliq.csv so only the
last two months are re-queried each day. token0 = ETH (native), token1 = EQTY,
both 18 decimals, so pool price P = token1/token0 = EQTY-per-ETH = eth_usd / eqty_usd.
"""
import csv
import json
import math
import sys
from collections import defaultdict
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

import requests

import market
from cdp_client import run_query

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "site" / "data"
STORE = DATA / "lp_modliq.csv"

POOL = "b2f142b923e23ade711c816a543bf1443f3f911fd2effbe9a417ae94bb8f8f25"
PM = "0x498581ff718922c3f8e6a244956af099b2652b2b"
POSITION = "0xa0f71c74054bcd9b1009b63770b7c6bdb227297c"  # confirmed DAO liquidity wallet
EQTY = "0xc71f37d9bf4c5d1e7fe4bccb97e6f30b11b37d29"
OWNER = "EQTY DAO"
FEE = 0.003
START = date(2025, 10, 1)
FIELDS = ["ts", "lp", "liq", "tick_lower", "tick_upper", "tx", "li"]

MODLIQ = """
SELECT block_timestamp AS ts, transaction_from AS lp,
       toFloat64(variantElement(parameters['liquidityDelta'],'Int256')) AS liq,
       toFloat64(variantElement(parameters['tickLower'],'Int256')) AS tick_lower,
       toFloat64(variantElement(parameters['tickUpper'],'Int256')) AS tick_upper,
       transaction_hash AS tx, log_index AS li
FROM base.events
WHERE address = '{pm}' AND event_name = 'ModifyLiquidity'
  AND parameters['id'] = unhex('{pool}')
  AND block_timestamp >= '{start}' AND block_timestamp < '{end}'
"""


def months(start, end):
    cur = date(start.year, start.month, 1)
    while cur <= end:
        nxt = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
        yield cur, nxt
        cur = nxt


def read_store():
    if not STORE.exists():
        return []
    with open(STORE, newline="") as f:
        return list(csv.DictReader(f))


def sync_modliq(today):
    rows = read_store()
    if rows:
        last = max(r["ts"] for r in rows)[:10]
        ranges = [(date.fromisoformat(last).replace(day=1), today + timedelta(days=1))]
    else:
        ranges = list(months(START, today))
        print(f"[lp] backfilling ModifyLiquidity in {len(ranges)} chunks", flush=True)
    seen = {(r["tx"], str(r["li"])) for r in rows}
    added = 0
    for s, e in ranges:
        sql = MODLIQ.format(pm=PM, pool=POOL, start=f"{s} 00:00:00", end=f"{e} 00:00:00")
        for r in run_query(sql):
            key = (str(r["tx"]), str(r["li"]))
            if key not in seen:
                seen.add(key)
                rows.append({"ts": str(r["ts"]), "lp": str(r["lp"]).lower(), "liq": r["liq"],
                             "tick_lower": r["tick_lower"], "tick_upper": r["tick_upper"],
                             "tx": str(r["tx"]), "li": r["li"]})
                added += 1
    rows.sort(key=lambda r: (r["ts"], int(float(r["li"]))))
    STORE.parent.mkdir(parents=True, exist_ok=True)
    with open(STORE, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"[lp] modliq events: +{added}, total {len(rows)}", flush=True)
    return rows


def amounts(L, P, Pa, Pb):
    """token0 (ETH) and token1 (EQTY), raw units, for liquidity L at price P (token1/token0)."""
    sp, spa, spb = math.sqrt(P), math.sqrt(Pa), math.sqrt(Pb)
    if sp <= spa:
        return L * (1 / spa - 1 / spb), 0.0
    if sp < spb:
        return L * (1 / sp - 1 / spb), L * (sp - spa)
    return 0.0, L * (spb - spa)


DEPOSIT_SQL = f"""
SELECT round(sum(toFloat64(variantElement(parameters['value'],'UInt256'))/1e18), 2) AS eqty
FROM base.events
WHERE address = '{EQTY}' AND event_name = 'Transfer'
  AND variantElement(parameters['from'],'String') = '{POSITION}'
  AND variantElement(parameters['to'],'String') = '{PM}'
"""


def deposit_eqty_direct():
    """EQTY the DAO actually sent into the pool at launch (direct on-chain transfers)."""
    try:
        rows = run_query(DEPOSIT_SQL)
        v = rows[0].get("eqty") if rows else None
        return float(v) if v else None
    except Exception as exc:
        print(f"[lp] deposit query failed: {exc}", file=sys.stderr)
        return None


def live_reserves():
    """Current pool reserves from DexScreener: (ETH, EQTY, USD). None if unavailable.

    baseToken = EQTY, quoteToken = ETH, so liquidity.quote = ETH and liquidity.base = EQTY.
    Tries the pair endpoint, then the token endpoint, with a retry; never raises.
    """
    import time as _t
    want = "0x" + POOL
    urls = ["https://api.dexscreener.com/latest/dex/pairs/base/" + POOL,
            "https://api.dexscreener.com/latest/dex/tokens/" + EQTY]
    hdr = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    for url in urls:
        for attempt in (1, 2):
            try:
                r = requests.get(url, headers=hdr, timeout=20).json()
                pairs = r.get("pairs") or ([r["pair"]] if r.get("pair") else [])
                for pr in (pairs or []):
                    if str(pr.get("pairAddress", "")).lower() != want:
                        continue
                    liq = pr.get("liquidity") or {}
                    if liq.get("base") and liq.get("quote"):
                        return float(liq["quote"]), float(liq["base"]), float(liq["usd"])
            except Exception:
                pass
            _t.sleep(2)
    print("[lp] live reserves unavailable (all sources); using model", file=sys.stderr)
    return None


def compute(events):
    pos_L, tlo, thi, first_add = 0.0, None, None, None
    for r in events:
        if r["lp"] == POSITION:
            liq = float(r["liq"])
            pos_L += liq
            if liq > 0:
                first_add = r["ts"][:10] if first_add is None else min(first_add, r["ts"][:10])
                tl, tu = float(r["tick_lower"]), float(r["tick_upper"])
                tlo = tl if tlo is None else min(tlo, tl)
                thi = tu if thi is None else max(thi, tu)
    Pa, Pb = 1.0001 ** tlo, 1.0001 ** thi

    by_day = defaultdict(float)
    for r in events:
        by_day[r["ts"][:10]] += float(r["liq"])
    days_sorted = sorted(by_day)
    total_L, cum = {}, 0.0
    for d in days_sorted:
        cum += by_day[d]
        total_L[d] = cum

    def share_on(d):
        earlier = [x for x in days_sorted if x <= d]
        tot = total_L[earlier[-1]] if earlier else pos_L
        return min(1.0, pos_L / tot) if tot > 0 else 1.0

    swaps = market.load_swaps()
    eth = {r["date"]: float(r["eth_usd"]) for r in market.read_csv(DATA / "eth_usd.csv")}
    trades, vwap = market.enrich(swaps, eth, market.load_pools())
    vol_day = defaultdict(float)
    for t in trades:
        if t["main"]:          # fees accrue only in the DAO's own pool (ETH/EQTY 0.3%)
            vol_day[t["day"]] += t["usd"]

    vwap_keys, eth_keys = sorted(vwap), sorted(eth)

    def ff(mapping, keys, d):
        if d in mapping:
            return mapping[d]
        earlier = [k for k in keys if k <= d]
        return mapping[earlier[-1]] if earlier else (mapping[keys[0]] if keys else None)

    # start at the DAO's first deposit, never earlier (no fees before the position existed)
    launch = first_add or (min(vwap) if vwap else str(date.today()))
    if vwap and launch < min(vwap):
        launch = min(vwap)
    e0, h0 = ff(vwap, vwap_keys, launch), ff(eth, eth_keys, launch)
    P0 = h0 / e0
    dep_eth, dep_eqty_math = amounts(pos_L, P0, Pa, Pb)
    dep_eth /= 1e18
    dep_eqty_math /= 1e18
    dep_eqty = deposit_eqty_direct() or round(dep_eqty_math, 2)   # prefer the on-chain transfer total
    deposit_usd = dep_eth * h0 + dep_eqty * e0

    series, fees_cum = [], 0.0
    today = datetime.now(timezone.utc).date()
    d = date.fromisoformat(launch)
    while d <= today:
        ds = d.isoformat()
        eq, et = ff(vwap, vwap_keys, ds), ff(eth, eth_keys, ds)
        if eq and et:
            P = et / eq
            a0, a1 = amounts(pos_L, P, Pa, Pb)
            a0 /= 1e18
            a1 /= 1e18
            in_range = Pa <= P <= Pb
            if in_range:
                fees_cum += vol_day.get(ds, 0.0) * FEE * share_on(ds)
            series.append({"date": ds, "pos_value": round(a0 * et + a1 * eq, 2),
                           "hodl_value": round(dep_eth * et + dep_eqty * eq, 2),
                           "fees_cum": round(fees_cum, 2), "eth": round(a0, 6), "eqty": round(a1, 2),
                           "in_range": in_range})
        d += timedelta(days=1)

    # current state: prefer live on-chain pool reserves over the daily model
    et_now = ff(eth, eth_keys, today.isoformat())
    eq_now = ff(vwap, vwap_keys, today.isoformat())
    live = live_reserves()
    last = series[-1]
    if live:
        now_eth, now_eqty, pos_val = live
        now_src = "live pool reserves"
    else:
        now_eth, now_eqty, pos_val = last["eth"], last["eqty"], last["pos_value"]
        now_src = "model"
    hodl_now = round(dep_eth * et_now + dep_eqty * eq_now, 2) if (et_now and eq_now) else last["hodl_value"]
    il = round(pos_val - hodl_now, 2)

    # keep the chart's last point consistent with the live figures
    last["pos_value"] = round(pos_val, 2)
    last["hodl_value"] = hodl_now
    last["eth"] = round(now_eth, 6)
    last["eqty"] = round(now_eqty, 2)

    kpis = {
        "owner": OWNER, "wallet": POSITION, "tick_lower": tlo, "tick_upper": thi,
        "full_range": tlo <= -887000 and thi >= 887000,
        "deposit_date": launch, "deposit_eth": round(dep_eth, 4), "deposit_eqty": round(dep_eqty, 2),
        "deposit_usd": round(deposit_usd, 2), "deposit_source": "on-chain transfers",
        "now_eth": round(now_eth, 4), "now_eqty": round(now_eqty, 2),
        "position_value_usd": round(pos_val, 2), "now_source": now_src,
        "hodl_value_usd": hodl_now, "impermanent_loss_usd": il,
        "fees_est_usd": round(fees_cum, 2),
        "net_vs_deposit_usd": round(pos_val + fees_cum - deposit_usd, 2),
        "net_vs_hodl_usd": round(pos_val + fees_cum - hodl_now, 2),
        "return_pct": round((pos_val + fees_cum - deposit_usd) / deposit_usd * 100, 1) if deposit_usd else None,
        "in_range_now": bool(Pa <= (et_now / eq_now) <= Pb) if (et_now and eq_now) else last["in_range"],
    }
    return {"kpis": kpis, "series": series}


def update(now_iso):
    today = datetime.now(timezone.utc).date()
    events = sync_modliq(today)
    data = compute(events)
    (OUT / "lp.json").write_text(json.dumps({"updated_at": now_iso, **data}, indent=1))
    k = data["kpis"]
    print(f"[lp] lp.json: value ${k['position_value_usd']:,.0f}, fees ${k['fees_est_usd']:,.0f}, "
          f"vs HODL ${k['net_vs_hodl_usd']:,.0f}", flush=True)
    return data


if __name__ == "__main__":
    res = update(datetime.now(timezone.utc).isoformat(timespec="seconds"))
    print("LPJSON_START")
    print(json.dumps({"kpis": res["kpis"], "series": res["series"]}, separators=(",", ":")))
    print("LPJSON_END")
