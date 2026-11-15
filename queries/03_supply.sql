-- Total supply = gemunt - verbrand (dynamisch i.p.v. hardcoded)
SELECT
    round(sumIf(v, frm = '0x0000000000000000000000000000000000000000') / 1e18, 2) AS minted,
    round(sumIf(v, too = '0x0000000000000000000000000000000000000000') / 1e18, 2) AS burned,
    minted - burned AS total_supply
FROM (
    SELECT
        variantElement(parameters['from'], 'String') AS frm,
        variantElement(parameters['to'], 'String') AS too,
        toFloat64(variantElement(parameters['value'], 'UInt256')) AS v
    FROM base.events
    WHERE address = '0xc71f37d9bf4c5d1e7fe4bccb97e6f30b11b37d29'
      AND event_name = 'Transfer'
)
