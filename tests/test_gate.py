"""Offline test for scripts/gate.py with a fake Gate.io API.

Run: python tests/test_gate.py
Covers: backfill, window splitting on full pages (burst day), dedup across overlapping runs,
the ~30-day history limit, gap warning, candle failure fallback, empty API, monthly CSV storage.
"""
import random
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import gate  # noqa: E402
import requests  # noqa: E402

NOW = datetime.now(timezone.utc)
random.seed(1)


def make_trades(now: datetime, days: int = 40) -> list[dict]:
    out, tid = [], 100000
    t = now - timedelta(days=days)
    while t < now:
        # one burst day with ~2500 trades, otherwise ~50/day
        burst = (now - t).days == 3
        t += timedelta(seconds=random.randint(10, 50) if burst else random.randint(600, 2800))
        if t >= now:
            break
        tid += 1
        out.append({"id": str(tid), "create_time": str(int(t.timestamp())),
                    "create_time_ms": f"{t.timestamp() * 1000:.3f}", "side": random.choice(["buy", "sell"]),
                    "amount": str(random.randint(100, 200000)), "price": "0.00105"})
    return out


ALL = make_trades(NOW)
CALLS = {"trades": 0}
FAIL_CANDLES = {"on": False}
EMPTY = {"on": False}
LIMIT_DAYS = {"n": 30}


def fake_api_get(path, params):
    if path == "/spot/candlesticks":
        if FAIL_CANDLES["on"]:
            raise requests.ConnectionError("down")
        rows = []
        for i in range(383):
            ts = int((NOW - timedelta(days=382 - i)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
            rows.append([str(ts), "1000.5", "0.0011", "0.0012", "0.0009", "0.001", "950000", "true"])
        return rows
    CALLS["trades"] += 1
    if EMPTY["on"]:
        return []
    f, t = params["from"], params["to"]
    if f < NOW.timestamp() - LIMIT_DAYS["n"] * 86400:
        raise requests.HTTPError("400 Client Error")   # Gate's history limit
    sel = [x for x in ALL if f <= int(float(x["create_time"])) <= t]
    sel.sort(key=lambda x: -int(x["id"]))              # newest first, like Gate
    return sel[: params["limit"]]


def run(tmp: Path):
    gate.TRADE_DIR = tmp / "gate_trades"
    gate.CANDLES = tmp / "gate_candles.csv"
    gate.api_get = fake_api_get
    gate.WARNINGS.clear()
    return gate.update(NOW.isoformat())


def main():
    tmp = Path(tempfile.mkdtemp())
    try:
        # 1. backfill: everything in the last 29 days, burst day complete (needs splitting)
        out = run(tmp)
        expected = {x["id"] for x in ALL if int(float(x["create_time"])) >= NOW.timestamp() - 29 * 86400}
        stored = {r["id"] for r in gate.load_trades()}
        assert stored == expected, (len(stored), len(expected))
        assert not gate.WARNINGS, gate.WARNINGS
        assert len(out["daily_90d"]) == 90 and out["daily_90d"][-1]["date"] == str(NOW.date())
        burst = max(out["daily_90d"], key=lambda r: r["trades"])
        assert burst["trades"] > 1000, burst
        assert len(out["recent_trades"]) == 100 and out["recent_trades"][0]["time"] > out["recent_trades"][-1]["time"]
        assert len(out["monthly"]) >= 12
        k = out["kpis"]
        assert abs(k["buy_30d_usd"] + k["sell_30d_usd"] - k["volume_30d_usd"]) < 0.05
        assert all(not r["covered"] for r in out["daily_90d"][:55])
        print(f"[ok] backfill: {len(stored)} trades, burst day {burst['trades']} trades, "
              f"{CALLS['trades']} API calls, files {sorted(p.name for p in gate.TRADE_DIR.iterdir())}")

        # 2. second run: no duplicates, months unchanged -> files untouched
        mtimes = {p: p.stat().st_mtime_ns for p in gate.TRADE_DIR.iterdir()}
        CALLS["trades"] = 0
        run(tmp)
        assert len(gate.load_trades()) == len(expected)
        assert all(p.stat().st_mtime_ns == m for p, m in mtimes.items())
        print(f"[ok] incremental: no duplicates, {CALLS['trades']} API calls, files unchanged")

        # 3. stale store (last trade 35 days ago) -> clamp to the history limit + warning
        shutil.rmtree(gate.TRADE_DIR)
        old = gate.to_row(ALL[0])
        gate.save_trades([old])
        run(tmp)
        assert any("could not be fetched" in w for w in gate.WARNINGS), gate.WARNINGS
        print("[ok] gap beyond 30 days: warning ->", gate.WARNINGS[0][:80], "…")

        # 4. candles down -> stored candles used, warning, no crash
        FAIL_CANDLES["on"] = True
        out = run(tmp)
        assert out["monthly"] and any("candles" in w for w in gate.WARNINGS)
        FAIL_CANDLES["on"] = False
        print("[ok] candle failure falls back to stored candles")

        # 5. empty API on a fresh store
        shutil.rmtree(gate.TRADE_DIR)
        EMPTY["on"] = True
        out = run(tmp)
        assert out["since"] is None and out["kpis"]["trades_30d"] == 0 and out["recent_trades"] == []
        EMPTY["on"] = False
        print("[ok] empty API handled")

        # 6. Gate's limit is tighter than 29 days (e.g. 27): old windows skipped, no failure
        shutil.rmtree(gate.TRADE_DIR, ignore_errors=True)
        LIMIT_DAYS["n"] = 27
        out = run(tmp)
        assert out["since"] and out["kpis"]["trades_30d"] > 0
        LIMIT_DAYS["n"] = 30
        print(f"[ok] tighter history limit: data since {out['since']}")
    finally:
        shutil.rmtree(tmp)
    print("all gate tests passed")


if __name__ == "__main__":
    main()
