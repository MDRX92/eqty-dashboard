-- Top 50 holders + concentratie (contracten labelen we later in Python via labels.csv)
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
),
ranked AS (
    SELECT addr, balance,
           row_number() OVER (ORDER BY balance DESC) AS rank,
           sum(balance) OVER () AS circ,
           count() OVER () AS total_holders,
           sum(balance) OVER (ORDER BY balance DESC) AS cum_bal
    FROM bal
)
SELECT rank, addr AS address, round(balance, 2) AS balance,
       round(balance / circ * 100, 2) AS pct_of_supply,
       round(cum_bal / circ * 100, 2) AS cumulative_pct,
       total_holders
FROM ranked
WHERE rank <= 50
ORDER BY rank
