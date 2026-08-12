-- Class 1 breakdowns, computed inside ClickHouse.
--
-- These replace pulling every row into pandas. Measured at 20M rows: the
-- transfer and parse alone cost ~11s before any aggregation, against 2.73s to
-- aggregate the same 20M in SQL. Aggregation is what the engine is for, and
-- doing it in Python is what made the batch pipeline slow in the first place.
--
-- Every read collapses with FINAL (ADR-0012). Omitting it does not merely
-- inflate — it can invert the sign of GGR, and it is intermittent, because a
-- background merge makes the wrong query start returning the right answer.
--
-- Money never crosses a currency (ADR-0001): every money aggregate is grouped
-- by currency, so a cross-currency total is unexpressible rather than merely
-- discouraged.
--
-- Parameters: {limit:UInt32} — top-N cut for the wide dimensions.

-- name: by_dimension
-- Leg-grain breakdown over one dimension. `{dim:Identifier}` is bound by the
-- caller from a fixed allow-list, never interpolated from user input.
SELECT
    {dim:Identifier}          AS label,
    currency,
    count()                   AS legs,
    uniqExact(uid)            AS uids,
    round(sum(turnover), 2)   AS turnover,
    round(sum(ggr), 2)        AS ggr,
    round(avg(price), 4)      AS mean_price
FROM srisk.betslip_leg FINAL
GROUP BY label, currency
ORDER BY turnover DESC
LIMIT {limit:UInt32} BY currency;

-- name: betslip_grain
-- Betslip-grain breakdown. Turnover is only real at betslip grain (ADR-0003):
-- a combined bet repeats its stake on every leg, so summing legs inflates it by
-- a measured 1.087x on EUR. The inner query reduces legs to betslips first,
-- taking one stake per betslip rather than summing them.
SELECT
    label,
    currency,
    count()                   AS betslips,
    round(sum(turnover), 2)   AS turnover,
    round(sum(ggr), 2)        AS ggr
FROM
(
    SELECT
        argMin({dim:Identifier}, placed_at) AS label,
        argMin(currency, placed_at)         AS currency,
        argMin(turnover, placed_at)         AS turnover,
        argMin(ggr, placed_at)              AS ggr
    FROM srisk.betslip_leg FINAL
    -- The betslip identity of ADR-0003: Uid plus second-resolution timestamp,
    -- split by bet type because SIMPLE bets from one customer in one second are
    -- distinct betslips.
    GROUP BY uid, placed_at, bet_type
)
GROUP BY label, currency
ORDER BY turnover DESC
LIMIT {limit:UInt32} BY currency;

-- name: universe
-- The overview counters, in one pass rather than one query per figure.
SELECT
    count()                                        AS legs,
    uniqExact((uid, placed_at, bet_type))          AS betslips,
    uniqExact(uid)                                 AS uids,
    uniqExact(match_id)                            AS fixtures,
    uniqExact(competition)                         AS competitions,
    min(placed_at)                                 AS date_min,
    max(placed_at)                                 AS date_max,
    countIf(is_inplay = 1)                         AS inplay_legs
FROM srisk.betslip_leg FINAL;

-- name: money_by_currency
-- Betslip-grain money, per currency. Never summed across currencies (ADR-0001).
SELECT
    currency,
    count()                   AS betslips,
    round(sum(turnover), 2)   AS turnover,
    round(sum(ggr), 2)        AS ggr
FROM
(
    SELECT
        argMin(currency, placed_at) AS currency,
        argMin(turnover, placed_at) AS turnover,
        argMin(ggr, placed_at)      AS ggr
    FROM srisk.betslip_leg FINAL
    GROUP BY uid, placed_at, bet_type
)
GROUP BY currency
ORDER BY turnover DESC;

-- name: daily
-- Daily series at betslip grain.
SELECT
    toDate(placed_at)         AS day,
    currency,
    count()                   AS betslips,
    round(sum(turnover), 2)   AS turnover,
    round(sum(ggr), 2)        AS ggr
FROM
(
    SELECT
        argMin(placed_at, placed_at) AS placed_at,
        argMin(currency, placed_at)  AS currency,
        argMin(turnover, placed_at)  AS turnover,
        argMin(ggr, placed_at)       AS ggr
    FROM srisk.betslip_leg FINAL
    GROUP BY uid, placed_at, bet_type
)
GROUP BY day, currency
ORDER BY day;

-- name: phases
-- Timing relative to kick-off. Bin boundaries mirror PHASES in betflow.py; the
-- 60-minute boundary stands in for "after team news" and is a proxy, labelled
-- as one everywhere it appears.
SELECT
    multiIf(
        minutes_to_kickoff < -10080, 'More than 7d before',
        minutes_to_kickoff < -1440,  '7d to 24h before',
        minutes_to_kickoff < -360,   '24h to 6h before',
        minutes_to_kickoff < -60,    '6h to 60m before',
        minutes_to_kickoff < -5,     '60m to 5m before (post-lineups proxy)',
        minutes_to_kickoff < 0,      '5m to kick-off',
        minutes_to_kickoff < 45,     'In-play: 0-45m',
        minutes_to_kickoff < 90,     'In-play: 45-90m',
        minutes_to_kickoff < 120,    'In-play: 90-120m (extra time)',
                                     'More than 120m after kick-off (residual)'
    )                         AS phase,
    currency,
    count()                   AS legs,
    round(sum(turnover), 2)   AS turnover
FROM srisk.betslip_leg FINAL
GROUP BY phase, currency;
