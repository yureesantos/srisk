# 8. ClickHouse as the analytical store, with supersedence by version

Date: 2026-08-12

## Status

Accepted, **with the read-path mechanism superseded by
[ADR-0012](0012-final-not-argmax-measured.md)**. The store, engine and schema
below stand. The instruction to collapse with `argMax(col, version)` rather than
`FINAL` is **wrong** and was merged unmeasured: `argMax` exceeds memory at 20M
identities, while `FINAL` completes in 0.29–0.82s. The storage and latency
figures in this record are estimates that ADR-0012 replaces with measurements.

Implements the ingestion contract of ADR-0007, which fixed the semantics
(identity + version, idempotent, order-independent) and deliberately left the
mechanism open.

## Context

The brief asks for a store "to perform the same **analysis** on the betslip". The
emphasis decides the choice: this is an analytical workload, and none of the
guarantees a transactional store exists to provide are exercised by it.

### What the workload actually is

Measured from the artifacts the batch pipeline already emits, not hypothesised:

| Work | Shape | Cardinality |
|---|---|---|
| Seven dimensional breakdowns | `GROUP BY dim, currency` with `SUM`/counts over the whole table | 2 (bet type) → 56 (competition) → 453 (fixture) → 6,014 (selection) |
| Daily series, timing histograms | `GROUP BY` bucketed time | ~23 active days |
| Concentration (Gini/Lorenz) | sort the full per-Uid population, cumulative sum | 10,405 Uids |
| Price reference | last pre-kick-off price per `(fixture, market, selection)` | ~34k groups |
| Sharp test | `beats`/`trials` per Uid window, then Wilson + exact binomial + BH | ~700 testable windows |
| Anomaly detectors | median/MAD per day per currency; share-of-fixture per selection | small |

Every read is an aggregation. **There is not one lookup by primary key in the
entire dashboard** — no `WHERE betslip_id = ?`, no row-level read path. Choosing
a row-store here means paying for transactional machinery that nothing uses.

Design point: 20M+ rows, ingest from 70k/min to **500k/min (8,333 events/s)**,
and 100 concurrent front-end readers.

### The read load is not 100 concurrent scans

Worth stating because it changes the sizing: all 100 readers are looking at the
*same* seven breakdowns and the same curves. The correct architecture computes
each artifact **once per refresh tick** and serves all readers from that result —
the artifact shape the batch pipeline already produces. The database therefore
sees roughly **one analytical sweep per tick**, not one per reader.

Sub-second freshness would be dishonest anyway. ADR-0007 measured settlements
being reversed inside a 95-second window, so a GGR figure fresher than the
settlement churn reports noise as signal. The refresh interval is a data-driven
number, not a performance ceiling; ADR-0009 sets it.

### Candidates

**MongoDB.** Rejected on the merits. The rows are flat, fixed-schema, 17
columns — the document model buys nothing here: no nesting, no polymorphism, no
schema drift. What it costs is the whole read side: `$group` runs over a
row-oriented store with no vectorised execution, so seven full-collection groups
per tick means deserialising 20M BSON documents seven times. `$setWindowFields`
exists but sorting a 20M-document partition hits the 100 MB stage limit and
spills — and sort-then-cumulate is exactly the Gini shape. Its one strong leg is
the write path: `bulkWrite` upserts on a hashed key would keep up with 8k/s. Not
enough. (Mongo would be a reasonable choice for a *fixture and market catalogue* —
nested, irregular, low-volume. That is a different problem than this one.)

**PostgreSQL / TimescaleDB.** The respectable runner-up, and the strongest write
path of the three: `INSERT … ON CONFLICT DO UPDATE` gives exact, immediate,
transactional supersedence with no window in which a duplicate is visible.
Nothing in ClickHouse matches that. TimescaleDB's continuous aggregates with
invalidation are genuinely the best mechanism available for keeping *additive*
aggregates correct under retroactive mutation.

Two things decide against it. First, the measured mutation rate is high — 14 of
42 rows rewrite `GGR` — and on a heap store a sustained ~33% update rate means
dead tuples at thousands per second and continuous autovacuum pressure. HOT
updates apply (only `GGR`/`Net Revenue` change, never the key columns), which
makes it survivable, but it is a system that needs babysitting. Second, and
decisive: continuous aggregates only cover the additive work. Gini is not
decomposable into mergeable partials, and neither the price-reference window nor
the sharp test can be continuously aggregated — those keep requiring full sweeps
of a 20M-row heap, forever, on a row store.

At exactly 20M rows a well-tuned Postgres copes. The choice is between the engine
that must be tuned to cope and the engine for which this workload is small.

**Vector database.** No role. There are no embeddings, no similarity search, no
unstructured text; every query is exact aggregation over typed columns. The brief
offered it as an option and the honest answer is to decline it.

## Decision

**ClickHouse, with `ReplacingMergeTree(version)` as the mechanism satisfying
ADR-0007's supersedence contract.**

