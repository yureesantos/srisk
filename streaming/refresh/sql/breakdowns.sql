-- Class 1 breakdowns, computed inside ClickHouse.
--
-- These replace pulling every row into pandas. Measured at 20M rows: transfer
-- and parse alone cost ~11s before any aggregation, against 2.73s to aggregate
-- the same 20M in SQL. Aggregation is what the engine is for, and doing it in
-- Python is what made the batch pipeline slow in the first place.
--
-- Three rules from the batch pipeline are reproduced here exactly, because the
-- oracle comparison is the test:
--
--   * **Ranking is by count, never by turnover** (ADR-0001). Turnover cannot be
--     ordered across currencies, so a turnover ranking would be meaningless the
--     moment two currencies appear in one table.
--   * **Money never crosses a currency.** Every money figure is grouped by
--     currency; rows with no currency are counted, never summed.
--   * **A tail rollup carries the remainder.** Top-N plus one `__other__` row,
--     so shares add to 1 and nothing is silently dropped.
--
-- Every read collapses with FINAL (ADR-0012). Omitting it does not merely
-- inflate — it can invert the sign of GGR, and it is intermittent, because a
-- background merge makes the wrong query start returning the right answer.
--
-- Parameters: {dim:Identifier}, {top_n:UInt32}

-- name: leg_breakdown
-- Leg-grain breakdown over one dimension, ranked by leg count, with per-currency
-- money and a tail rollup. `{dim:Identifier}` is bound from a fixed allow-list
-- in the caller, never interpolated from input.
WITH
    ranked AS (
        SELECT
            {dim:Identifier}                                  AS key,
            count()                                           AS legs,
            uniqExact((if(bet_type = 'SIMPLE', row_key, 0), uid, placed_at, bet_type))             AS betslips,
            row_number() OVER (ORDER BY count() DESC, key ASC) AS rank
        FROM betslip_leg FINAL
        GROUP BY key
    ),
    money AS (
        SELECT
            {dim:Identifier}          AS key,
            currency,
            round(sum(turnover), 2)   AS turnover,
            round(sum(ggr), 2)        AS ggr
        FROM betslip_leg FINAL
        WHERE currency != ''
        GROUP BY key, currency
    )
SELECT
    if(r.rank <= {top_n:UInt32}, r.key, '__other__')          AS key,
    sum(r.legs)                                               AS legs,
    sum(r.betslips)                                           AS betslips,
    countDistinct(r.key)                                      AS members,
    -- Money is emitted as parallel arrays and nested by the caller: a currency
    -- key is never summed across, so the shape has to survive the transport.
    groupArrayIf(m.currency, m.currency != '')                AS currencies,
    groupArrayIf(m.turnover, m.currency != '')                AS turnovers,
    groupArrayIf(m.ggr, m.currency != '')                     AS ggrs
FROM ranked AS r
LEFT JOIN money AS m ON r.key = m.key
GROUP BY key
ORDER BY legs DESC;

-- name: betslip_breakdown
-- Betslip-grain breakdown. Turnover is only real at betslip grain (ADR-0003):
-- a combined bet repeats its stake on every leg, so summing legs inflates it by
-- a measured 1.087x on EUR. The inner query reduces legs to betslips first.
WITH
    betslips AS (
        SELECT
            argMin({dim:Identifier}, placed_at) AS key,
            argMin(currency, placed_at)         AS currency,
            argMin(turnover, placed_at)         AS turnover,
            argMin(ggr, placed_at)              AS ggr
        FROM betslip_leg FINAL
        -- The betslip identity of ADR-0003, and it is subtler than it looks.
        -- `GROUP BY uid, placed_at, bet_type` is NOT enough: a customer placing
        -- several SIMPLE bets in the same second has several betslips, not one.
        -- Measured on the export — 1,662 such groups holding 27,865 SIMPLE legs,
        -- worth 3,265 betslips that the naive key merges away (55,299 against
        -- 52,034, a 5.9% undercount that propagates into every betslip-grain
        -- figure including turnover).
        --
        -- So: a SIMPLE leg is its own betslip; COMBINED legs group by
        -- (uid, timestamp). The `if` on row_key is what splits them.
        GROUP BY
            if(bet_type = 'SIMPLE', row_key, 0),
            uid, placed_at, bet_type
    ),
    ranked AS (
        SELECT key, count() AS betslips,
               row_number() OVER (ORDER BY count() DESC, key ASC) AS rank
        FROM betslips GROUP BY key
    ),
    money AS (
        SELECT key, currency, round(sum(turnover), 2) AS turnover,
               round(sum(ggr), 2) AS ggr
        FROM betslips WHERE currency != '' GROUP BY key, currency
    )
