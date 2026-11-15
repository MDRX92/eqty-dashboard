-- Which events do these addresses emit? Used to recognise Safe multisigs, Coinbase Smart Wallets
-- and other contracts among the top holders, traders and whales.
-- Placeholder {addresses} = comma-separated, quoted, lowercase addresses (filled in by scripts/labels.py).
SELECT address, event_signature, count() AS n
FROM base.events
WHERE address IN ({addresses})
  AND block_timestamp >= '2023-01-01 00:00:00'
GROUP BY address, event_signature
