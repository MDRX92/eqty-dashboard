# EQTY on Base – community dashboard

Free, open-source data dashboard for the EQTY DAO.
Replaces the earlier Dune Analytics dashboard (Dune's free plan became view-only in 2026).

**How it works**

```
GitHub Actions (daily)  →  Coinbase CDP SQL API  →  JSON in site/data  →  GitHub Pages
```

- `queries/` – SQL for the CDP SQL API (ClickHouse dialect). See `queries/README.md` for notes and gotchas.
- `scripts/update.py` – runs the queries and writes `site/data/*.json`.
- `scripts/gate.py` – Gate.io EQTY/USDT trades and daily candles from Gate's public API (no key). Gate only serves individual trades for ~30 days, so they are stored in `data/gate_trades/` (one CSV per month) and fetched incrementally each day. Test offline with `python tests/test_gate.py`.
- `site/` – the static dashboard (plain HTML, no build step).
- `pools.csv` – all EQTY pools on Uniswap v4 (spam pools with 88–99.5% fee are excluded).
- `labels.csv` – known contract/exchange addresses. **Add labels via pull request.**

**Run it yourself**

1. Create a free CDP Secret API key (portal.cdp.coinbase.com → API Keys) with no account permissions.
2. Add repository secrets `CDP_API_KEY_ID` and `CDP_API_KEY_SECRET`.
3. Settings → Pages → Source: *GitHub Actions*.
4. Actions → *Update dashboard* → *Run workflow*.

Locally: `pip install -r requirements.txt`, export both variables, `python scripts/update.py`, then open `site/index.html` via a local web server.

**Cost:** CDP gives 1,000 free queries per month; this dashboard uses ~3–10 per day.

## Roadmap
- [x] Supply, top 50 holders, daily transfers
- [x] Holder growth (new / exited / total) and cohorts
- [x] Swaps: buy/sell volume, trade-size buckets (incremental storage + monthly backfill)
- [x] Price (USD/EUR) via GeckoTerminal + on-chain history
- [x] Whale transfers and most active senders
- [x] Gate.io trades (buy/sell) and volume since listing
- [ ] Gate.io orderbook depth snapshots; deposits to the Gate.io hot wallet
