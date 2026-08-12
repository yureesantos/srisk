-- Betslip legs, as specified by ADR-0008.
--
-- Engine choice: ReplacingMergeTree(version) implements ADR-0007's supersedence
-- contract — highest version per identity wins, re-delivery is idempotent, and
-- arrival order is irrelevant. Background merges collapse duplicates, so reads
-- MUST collapse explicitly with argMax(col, version); see 002_read_views.sql.
--
-- LowCardinality is applied on measured cardinalities from the real export
-- (competition 56, fixture 453, market 119, player 2,714, selection 6,014,
-- region 31, currency 3) — all far below the ~10k threshold where the
-- dictionary encoding stops paying. `uid` is deliberately NOT LowCardinality:
-- 10,405 distinct already, and unbounded in a stream.

CREATE TABLE IF NOT EXISTS srisk.betslip_leg
(
    -- Identity and version (ADR-0007)
    row_key        UInt64,                    -- hash of the identity tuple
    version        UInt64,                    -- source snapshot time, epoch ms

    -- Customer window and timing
    uid            String,
    placed_at      DateTime64(3, 'UTC'),
    event_at       DateTime64(3, 'UTC'),

    -- Dimensions
    bet_type       LowCardinality(String),
    match_id       UInt32,
    fixture        LowCardinality(String),
    competition    LowCardinality(String),
    market         LowCardinality(String),
    player         LowCardinality(String),
    selection      LowCardinality(String),
    region         LowCardinality(String),
    currency       LowCardinality(String),

    -- Facts. The mutability split is ADR-0007's central measured finding:
    -- turnover differed on 0 of 42 shared rows, GGR on 14 of 42.
    price          Decimal(10, 3),
    turnover       Decimal(18, 2),            -- immutable: known at placement
    ggr            Decimal(18, 2),            -- mutable: revised at settlement
    net_revenue    Decimal(18, 2),            -- mutable

    -- Provenance
    event_kind     LowCardinality(String),    -- placement | settlement | reversal
    source         LowCardinality(String),    -- partner feed identifier

    -- Derived at ingest so readers never recompute it
    is_inplay      UInt8,
    minutes_to_kickoff Float32
)
ENGINE = ReplacingMergeTree(version)
ORDER BY row_key
PARTITION BY toYYYYMM(placed_at)
SETTINGS index_granularity = 8192;

-- A skip index on placed_at: the ORDER BY is row_key (required for
-- supersedence), so time-ranged queries would otherwise scan every part. This
-- gives them a coarse filter without a second table.
ALTER TABLE srisk.betslip_leg
    ADD INDEX IF NOT EXISTS idx_placed_at placed_at TYPE minmax GRANULARITY 4;
