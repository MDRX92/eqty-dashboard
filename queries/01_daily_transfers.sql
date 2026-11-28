-- Dagelijkse EQTY transfers (laatste 30 UTC-kalenderdagen, vandaag (deels) inbegrepen)
SELECT
    toDate(block_timestamp) AS date,
    count() AS total_transfers,
    round(sum(toFloat64(variantElement(parameters['value'], 'UInt256'))) / 1e18, 2) AS total_volume_tokens
FROM base.events
WHERE address = '0xc71f37d9bf4c5d1e7fe4bccb97e6f30b11b37d29'
  AND event_name = 'Transfer'
  AND block_timestamp >= toStartOfDay(now()) - INTERVAL 29 DAY
GROUP BY date
ORDER BY date DESC
