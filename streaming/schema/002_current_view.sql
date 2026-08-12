-- The collapse, encapsulated.
--
-- ADR-0007 requires that the highest version per identity wins. ClickHouse's
-- background merge is asynchronous, so between an insert and its merge both
-- versions are present in the table. A query that does not collapse is not
-- slow — it is WRONG, and wrong in the direction of double-counting revenue.
-- Measured on 22M rows over 20M identities: omitting the collapse overstates
-- GGR by 22% (-401,274,687 against -329,706,563).
--
-- The collapse lives here so no caller has to remember it.
--
-- MECHANISM: FINAL, not argMax (ADR-0012). ADR-0008 originally specified
-- argMax(col, version) GROUP BY row_key and advised against FINAL. That was
-- wrong and was merged unmeasured: argMax builds a hash table over 20M distinct
-- identities and dies with MEMORY_LIMIT_EXCEEDED at 3.6 GiB after 52s, while
-- FINAL performs a streaming merge over already-sorted parts in 0.29-0.82s
-- depending on part count.
--
-- Read latency depends on merge state, so OPTIMIZE TABLE ... FINAL on sealed
-- partitions is routine operation rather than a contingency: 5 parts cost 0.82s,
-- one compacted part costs 0.29s for the same query.

CREATE OR REPLACE VIEW srisk.betslip_leg_current AS
SELECT
    row_key,
    version,
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
FROM srisk.betslip_leg
FINAL;
