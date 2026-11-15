-- Swaps in EQTY-pools op Uniswap v4 (alleen pools met fee <= 1%; spampools uitgesloten).
-- Placeholders {start} en {end} (UTC 'YYYY-MM-DD HH:MM:SS') worden door het script ingevuld.
-- Max ~1 maand per query i.v.m. de scanlimiet van de PoolManager.
-- eqty_amount > 0 = koop, < 0 = verkoop (delta vanuit de swapper). EQTY is in alle opgenomen pools currency1.
SELECT
    block_timestamp AS time,
    transaction_hash AS tx_hash,
    transaction_from AS taker,
    lower(hex(variantElement(parameters['id'], 'String'))) AS pool_id,
    toFloat64(variantElement(parameters['amount1'], 'Int256')) / 1e18 AS eqty_amount,
    toFloat64(variantElement(parameters['amount0'], 'Int256')) AS amount0_raw
FROM base.events
WHERE address = '0x498581ff718922c3f8e6a244956af099b2652b2b'
  AND event_name = 'Swap'
  AND block_timestamp >= '{start}' AND block_timestamp < '{end}'
  AND parameters['id'] IN (unhex('b2f142b923e23ade711c816a543bf1443f3f911fd2effbe9a417ae94bb8f8f25'), unhex('8ac62b66b2f9488727add02917498d5ce4b9e74447f471925bb9f5e6d46d9fe7'), unhex('8389aadf1703231b23990a9b32d2f49cc9fdcbc2e53db1044670b6660e38c84f'), unhex('6952a26959b599d26aa0ba4033b7abdcd3e5648ba88fa59cd0a14c4ca1ecc2b7'), unhex('9bcc8c7f1b7a727f652bf7dde3f7e5e9c3ec0aebf6ccaaffca2cde9a38462d33'), unhex('c8f87f1f5ba63424d618ecfcf356454c0fa356136690713d5940e2f1d2ef2f44'))
ORDER BY time
