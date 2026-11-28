"""Gate.io (CEX) data for EQTY_USDT: individual trades + daily candles -> site/data/gate.json.

Gate's public API needs no key, but only serves individual trades for roughly the last 30 days.
We therefore store every trade in the repo (one CSV per month, like the Uniswap swaps) and fetch
only what is new on each daily run. If the daily run stops for more than ~25 days, older trades
can no longer be fetched: a warning is written to meta.json well before that happens.

Storage:
  data/gate_trades/YYYY-MM.csv  one row per trade (deduplicated on Gate's trade id)
  data/gate_candles.csv         daily candles since listing (total volume only, no buy/sell split)

Side = taker side, the same convention as the Uniswap swaps (buy = someone bought EQTY).
Trades are in USDT, treated as USD.
"""
import csv
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TRADE_DIR = DATA / "gate_trades"
CANDLES = DATA / "gate_candles.csv"

API = "https://api.gateio.ws/api/v4"
PAIR = "EQTY_USDT"
LIMIT = 1000                 # max trades per request
HISTORY_DAYS = 29            # Gate refuses windows that start ~30 days back
GAP_WARN_DAYS = 25           # warn when the newest stored trade is older than this
TRADE_FIELDS = ["id", "time", "side", "amount", "price", "usdt"]
CANDLE_FIELDS = ["date", "volume_usdt", "volume_eqty", "open", "high", "low", "close"]
BUCKETS = [(10, "Micro (under $10)"), (50, "Small ($10–50)"), (250, "Medium ($50–250)"),
           (1000, "Large ($250–1k)"), (float("inf"), "Very large ($1k+)")]

WARNINGS: list[str] = []
SESSION = requests.Session()
SESSION.headers["Accept"] = "application/json"


# ---------------------------------------------------------------- http
def api_get(path: str, params: dict):
    """GET with one retry. Raises on persistent failure."""
    for attempt in (1, 2):
        try:
            r = SESSION.get(f"{API}{path}", params=params, timeout=30)
            if r.status_code == 429 and attempt == 1:
                time.sleep(3)
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(2)


# ---------------------------------------------------------------- csv helpers
def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def write_if_changed(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    if path.exists() and path.read_bytes() == tmp.read_bytes():
        tmp.unlink()
    else:
        tmp.replace(path)


def load_trades() -> list[dict]:
    rows, seen = [], set()
    for f in sorted(TRADE_DIR.glob("*.csv")):
        for r in read_csv(f):
            if r["id"] not in seen:
                seen.add(r["id"])
                rows.append(r)
    return rows


def save_trades(rows: list[dict]) -> None:
    by_month: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_month[r["time"][:7]].append(r)
    for month, rs in by_month.items():
        write_if_changed(TRADE_DIR / f"{month}.csv", rs, TRADE_FIELDS)


# ---------------------------------------------------------------- fetch
def to_row(t: dict) -> dict:
    ms = float(t.get("create_time_ms") or float(t["create_time"]) * 1000)
    ts = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    amount, px = float(t["amount"]), float(t["price"])
    return {"id": str(t["id"]), "time": ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:23] + "Z",
            "side": t["side"], "amount": amount, "price": px, "usdt": round(amount * px, 6)}


def fetch_window(start: int, end: int, depth: int = 0) -> list[dict]:
    """All trades with start <= time <= end (unix seconds). A full page means there may be more:
    split the window in half instead of relying on page offsets."""
    batch = api_get("/spot/trades", {"currency_pair": PAIR, "limit": LIMIT, "from": start, "to": end})
    if len(batch) < LIMIT:
        return batch
    if end - start <= 60 or depth > 12:
        WARNINGS.append(f"Gate.io: more than {LIMIT} trades in one minute around "
                        f"{datetime.fromtimestamp(start, tz=timezone.utc):%Y-%m-%d %H:%M}; some may be missing.")
        return batch
    mid = (start + end) // 2
    return fetch_window(start, mid, depth + 1) + fetch_window(mid + 1, end, depth + 1)


def sync_trades(now: datetime) -> list[dict]:
    rows = load_trades()
    now_s = int(now.timestamp())
    oldest_allowed = now_s - HISTORY_DAYS * 86400
    if rows:
        last = datetime.fromisoformat(max(r["time"] for r in rows).replace("Z", "+00:00"))
        start = int(last.timestamp()) - 3600            # small overlap; duplicates are dropped
        if start < oldest_allowed:
            WARNINGS.append(f"Gate.io: trades between {last:%Y-%m-%d} and "
                            f"{datetime.fromtimestamp(oldest_allowed, tz=timezone.utc):%Y-%m-%d} "
                            "could not be fetched any more (Gate keeps ~30 days).")
            start = oldest_allowed
    else:
        start = oldest_allowed
        print(f"[gate] backfilling trades for the last {HISTORY_DAYS} days")

    seen = {r["id"] for r in rows}
    added = 0
    skipped = []
    for s in range(start, now_s + 1, 86400):            # one-day windows
        try:
            batch = fetch_window(s, min(s + 86399, now_s))
        except requests.HTTPError:
            # Gate's exact history limit lies between ~25 and 30 days: skip refused old windows.
            if s < now_s - 20 * 86400:
                skipped.append(s)
                continue
            raise
        for t in batch:
            row = to_row(t)
            if row["id"] not in seen:
                seen.add(row["id"])
                rows.append(row)
                added += 1
    if skipped:
        print(f"[gate] {len(skipped)} old day window(s) refused by Gate (history limit)", file=sys.stderr)
    rows.sort(key=lambda r: (r["time"], int(r["id"])))
    save_trades(rows)
    print(f"[gate] trades: +{added}, total {len(rows)}")
    return rows


