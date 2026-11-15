# EQTY dashboard – CDP SQL queries

Alle queries draaien op de Coinbase CDP SQL API (`base.events`, ClickHouse-dialect "CoinbaSeQL").
Getest in de CDP SQL Playground op 15-11-2026.

| Bestand | Vervangt (Dune) | Draait | Opmerking |
|---|---|---|---|
| 01_daily_transfers.sql | EQTY Dail transfers | dagelijks | laatste 30 dagen |
| 02_monthly_volume.sql | Monthly volume | dagelijks | 12 volle maanden |
| 03_supply.sql | Total EQTY supply | dagelijks | gemunt − verbrand (geen hardcode meer) |
| 04_top_holders.sql | EQTY Top 50 holders | dagelijks | + totaal aantal holders |
| 05_holder_metrics.sql | Holder metrics | dagelijks | cohort × lifecycle |
| 06_holder_growth.sql | EQTY Active wallets growth | dagelijks | historisch correct: nieuw / uitgestapt / totaal |
| 07_swaps.sql | Uniswap buy sell volume (+ agg) | dagelijks incrementeel, backfill per maand | ruwe swaps → opslag in repo; USD, buckets en aggregaties in Python |
| 08_large_transfers.sql | Latest 100 large transfers + Pivot | dagelijks | kandidaten ≥ 100k EQTY; drempel en pivot in Python |
| 09_eth_usd_daily.sql | (prijs-backfill) | eenmalig per maand | ETH/USD on-chain voor periode vóór GeckoTerminal-historie |
| — | Uniswap current price | dagelijks | GeckoTerminal API (geen SQL) |
| — | Wallet balance - top 50 active wallets | — | vervalt |

## Belangrijke CDP-eigenaardigheden
- Parameters staan in `parameters` (Map met Variant-waarden): gebruik `variantElement(parameters['value'], 'UInt256')`, `variantElement(parameters['from'], 'String')`, `variantElement(parameters['amount1'], 'Int256')`.
- Adressen altijd lowercase.
- bytes32 (bv. Uniswap v4 pool-id) staat als ruwe bytes: filter met `parameters['id'] = unhex('…')`, weergeven met `lower(hex(variantElement(parameters['id'], 'String')))`.
- Niet ondersteund: `ROWS BETWEEN`-frames, `lagInFrame`, `NOT IN` (gebruik `NOT (x IN (…))`).
- Wel ondersteund: CTE's, `UNION ALL`, `row_number()/sum() OVER (PARTITION BY … ORDER BY …)`, `countIf/sumIf`, `multiIf`.
- Scanlimiet ~93 GiB per query: PoolManager-events nooit over de volledige historie; ≤ 3 maanden werkt, script gebruikt 1 maand.
- Max 50.000 rijen per resultaat, 30 s timeout.

## Pools (zie ../pools.csv)
19 EQTY-pools op Uniswap v4, waarvan 13 spampools met 88–99,5% fee. Opgenomen (fee ≤ 1%):
ETH/EQTY 0,3% (`b2f1…`, hoofdpool, sinds 10-10-2025), USDC/EQTY 0,3% (`8ac6…`), WETH, AERO, USDC 1% en 0,4%.
Teken: `eqty_amount` > 0 = koop, < 0 = verkoop.

## Prijs
- Dagkoers EQTY/USD: GeckoTerminal OHLCV van de ETH-pool (gratis ~6 maanden historie).
- Daarvoor: EQTY/ETH uit swaps × ETH/USD (query 09).
- Actuele prijs + EUR: GeckoTerminal token price; EUR-koers via CoinGecko.
