-- Holders per cohortjaar en lifecycle-status
WITH moves AS (
    SELECT block_timestamp AS ts, variantElement(parameters['to'], 'String') AS addr,
           toFloat64(variantElement(parameters['value'], 'UInt256')) / 1e18 AS amt
    FROM base.events
    WHERE address = '0xc71f37d9bf4c5d1e7fe4bccb97e6f30b11b37d29' AND event_name = 'Transfer'
    UNION ALL
    SELECT block_timestamp AS ts, variantElement(parameters['from'], 'String') AS addr,
           -toFloat64(variantElement(parameters['value'], 'UInt256')) / 1e18 AS amt
    FROM base.events
    WHERE address = '0xc71f37d9bf4c5d1e7fe4bccb97e6f30b11b37d29' AND event_name = 'Transfer'
),
w AS (
    SELECT addr, min(ts) AS first_seen, max(ts) AS last_active, sum(amt) AS bal
    FROM moves
    WHERE addr != '0x0000000000000000000000000000000000000000'
    GROUP BY addr
    HAVING bal > 0.0001
)
SELECT toString(toYear(first_seen)) AS cohort_year,
       multiIf(last_active >= now() - INTERVAL 30 DAY, '1. Active (0-30d)',
               last_active >= now() - INTERVAL 90 DAY, '2. Steady holder (30-90d)',
               last_active >= now() - INTERVAL 365 DAY, '3. Diamond hands (90d-1yr)',
               '4. Long-term sleeping (>1yr)') AS lifecycle_status,
       count() AS unique_holders,
       round(sum(bal), 2) AS total_token_balance
FROM w
GROUP BY cohort_year, lifecycle_status
ORDER BY cohort_year DESC, lifecycle_status ASC
