-- Kandidaten voor grote wallet-transfers (geen swaps/LP, geen mints).
-- Swaps en liquiditeit lopen via de Uniswap v4 PoolManager: transacties waarin EQTY van/naar de
-- PoolManager gaat worden uitgesloten. De definitieve drempel (>= 0,25% supply OF >= $10k)
-- en de pivot per afzender worden in Python toegepast met de dagkoers.
WITH pm_tx AS (
    SELECT DISTINCT transaction_hash
    FROM base.events
    WHERE address = '0xc71f37d9bf4c5d1e7fe4bccb97e6f30b11b37d29'
      AND event_name = 'Transfer'
      AND (parameters['from'] = '0x498581ff718922c3f8e6a244956af099b2652b2b'
           OR parameters['to'] = '0x498581ff718922c3f8e6a244956af099b2652b2b')
)
SELECT
    block_timestamp AS time,
    transaction_hash AS tx_hash,
    variantElement(parameters['from'], 'String') AS sender,
    variantElement(parameters['to'], 'String') AS recipient,
    toFloat64(variantElement(parameters['value'], 'UInt256')) / 1e18 AS eqty_amount
FROM base.events
WHERE address = '0xc71f37d9bf4c5d1e7fe4bccb97e6f30b11b37d29'
  AND event_name = 'Transfer'
  AND parameters['from'] != '0x0000000000000000000000000000000000000000'   -- geen mints
  AND parameters['to']   != '0x0000000000000000000000000000000000000000'   -- geen burns
  AND toFloat64(variantElement(parameters['value'], 'UInt256')) / 1e18 >= 100000
  AND NOT (transaction_hash IN (SELECT transaction_hash FROM pm_tx))
ORDER BY time DESC
LIMIT 5000