SELECT
    if(r.rank <= {top_n:UInt32}, r.key, '__other__') AS key,
    sum(r.betslips)                                  AS betslips,
    countDistinct(r.key)                             AS members,
    groupArrayIf(m.currency, m.currency != '')       AS currencies,
    groupArrayIf(m.turnover, m.currency != '')       AS turnovers,
    groupArrayIf(m.ggr, m.currency != '')            AS ggrs
FROM ranked AS r
LEFT JOIN money AS m ON r.key = m.key
GROUP BY key
ORDER BY betslips DESC;

-- name: universe
-- The overview counters, in one pass rather than one query per figure.
SELECT
    count()                               AS legs,
    uniqExact((if(bet_type = 'SIMPLE', row_key, 0), uid, placed_at, bet_type)) AS betslips,
    uniqExact(uid)                        AS uids,
    uniqExact(match_id)                   AS fixtures,
    uniqExact(competition)                AS competitions,
    toString(min(placed_at))              AS date_min,
    toString(max(placed_at))              AS date_max,
    countIf(placed_at > event_at)         AS inplay_legs
FROM betslip_leg FINAL;

-- name: money_by_currency
-- Betslip-grain money per currency, plus the unresolved population that is
-- counted but never summed (ADR-0001).
SELECT
    currency,
    count()                 AS betslips,
    round(sum(turnover), 2) AS turnover,
    round(sum(ggr), 2)      AS ggr
FROM
(
    SELECT argMin(currency, placed_at) AS currency,
           argMin(turnover, placed_at) AS turnover,
           argMin(ggr, placed_at)      AS ggr
    FROM betslip_leg FINAL
    -- ADR-0003 betslip identity: a SIMPLE leg is its own betslip.
    -- See the note in betslip_breakdown; the naive key undercounts by 5.9%.
    GROUP BY if(bet_type = 'SIMPLE', row_key, 0), uid, placed_at, bet_type
)
GROUP BY currency
ORDER BY turnover DESC;

-- name: daily
-- Daily series at betslip grain.
SELECT
    toString(toDate(placed_at)) AS day,
    currency,
    count()                     AS betslips,
    round(sum(turnover), 2)     AS turnover,
    round(sum(ggr), 2)          AS ggr
FROM
(
    SELECT argMin(placed_at, placed_at) AS placed_at,
           argMin(currency, placed_at)  AS currency,
           argMin(turnover, placed_at)  AS turnover,
           argMin(ggr, placed_at)       AS ggr
    FROM betslip_leg FINAL
    -- ADR-0003 betslip identity: a SIMPLE leg is its own betslip.
    -- See the note in betslip_breakdown; the naive key undercounts by 5.9%.
    GROUP BY if(bet_type = 'SIMPLE', row_key, 0), uid, placed_at, bet_type
)
GROUP BY day, currency
ORDER BY day;

-- name: phases
-- Timing relative to kick-off. Boundaries mirror PHASES in betflow.py; the
-- 60-minute boundary stands in for "after team news" and is a proxy, labelled
-- as one everywhere it appears. minutes_to_kickoff is derived here rather than
-- read from the column, because a stored value can be stale or wrong — as the
-- is_inplay column was, defaulted to 0 for every row by the export adapter.
SELECT
    multiIf(
        mtk < -10080, 'More than 7d before',
        mtk < -1440,  '7d to 24h before',
        mtk < -360,   '24h to 6h before',
        mtk < -60,    '6h to 60m before',
        mtk < -5,     '60m to 5m before (post-lineups proxy)',
        mtk < 0,      '5m to kick-off',
        mtk < 45,     'In-play: 0-45m',
        mtk < 90,     'In-play: 45-90m',
        mtk < 120,    'In-play: 90-120m (extra time)',
                      'More than 120m after kick-off (residual)'
    )                       AS phase,
    currency,
    count()                 AS legs,
    round(sum(turnover), 2) AS turnover
FROM
(
    SELECT dateDiff('second', event_at, placed_at) / 60.0 AS mtk,
           currency, turnover
    FROM betslip_leg FINAL
)
GROUP BY phase, currency;
