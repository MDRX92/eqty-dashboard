-- Maandelijkse EQTY transfers en volume (laatste 12 maanden)
SELECT
    toStartOfMonth(block_timestamp) AS month,
    count() AS monthly_transfers,
    round(sum(toFloat64(variantElement(parameters['value'], 'UInt256'))) / 1e18, 2) AS monthly_volume_tokens
FROM base.events
WHERE address = '0xc71f37d9bf4c5d1e7fe4bccb97e6f30b11b37d29'
  AND event_name = 'Transfer'
  AND block_timestamp >= toStartOfMonth(now()) - INTERVAL 12 MONTH
GROUP BY month
ORDER BY month ASC
