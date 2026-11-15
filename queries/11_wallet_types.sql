-- Which events do these addresses emit? Used to recognise Safe multisigs, Coinbase Smart Wallets
-- and other contracts among the top holders, traders and whales.
-- The address list placeholder is filled in by scripts/labels.py (batches of 25, quoted, lowercase).
SELECT address, event_signature, count() AS n
FROM base.events
WHERE address IN ({addresses})
  AND block_timestamp >= '2023-01-01 00:00:00'
GROUP BY address, event_signature
