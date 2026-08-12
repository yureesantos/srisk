-- Synthesise betslip legs directly in ClickHouse for the 20M-row measurement.
--
-- This exists to answer build step 1's question — does the analytical read path
-- hold up at target volume — before a producer or consumer exists. Generating
-- server-side avoids conflating storage/query performance with the cost of
-- pushing rows over a client connection, which is a separate measurement.
--
-- Cardinalities and shape are taken from the real export, not invented, so the
-- LowCardinality encoding and the GROUP BY costs are representative:
--   competition 56 · fixture 453 · market 119 · player 2,714 · selection 6,014
--   region 31 · currency 3 (EUR 88% / PEN 12% / USD <1%) · uid 10,405
--
-- Stakes are log-normal rather than uniform: a uniform stake distribution gives
-- a Gini near 0 and would make the concentration metrics meaningless. The real
-- export measures Gini 0.819 (EUR) on turnover per Uid.
--
-- Parameters: {rows:UInt64}, {uid_pool:UInt64}, {version_base:UInt64}

INSERT INTO srisk.betslip_leg
SELECT
    -- Identity hash over the ADR-0007 tuple. cityHash64 stands in for the
    -- consumer's BLAKE2b; what matters here is the distribution, not the digest.
    cityHash64(uid, placed_at, bet_type, match_id, market, player, selection, price) AS row_key,
    {version_base:UInt64} + intDiv(number, 1000)                                    AS version,
    uid,
    placed_at,
    event_at,
    bet_type,
    match_id,
    fixture,
    competition,
    market,
    player,
    selection,
    region,
    currency,
    price,
    turnover,
    ggr,
    net_revenue,
    event_kind,
    source,
    is_inplay,
    minutes_to_kickoff
FROM
(
    SELECT
        number,
        -- Activity skew across Uids, which is the dominant source of measured
        -- concentration: in the real export the busiest Uid carries 2,238 legs
        -- against a median of 4 — a 560x ratio — and turnover Gini per Uid is
        -- 0.803 (EUR). A near-uniform assignment reproduces neither.
        --
        -- A power transform on a uniform draw gives that shape. The exponent
        -- (2.0), the pool size and the stake sigma (2.4, below) were calibrated
        -- together against the real export rather than guessed — they reproduce
        -- Gini 0.820 (real 0.803), a median of 4 legs per Uid (real 4) and a
        -- max/median ratio of 530x (real 560x).
        toString(toUInt64(pow(toFloat64(cityHash64(number, 'uid') % 1000000) / 1000000, 2.0)
                          * {uid_pool:UInt64}))                                       AS uid,

        -- June book, matching the export's shape: 23 dense trading days.
        toDateTime64('2026-06-01 00:00:00', 3, 'UTC')
            + toIntervalSecond(cityHash64(number, 'ts') % 1987200)                   AS placed_at,
        placed_at + toIntervalSecond(cityHash64(number, 'ko') % 172800 - 86400)      AS event_at,

        multiIf(cityHash64(number, 'bt') % 100 < 78, 'SIMPLE', 'COMBINED')           AS bet_type,
        toUInt32(30000000 + cityHash64(number, 'mid') % 453)                         AS match_id,
        concat('Fixture ', toString(cityHash64(number, 'mid') % 453))                AS fixture,
        concat('Competition ', toString(cityHash64(number, 'comp') % 56))            AS competition,
        concat('Market ', toString(cityHash64(number, 'mkt') % 119))                 AS market,
        concat('Player ', toString(cityHash64(number, 'ply') % 2714))                AS player,
        concat('Selection ', toString(cityHash64(number, 'sel') % 6014))             AS selection,
        concat('Region ', toString(cityHash64(number, 'reg') % 31))                  AS region,
        multiIf(cityHash64(number, 'cur') % 1000 < 880, 'EUR',
                cityHash64(number, 'cur') % 1000 < 998, 'PEN', 'USD')                AS currency,

        -- Box-Muller gives a genuine standard normal from two uniforms. A
        -- scaled uniform was tried first and is wrong for this purpose: it
        -- truncates the tail, and the tail is precisely what produces the
        -- measured concentration (Gini 0.819 on EUR turnover per Uid). With a
        -- uniform the p99 and the max sit almost on top of each other.
        sqrt(-2 * log(greatest(toFloat64(cityHash64(number, 'u1') % 1000000) / 1000000, 1e-9)))
            * cos(2 * pi() * toFloat64(cityHash64(number, 'u2') % 1000000) / 1000000)   AS z_stake,
        sqrt(-2 * log(greatest(toFloat64(cityHash64(number, 'u3') % 1000000) / 1000000, 1e-9)))
            * cos(2 * pi() * toFloat64(cityHash64(number, 'u4') % 1000000) / 1000000)   AS z_price,

        -- Price: log-normal around ~2.5, clipped to a plausible betting range.
        toDecimal64(least(greatest(exp(0.85 + 0.55 * z_price), 1.01), 250.0), 3)         AS price,

        -- Stake: log-normal with a real tail. This is what makes Gini and the
        -- concentration curves meaningful rather than flat.
        toDecimal64(least(greatest(exp(2.3 + 2.4 * z_stake), 0.10), 500000.0), 2)        AS turnover,

        -- Settled outcome: house keeps the stake, or pays out at the taken price.
        -- Both branches are cast to the same Decimal scale explicitly: a
        -- conditional over differing scales is rejected outright (NOT_IMPLEMENTED).
        multiIf(cityHash64(number, 'win') % 1000 < 556,
                toDecimal64(toFloat64(turnover), 2),
                toDecimal64(-1 * toFloat64(turnover) * (toFloat64(price) - 1), 2))    AS ggr,
        toDecimal64(toFloat64(ggr) * 0.08, 2)                                        AS net_revenue,

        'placement'                                                                  AS event_kind,
        multiIf(cityHash64(number, 'src') % 100 < 70, 'partner_a', 'partner_b')      AS source,

        toUInt8(placed_at > event_at)                                                AS is_inplay,
        toFloat32(dateDiff('second', event_at, placed_at) / 60.0)                     AS minutes_to_kickoff
    FROM numbers_mt({rows:UInt64})
);