```sql
CREATE TABLE betslip_leg (
    row_key        UInt64,                      -- hash of the ADR-0007 identity
    version        UInt64,                      -- source snapshot time (epoch ms)
    uid            String,
    placed_at      DateTime64(3),
    event_at       DateTime64(3),
    bet_type       LowCardinality(String),
    match_id       UInt32,
    fixture        LowCardinality(String),
    competition    LowCardinality(String),
    market         LowCardinality(String),
    player         LowCardinality(String),
    option         LowCardinality(String),
    region         LowCardinality(String),
    currency       LowCardinality(String),
    price          Decimal(10, 3),
    turnover       Decimal(18, 2),              -- immutable  (ADR-0007)
    ggr            Decimal(18, 2),              -- mutable    (ADR-0007)
    net_revenue    Decimal(18, 2)               -- mutable    (ADR-0007)
)
ENGINE = ReplacingMergeTree(version)
ORDER BY row_key
PARTITION BY toYYYYMM(placed_at);
```

`LowCardinality` is applied on measured evidence: every dimension is under 10k
distinct values (competition 56, fixture 453, market 119, player 2,714, selection
6,014, region 31, currency 3). `uid` is deliberately excluded — 10,405 distinct
already and unbounded in a stream, which is where the encoding stops paying.

**Supersedence.** Every delivery is an insert carrying a version. Background
merges collapse rows sharing `row_key`, keeping the highest version. Redelivery
is absorbed; a settlement reversal supersedes because its version is higher;
out-of-order arrival is irrelevant because the winner is chosen by version, not
by arrival.

~~**Reads collapse explicitly with `argMax(col, version) GROUP BY row_key`, not
with `FINAL`.** `FINAL` forces the merge at query time and is the wrong default
under a 100-reader refresh loop.~~

**Superseded by ADR-0012.** Measured: `argMax` per `row_key` builds a hash table
over 20M identities and dies with `MEMORY_LIMIT_EXCEEDED` after 52s, while
`FINAL` streams a merge over already-sorted parts in 0.29–0.82s. The claim that
`FINAL` "forces the merge at query time" misread its cost model.

**Aggregation over mutable columns must never be pre-computed on insert.** A
`SummingMergeTree` materialized view over this table would be *wrong*: MVs fire
per insert and never observe the collapse, so a superseding row would be added to
the old one instead of replacing it. GGR rollups are therefore query-time sweeps.
Turnover, being immutable (measured: 0 of 42 rows differ), is the only column for
which insert-time pre-aggregation would be safe — and it is not worth a second
mechanism at this size.

**The statistics stay out of the database.** The exact binomial test, the Wilson
bound and the Benjamini–Hochberg procedure run in the refresh job, against the
existing tested code in `betflow/src/sharp.py`. The database reduces 20M rows to
~700 `(beats, trials)` pairs; the statistics then take milliseconds. BH is
inherently a whole-result-set procedure and is miserable to express in SQL, and
reimplementing a validated test in a second language to save one round trip
would be a regression. The same applies to the final Gini step: the database
returns the sorted per-Uid sums, `gini_lorenz()` finishes the job.

## Consequences

**Positive**

- The workload is what the engine is built for: a sorted, compressed, columnar
  store with vectorised execution, scanning a handful of `LowCardinality` columns
  over 20M rows. Seven breakdowns per tick is not a demanding read pattern for it.
- Ingest at 8,333/s via batched or async inserts is well inside its envelope,
  with no write-path tuning campaign.
- The non-additive work is native rather than worked around: `argMax(price,
  placed_at)` per group gives the price reference; `groupArray` + `arraySort` +
  `arrayCumSum` is a first-class pattern for the Lorenz curve.
- Existing validated Python (`sharp.py`, `gini_lorenz`) is reused unchanged
  rather than reimplemented in SQL.
- It is the stack Sporting Risk already runs. Not a technical argument, and not
  the reason for the choice — but it means the design is deployable in their
  environment rather than adjacent to it.

**Negative**

- **Deduplication is eventual, and this is the real cost.** Between insert and
  background merge, both versions of a row coexist. Every read must collapse
  (with `FINAL` — ADR-0012); a query that forgets to is silently wrong, and wrong
  in the direction of double-counting revenue. Measured at 22M rows over 20M
  identities: a 22% overstatement of GGR. This is a correctness property enforced
  by discipline and tests, not by the engine.
- **This is money data with a measured ~33% retroactive mutation rate, and
  ClickHouse is the weakest of the three candidates at mutation.** Correctness
  under update is eventual-with-read-time-repair, not transactional. The pick
  holds because every consumer here is an aggregate computed with read-time
  collapse, because `TURNOVER` — the figure that must never double-count — is
  measured immutable, and because mutation is confined to two settlement columns
  that version supersedence handles correctly. If this store ever had to serve
  exact per-row extracts for dispute or regulatory purposes, Postgres's
  `ON CONFLICT` semantics would be categorically safer.
- **Losing insert-time pre-aggregation** forfeits the standard ClickHouse
  optimisation. Acceptable only because base-table sweeps are fast at this size;
  it is a constraint inherited for as long as the table stays `Replacing`.
- **What breaks first as scale grows:** the read-time collapse over full history.
  Free at 20M rows, dominant at 2B. The fixes are known and incremental — restrict
  the collapse to recent partitions and run `OPTIMIZE … FINAL` on sealed cold
  partitions so history is physically deduplicated — but they are operational
  work, and going multi-node (`ReplicatedReplacingMergeTree` + Keeper) is a real
  step up in operational burden compared with a Postgres primary/replica pair.
- No transactions, no referential integrity, no constraints. Identity
  canonicalisation and hashing live in the ingest service, in one place, and are
  tested there.
