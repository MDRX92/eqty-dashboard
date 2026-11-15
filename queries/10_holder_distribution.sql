-- Holder distribution by balance size: number of wallets and share of supply per band.
WITH moves AS (
    SELECT variantElement(parameters['to'], 'String') AS addr,
           toFloat64(variantElement(parameters['value'], 'UInt256')) / 1e18 AS amt
    FROM base.events
    WHERE address = '0xc71f37d9bf4c5d1e7fe4bccb97e6f30b11b37d29' AND event_name = 'Transfer'
    UNION ALL
    SELECT variantElement(parameters['from'], 'String') AS addr,
           -toFloat64(variantElement(parameters['value'], 'UInt256')) / 1e18 AS amt
    FROM base.events
    WHERE address = '0xc71f37d9bf4c5d1e7fe4bccb97e6f30b11b37d29' AND event_name = 'Transfer'
),
bal AS (
    SELECT addr, sum(amt) AS balance
    FROM moves
    WHERE addr != '0x0000000000000000000000000000000000000000'
    GROUP BY addr
    HAVING balance > 0.0001
)
SELECT
    multiIf(balance < 1000, 1, balance < 10000, 2, balance < 100000, 3,
            balance < 1000000, 4, balance < 10000000, 5, 6) AS band,
    multiIf(balance < 1000, 'under 1k', balance < 10000, '1k - 10k', balance < 100000, '10k - 100k',
            balance < 1000000, '100k - 1M', balance < 10000000, '1M - 10M', '10M+') AS band_label,
    count() AS wallets,
    round(sum(balance), 2) AS total_eqty
FROM bal
GROUP BY band, band_label
ORDER BY band
