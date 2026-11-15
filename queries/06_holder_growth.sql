-- Holders door de tijd, historisch correct: nieuwe holders, uitstappers en totaal per dag
WITH moves AS (
    SELECT toDate(block_timestamp) AS d, variantElement(parameters['to'], 'String') AS addr,
           toFloat64(variantElement(parameters['value'], 'UInt256')) / 1e18 AS amt
    FROM base.events
    WHERE address = '0xc71f37d9bf4c5d1e7fe4bccb97e6f30b11b37d29' AND event_name = 'Transfer'
    UNION ALL
    SELECT toDate(block_timestamp) AS d, variantElement(parameters['from'], 'String') AS addr,
           -toFloat64(variantElement(parameters['value'], 'UInt256')) / 1e18 AS amt
    FROM base.events
    WHERE address = '0xc71f37d9bf4c5d1e7fe4bccb97e6f30b11b37d29' AND event_name = 'Transfer'
),
daily AS (
    SELECT addr, d, sum(amt) AS net
    FROM moves
    WHERE addr != '0x0000000000000000000000000000000000000000'
    GROUP BY addr, d
),
run AS (
    SELECT d, net,
           sum(net) OVER (PARTITION BY addr ORDER BY d) AS cum
    FROM daily
),
st AS (
    -- holder na deze dag vs. holder vóór deze dag (cum - net); lagInFrame is niet toegestaan in CDP
    SELECT d, toUInt8(cum > 0.0001) AS is_h, toUInt8(cum - net > 0.0001) AS was_h
    FROM run
),
per_day AS (
    SELECT d, countIf(is_h = 1 AND was_h = 0) AS new_holders, countIf(is_h = 0 AND was_h = 1) AS exited_holders
    FROM st
    GROUP BY d
)
SELECT d AS date, new_holders, exited_holders,
       sum(toInt64(new_holders) - toInt64(exited_holders)) OVER (ORDER BY d) AS total_holders
FROM per_day
ORDER BY date DESC
