-- Dagkoers ETH/USD on-chain uit de Uniswap v3 WETH/USDC 0,05%-pool op Base (token0 = WETH, token1 = USDC).
-- Alleen nodig voor de eenmalige backfill vóór de periode die GeckoTerminal gratis levert (~6 maanden).
-- Placeholders {start} en {end}; per maand draaien.
SELECT
    toDate(block_timestamp) AS date,
    round(avg(pow(toFloat64(variantElement(parameters['sqrtPriceX96'], 'UInt256')) / pow(2, 96), 2) * 1e12), 2) AS eth_usd
FROM base.events
WHERE address = '0xd0b53d9277642d899df5c87a3966a349a798f224'
  AND event_name = 'Swap'
  AND block_timestamp >= '{start}' AND block_timestamp < '{end}'
GROUP BY date
ORDER BY date