def sync_candles() -> list[dict]:
    """Daily candles since listing. Row: [t, quote_vol, close, high, low, open, base_vol, closed]."""
    raw = api_get("/spot/candlesticks", {"currency_pair": PAIR, "interval": "1d", "limit": 1000})
    old = {r["date"]: r for r in read_csv(CANDLES)}
    for c in raw:
        d = datetime.fromtimestamp(int(c[0]), tz=timezone.utc).date().isoformat()
        old[d] = {"date": d, "volume_usdt": round(float(c[1]), 2), "volume_eqty": round(float(c[6]), 2),
                  "open": c[5], "high": c[3], "low": c[4], "close": c[2]}
    rows = [old[d] for d in sorted(old)]
    write_if_changed(CANDLES, rows, CANDLE_FIELDS)
    print(f"[gate] candles: {len(rows)} days")
    return rows


# ---------------------------------------------------------------- aggregate
def bucket(usd: float) -> str:
    return next(label for limit, label in BUCKETS if usd < limit)


def aggregate(trades: list[dict], candles: list[dict], today: date) -> dict:
    for t in trades:
        t["usdt"] = float(t["usdt"])
        t["amount"] = float(t["amount"])
    since = min((t["time"][:10] for t in trades), default=None)
    # 30-day windows = the 30 most recent UTC calendar days, today (partial) included
    d30 = str(today - timedelta(days=29))
    d90 = str(today - timedelta(days=89))
    last30 = [t for t in trades if t["time"][:10] >= d30]

    day = defaultdict(lambda: {"buy_usd": 0.0, "sell_usd": 0.0, "buy_eqty": 0.0, "sell_eqty": 0.0, "trades": 0})
    for t in trades:
        if t["time"][:10] >= d90:
            a = day[t["time"][:10]]
            a[f"{t['side']}_usd"] += t["usdt"]
            a[f"{t['side']}_eqty"] += t["amount"]
            a["trades"] += 1
    daily = []
    for i in range(90):
        d = str(today - timedelta(days=89 - i))
        a = day.get(d, {"buy_usd": 0.0, "sell_usd": 0.0, "buy_eqty": 0.0, "sell_eqty": 0.0, "trades": 0})
        daily.append({"date": d, "covered": bool(since and d >= since), **{k: round(v, 2) for k, v in a.items()}})

    mon = defaultdict(lambda: {"volume_usdt": 0.0, "volume_eqty": 0.0})
    for c in candles:
        m = mon[c["date"][:7]]
        m["volume_usdt"] += float(c["volume_usdt"])
        m["volume_eqty"] += float(c["volume_eqty"])
    monthly = [{"month": k, **{x: round(y, 2) for x, y in v.items()}} for k, v in sorted(mon.items())]

    b = {label: {"bucket": label, "trades": 0, "usd": 0.0} for _, label in BUCKETS}
    for t in last30:
        x = b[bucket(t["usdt"])]
        x["trades"] += 1
        x["usd"] = round(x["usd"] + t["usdt"], 2)

    buy = sum(t["usdt"] for t in last30 if t["side"] == "buy")
    sell = sum(t["usdt"] for t in last30 if t["side"] == "sell")
    kpis = {
        "window_start": max(d30, since) if since else None,   # buy/sell data may start later than 30 days ago
        "volume_30d_usd": round(buy + sell, 2), "buy_30d_usd": round(buy, 2), "sell_30d_usd": round(sell, 2),
        "buy_30d_eqty": round(sum(t["amount"] for t in last30 if t["side"] == "buy"), 2),
        "sell_30d_eqty": round(sum(t["amount"] for t in last30 if t["side"] == "sell"), 2),
        "trades_30d": len(last30),
        "candle_volume_30d_usd": round(sum(float(c["volume_usdt"]) for c in candles if c["date"] >= d30), 2),
        "last_price": float(trades[-1]["price"]) if trades else None,
    }
    recent = [{"time": t["time"], "side": t["side"], "eqty": round(t["amount"], 2), "usd": round(t["usdt"], 2),
               "price": float(t["price"])} for t in trades[-100:][::-1]]
    return {"pair": PAIR, "since": since, "kpis": kpis, "daily_90d": daily, "monthly": monthly,
            "buckets_30d": list(b.values()), "recent_trades": recent}


# ---------------------------------------------------------------- entry
def update(now_iso: str) -> dict:
    now = datetime.now(timezone.utc)
    trades = sync_trades(now)
    try:
        candles = sync_candles()
    except Exception as exc:              # candles are nice-to-have; keep the stored ones
        print(f"[gate] candles unavailable: {exc}", file=sys.stderr)
        WARNINGS.append("Gate.io: daily candles could not be refreshed.")
        candles = read_csv(CANDLES)
    if trades:
        newest = datetime.fromisoformat(trades[-1]["time"].replace("Z", "+00:00"))
        if (now - newest).days >= GAP_WARN_DAYS:
            WARNINGS.append(f"Gate.io: newest stored trade is from {newest:%Y-%m-%d}; "
                            "older trades disappear from the API after ~30 days.")
    return {"updated_at": now_iso, **aggregate(trades, candles, now.date())}
